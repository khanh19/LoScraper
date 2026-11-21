"""Soft collection targets, measured only from eligible database results."""
from collections import Counter
from urllib.parse import urlsplit

TARGETS = {'hanoi':15, 'hcmc':15, 'danang':8}


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
    return {'target':target,'eligible_unique_items':len(items),
            'shortfall':max(0,target-len(items)),
            'target_met':len(items)>=target,
            'sections':dict(Counter(i.get('section','weekly') for i in items.values())),
            'categories':dict(Counter(i.get('category','unknown') for i in items.values())),
            'items_by_supporting_platform':dict(sources),
            'missing_social_platforms':[p for p in ('instagram','tiktok') if not sources[p]],
            'note':'Soft target across weekly and planning; multi-source items count once.'}
