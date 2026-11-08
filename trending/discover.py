"""Automatically discover public social leads and report coverage gaps, without providers."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,urljoin
from .http import PublicClient,FetchError
from .model import CITIES,canonical
from .social_links import extract_posts
from .intent import queries

DIRECTORY=Path(__file__).with_name('source_directory.json')

def discover(city,client,now,counts=None,limit=6):
    seeds=[s for s in json.loads(DIRECTORY.read_text()) if city in s['cities']]
    seeds.sort(key=lambda s:(sum((counts or {}).get(c,0) for c in s['categories']),s['id']))
    posts={};pages=[]
    for seed in seeds[:limit]:
        try:
            host=urlsplit(seed['url']).hostname
            soup=client.get(seed['url'],{host})
            targets=[(seed['url'],soup)]
            # Bounded same-site event/detail navigation; no profile or hashtag crawl.
            links=[]
            for a in soup.select('a[href]'):
                u=urljoin(seed['url'],a['href'])
                if urlsplit(u).hostname==host and u!=seed['url'] and any(x in u.lower() for x in ['/event','/su-kien',f'/{now.year}/','/weekly']):
                    if u not in links:links.append(u)
            for u in links[:2]:
                try:targets.append((u,client.get(u,{host})))
                except (FetchError,ValueError) as e:pages.append({'source':seed['id'],'url':u,'status':'failed','reason':str(e)})
            for u,html in targets:
                found=extract_posts(str(html),u,now)
                pages.append({'source':seed['id'],'url':u,'status':'complete','leads':len(found)})
                for post in found:
                    post['publisher_id']=seed['publisher_id']
                    post['city_hint']=city  # NEVER independent location evidence.
                    posts.setdefault(post['url'],post)
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
