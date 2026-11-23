"""Export relevance-reviewed posts for the local app, never publish them."""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

import psycopg
from .engagement import metrics
from .model import folded


def media_references(raw):
    """Post-scoped candidates; neither venue association nor reuse approval."""
    candidates=[raw.get('displayUrl'),(raw.get('videoMeta') or {}).get('coverUrl')]
    candidates += [v.get('displayUrl') for v in (raw.get('childPosts') or []) if isinstance(v,dict)]
    return list(dict.fromkeys(v for v in candidates if isinstance(v,str) and v.startswith('https://')))[:6]


def preview_record(raw, selection, retrieved_at):
    text = str(raw.get('caption') or raw.get('text') or '')[:12000]
    lines = [v.strip() for v in text.splitlines() if v.strip()]
    category = 'cafe' if any(w in folded(text) for w in ('cafe', 'coffee', 'ca phe', 'matcha', 'latte')) else 'restaurant' if any(w in folded(text) for w in ('quan an', 'bun ', 'com ', 'banh ', 'nha hang')) else 'unknown'
    address = next((v for v in lines if re.search(r'🏠|🏡|\b\d+[/\w]*\s+(?:Nguyễn|Trần|Lê|Phan|Đỗ|Hàm|Xuân)', v)), '')
    title=str(selection.get('title') or (lines[0] if lines else 'Bài đăng cộng đồng')).strip()
    if len(title)>80:
        title=title[:77].rsplit(' ',1)[0]+'…'
    return {'source_slug':selection['platform'], 'source_url':selection['url'],
            'title':title,
            'description':text, 'city_slug':selection.get('city'), 'category':category,
            'address_excerpt':address[:500], 'published_at':raw.get('timestamp') or raw.get('createTimeISO'),
            'verified_at':retrieved_at, 'creator':raw.get('ownerUsername') or (raw.get('authorMeta') or {}).get('name',''),
            'engagement':metrics(raw), 'review_scope':'relevance_only',
            'image_permission':'unknown', 'publication':'held'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database-url',required=True);p.add_argument('--selection',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if urlsplit(a.database_url).hostname not in {'localhost','127.0.0.1','::1'}:p.error('local ledger required')
    selected=json.loads(a.selection.read_text())['records']
    if len(selected)>90:p.error('selection limit')
    by_url={v['url'].rstrip('/'):v for v in selected if v.get('approved_relevance') is True and v.get('platform') in {'tiktok','instagram'}}
    found={};media={}
    with psycopg.connect(a.database_url,options='-c default_transaction_read_only=on') as db:
        for data,at in db.execute("SELECT result,created_at FROM discovery_engine_requests WHERE provider='apify' AND status='complete' ORDER BY created_at"):
            for raw in data if isinstance(data,list) else []:
                url=str(raw.get('webVideoUrl') or raw.get('url') or '').rstrip('/')
                if url in by_url and not raw.get('error'):
                    found[url]=preview_record(raw,by_url[url],at.isoformat())
                    media[url]={'images':media_references(raw),'permission':'unverified','association':'post_only'}
    missing=sorted(set(by_url)-set(found))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({'generated_at':datetime.now(timezone.utc).isoformat(),
        'reviewed_social':list(found.values()),'missing':missing},ensure_ascii=False,indent=2)+'\n')
    a.output.with_name('media-candidates.private.json').write_text(json.dumps(media,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'exported':len(found),'missing':len(missing),'published':0}))
    return 2 if missing else 0


if __name__=='__main__':raise SystemExit(main())
