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
from .progress import Progress


def load_env_files(paths):
    # Explicit files only, a small allowlist, no shell evaluation or key logging.
    allowed = {'QUOTA_DATABASE_URL','DATABASE_URL','SERPAPI_API_KEY','BRIGHTDATA_API_KEY','BRIGHT_DATA_API_KEY',
               'BRIGHTDATA_FREE_VERIFICATION_JSON','BRIGHTDATA_BILLING_API_KEY','LO_BROWSER_CHANNEL',
               'OPENAI_API_KEY','YOUTUBE_API_KEY','APIFY_API_KEY','OPENAI_DATABASE_URL',
               'APIFY_FREE_VERIFICATION_JSON','YOUTUBE_QUOTA_VERIFICATION_JSON'}
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
    refresh = getattr(args, "refresh_existing", False)
    configs = load_sources()
    selected = args.sources.split(',') if args.sources else list(CLASSES)
    if any(s not in CLASSES for s in selected):
        raise ValueError('Unknown source')
    url = os.environ.get('DATABASE_URL')
    if refresh and (not args.write_db or args.providers or args.supplemental or args.pilot):
        raise ValueError('Refresh requires --write-db without providers, supplemental discovery or pilot')
    if args.write_db and not url:
        raise ValueError('DATABASE_URL is required for --write-db; omit the flag for a read-only pilot')
    # Unvalidated adapters may only publish into a local test database.
    if args.pilot and args.write_db and urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'}:
        raise ValueError('Pilot imports require a local test database')
    leads = getattr(args, 'lead_url', []) or []
    if leads and refresh:
        raise ValueError('Refresh cannot accept new leads')
    lead_map = {slug: [] for slug in selected}
    for lead in leads:
        matched = [slug for slug in selected if urlsplit(lead).hostname in configs[slug]['hosts']]
        if len(matched) != 1:
            raise ValueError('Lead must match exactly one selected source')
        lead_map[matched[0]].append(lead)
    store = Store(url) if url and (args.write_db or args.providers) else None
    client = PublicClient(browser=args.browser)
    progress = Progress(store if args.write_db else None, selected, [args.city] if args.city else list(CITIES),
                        mode="refresh_existing" if refresh else "discovery")
    report = {'run_id':progress.run_id,'generated_at':now.isoformat(),'pilot':args.pilot,'mode':'refresh_existing' if refresh else 'discovery','sources':{},'accepted':[],'rejected':[], 'providers':{}}
    try:
        if store and args.write_db:
            from .images import permissions
            synced,_=progress.call('sync_image_permissions',permissions(now))
            if not synced:
                progress.available=False
                progress.fatal=True
        if store and args.write_db and args.providers:
            for platform in ['facebook','tiktok','instagram']:
                progress.call('register',platform,platform.title(),bool(args.pilot or configs.get(platform,{}).get('enabled',False)),platform)
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
        for slug, urls in lead_map.items():
            extra[slug] = urls + extra.get(slug, [])
        primaries = []
        for slug in selected:
            config = configs[slug]
            if not config['enabled'] and not args.pilot:
                if store and args.write_db:
                    progress.call('register',slug,config['name'],False)
                report['sources'][slug] = {'status':'disabled_pending_pilot'}
                continue
            stats = progress.start_source(slug)
            if store and args.write_db:
                ok, _ = progress.call('register',slug,config['name'],True)
                if not ok:
                    progress.fail('source_registration_failed')
            try:
                metrics = {}
                known = None
                if refresh:
                    ok, targets = progress.call('refresh_targets',slug,now,args.city)
                    if not ok: raise RuntimeError('refresh_targets_unavailable')
                    urls = list(dict.fromkeys(t['source_url'] for t in targets))
                    selected_urls = urls[:200]
                    known = {(t['source_url'],t['entry_key']) for t in targets if t['source_url'] in selected_urls}
                    candidates, failures = collect_source(slug,config,client,now,200,selected_urls,
                        heartbeat=progress.heartbeat,metrics=metrics,existing_only=True)
                    candidates = [c for c in candidates if (c.source_url,c.entry_key) in known]
                    found = {(c.source_url,c.entry_key) for c in candidates}
                    if known-found: failures.append({'stage':'refresh','reason':'existing_entry_not_recovered'})
                    if len(urls)>200: failures.append({'stage':'refresh','reason':'refresh_page_limit'})
                    metrics.update(existing_entries=len(known),deferred_pages=max(0,len(urls)-200))
                else:
                    candidates, failures = collect_source(slug,config,client,now,args.limit,extra.get(slug,[]),
                                                          heartbeat=progress.heartbeat,metrics=metrics)
                stats.update(metrics)
            except Exception as exc:
                candidates, failures = [], [{'stage':'source','reason':type(exc).__name__}]
            stats['failures'] = failures
            for failure in failures:
                progress.fail(failure['reason'])
            progress.heartbeat()
            for c in candidates:
                city = getattr(c,'city_slug',None)
                if args.city and city and city != args.city:
                    continue
                try:
                    invalid = c.validate(now)
                    if invalid:
                        progress.count('rejected',city,invalid,kind=c.kind)
                        report['rejected'].append({'source':slug,'reasons':invalid,
                            'sample': {k:c.payload().get(k) for k in
                                ('source_url','title','city_slug','published_at','verified_at','venue_name','kind')}})
                        if c.status == 'cancelled' and store and args.write_db:
                            ok,_ = progress.call('cancel',slug,c.source_url,now,c.entry_key)
                            if not ok:
                                progress.count('failed',city,['cancellation_write_failed'])
                        continue
                    payload = c.payload()
                    if store and args.write_db:
                        ok,result = progress.call('upsert',c,now)
                        if result in {'identity_conflict','stale_roundup_evidence'}:
                            progress.count('rejected',city,[result])
                            continue
                        if not ok:
                            progress.count('failed',city,['candidate_write_failed'])
                            continue
                    progress.count('accepted',city,kind=c.kind)
                    primaries.append(c)
                    report['accepted'].append(payload)
                except Exception as exc:
                    progress.count('failed',city,[type(exc).__name__])
            progress.finish_source()
            report['sources'][slug] = stats
            print(json.dumps({'source':slug,**{k:stats[k] for k in ('accepted','rejected','failed','status')}}),flush=True)
        if args.providers and store and progress.available:
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
            progress.call('cleanup', include_provider_jobs=args.providers)
        progress.heartbeat(final=True)
        report['status'] = progress.status()
        report['persistence_errors'] = dict(progress.errors)
    except BaseException as exc:
        progress.fatal = True
        progress.errors[type(exc).__name__] += 1
        progress.heartbeat(final=True)
        print(json.dumps({'run_id':progress.run_id,'status':'failed','counts':progress.totals(),
                          'errors':dict(progress.errors)}),flush=True)
        raise
    finally:
        client.close()
        if store:
            store.close()
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'run_id':report['run_id'],'status':report['status'],
                      'persistence_errors':report['persistence_errors'],
                      'sources':report['sources'],'providers':report['providers'],
                      'accepted_by_city':dict(Counter(c['city_slug'] for c in report['accepted']))},ensure_ascii=False,indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description='Lô free-only trending collectors')
    parser.add_argument('--city',choices=list(CITIES))
    parser.add_argument('--sources',help='Comma-separated source slugs')
    parser.add_argument('--lead-url',action='append',default=[],help='Public detail URL from a selected source; shares the detail-page limit')
    parser.add_argument('--limit',type=int,default=12,help='Maximum detail pages per source (1–30)')
    parser.add_argument('--pilot',action='store_true',help='Inspect disabled adapters; no production imports')
    parser.add_argument('--browser',action='store_true',help='Enable local Playwright for rendered pages')
    parser.add_argument('--supplemental',action='store_true')
    parser.add_argument('--providers',action='store_true',help='Opt in to verified-free providers; missing access is skipped')
    parser.add_argument('--write-db',action='store_true')
    parser.add_argument('--refresh-existing',action='store_true',help='Recheck existing website entries only; no new discovery or providers')
    parser.add_argument('--out',help='Optional local audit report (never committed/uploaded automatically)')
    parser.add_argument('--env-file',action='append',default=[],help='Explicit local credentials file (repeatable; never echoed)')
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error('--limit must be between 1 and 30')
    try:
        load_env_files(args.env_file)
        report = run(args)
        raise SystemExit({'complete':0,'partial':2,'failed':1}[report.get('status','complete')])
    except (Exception, KeyboardInterrupt) as exc:
        # Connection/provider exceptions may contain credentials: only print their class.
        print(json.dumps({'status':'failed','reason':type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
