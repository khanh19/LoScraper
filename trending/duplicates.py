"""Manual embedding suggestions among already eligible items; never merge records."""
import argparse,json,os
from datetime import datetime,timezone
from .__main__ import load_env_files
from .engine import local_store
from .engine_providers import OpenAI
from .engine_store import EngineStore
from .multimodal import similar_candidates
from .model import CITIES


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',action='append',default=[])
    p.add_argument('--city',choices=list(CITIES),required=True)
    p.add_argument('--live',action='store_true',help='Explicitly authorize metered embeddings within the fixed campaign')
    args=p.parse_args();load_env_files(args.env_file)
    if not args.live:p.error('--live required; no automatic embedding requests')
    feed=local_store(os.environ.get('DATABASE_URL'));ledger=local_store(os.environ.get('OPENAI_DATABASE_URL'))
    try:
        rows=feed.db.execute("SELECT item_id::text id,payload FROM discovery_evaluate_all(%s,%s) WHERE reason='eligible' ORDER BY item_id LIMIT 30",(datetime.now(timezone.utc),args.city)).fetchall()
        ai=OpenAI(EngineStore(ledger));vectors=[]
        for r in rows:
            item=r['payload']
            vectors.append({'id':r['id'],'city_slug':args.city,'category':item['category'],
                            'embedding':ai.embed(json.dumps({k:item.get(k) for k in ['title_vi','venue_name','address']},ensure_ascii=False))})
        out=[{'id':v['id'],'suggestions':similar_candidates(v['embedding'],[o for o in vectors if o['id']!=v['id']],args.city,v['category'])} for v in vectors]
        print(json.dumps({'suggestions':out,'merged':0,'requires_operator_review':True},ensure_ascii=False))
    finally:feed.close();ledger.close()


if __name__=='__main__':main()
