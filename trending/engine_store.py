"""Durable, conservative campaign accounting. Dollar amounts are integer microdollars.

Unknown/failed requests keep their full reservation. New campaign names cannot
reset the lifetime OpenAI ceiling. Never initialize this store as a replacement
for the lost legacy Bright Data/SerpAPI ledger.
"""
import hashlib
import json
from datetime import timedelta

from psycopg.types.json import Jsonb
from .providers import ProviderDisabled

CAMPAIGN = 'multimodal-v1'
CAPS = {'openai': 30_000_000, 'apify': 3_000_000, 'youtube': 0, 'brightdata': 0}
UNIT_CAPS = {'apify': 90, 'youtube': 1200, 'brightdata': 150, 'openai': 500}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class EngineStore:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def key(self, provider, operation, inputs):
        return digest([CAMPAIGN, provider, operation, inputs])

    def get(self, key):
        return self.db.execute('SELECT * FROM discovery_engine_requests WHERE id=%s', (key,)).fetchone()

    def reserve(self, provider, operation, inputs, micros, units=1, remaining=None, verified_at=None):
        if provider not in CAPS or type(micros) is not int or micros < 0 or type(units) is not int or units < 1:
            raise ValueError('invalid_reservation')
        key = self.key(provider, operation, inputs)
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-engine-accounting',0))")
            old = self.get(key)
            if old:
                return old, False
            if self.db.execute('SELECT 1 FROM discovery_engine_requests WHERE actual_usd_micros > reserved_usd_micros LIMIT 1').fetchone():
                raise ProviderDisabled('accounting_overrun_requires_review')
            operation_cap = {('youtube','search'):12, ('openai','web_search'):30}.get((provider,operation))
            if operation_cap and self.db.execute('SELECT count(*) n FROM discovery_engine_requests WHERE campaign=%s AND provider=%s AND operation=%s',
                    (CAMPAIGN,provider,operation)).fetchone()['n'] >= operation_cap:
                raise ProviderDisabled('operation_budget_exhausted')
            totals = self.db.execute('''SELECT
                coalesce(sum(greatest(reserved_usd_micros,coalesce(actual_usd_micros,0))) FILTER(WHERE campaign=%s),0) campaign_usd,
                coalesce(sum(units) FILTER(WHERE campaign=%s),0) campaign_units,
                coalesce(sum(greatest(reserved_usd_micros,coalesce(actual_usd_micros,0))),0) lifetime
                FROM discovery_engine_requests WHERE provider=%s''', (CAMPAIGN,CAMPAIGN,provider)).fetchone()
            if totals['campaign_usd'] + micros > CAPS[provider] or totals['campaign_units'] + units > UNIT_CAPS[provider]:
                raise ProviderDisabled('campaign_budget_exhausted')
            if provider == 'openai' and totals['lifetime'] + micros > 250_000_000:
                raise ProviderDisabled('openai_lifetime_budget_exhausted')
            if remaining is not None:
                # Snapshot balances may lag; count all use since verification and
                # unresolved older reservations, never just completed jobs.
                pending = self.db.execute('''SELECT coalesce(sum(units),0) n FROM discovery_engine_requests
                    WHERE provider=%s AND (created_at >= %s OR status <> 'complete')''',
                    (provider,verified_at)).fetchone()['n']
                if units + pending > remaining:
                    raise ProviderDisabled('verified_allowance_exhausted')
            row = self.db.execute('''INSERT INTO discovery_engine_requests
                (id,campaign,provider,operation,status,reserved_usd_micros,units,input_hash)
                VALUES (%s,%s,%s,%s,'reserved',%s,%s,%s) RETURNING *''',
                (key,CAMPAIGN,provider,operation,micros,units,digest(inputs))).fetchone()
            return row, True

    def update(self, key, status, result=None, usage=None, actual=None, provider_id=None):
        self.db.execute('''UPDATE discovery_engine_requests SET status=%s,
            result=coalesce(%s,result),usage=coalesce(usage,'{}'::jsonb)||coalesce(%s,'{}'::jsonb),
            actual_usd_micros=coalesce(%s,actual_usd_micros),
            provider_job_id=coalesce(%s,provider_job_id),updated_at=now() WHERE id=%s''',
            (status,Jsonb(result) if result is not None else None,Jsonb(usage) if usage is not None else None,
             actual,provider_id,key))

    def evidence(self, package, extraction=None, judgment=None, reasons=()):
        identity = digest([package['url'],package['content_hash'],package['city_hint'],'lo-evidence-v2'])
        # No data URLs/audio/video bytes are persisted. Media URLs are references.
        record = json.loads(json.dumps({k:v for k,v in package.items() if k not in {'image_inputs','audio_bytes'}},default=str))
        self.db.execute('''INSERT INTO discovery_engine_evidence
            (id,source_url,platform,city_hint,content_hash,fetched_at,retain_until,record,extraction,judgment,model_versions,reasons)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET record=CASE WHEN excluded.extraction IS NULL THEN discovery_engine_evidence.record ELSE excluded.record END,extraction=coalesce(excluded.extraction,discovery_engine_evidence.extraction),
            judgment=coalesce(excluded.judgment,discovery_engine_evidence.judgment),reasons=CASE WHEN excluded.extraction IS NULL THEN discovery_engine_evidence.reasons ELSE excluded.reasons END,updated_at=now()''',
            (identity,package['url'],package['platform'],package['city_hint'],package['content_hash'],package['fetched_at'],
             package['fetched_at']+timedelta(days=29),Jsonb(record),Jsonb(extraction) if extraction is not None else None,Jsonb(judgment) if judgment is not None else None,
             Jsonb({'extractor':'gpt-5.4-mini-2026-03-17','judge':'gpt-6-astra','prompt':'lo-evidence-v2'}),Jsonb(list(reasons))))
        return identity

    def health(self):
        rows = self.db.execute('''SELECT provider,operation,status,count(*) requests,sum(units) units,
            sum(reserved_usd_micros) reserved_usd_micros,sum(actual_usd_micros) actual_usd_micros
            FROM discovery_engine_requests GROUP BY 1,2,3 ORDER BY 1,2,3''').fetchall()
        evidence = self.db.execute('''SELECT city_hint,platform,coalesce(judgment->>'verdict','not_judged') verdict,
            count(*) records FROM discovery_engine_evidence GROUP BY 1,2,3 ORDER BY 1,2,3''').fetchall()
        reasons=self.db.execute("SELECT reason,count(*) records FROM discovery_engine_evidence CROSS JOIN LATERAL jsonb_array_elements_text(reasons) reason GROUP BY reason ORDER BY records DESC,reason").fetchall()
        modalities=self.db.execute("SELECT platform,count(*) records,sum(jsonb_array_length(coalesce(record->'analyzed_images','[]'))) analyzed_images,count(*) FILTER(WHERE discovery_item_id IS NOT NULL) linked_items FROM discovery_engine_evidence GROUP BY platform ORDER BY platform").fetchall()
        totals=self.db.execute("SELECT coalesce(sum(actual_usd_micros),0) estimated_cost FROM discovery_engine_requests").fetchone()
        published=self.db.execute("SELECT count(DISTINCT discovery_item_id) n FROM discovery_engine_evidence WHERE discovery_item_id IS NOT NULL").fetchone()['n']
        return {'label':'Local accounting, not provider balance','requests':rows,'evidence':evidence,'held_reasons':reasons,'modality_coverage':modalities,
                'cost_per_linked_item_usd':totals['estimated_cost']/1000000/published if published else None,
                'cost_note':'OpenAI usage cost estimated from published rates; reservations remain conservative. Apify reports provider usage.',
                'campaign':CAMPAIGN,'openai_campaign_cap_usd':30,'openai_lifetime_cap_usd':250,
                'routine_social_publication':False,'human_calibration':'pending'}

    def expire_content(self, now):
        # Keep accounting forever while removing cached content within 30 days.
        self.db.execute("UPDATE discovery_engine_requests SET result=NULL WHERE created_at < %s-interval '29 days' AND result IS NOT NULL",(now,))
        self.db.execute('DELETE FROM discovery_engine_evidence WHERE retain_until < %s',(now,))
