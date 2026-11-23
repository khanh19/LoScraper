"""Automatically discover public social leads and report coverage gaps, without providers."""
import argparse
from datetime import datetime, timezone
from itertools import islice
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit,urljoin
from .adapters import CLASSES, is_type, load_sources, structured
from .http import PublicClient, FetchError, fetch_failure_reason
from .model import CITIES,canonical
from .social_links import TikTokShareResolver, extract_posts, remember_lead
from .intent import queries

DIRECTORY=Path(__file__).with_name('source_directory.json')

def canonical_tiktok_profile(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(canonical(url))
    except ValueError:
        return None
    if (parts.hostname in {'tiktok.com', 'www.tiktok.com'}
            and re.fullmatch(r'/@[A-Za-z0-9_.]+', parts.path)):
        return 'https://www.tiktok.com' + parts.path
    return None


def reviewed_profiles(city, client, platform, normalize):
    seen = set()
    for source in json.loads(DIRECTORY.read_text()):
        accounts = [a for a in source['accounts'] if a['platform'] == platform]
        if city not in source['cities'] or not accounts:
            continue
        page = source['review_evidence']
        try:
            soup = client.get(page, {urlsplit(page).hostname})
        except FetchError:
            continue
        links = {normalize(a['href']) for a in soup.select('a[href]')}
        for entry in structured(soup):
            owner, aliases = entry.get('url'), entry.get('sameAs')
            if (is_type(entry, 'Organization') and isinstance(owner, str)
                    and owner.rstrip('/') == page.rstrip('/') and isinstance(aliases, list)):
                links.update(normalize(alias) for alias in aliases)
        for account in accounts:
            url = normalize(account['url'])
            if url and url in links and url not in seen:
                seen.add(url)
                yield {'url': url, 'ownership_evidence': page,
                       'publisher_id': source['publisher_id'], 'city_hint': city}

def reviewed_tiktok_profiles(city, client):
    return reviewed_profiles(city, client, 'tiktok', canonical_tiktok_profile)


def reviewed_tiktok_profile(city, client):
    return next(reviewed_tiktok_profiles(city, client), None)

def discover(city,client,now,counts=None,limit=6):
    seeds=[s for s in json.loads(DIRECTORY.read_text()) if city in s['cities']]
    seeds.sort(key=lambda s:(sum((counts or {}).get(c,0) for c in s['categories']),s['id']))
    configs = load_sources()
    resolver = TikTokShareResolver(client)
    posts={};pages=[]
    for seed in seeds[:limit]:
        try:
            slug = seed['id']
            host = urlsplit(seed['url']).hostname
            adapter = CLASSES[slug](slug, configs[slug]) if slug in CLASSES and slug in configs else None

            def fetch(url):
                if adapter and getattr(client, 'browser_enabled', False):
                    return adapter.fetch(client, url)
                return client.get(url, {host})

            soup = fetch(seed['url'])
            targets = [(seed['url'], soup)]
            seed_url = canonical(seed['url'])
            if slug == 'ticketbox' and adapter:
                # Listing city labels route the limited detail reads. The
                # destination still needs independent verification.
                try:
                    links = adapter.public_listing_links(client, city_hint=city)
                except (FetchError, ValueError) as error:
                    pages.append({'source': slug, 'stage': 'on_sale_listing',
                                  'status': 'failed', 'reason': fetch_failure_reason(error)})
                    links = []
            elif adapter:
                # Website adapters already distinguish detail links from calendar
                # exports, related indexes, and locale switches.
                links = adapter.links(soup, seed['url'])
            else:
                links = (
                    urljoin(seed['url'], a['href']) for a in soup.select('a[href]')
                    if any(path in a['href'].lower() for path in ('/event/', '/su-kien/', f'/{now.year}/'))
                )
            details = (u for u in dict.fromkeys(links) if urlsplit(u).hostname == host and u != seed_url)
            for u in islice(details, 2):
                try:
                    targets.append((u, fetch(u)))
                except (FetchError, ValueError) as error:
                    pages.append({'source': slug, 'url': u, 'status': 'failed', 'reason': fetch_failure_reason(error)})
            for u,html in targets:
                found=extract_posts(str(html),u,now,resolve_share=resolver.resolve)
                pages.append({'source':seed['id'],'url':u,'status':'complete','leads':len(found)})
                for post in found:
                    post['publisher_id']=seed['publisher_id']
                    post['city_hint']=city  # NEVER independent location evidence.
                    remember_lead(posts, post)
        except (FetchError, ValueError) as error:
            pages.append({'source': slug, 'url': seed['url'], 'status': 'failed', 'reason': fetch_failure_reason(error)})
    return {'city':city,'pages':pages,'posts':list(posts.values())[:30],
            'tiktok_share_links':resolver.results,
            'queries':queries(city,counts),'provider_requests':0,'published':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city',choices=list(CITIES),required=True)
    p.add_argument('--max-sources',type=int,default=6)
    p.add_argument('--browser', action='store_true', help='Use website adapters with browser support for public publisher pages')
    p.add_argument('--review-instagram', action='store_true',
                   help='Check discovered Instagram permalinks and up to three verified organizer profiles')
    p.add_argument('--write-leads',action='store_true')
    p.add_argument('--env-file',action='append',default=[])
    args=p.parse_args()
    if not 1<=args.max_sources<=6:p.error('max-sources must be 1..6')
    from .__main__ import load_env_files
    load_env_files(args.env_file)
    store=None;counts={};now=datetime.now(timezone.utc)
    client = PublicClient(browser=args.browser)
    try:
        if args.write_leads:
            url=os.environ.get('DATABASE_URL','');parts=urlsplit(url)
            if parts.hostname not in {'127.0.0.1','localhost','::1'} or not parts.path.startswith('/lo_setup_check_'):
                p.error('write-leads requires an isolated local preview')
            from .store import Store
            store=Store(url)
            counts={r['category']:r['n'] for r in store.db.execute("SELECT payload->>'category' category,count(*) n FROM discovery_evaluate_all(%s,%s) WHERE reason='eligible' GROUP BY 1",(now,args.city)).fetchall()}
        report=discover(args.city,client,now,counts,args.max_sources)
        if args.review_instagram:
            from .instagram_public import instagram_profile, review, review_profile
            urls = (post['url'] for post in report['posts'] if post['platform'] == 'instagram')
            report['public_instagram_reviews'] = [review(url, client, now) for url in islice(urls, 3)]
            profiles = reviewed_profiles(args.city, client, 'instagram', instagram_profile)
            report['public_instagram_profile_reviews'] = [
                review_profile(profile, client, now) for profile in islice(profiles, 3)
            ]
            leads = {}
            for lead in report['posts']:
                remember_lead(leads, lead)
            for profile in report['public_instagram_profile_reviews']:
                for post in profile['posts']:
                    remember_lead(leads, {
                        'url': post['url'], 'platform': 'instagram', 'city_hint': args.city,
                        'published_at': post['published_at'], 'text': post['caption'],
                        'discovered_on': profile['embed_url'], 'publisher_id': profile['publisher_id'],
                        'requires_provider_validation': True,
                    })
            report['posts'] = sorted(
                leads.values(), key=lambda row: (row['published_at'] or '', row['url']), reverse=True,
            )[:30]
        if store:
            for row in report['posts']:
                store.db.execute("""INSERT INTO discovery_leads(url,platform,discovered_on,published_at,publisher_id,city_slug)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(url) DO NOTHING""",(row['url'],row['platform'],row['discovered_on'],row['published_at'],row['publisher_id'],args.city))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 2 if any(r['status']=='failed' for r in report['pages']) else 0
    finally:
        client.close()
        if store:store.close()

if __name__=='__main__':raise SystemExit(main())
