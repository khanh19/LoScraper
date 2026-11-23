"""Soft collection targets, measured only from eligible database results."""
from collections import Counter
from datetime import datetime, timezone
import os
from urllib.parse import urlsplit

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


def read_coverage(db, now):
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return {
            city: summarize(db.execute(
                'SELECT item_id, reason, payload FROM public.discovery_evaluate_all(%s,%s)',
                (now, city),
            ).fetchall(), city)
            for city in SECTION_TARGETS
        }


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


def main():
    import psycopg
    from psycopg.rows import dict_row

    try:
        url = os.environ['DATABASE_URL']
        if not url:
            raise ValueError('missing_database')
        now = datetime.now(timezone.utc)
        with psycopg.connect(url, connect_timeout=10, autocommit=True, row_factory=dict_row) as db:
            db.execute("SET statement_timeout = '30s'")
            result = read_coverage(db, now)
        print(markdown_coverage(result, now))
    except (KeyError, ValueError, psycopg.Error) as exc:
        print(f'Verified discovery coverage unavailable ({type(exc).__name__}).')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
