"""Offline reference inventory. Reference usefulness is not live eligibility.

Accepts exported sheet rows (A..AC) and cached public retrieval results. Never
contacts providers, changes a sheet, or treats a caption as a watched video.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def post_identity(url):
    parts=urlsplit(url or '')
    host=(parts.hostname or '').lower()
    if host in {'tiktok.com','www.tiktok.com','m.tiktok.com'}:
        match=re.search(r'/(?:video|photo)/(\d+)(?:/|$)',parts.path)
        if match:return 'tiktok:'+match[1]
    if host in {'instagram.com','www.instagram.com'}:
        match=re.match(r'/(?:p|reel|reels)/([\w-]+)(?:/|$)',parts.path)
        if match:return 'instagram:'+match[1]
    return None  # Short links must actually be resolved before identity is known.


def inventory(rows, retrieved):
    result=[]
    by_url=retrieved if isinstance(retrieved,dict) else {r['url']:r for r in retrieved}
    for row in rows:
        url=row.get('C','')
        if not url:continue
        record=by_url.get(url,{})
        resolved=record.get('resolved_url') or url
        identity=post_identity(resolved) or post_identity(url)
        result.append({'sample_id':row.get('A'),'sheet_row':row.get('row'),
            'original_url':url,'resolved_url':resolved,'post_identity':identity,
            'reference_usefulness':'unassessed','publication_readiness':'unassessed',
            'coverage':{'caption':'retrieved' if record.get('caption') else 'unavailable',
                        'video':'not_reviewed','carousel':'not_reviewed',
                        'audio':'not_reviewed','comments':'not_reviewed'},
            'retrieval_status':record.get('status','not_retrieved'),
            'duplicate_sample_ids':[]})
    groups={}
    for item in result:
        if item['post_identity']:groups.setdefault(item['post_identity'],[]).append(item['sample_id'])
    for item in result:
        item['duplicate_sample_ids']=[i for i in groups.get(item['post_identity'],[]) if i!=item['sample_id']]
    return {'schema_version':1,'samples':result,'sample_count':len(result),
            'resolved_post_count':len(groups),
            'unresolved_identity_count':sum(r['post_identity'] is None for r in result),
            'holdout_exclusions':sorted(groups)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',required=True,type=Path)
    parser.add_argument('--retrieved',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    report=inventory(json.loads(args.rows.read_text()),json.loads(args.retrieved.read_text()))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'samples','holdout_exclusions'}}))


if __name__=='__main__':main()
