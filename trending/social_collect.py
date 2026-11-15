"""Manual, automatically discovered social pilot; no user-supplied post URLs required."""
import argparse,json,os
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .__main__ import load_env_files
from .discover import discover
from .http import PublicClient
from .model import CITIES
from .pilot import PILOT_ID
from .providers import BrightSocial,ProviderDisabled
from .announcements import announcement
from .store import Store


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city',choices=list(CITIES),required=True)
    p.add_argument('--env-file',action='append',default=[])
    p.add_argument('--providers',action='store_true',help='Use remaining existing pilot reservations; never resets caps')
    p.add_argument('--write-db',action='store_true',help='Import only publication-enabled reviewed organizers in isolated preview')
    args=p.parse_args();load_env_files(args.env_file)
    now=datetime.now(timezone.utc)
    result=discover(args.city,PublicClient(),now)
    result['collection']=[]
    if not args.providers:
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    feed_url=os.environ.get('DATABASE_URL','');ledger_url=os.environ.get('QUOTA_DATABASE_URL','')
    if feed_url==ledger_url or any(urlsplit(u).hostname not in {'127.0.0.1','localhost','::1'} for u in (feed_url,ledger_url)) or not urlsplit(feed_url).path.startswith('/lo_setup_check_'):
        p.error('separate isolated feed and existing canonical quota ledger required')
    feed=Store(feed_url);ledger=Store(ledger_url)
    try:
        social=BrightSocial(ledger,pilot_id=PILOT_ID)
        attempted={}
        # Also resume existing known jobs if a webpage no longer lists the post.
        pending=ledger.db.execute("SELECT input_data FROM discovery_provider_jobs WHERE pilot_id=%s AND provider='brightdata' AND status='submitted'",(PILOT_ID,)).fetchall()
        leads={r['url']:r for r in result['posts']}
        for r in pending:
            url=r['input_data']['url']
            if url not in leads:leads[url]={'url':url,'platform':r['input_data']['platform'],'publisher_id':None}
        for lead in leads.values():
            platform=lead['platform']
            if platform not in {'instagram','tiktok','facebook'} or attempted.get(platform,0)>=3:continue
            status={'url':lead['url'],'platform':platform,'published':False}
            try:
                # Retrieval is bounded even when independent venue evidence is not ready.
                attempted[platform]=attempted.get(platform,0)+1
                rows=social.collect(lead['url'],now)
                status.update(status='retrieved',records=len(rows))
                for row in rows:
                    owner=str(row.get('profile_url') or row.get('user_url') or row.get('user_posted') or '').rstrip('/')
                    account=feed.db.execute("SELECT * FROM discovery_publisher_accounts WHERE platform=%s AND rtrim(owner_key,'/')=%s AND NOT revoked",(platform,owner)).fetchone()
                    if not account:status['reason']='unreviewed_account';continue
                    venues=feed.db.execute('SELECT * FROM discovery_verified_venues WHERE publisher_id=%s AND city_slug=%s AND NOT revoked',(account['publisher_id'],args.city)).fetchall()
                    matches=[];reasons=[]
                    for venue in venues:
                        candidate,reason=announcement(row,account,venue,now)
                        if candidate:matches.append(candidate)
                        else:reasons.append(reason)
                    if len(matches)!=1:status['reason']='ambiguous_destination' if len(matches)>1 else (reasons[0] if reasons else 'no_independent_venue');continue
                    if not account['publication_enabled']:status['reason']='publication_gated';continue
                    if args.write_db:
                        feed.register(platform,platform.title(),True,platform)
                        item_id=feed.upsert(matches[0],now)
                        evaluation=feed.db.execute("SELECT reason FROM discovery_evaluate_all(%s,%s) WHERE item_id=%s::uuid",(now,args.city,item_id)).fetchone()
                        status['published']=bool(evaluation and evaluation['reason']=='eligible')
                        status['reason']=evaluation['reason'] if evaluation else 'withheld'
            except ProviderDisabled as exc:status.update(status='blocked',reason=str(exc))
            result['collection'].append(status)
        result['published']=sum(r['published'] for r in result['collection'])
        result['accounting']=ledger.db.execute("SELECT provider,status,count(*) AS jobs,sum(reserved_units) AS units FROM discovery_provider_jobs WHERE pilot_id=%s GROUP BY 1,2",(PILOT_ID,)).fetchall()
    finally:feed.close();ledger.close()
    print(json.dumps(result,ensure_ascii=False,default=str,indent=2))
    return 2 if any(r.get('reason') not in (None,'eligible') for r in result['collection']) else 0

if __name__=='__main__':raise SystemExit(main())
