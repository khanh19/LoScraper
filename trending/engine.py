"""Manual multimodal campaign. Without --live this command never contacts providers."""
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

from .__main__ import load_env_files
from .discover import discover,DIRECTORY
from .engine_providers import OpenAI,YouTube,ApifyTikTok,lead_platform,resume_snapshot
from .engine_store import EngineStore,CAMPAIGN
from .http import PublicClient
from .intent import queries,ACTIVITIES
from .model import CITIES,ICT
from .multimodal import normalize_record,process
from .providers import BrightSocial,ProviderDisabled
from .store import Store


def local_store(url):
    p=urlsplit(url or '')
    if p.hostname not in {'127.0.0.1','localhost','::1'} or not p.path.startswith('/lo_'):
        raise ValueError('isolated_local_database_required')
    return Store(url)


def run(args):
    now=datetime.now(timezone.utc);cities=[args.city] if args.city else list(CITIES)
    report={'campaign':CAMPAIGN,'generated_at':now.isoformat(),'live':args.live,'cities':{},'providers':{},
            'routine_social_publication':False,'human_calibration':'pending','published':0}
    ledger_store=feed=legacy=None;ledger=None
    try:
        if args.live or args.health:
            ledger_store=local_store(os.environ.get('OPENAI_DATABASE_URL'))
            ledger=EngineStore(ledger_store)
            if args.health:return ledger.health()
            ledger.expire_content(now)
        if os.environ.get('DATABASE_URL'):
            feed=local_store(os.environ['DATABASE_URL'])
        if 'brightdata' in args.providers and args.live:
            try:
                legacy=local_store(os.environ.get('QUOTA_DATABASE_URL'))
                if not legacy.db.execute('SELECT 1 FROM discovery_provider_jobs LIMIT 1').fetchone():
                    raise ProviderDisabled('canonical_history_missing')
            except Exception:
                if legacy:legacy.close();legacy=None
                report['providers']['brightdata']={'status':'blocked','reason':'canonical_ledger_unavailable'}
        client=PublicClient()
        ai=OpenAI(ledger) if ledger else None
        for city in cities:
            counts={}
            if feed:
                counts={r['category']:r['n'] for r in feed.db.execute("SELECT payload->>'category' category,count(*) n FROM discovery_evaluate_all(%s,%s) WHERE reason='eligible' GROUP BY 1",(now,city)).fetchall()}
            selection=[q for q in queries(city,counts) if not args.category or q['category']==args.category][:args.queries_per_city]
            for q in selection:q['query']+=f' tháng {now.astimezone(ICT).month} năm {now.astimezone(ICT).year}'
            city_report={'queries':selection,'leads':[],'results':[],'errors':[]}
            report['cities'][city]=city_report
            leads={};rows={}
            if args.websites:
                discovered=discover(city,client,now,counts)
                city_report['website_pages']=discovered['pages']
                leads.update({r['url']:r for r in discovered['posts']})
            if not args.live:continue
            for q in selection:
                for provider in args.providers:
                    try:
                        if provider=='openai':
                            for lead in ai.search(q['query'],city,now):leads.setdefault(lead['url'],lead)
                        elif provider=='youtube':
                            for row in YouTube(ledger).search(q['query'],city,now):rows.setdefault(row['url'],row)
                        elif provider=='apify':
                            for row in ApifyTikTok(ledger).discover(q['query'],city,now):rows.setdefault(row['url'],row)
                    except ProviderDisabled as exc:
                        city_report['errors'].append({'provider':provider,'reason':str(exc),'stage':'discovery'})
            if args.youtube_channels and 'youtube' in args.providers:
                channels=[a for seed in json.loads(DIRECTORY.read_text()) if city in seed['cities']
                          for a in seed.get('accounts',[]) if a.get('platform')=='youtube' and a.get('ownership_evidence')]
                for channel in channels[:3]:
                    try:
                        for row in YouTube(ledger).uploads(channel['channel_id'],city,now):rows.setdefault(row['url'],row)
                    except (ProviderDisabled,KeyError,ValueError) as exc:
                        city_report['errors'].append({'provider':'youtube','stage':'reviewed_uploads','reason':type(exc).__name__})
            if args.snapshots:
                for receipt in json.loads(args.snapshots.read_text())[:3]:
                    if receipt.get('city')!=city:continue
                    try:
                        row=resume_snapshot(receipt);rows.setdefault(row['url'],row)
                    except (ProviderDisabled,ValueError) as exc:
                        city_report['errors'].append({'provider':'brightdata','reason':str(exc),'stage':'snapshot_read'})
            if args.web_evidence:
                for lead in [l for l in leads.values() if lead_platform(l['url'])=='web'][:2]:
                    try:
                        soup=client.get(lead['url'],{urlsplit(lead['url']).hostname})
                        published=soup.select_one('meta[property="article:published_time"],meta[name="pubdate"]')
                        for tag in soup.select('script,style,nav,footer,header'):tag.decompose()
                        text=soup.get_text(' ',strip=True)[:12000]
                        rows.setdefault(lead['url'],{'url':lead['url'],'description':text,
                            'date_posted':published.get('content') if published else None})
                    except Exception as exc:city_report['errors'].append({'provider':'website','reason':type(exc).__name__,'stage':'retrieval'})
            if legacy:
                social=BrightSocial(legacy)
                for lead in list(leads.values())[:args.max_candidates]:
                    if lead_platform(lead['url']) not in {'instagram','facebook','tiktok'}:continue
                    try:
                        request,created=ledger.reserve('brightdata','post',{'url':lead['url']},0)
                        if not created and request['status']=='complete' and request['result']:
                            found=request['result']
                        else:
                            ledger.update(request['id'],'unknown')
                            found=social.collect(lead['url'],now)
                            original=legacy.db.execute("SELECT created_at FROM discovery_provider_jobs WHERE provider='brightdata' AND rtrim(input_data->>'url','/')=rtrim(%s,'/') AND status='complete' ORDER BY created_at DESC LIMIT 1",(lead['url'],)).fetchone()
                            if original:
                                found=[{**r,'_source_verified_at':original['created_at'].isoformat()} for r in found]
                            ledger.update(request['id'],'complete',result=found)
                        for row in found:rows.setdefault(row['url'],row)
                    except ProviderDisabled as exc:city_report['errors'].append({'provider':'brightdata','reason':str(exc),'stage':'retrieval'})
            city_report['leads']=list(leads.values())
            from .model import parse_time,folded
            def priority(row):
                published=parse_time(row.get('date_posted'))
                text=folded(str(row.get('description','')))
                local=any(folded(alias) in text for alias in [CITIES[city],{'hcmc':'Sài Gòn','hanoi':'Hanoi','danang':'Danang'}[city]])
                return (not local,not bool(published and (now-published).days<=7),-(published.timestamp() if published else 0),row['url'])
            # Website leads are still collected by dedicated adapters. Search
            # snippets and invented synthetic posts never become evidence here.
            for row in sorted(rows.values(),key=priority)[:args.max_candidates]:
                outcome={'url':row['url'],'platform':lead_platform(row['url']),'retrieval':'passed','published':False}
                try:
                    package=normalize_record(row,outcome['platform'],city,now)
                    if feed:
                        account=feed.db.execute('SELECT * FROM discovery_publisher_accounts WHERE platform=%s AND owner_key=%s AND NOT revoked',
                                               (package['platform'],package['owner_key'])).fetchone()
                        package['authority']=dict(account) if account else None
                        if account:
                            package['verified_venues']=feed.db.execute('SELECT * FROM discovery_verified_venues WHERE publisher_id=%s AND city_slug=%s AND NOT revoked',
                                    (account['publisher_id'],city)).fetchall()
                    ledger.evidence(package)
                    permissions=json.loads(args.media_permissions.read_text()) if args.media_permissions else []
                    outcome.update(process(package,ai,ledger,now,fetch_images=args.images,media_permissions=permissions))
                    outcome['extraction_status']='passed'
                    outcome['validation_status']='passed' if not outcome['reasons'] else 'held'
                except ProviderDisabled as exc:outcome.update(extraction_status='blocked',reason=str(exc))
                except Exception as exc:outcome.update(extraction_status='failed',reason=type(exc).__name__)
                city_report['results'].append(outcome)
            city_report['counts']={'leads':len(leads),'retrieved':len(rows),'processed':len(city_report['results']),
                                    'published':0,'publication_status':'blocked_pending_human_calibration'}
        client.close()
        if ledger:report['accounting']=ledger.health()
        return report
    finally:
        for store in (feed,legacy,ledger_store):
            if store:store.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',action='append',default=[])
    p.add_argument('--city',choices=list(CITIES))
    p.add_argument('--providers',default='openai,youtube,brightdata,apify')
    p.add_argument('--live',action='store_true')
    p.add_argument('--health',action='store_true')
    p.add_argument('--websites',action='store_true',help='Free website leads, even without --live')
    p.add_argument('--images',action='store_true')
    p.add_argument('--web-evidence',action='store_true',help='Read up to two cited public pages per city for shadow extraction')
    p.add_argument('--snapshots',type=Path,help='Receipt list of existing snapshots; GET only, no scraping submission')
    p.add_argument('--media-permissions',type=Path,help='Operator-reviewed analysis permissions; not publisher display rights')
    p.add_argument('--category',choices=list(ACTIVITIES))
    p.add_argument('--youtube-channels',action='store_true',help='Also read up to three ownership-reviewed channel upload lists per city')
    p.add_argument('--queries-per-city',type=int,default=1)
    p.add_argument('--max-candidates',type=int,default=10)
    p.add_argument('--out',type=Path)
    args=p.parse_args();args.providers=args.providers.split(',')
    if set(args.providers)-{'openai','youtube','brightdata','apify'}:p.error('unknown provider')
    if not 1<=args.queries_per_city<=10 or not 1<=args.max_candidates<=30:p.error('invalid campaign bounds')
    try:
        load_env_files(args.env_file)
        result=run(args)
        output=json.dumps(result,ensure_ascii=False,indent=2,default=str)
        if args.out:
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(output)
        print(output)
        return 2 if result.get('providers') or any(c.get('errors') for c in result.get('cities',{}).values()) else 0
    except Exception as exc:
        print(json.dumps({'status':'failed','reason':type(exc).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
