"""Automatically discover public social leads and report coverage gaps, without providers."""
import argparse
from datetime import datetime, timezone
from itertools import islice
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,urljoin
from .adapters import CLASSES, is_type, load_sources, structured
from .http import PublicClient,FetchError
from .model import CITIES,canonical
from .social_links import extract_posts, remember_lead
from .intent import queries

DIRECTORY=Path(__file__).with_name('source_directory.json')

def reviewed_tiktok_profile(city, client):
    for source in json.loads(DIRECTORY.read_text()):
        accounts = [a for a in source['accounts'] if a['platform'] == 'tiktok']
        if city not in source['cities'] or not accounts:
            continue
        page = source['review_evidence']
        try:
            soup = client.get(page, {urlsplit(page).hostname})
        except FetchError:
            continue
        links = {a['href'].rstrip('/') for a in soup.select('a[href]')}
        for entry in structured(soup):
            owner, aliases = entry.get('url'), entry.get('sameAs')
            if (is_type(entry, 'Organization') and isinstance(owner, str)
                    and owner.rstrip('/') == page.rstrip('/') and isinstance(aliases, list)):
                links.update(alias.rstrip('/') for alias in aliases if isinstance(alias, str))
        for account in accounts:
            if account['url'].rstrip('/') in links:
                return {'url': account['url'], 'ownership_evidence': page,
                        'publisher_id': source['publisher_id'], 'city_hint': city}
    return None

def discover(city,client,now,counts=None,limit=6):
    seeds=[s for s in json.loads(DIRECTORY.read_text()) if city in s['cities']]
    seeds.sort(key=lambda s:(sum((counts or {}).get(c,0) for c in s['categories']),s['id']))
    configs = load_sources()
    posts={};pages=[]
    for seed in seeds[:limit]:
        try:
            host=urlsplit(seed['url']).hostname
            soup=client.get(seed['url'],{host})
            targets=[(seed['url'],soup)]
            slug = seed['id']
            seed_url = canonical(seed['url'])
            if slug in CLASSES and slug in configs:
                # Website adapters already distinguish detail links from calendar
                # exports, related indexes, and locale switches.
                links = CLASSES[slug](slug, configs[slug]).links(soup, seed['url'])
            else:
                links = (
                    urljoin(seed['url'], a['href']) for a in soup.select('a[href]')
                    if any(path in a['href'].lower() for path in ('/event/', '/su-kien/', f'/{now.year}/'))
                )
            details = (u for u in dict.fromkeys(links) if urlsplit(u).hostname == host and u != seed_url)
            for u in islice(details, 2):
                try:targets.append((u,client.get(u,{host})))
                except (FetchError,ValueError) as e:pages.append({'source':seed['id'],'url':u,'status':'failed','reason':str(e)})
            for u,html in targets:
                found=extract_posts(str(html),u,now)
                pages.append({'source':seed['id'],'url':u,'status':'complete','leads':len(found)})
                for post in found:
                    post['publisher_id']=seed['publisher_id']
                    post['city_hint']=city  # NEVER independent location evidence.
                    remember_lead(posts, post)
        except (FetchError,ValueError) as e:pages.append({'source':seed['id'],'status':'failed','reason':str(e)})
    return {'city':city,'pages':pages,'posts':list(posts.values())[:30],
            'queries':queries(city,counts),'provider_requests':0,'published':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city',choices=list(CITIES),required=True)
    p.add_argument('--max-sources',type=int,default=6)
    p.add_argument('--write-leads',action='store_true')
    p.add_argument('--env-file',action='append',default=[])
    args=p.parse_args()
    if not 1<=args.max_sources<=6:p.error('max-sources must be 1..6')
    from .__main__ import load_env_files
    load_env_files(args.env_file)
    store=None;counts={};now=datetime.now(timezone.utc)
    try:
        if args.write_leads:
            url=os.environ.get('DATABASE_URL','');parts=urlsplit(url)
            if parts.hostname not in {'127.0.0.1','localhost','::1'} or not parts.path.startswith('/lo_setup_check_'):
                p.error('write-leads requires an isolated local preview')
            from .store import Store
            store=Store(url)
            counts={r['category']:r['n'] for r in store.db.execute("SELECT payload->>'category' category,count(*) n FROM discovery_evaluate_all(%s,%s) WHERE reason='eligible' GROUP BY 1",(now,args.city)).fetchall()}
        report=discover(args.city,PublicClient(),now,counts,args.max_sources)
        if store:
            for row in report['posts']:
                store.db.execute("""INSERT INTO discovery_leads(url,platform,discovered_on,published_at,publisher_id,city_slug)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(url) DO NOTHING""",(row['url'],row['platform'],row['discovered_on'],row['published_at'],row['publisher_id'],args.city))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 2 if any(r['status']=='failed' for r in report['pages']) else 0
    finally:
        if store:store.close()

if __name__=='__main__':raise SystemExit(main())
