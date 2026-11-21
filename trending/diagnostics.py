"""Local, read-only sample viewer. Never collects, publishes, or contacts providers."""
import argparse
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import psycopg
from psycopg.rows import dict_row

SOURCES = ['instagram', 'facebook', 'youtube', 'tiktok', 'vietnamnightlife',
           'ticketbox', 'hanoigrapevine', 'danangfantasticity', 'vnexpress',
           'ticketgo', 'lifeofdanang', 'saigoneer', 'visithcmc', 'threads']


def safe_url(value):
    try:
        u = urlsplit(value or '')
        if u.scheme != 'https' or not u.hostname or u.username or u.password:
            return ''
        # Never expose signed media tokens or arbitrary query strings.
        query = urlencode({'v': parse_qs(u.query)['v'][0]}) if u.hostname in {'www.youtube.com','youtube.com'} and 'v' in parse_qs(u.query) else ''
        return urlunsplit(('https',u.hostname,u.path,query,''))
    except ValueError:
        return ''


def sample(c, reasons, stage):
    return {'url':safe_url(c.get('source_url',c.get('url'))),
            'title':str(c.get('title') or c.get('venue_name') or 'Bản ghi nguồn')[:240],
            'city':c.get('city_slug',c.get('city_hint')),
            'published_at':str(c.get('published_at') or ''),
            'retrieved_at':str(c.get('verified_at',c.get('fetched_at')) or ''),
            'stage':stage,'reasons':[str(r)[:160] for r in reasons][:12]}


def snapshot(reports, engine_url):
    groups = {s:{'source':s,'samples':[],'counts':{},'status':'not_collected'} for s in SOURCES}
    seen = set()
    loaded = sorted((json.loads(Path(path).read_text()) for path in reports), key=lambda p:p.get('generated_at',''))
    reviewed=[]
    for p in loaded:
        for c in p.get('reviewed_social',[])[:90]:
            item=sample(c,['Thông tin từ bài gốc; chưa xác minh độc lập'],'relevance_reviewed_not_published')
            if not item['url'] or c.get('source_slug') not in ('tiktok','instagram'):continue
            item.update(source=c['source_slug'],description=str(c.get('description',''))[:12000],
                        category=c.get('category','experience'),engagement=c.get('engagement',{}),
                        address_excerpt=str(c.get('address_excerpt',''))[:500],
                        image_status='illustrative_permission_pending',creator=str(c.get('creator',''))[:100])
            if item['url'] not in {v['url'] for v in reviewed}:reviewed.append(item)
        for slug,stats in p.get('sources',{}).items():
            g=groups.setdefault(slug,{'source':slug,'samples':[]})
            g.update(counts={k:stats.get(k,0) for k in ('accepted','rejected','failed','detail_pages','extracted_entries')},status=stats.get('status'),last_run=p.get('generated_at'), reason_summary=stats.get('reasons',{}))
        rows=[(c.get('source_slug'),c,[], 'collector_accepted_not_feed_confirmation') for c in p.get('accepted',[])]
        rows += [(c.get('source'),c.get('sample',{}),c.get('reasons',[]),'withheld') for c in p.get('rejected',[]) if c.get('sample')]
        for slug,c,reasons,stage in rows:
            item=sample(c,reasons,stage);key=(slug,item['url'],item['title'])
            if slug in groups and item['url'] and key not in seen:
                seen.add(key);groups[slug]['samples'].append(item)
    if engine_url:
        if urlsplit(engine_url).hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('local_accounting_only')
        with psycopg.connect(engine_url,row_factory=dict_row,options='-c default_transaction_read_only=on') as db:
            rows=db.execute('SELECT source_url,platform,record,reasons,judgment FROM discovery_engine_evidence WHERE retain_until > now() ORDER BY fetched_at DESC,id').fetchall()
            for row in rows:
                slug=row['platform']
                if slug not in groups:continue
                c=dict(row['record']);c['url']=row['source_url']
                texts=[v.get('text','') for v in c.get('sources',[]) if isinstance(v,dict)]
                c['title']=' '.join(texts)[:240] or slug
                item=sample(c,row['reasons'] or ['publication_not_approved'],'retrieved_not_published')
                if item['url'] not in {v['url'] for v in groups[slug]['samples']}:
                    groups[slug]['samples'].append(item)
                groups[slug]['status']='retrieved'
    groups['facebook']['note']='New retrieval blocked: historical quota ledger unavailable.'
    groups['threads']['note']='Dedicated retrieval not validated; link discovery only.'
    groups['visithcmc']['note']='Supplemental discovery only; no dedicated collector sample.'
    for g in groups.values():
        g['available_samples']=len(g['samples']);g['samples']=g['samples'][:5]
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'groups':list(groups.values()),'reviewed_social':reviewed,'read_only':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',action='append',required=True)
    parser.add_argument('--port',type=int,default=4110)
    args=parser.parse_args()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            origin=self.headers.get('Origin','')
            if self.headers.get('Host') not in {f'localhost:{args.port}',f'127.0.0.1:{args.port}'} or (origin and (urlsplit(origin).hostname not in {'localhost','127.0.0.1'} or urlsplit(origin).scheme!='http')):
                self.send_error(403);return
            if self.path!='/samples':self.send_error(404);return
            try:data=snapshot(args.report,os.environ.get('LO_DIAGNOSTICS_ENGINE_DATABASE_URL'))
            except Exception:data={'error':'diagnostic_store_unavailable'}
            body=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(503 if 'error' in data else 200)
            if origin:self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    print(f'Local read-only diagnostics: http://localhost:{args.port}/samples',flush=True)
    HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__':main()
