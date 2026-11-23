"""Soft collection targets, measured only from eligible database results."""
from collections import Counter
import argparse
import os
from urllib.parse import urlsplit

from psycopg.errors import InsufficientPrivilege

from .store import WEBSITE_COLLECTION_PLANS

SECTION_TARGETS = {'hanoi': {'weekly':14,'planning':7},
                   'hcmc': {'weekly':18,'planning':7},
                   'danang': {'weekly':12,'planning':5}}
TARGETS = {city:sum(sections.values()) for city,sections in SECTION_TARGETS.items()}


def platform(url):
    host=(urlsplit(url).hostname or '').lower()
    for name,domain in [('instagram','instagram.com'),('tiktok','tiktok.com'),
                        ('facebook','facebook.com'),('youtube','youtube.com')]:
        if host==domain or host.endswith('.'+domain):return name
    return 'web'


def summarize(rows, city):
    # Shared evaluator already handles dates, cancellations, source authority,
    # deduplication and conflicts. Targets never loosen those rules.
    items={str(row['item_id']):row['payload'] for row in rows
           if row['reason']=='eligible' and row.get('payload')}
    sources=Counter()
    for item in items.values():
        sources.update({platform(s['url']) for s in item.get('sources',[]) if s.get('url')})
    target=TARGETS[city]
    sections=Counter(i.get('section','weekly') for i in items.values())
    deficits={section:max(0,count-sections[section]) for section,count in SECTION_TARGETS[city].items()}
    return {'target':target,'eligible_unique_items':len(items),
            'shortfall':max(0,target-len(items)),
            'target_met':not any(deficits.values()),
            'sections':dict(sections),
            'section_targets':SECTION_TARGETS[city],
            'section_shortfalls':deficits,
            'categories':dict(Counter(i.get('category','unknown') for i in items.values())),
            'items_by_supporting_platform':dict(sources),
            'missing_social_platforms':[p for p in ('instagram','tiktok') if not sources[p]],
            'note':'Soft section targets; surplus weekly items cannot fill planning gaps. Multi-source items count once.'}


def read_coverage(db):
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        rows = db.execute('SELECT * FROM public.discovery_coverage_snapshot()').fetchall()
    by_section = {(row['city_slug'], row['section']): row for row in rows}
    results = {}
    for city, targets in SECTION_TARGETS.items():
        city_rows = {section: by_section[city, section] for section in targets}
        counts = {section: row['item_count'] for section, row in city_rows.items()}
        results[city] = {
            'sections': counts,
            'section_targets': targets,
            'items_by_supporting_platform': {
                name: sum(row[name + '_count'] for row in city_rows.values())
                for name in ('instagram', 'tiktok')
            },
            'target_met': all(counts[section] >= target for section, target in targets.items()),
        }
    return results, rows[0]['evaluated_at']


def markdown_coverage(results, now):
    lines = [
        '### Verified discovery coverage',
        '',
        f'Feed snapshot at {now.isoformat(timespec="seconds")}. Weekly and planning targets are measured separately.',
        '',
        '| City | Weekly / target | Planning / target | With Instagram evidence | With TikTok evidence | City targets |',
        '| --- | ---: | ---: | ---: | ---: | --- |',
    ]
    for city, coverage in results.items():
        sections = coverage['sections']
        targets = coverage['section_targets']
        platforms = coverage['items_by_supporting_platform']
        status = 'Met' if coverage['target_met'] else 'Below target'
        lines.append(
            f"| {city} | {sections.get('weekly', 0)} / {targets['weekly']} |"
            f" {sections.get('planning', 0)} / {targets['planning']} |"
            f" {platforms.get('instagram', 0)} | {platforms.get('tiktok', 0)} | {status} |"
        )
    return '\n'.join(lines)


def collector_write_blocker(db):
    state = db.execute("""SELECT pg_is_in_recovery() AS replica,
        current_setting('transaction_read_only') = 'on' AS read_only""").fetchone()
    if state['replica']:
        return 'replica'
    if state['read_only']:
        return 'read_only_connection'

    # PostgreSQL checks planning-time privileges without executing these statements.
    stage = 'collector'
    try:
        with db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            for stage, statement in WEBSITE_COLLECTION_PLANS:
                db.execute('EXPLAIN (COSTS OFF) ' + statement, (None,) * statement.count('%s'))
    except InsufficientPrivilege:
        return stage + '_forbidden'
    return None


def main():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-verified-tls', action='store_true')
    parser.add_argument('--check-collector-writes', action='store_true')
    args = parser.parse_args()
    try:
        url = os.environ.get('DATABASE_URL', '')
        if not url:
            print('Discovery target check failed (missing_database).')
            raise SystemExit(1)
        if args.require_verified_tls and conninfo_to_dict(url).get('sslmode') != 'verify-full':
            print('Discovery target check failed (verify_full_required).')
            raise SystemExit(1)
        with psycopg.connect(url, connect_timeout=10, autocommit=True, row_factory=dict_row) as db:
            db.execute("SET statement_timeout = '30s'")
            if args.check_collector_writes:
                blocker = collector_write_blocker(db)
                if blocker:
                    print(f'Discovery target check failed ({blocker}).')
                    raise SystemExit(1)
            result, now = read_coverage(db)
        if args.check_collector_writes:
            print('Collector connection and website collection grants passed read-only planning checks.\n')
        print(markdown_coverage(result, now))
    except (KeyError, ValueError, psycopg.Error) as exc:
        print(f'Verified discovery coverage unavailable ({type(exc).__name__}).')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
