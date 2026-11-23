"""Explicit, resumable social pilot. Never runs from the scheduled collector."""
import argparse
from dataclasses import fields
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from .__main__ import load_env_files
from .model import Candidate, Occurrence
from .providers import BrightSocial, SerpDiscovery, ProviderDisabled, post_platform, social_evidence
from .store import Store

PILOT_ID='coverage-20261108'
# Minimum history already established by the original pilot receipts.
PILOT_HISTORY = {('serpapi', None): 6, ('brightdata', 'facebook'): 1, ('brightdata', 'instagram'): 2}


def open_pilot_ledger(url):
    try:
        ledger = Store(url)
    except psycopg.Error:
        raise ProviderDisabled('existing_local_quota_ledger_unavailable') from None
    try:
        history = ledger.db.execute("""SELECT provider,input_data->>'platform' AS platform,
            count(*) AS attempts FROM discovery_provider_jobs WHERE pilot_id=%s GROUP BY 1,2""",
            (PILOT_ID,)).fetchall()
        attempts = {(row['provider'], row['platform']): row['attempts'] for row in history}
        if any(attempts.get(key, 0) < minimum for key, minimum in PILOT_HISTORY.items()):
            raise ProviderDisabled('existing_pilot_history_required')
    except psycopg.Error:
        ledger.close()
        raise ProviderDisabled('existing_local_quota_ledger_unavailable') from None
    except BaseException:
        ledger.close()
        raise
    return ledger


def validate_manifest(manifest):
    posts=manifest.get('posts',[]);queries=manifest.get('queries',[])
    if len(posts)>9 or len(queries)>6:raise ValueError('manifest_budget_exceeded')
    platforms=[post_platform(p['url']) for p in posts]
    if None in platforms or any(platforms.count(p)>3 for p in set(platforms)):
        raise ValueError('invalid_platform_budget')
    if len({p['url'] for p in posts})!=len(posts):raise ValueError('duplicate_post')
    return posts,queries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',action='append',default=[])
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();load_env_files(args.env_file)
    manifest=json.loads(args.manifest.read_text());posts,queries=validate_manifest(manifest)
    feed_url=os.environ.get('DATABASE_URL');ledger_url=os.environ.get('QUOTA_DATABASE_URL')
    if not feed_url or not ledger_url or feed_url==ledger_url:
        raise ValueError('separate_feed_and_canonical_ledger_required')
    for url in (feed_url,ledger_url):
        if urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'}:raise ValueError('local_pilot_only')
    if not urlsplit(feed_url).path.startswith('/lo_setup_check_'):
        raise ValueError('isolated_preview_required')
    now=datetime.now(timezone.utc)
    report={'pilot_id':PILOT_ID,'searches':[],'posts':[],'routine_social_enabled':False}
    try:
        ledger = open_pilot_ledger(ledger_url)
    except ProviderDisabled as exc:
        print(json.dumps({**report, 'status': 'blocked', 'reason': str(exc)}, ensure_ascii=False, indent=2))
        return 2
    feed = None
    try:
        feed = Store(feed_url)
        search=SerpDiscovery(ledger,pilot_id=PILOT_ID)
        social=BrightSocial(ledger,pilot_id=PILOT_ID)
        for query in queries:
            try:report['searches'].append({'query':query,'urls':search.search(query,now),'status':'passed'})
            except ProviderDisabled as exc:report['searches'].append({'status':'blocked','reason':str(exc)})
        for post in posts:
            platform=post_platform(post['url'])
            outcome={'platform':platform,'url':post['url'],'accepted':0}
            try:
                raw=post['primary']
                primary=Candidate(**{k:v for k,v in raw.items() if k in {f.name for f in fields(Candidate)} and k!='occurrences'})
                primary.occurrences=[Occurrence(**o) for o in raw.get('occurrences',[])]
                if primary.platform!='web' or primary.validate(now):raise ProviderDisabled('invalid_primary_evidence')
                # Require an existing freshly collected website observation in this preview.
                exists=feed.db.execute("SELECT facts FROM discovery_observations WHERE source_slug=%s AND source_url=%s AND entry_key=%s AND verified_at>now()-interval '168 hours'",(primary.source_slug,primary.source_url,primary.entry_key)).fetchone()
                if not exists:raise ProviderDisabled('primary_not_imported')
                facts=exists['facts']
                expected={'original_title':primary.title,'kind':primary.kind,'city_slug':primary.city_slug,'venue_name':primary.venue_name,'address':primary.address}
                if any(facts.get(k)!=v for k,v in expected.items()):raise ProviderDisabled('primary_facts_mismatch')
                rows=social.collect(post['url'],now)
                for row in rows:
                    evidence=social_evidence(primary,row,platform,now)
                    if evidence and not evidence.validate(now):
                        feed.register(platform,platform.title(),True,platform)
                        feed.upsert(evidence,now);outcome['accepted']+=1
                outcome['status']='passed' if outcome['accepted'] else 'failed'
                if not outcome['accepted']:outcome['reason']='no_valid_destination_evidence'
            except ProviderDisabled as exc:
                outcome.update(status='failed' if str(exc).startswith('provider_http_4') else 'blocked',reason=str(exc))
            except Exception as exc:
                outcome.update(status='failed',reason=type(exc).__name__)
            report['posts'].append(outcome)
        report['reservations']=ledger.db.execute("SELECT provider,input_data->>'platform' AS platform,count(*) AS attempts,sum(reserved_units) AS units FROM discovery_provider_jobs WHERE pilot_id=%s GROUP BY 1,2",(PILOT_ID,)).fetchall()
    finally:
        if feed:
            feed.close()
        ledger.close()
    print(json.dumps(report,ensure_ascii=False,default=str,indent=2))
    return 0 if all(r['status']=='passed' for r in report['posts']+report['searches']) else 2

if __name__=='__main__':raise SystemExit(main())
