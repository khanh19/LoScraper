from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .model import Candidate


class Store:
    def __init__(self, url):
        self.db = psycopg.connect(url, connect_timeout=10, autocommit=True, row_factory=dict_row)

    def close(self):
        self.db.close()

    def register(self, slug, name, enabled, platform="web"):
        self.db.execute("""INSERT INTO discovery_sources(slug,name,enabled,platform) VALUES (%s,%s,%s,%s)
            ON CONFLICT(slug) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,platform=excluded.platform""",
            (slug,name,enabled,platform))

    def upsert(self, c: Candidate, now: datetime):
        reasons = c.validate(now)
        if reasons:
            raise ValueError(",".join(reasons))
        p = c.payload()
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-discovery-import',0))")
            known = self.db.execute("SELECT item_id FROM discovery_observations WHERE source_slug=%s AND source_url=%s",
                                    (c.source_slug,c.source_url)).fetchone()
            existing = known or self.db.execute("SELECT id AS item_id FROM discovery_items WHERE fingerprint=%s",(p['fingerprint'],)).fetchone()
            # Only match an existing place when name AND address AND city agree.
            places = self.db.execute("""SELECT p.id FROM places p JOIN cities c ON c.id=p.city_id
                WHERE p.is_active AND c.slug=%s AND lower(trim(p.name))=lower(trim(%s))
                  AND lower(trim(p.address))=lower(trim(%s)) LIMIT 2""",(c.city_slug,c.venue_name,c.address)).fetchall()
            place_id = places[0]['id'] if len(places)==1 else None
            values = (c.kind,c.city_slug,c.category,p['title_vi'],p['description_vi'],c.title,c.venue_name,c.address,place_id)
            if existing:
                item_id = existing['item_id']
                self.db.execute("""UPDATE discovery_items SET kind=%s,city_slug=%s,category=%s,title_vi=%s,
                    description_vi=%s,original_title=%s,venue_name=%s,address=%s,place_id=%s,updated_at=now() WHERE id=%s""",(*values,item_id))
            else:
                item_id = self.db.execute("""INSERT INTO discovery_items(kind,city_slug,category,title_vi,description_vi,
                    original_title,venue_name,address,place_id,fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (*values,p['fingerprint'])).fetchone()['id']
            observation_id = self.db.execute("""INSERT INTO discovery_observations
                (item_id,source_slug,source_url,owner_key,content_hash,original_text,location_evidence,published_at,verified_at,status,image_url,metrics,facts)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
                ON CONFLICT(source_slug,source_url) DO UPDATE SET
                    owner_key=excluded.owner_key,content_hash=excluded.content_hash,original_text=excluded.original_text,
                    location_evidence=excluded.location_evidence,published_at=excluded.published_at,
                    previous_metrics=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
                        THEN discovery_observations.metrics ELSE discovery_observations.previous_metrics END,
                    previous_observed_at=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
                        THEN discovery_observations.verified_at ELSE discovery_observations.previous_observed_at END,
                    metrics=excluded.metrics,verified_at=excluded.verified_at,status='active',image_url=excluded.image_url,facts=excluded.facts
                RETURNING id""",(item_id,c.source_slug,c.source_url,p['owner_key'],p['content_hash'],p['original_text'],c.location_evidence,
                                 c.published_at,c.verified_at,p['image_url'],Jsonb(c.metrics),Jsonb({'price_text':c.price_text}))).fetchone()['id']
            # Replace occurrences for THIS successfully parsed page only, inside its transaction.
            self.db.execute("DELETE FROM discovery_occurrences WHERE observation_id=%s",(observation_id,))
            for o in c.occurrences:
                self.db.execute("""INSERT INTO discovery_occurrences(observation_id,starts_at,ends_at,precision)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(observation_id,o.starts_at,o.ends_at,o.precision))
        return str(item_id)

    def cancel(self, source_slug, url, now):
        self.db.execute("""UPDATE discovery_observations SET status='cancelled',verified_at=%s
            WHERE source_slug=%s AND source_url=%s""",(now,source_slug,url))

    def receipt(self, source, city, accepted, rejected, failures, reasons, started):
        self.db.execute("""INSERT INTO discovery_ingestion_runs
            (source_slug,city_slug,started_at,finished_at,status,accepted,rejected,diagnostics)
            VALUES (%s,%s,%s,now(),%s,%s,%s,%s)""",
            (source,city,started,'partial' if failures else 'complete',accepted,rejected,Jsonb({'failures':failures,'reasons':reasons})))

    def reserve(self, provider, key, units, cap, remaining, inputs, now, verified_at=None):
        month = now.date().replace(day=1)
        if units <= 0 or units > remaining:
            return None
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('lo-quota-'+provider,))
            old = self.db.execute("SELECT * FROM discovery_provider_jobs WHERE job_key=%s",(key,)).fetchone()
            if old:
                old['created_now'] = False
                return old
            used = self.db.execute("SELECT COALESCE(sum(reserved_units),0) AS used FROM discovery_provider_jobs WHERE provider=%s AND billing_month=%s",(provider,month)).fetchone()['used']
            # The remote balance can lag in-flight requests. Conservatively charge
            # unresolved reservations against it as well as against our monthly cap.
            pending = self.db.execute("SELECT COALESCE(sum(reserved_units),0) AS used FROM discovery_provider_jobs WHERE provider=%s AND billing_month=%s AND status <> 'complete'",(provider,month)).fetchone()['used']
            if verified_at:
                # Subtract snapshot usage while holding the reservation lock.
                # Include completed jobs since inspection and older unresolved
                # jobs, even from the previous month. Neither may be re-spent.
                pending = self.db.execute("""SELECT COALESCE(sum(reserved_units),0) AS used
                    FROM discovery_provider_jobs WHERE provider=%s
                    AND (created_at >= %s OR status <> 'complete')""",
                    (provider, verified_at)).fetchone()['used']
            if used + units > cap or pending + units > remaining:
                return None
            row = self.db.execute("""INSERT INTO discovery_provider_jobs(job_key,provider,billing_month,reserved_units,input_data)
                VALUES (%s,%s,%s,%s,%s) RETURNING *""",(key,provider,month,units,Jsonb(inputs))).fetchone()
            row['created_now'] = True
            return row

    def pending(self, provider, url):
        return self.db.execute("""SELECT * FROM discovery_provider_jobs WHERE provider=%s AND input_data->>'url'=%s
            AND status IN ('reserved','unknown','submitted') ORDER BY created_at DESC LIMIT 1""",(provider,url)).fetchone()

    def submitted(self, provider):
        return self.db.execute("SELECT * FROM discovery_provider_jobs WHERE provider=%s AND status='submitted' ORDER BY created_at LIMIT 20",(provider,)).fetchall()

    def job(self, key):
        return self.db.execute("SELECT * FROM discovery_provider_jobs WHERE job_key=%s",(key,)).fetchone()

    def update_job(self, key, status, provider_id=None, result=None):
        self.db.execute("""UPDATE discovery_provider_jobs SET status=%s,provider_job_id=COALESCE(%s,provider_job_id),
            input_data=CASE WHEN %s::jsonb IS NULL THEN input_data ELSE jsonb_set(input_data,'{result}',%s::jsonb) END,
            updated_at=now() WHERE job_key=%s""",(status,provider_id,Jsonb(result) if result is not None else None,
                                               Jsonb(result) if result is not None else None,key))

    def cleanup(self):
        self.db.execute("DELETE FROM discovery_ingestion_runs WHERE started_at < now() - interval '30 days'")
        self.db.execute("DELETE FROM discovery_provider_jobs WHERE created_at < now() - interval '90 days' AND status='complete'")
        self.db.execute("DELETE FROM discovery_items WHERE updated_at < now() - interval '90 days' AND NOT EXISTS (SELECT 1 FROM discovery_observations o WHERE o.item_id=discovery_items.id AND o.verified_at > now() - interval '90 days')")
