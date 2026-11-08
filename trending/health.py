"""Read-only local accounting and feed eligibility; never contacts data providers."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os

import psycopg
from psycopg.rows import dict_row

from .model import CITIES


def report(db, cities, now=None):
    now = now or datetime.now(timezone.utc)
    # READ ONLY prevents accidental writes; repeatable read gives every count one snapshot.
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        runs = db.execute("""SELECT id,source_slug,city_slug,requested_cities,requested_sources,
            started_at,finished_at,heartbeat_at,accepted,rejected,failed,diagnostics,
            CASE WHEN status='running' AND COALESCE(heartbeat_at,started_at)<%s-interval '30 minutes'
                THEN 'interrupted' ELSE status END AS status
            FROM discovery_ingestion_runs
            WHERE requested_cities && %s::text[] OR city_slug=ANY(%s) OR (city_slug IS NULL AND cardinality(requested_cities)=0)
            ORDER BY started_at DESC,id""",(now,list(cities),list(cities))).fetchall()
        sources = db.execute("SELECT slug,name,enabled FROM discovery_sources WHERE platform='web' ORDER BY slug").fetchall()
        feeds = {}
        coverage = []
        for city in cities:
            evaluated = db.execute('SELECT * FROM public.discovery_evaluate(%s,%s)',(now,city)).fetchall()
            eligible = [r for r in evaluated if r['reason']=='eligible']
            feeds[city] = dict(eligible=dict(Counter(r['kind'] for r in eligible)),
                eligible_total=len(eligible),empty=not eligible,
                withheld=dict(Counter(r['reason'] for r in evaluated if r['reason']!='eligible')),
                losing_last_fresh_evidence_within_24h=[str(r['item_id']) for r in eligible
                    if r['evidence_expires_at'] and r['evidence_expires_at']<=now+timedelta(hours=24)])
            for source in sources:
                attempts = [r for r in runs if r['source_slug']==source['slug']
                    and (city in r['requested_cities'] or r['city_slug']==city or
                         (not r['requested_cities'] and r['city_slug'] is None))]
                last = attempts[0] if attempts else None
                complete = next((r for r in attempts if r['status']=='complete'),None)
                coverage.append(dict(source=source['slug'],city=city,enabled=source['enabled'],
                    last_attempt=last['started_at'] if last else None,
                    last_completed=complete['finished_at'] if complete else None,
                    last_status=last['status'] if last else 'never_run',
                    # A failed page may not reveal its city. Do not invent city attribution.
                    city_counts=(last['diagnostics'].get('cities',{}).get(city,{}) if last else {}),
                    source_counts={k:last[k] for k in ('accepted','rejected','failed')} if last else {},
                    reasons=last['diagnostics'].get('reasons',{}) if last else {}))
        reservations = db.execute("""SELECT provider,billing_month,status,count(*) AS jobs,
            sum(reserved_units) AS reserved_units FROM discovery_provider_jobs
            GROUP BY provider,billing_month,status ORDER BY billing_month DESC,provider,status""").fetchall()
        unresolved = db.execute("""SELECT job_key,provider,provider_job_id,status,reserved_units,created_at,updated_at
            FROM discovery_provider_jobs WHERE status<>'complete' ORDER BY created_at""").fetchall()
        # Explicit projection: never echo stored inputs, URL query strings, or arbitrary diagnostics.
        safe_runs = []
        for r in runs:
            entry = {k:r[k] for k in ('id','source_slug','requested_cities','requested_sources','started_at','finished_at','heartbeat_at','status','accepted','rejected','failed')}
            entry['reasons'] = r['diagnostics'].get('reasons',{})
            entry['persistence_errors'] = r['diagnostics'].get('persistence_errors',{})
            safe_runs.append(entry)
        return dict(generated_at=now,cities=feeds,source_city_coverage=coverage,runs=safe_runs,
                    provider_accounting=dict(label='Persisted local reservations; NOT a live provider balance',
                                             reservations=reservations,unresolved_jobs=unresolved))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',action='append',default=[])
    parser.add_argument('--city',choices=list(CITIES))
    parser.add_argument('--json',action='store_true')
    args = parser.parse_args()
    # Loading an explicit env file does not instantiate provider clients.
    from .__main__ import load_env_files
    try:
        load_env_files(args.env_file)
        url = os.environ.get('DATABASE_URL')
        if not url:
            raise ValueError('missing configuration')
        with psycopg.connect(url,connect_timeout=10,autocommit=True,row_factory=dict_row) as db:
            result = report(db,[args.city] if args.city else list(CITIES))
        if args.json:
            print(json.dumps(result,default=str,ensure_ascii=False,indent=2))
        else:
            for city, feed in result['cities'].items():
                print(f"{city}: {feed['eligible_total']} eligible ({feed['eligible']}); empty={feed['empty']}; withheld={feed['withheld']}")
                print('  Last fresh evidence expires within 24h:',len(feed['losing_last_fresh_evidence_within_24h']))
            for row in result['source_city_coverage']:
                print(f"{row['source']} / {row['city']}: {row['last_status']}; attempted={row['last_attempt']}; completed={row['last_completed']}; counts={row['source_counts']}; reasons={row['reasons']}")
            for row in result['runs']:
                print(f"Run {row['id']} ({row['source_slug']}): {row['status']}; accepted={row['accepted']} rejected={row['rejected']} failed={row['failed']}")
            print(result['provider_accounting']['label'])
            print(json.dumps(result['provider_accounting'],default=str,ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'failed','reason':type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
