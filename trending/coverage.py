"""Soft collection targets, measured only from eligible database results."""
from collections import Counter
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
