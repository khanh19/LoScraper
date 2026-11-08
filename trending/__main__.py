from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .adapters import CLASSES, collect_source, load_sources, supplemental_links
from .http import PublicClient
from .model import CITIES
from .providers import BrightSocial, ProviderDisabled, SerpDiscovery, post_platform, social_evidence
from .store import Store


def load_env_files(paths):
    # Explicit files only, a small allowlist, no shell evaluation or key logging.
    allowed = {'DATABASE_URL','SERPAPI_API_KEY','BRIGHTDATA_API_KEY','BRIGHT_DATA_API_KEY',
               'BRIGHTDATA_FREE_VERIFICATION_JSON','BRIGHTDATA_BILLING_API_KEY','LO_BROWSER_CHANNEL'}
    for path in paths:
        for line in Path(path).read_text().splitlines():
            line = line.strip().removeprefix('export ')
            if '=' not in line or line.startswith('#'):
                continue
            name, value = line.split('=',1)
            if name.strip() in allowed:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
                    value = value[1:-1]
                os.environ.setdefault(name.strip(),value)


def run(args):
    now = datetime.now(timezone.utc)
    configs = load_sources()
    selected = args.sources.split(',') if args.sources else list(CLASSES)
    if any(s not in CLASSES for s in selected):
        raise ValueError('Unknown source')
    url = os.environ.get('DATABASE_URL')
    if args.write_db and not url:
        raise ValueError('DATABASE_URL is required for --write-db; omit the flag for a read-only pilot')
    # Unvalidated adapters may only publish into a local test database.
    if args.pilot and args.write_db and urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'}:
        raise ValueError('Pilot imports require a local test database')
    store = Store(url) if url and (args.write_db or args.providers) else None
    client = PublicClient(browser=args.browser)
    report = {'generated_at':now.isoformat(),'pilot':args.pilot,'sources':{},'accepted':[],'rejected':[], 'providers':{}}
    try:
        if store and args.write_db:
            for platform in ['facebook','tiktok','instagram']:
                store.register(platform,platform.title(),bool(args.pilot or configs.get(platform,{}).get('enabled',False)),platform)
        extra = supplemental_links(client, configs) if args.supplemental else {s:[] for s in selected}
        if args.providers and store:
            search = SerpDiscovery(store)
            for city in ([args.city] if args.city else CITIES):
                try:
                    query = f'"{CITIES[city]}" (sự kiện OR workshop OR cà phê) (site:ticketbox.vn OR site:hanoigrapevine.com OR site:vnexpress.net OR site:ticketgo.vn OR site:danangfantasticity.com)'
                    urls = search.search(query, now)
                    for slug in selected:
                        extra.setdefault(slug, []).extend(u for u in urls if urlsplit(u).hostname in configs[slug]['hosts'])
                except ProviderDisabled as exc:
                    report['providers']['serpapi'] = str(exc)
        primaries = []
        for slug in selected:
            config = configs[slug]
            if not config['enabled'] and not args.pilot:
                if store and args.write_db:
                    store.register(slug,config['name'],False)
                report['sources'][slug] = {'status':'disabled_pending_pilot'}
                continue
            if store and args.write_db:
                store.register(slug, config['name'], True)
            candidates, failures = collect_source(slug, config, client, now, args.limit, extra.get(slug, []))
            reasons = Counter()
            accepted = rejected = 0
            for c in candidates:
                if args.city and c.city_slug and c.city_slug != args.city:
                    continue
                invalid = c.validate(now)
                if invalid:
                    rejected += 1
                    reasons.update(invalid)
                    report['rejected'].append({'source':slug,'url':c.source_url,'title':c.title,'reasons':invalid})
                    if c.status == 'cancelled' and store and args.write_db:
                        store.cancel(slug,c.source_url,now)
                    continue
                if store and args.write_db:
                    store.upsert(c,now)
                accepted += 1
                primaries.append(c)
                report['accepted'].append(c.payload())
            report['sources'][slug] = {'accepted':accepted,'rejected':rejected,'failures':failures,'reasons':dict(reasons)}
            print(json.dumps({'source':slug,'accepted':accepted,'rejected':rejected,'failures':len(failures)}),flush=True)
            if store and args.write_db:
                store.receipt(slug,args.city,accepted,rejected,failures,dict(reasons),now)
        if args.providers and store:
            search, social = SerpDiscovery(store), BrightSocial(store)
            # Resume provider polling even if today's discovery omits yesterday's URL.
            for job in store.submitted('brightdata'):
                try:
                    rows = social.collect(job['input_data']['url'],now)
                    for primary in primaries:
                        for row in rows:
                            evidence = social_evidence(primary,row,job['input_data']['platform'],now)
                            if evidence and not evidence.validate(now) and args.write_db and (args.pilot or configs.get(evidence.source_slug,{}).get('enabled',False)):
                                store.register(evidence.source_slug,evidence.source_name,True,evidence.platform)
                                store.upsert(evidence,now)
                except ProviderDisabled as exc:
                    report['providers']['brightdata'] = str(exc)
            for city in ([args.city] if args.city else CITIES):
                primary = next((c for c in primaries if c.city_slug == city), None)
                if not primary:
                    continue
                try:
                    urls = search.search(f'"{primary.venue_name}" "{CITIES[city]}" (site:facebook.com OR site:tiktok.com OR site:instagram.com)',now)
                except ProviderDisabled as exc:
                    report['providers']['serpapi'] = str(exc)
                    continue
                for target in [u for u in urls if post_platform(u)][:3]:
                    platform = post_platform(target)
                    try:
                        for row in social.collect(target,now):
                            evidence = social_evidence(primary,row,platform,now)
                            if evidence and not evidence.validate(now) and args.write_db and (args.pilot or configs.get(platform,{}).get('enabled',False)):
                                store.register(platform,platform.title(),True,platform)
                                store.upsert(evidence,now)
                    except ProviderDisabled as exc:
                        report['providers']['brightdata'] = str(exc)
        elif args.providers:
            report['providers']['status'] = 'disabled_without_persistent_quota_store'
        if store and args.write_db:
            store.cleanup()
    finally:
        client.close()
        if store:
            store.close()
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'sources':report['sources'],'providers':report['providers'],
                      'accepted_by_city':dict(Counter(c['city_slug'] for c in report['accepted']))},ensure_ascii=False,indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description='Lô free-only trending collectors')
    parser.add_argument('--city',choices=list(CITIES))
    parser.add_argument('--sources',help='Comma-separated source slugs')
    parser.add_argument('--limit',type=int,default=12,help='Maximum detail pages per source (1–30)')
    parser.add_argument('--pilot',action='store_true',help='Inspect disabled adapters; no production imports')
    parser.add_argument('--browser',action='store_true',help='Enable local Playwright for rendered pages')
    parser.add_argument('--supplemental',action='store_true')
    parser.add_argument('--providers',action='store_true',help='Opt in to verified-free providers; missing access is skipped')
    parser.add_argument('--write-db',action='store_true')
    parser.add_argument('--out',help='Optional local audit report (never committed/uploaded automatically)')
    parser.add_argument('--env-file',action='append',default=[],help='Explicit local credentials file (repeatable; never echoed)')
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error('--limit must be between 1 and 30')
    try:
        load_env_files(args.env_file)
        run(args)
    except Exception as exc:
        # Connection/provider exceptions may contain credentials: only print their class.
        print(json.dumps({'status':'failed','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
