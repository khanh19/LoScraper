from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .model import Candidate


class Store:
    def __init__(self, url):
        self.url = url
        self.initial_reconnect = False
        try:
            self.db = psycopg.connect(url, connect_timeout=10, autocommit=True, row_factory=dict_row)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.initial_reconnect = True
            self.db = psycopg.connect(url, connect_timeout=10, autocommit=True, row_factory=dict_row)

    def reconnect(self):
        self.db.close()
        self.db = psycopg.connect(self.url, connect_timeout=10, autocommit=True, row_factory=dict_row)

    def close(self):
        self.db.close()

    def register(self, slug, name, enabled, platform="web"):
        self.db.execute("""INSERT INTO discovery_sources(slug,name,enabled,platform) VALUES (%s,%s,%s,%s)
            ON CONFLICT(slug) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,platform=excluded.platform""",
            (slug,name,enabled,platform))

    def sync_image_permissions(self, records):
        with self.db.transaction():
            self.db.execute('UPDATE discovery_image_permissions SET revoked=true WHERE NOT (id=ANY(%s::text[]))',([p['id'] for p in records],))
            for p in records:
                self.db.execute("""INSERT INTO discovery_image_permissions(id,policy,revoked) VALUES (%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET policy=excluded.policy,revoked=excluded.revoked""",
                    (p['id'],Jsonb(p),bool(p.get('revoked',False))))

    def upsert(self, c: Candidate, now: datetime):
        reasons = c.validate(now)
        if reasons:
            raise ValueError(",".join(reasons))
        p = c.payload()
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-discovery-import',0))")
            known = self.db.execute("SELECT o.item_id,i.kind,i.city_slug,o.published_at FROM discovery_observations o JOIN discovery_items i ON i.id=o.item_id WHERE source_slug=%s AND source_url=%s AND entry_key=%s",
                                    (c.source_slug,c.source_url,c.entry_key)).fetchone()
            if known and (known['kind'] != c.kind or known['city_slug'] != c.city_slug):
                raise ValueError('identity_conflict')
            if known and c.entry_key and c.kind == 'place' and known['published_at']:
                from .model import parse_time
                # A rotating roundup date cannot rejuvenate an existing entry.
                if parse_time(c.published_at) > known['published_at']:
                    from dataclasses import replace
                    c = replace(c,published_at=known['published_at'].isoformat())
                    if c.validate(now):
                        raise ValueError('stale_roundup_evidence')
            existing = known or self.db.execute("SELECT id AS item_id FROM discovery_items WHERE fingerprint=%s",(p['fingerprint'],)).fetchone()
            # Only match an existing place when name AND address AND city agree.
            places = self.db.execute("""SELECT p.id FROM places p JOIN cities c ON c.id=p.city_id
                WHERE p.is_active AND c.slug=%s AND lower(trim(p.name))=lower(trim(%s))
                  AND lower(trim(p.address))=lower(trim(%s)) LIMIT 2""",(c.city_slug,c.venue_name,c.address)).fetchall()
            place_id = places[0]['id'] if len(places)==1 else None
            values = (c.kind,c.city_slug,c.category,p['title_vi'],p['description_vi'],c.title,c.venue_name,c.address,place_id)
            facts = dict(version=1, authority_type=c.authority_type, verified_venue_id=c.verified_venue_id, image_association_verified=c.image_association_verified, image_permission_id=(c.image_permission or {}).get('id'), evidence_locator=c.evidence_locator, kind=c.kind, city_slug=c.city_slug, category=c.category,
                         title_vi=p['title_vi'], description_vi=p['description_vi'], original_title=c.title,
                         venue_name=c.venue_name, address=c.address, price_text=c.price_text,
                         place_id=str(place_id) if place_id else None)
            if existing:
                item_id = existing['item_id']
                if c.platform == "web":
                    self.db.execute("""UPDATE discovery_items SET kind=%s,city_slug=%s,category=%s,title_vi=%s,
                    description_vi=%s,original_title=%s,venue_name=%s,address=%s,place_id=%s,updated_at=now() WHERE id=%s""",(*values,item_id))
            else:
                item_id = self.db.execute("""INSERT INTO discovery_items(kind,city_slug,category,title_vi,description_vi,
                    original_title,venue_name,address,place_id,fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (*values,p['fingerprint'])).fetchone()['id']
            observation_id = self.db.execute("""INSERT INTO discovery_observations
                (item_id,source_slug,source_url,entry_key,owner_key,content_hash,original_text,location_evidence,published_at,verified_at,status,image_url,metrics,facts)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
                ON CONFLICT(source_slug,source_url,entry_key) DO UPDATE SET
                    owner_key=excluded.owner_key,content_hash=excluded.content_hash,original_text=excluded.original_text,
                    location_evidence=excluded.location_evidence,published_at=excluded.published_at,
                    previous_metrics=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
                        THEN discovery_observations.metrics ELSE discovery_observations.previous_metrics END,
                    previous_observed_at=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
                        THEN discovery_observations.verified_at ELSE discovery_observations.previous_observed_at END,
                    metrics=excluded.metrics,verified_at=excluded.verified_at,status='active',image_url=excluded.image_url,facts=excluded.facts
                RETURNING id""",(item_id,c.source_slug,c.source_url,c.entry_key,p['owner_key'],p['content_hash'],p['original_text'],c.location_evidence,
                                 c.published_at,c.verified_at,p['image_url'],Jsonb(c.metrics),Jsonb(facts))).fetchone()['id']
            # Replace occurrences for THIS successfully parsed page only, inside its transaction.
            self.db.execute("DELETE FROM discovery_occurrences WHERE observation_id=%s",(observation_id,))
            for o in c.occurrences:
                self.db.execute("""INSERT INTO discovery_occurrences(observation_id,starts_at,ends_at,precision)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(observation_id,o.starts_at,o.ends_at,o.precision))
        return str(item_id)

    def cancel(self, source_slug, url, now, entry_key=""):
        self.db.execute("""UPDATE discovery_observations SET status='cancelled',verified_at=%s
            WHERE source_slug=%s AND source_url=%s AND entry_key=%s""",(now,source_slug,url,entry_key))

    def start_run(self, sources, cities, source='__run__', parent_id=None):
        run_id = str(uuid4())
        self.db.execute("""INSERT INTO discovery_ingestion_runs
            (id,source_slug,city_slug,status,heartbeat_at,requested_cities,requested_sources,diagnostics)
            VALUES (%s,%s,%s,'running',now(),%s,%s,%s)""",
            (run_id,source,cities[0] if len(cities)==1 else None,cities,sources,
             Jsonb({'parent_id':parent_id} if parent_id else {})))
        return run_id

    def progress(self, run_id, accepted, rejected, failed, diagnostics, status='running'):
        self.db.execute("""UPDATE discovery_ingestion_runs SET heartbeat_at=now(),
            accepted=%s,rejected=%s,failed=%s,diagnostics=%s,status=%s,
            finished_at=CASE WHEN %s='running' THEN NULL ELSE COALESCE(finished_at,now()) END WHERE id=%s""",
            (accepted,rejected,failed,Jsonb(diagnostics),status,status,run_id))

    def receipt(self, source, city, accepted, rejected, failures, reasons, started):
        # Compatibility for callers writing a finished receipt.
        run_id = self.start_run([source], [city] if city else [], source)
        self.progress(run_id,accepted,rejected,len(failures),
                      {'failures':failures,'reasons':reasons},'partial' if failures else 'complete')

    def reserve(self, provider, key, units, cap, remaining, inputs, now, verified_at=None, pilot_id=None):
        month = now.date().replace(day=1)
        if units <= 0 or units > remaining:
            return None
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('lo-quota-'+provider,))
            old = self.db.execute("SELECT * FROM discovery_provider_jobs WHERE job_key=%s",(key,)).fetchone()
            if old:
                old['created_now'] = False
                return old
            if pilot_id:
                pilot=self.db.execute('SELECT id FROM discovery_pilots WHERE id=%s FOR UPDATE',(pilot_id,)).fetchone()
                if not pilot:raise ValueError('unknown_pilot')
                if provider not in {'brightdata','serpapi'}:raise ValueError('invalid_pilot_provider')
                platform=inputs.get('platform')
                if provider=='brightdata' and (units!=1 or platform not in {'facebook','instagram','tiktok'}):
                    raise ValueError('invalid_pilot_record')
                total=self.db.execute('SELECT COALESCE(sum(reserved_units),0) AS used FROM discovery_provider_jobs WHERE pilot_id=%s AND provider=%s',(pilot_id,provider)).fetchone()['used']
                platform_used=self.db.execute("SELECT COALESCE(sum(reserved_units),0) AS used FROM discovery_provider_jobs WHERE pilot_id=%s AND provider=%s AND input_data->>'platform'=%s",(pilot_id,provider,platform)).fetchone()['used']
                if total+units>(9 if provider=='brightdata' else 6) or (provider=='brightdata' and platform_used+units>3):return None
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
            row = self.db.execute("""INSERT INTO discovery_provider_jobs(job_key,provider,billing_month,reserved_units,input_data,pilot_id)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",(key,provider,month,units,Jsonb(inputs),pilot_id)).fetchone()
            row['created_now'] = True
            return row

    def pending(self, provider, url):
        return self.db.execute("""SELECT * FROM discovery_provider_jobs WHERE provider=%s AND input_data->>'url'=%s
            AND status IN ('reserved','unknown','submitted') ORDER BY created_at DESC LIMIT 1""",(provider,url)).fetchone()

    def pilot_job_for_url(self, provider, url, pilot_id):
        # Reuse legacy trailing-slash URLs without resetting reservations.
        return self.db.execute("""SELECT * FROM discovery_provider_jobs WHERE provider=%s AND pilot_id=%s
            AND rtrim(input_data->>'url','/')=rtrim(%s,'/') ORDER BY created_at DESC LIMIT 1""",(provider,pilot_id,url)).fetchone()

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
        self.db.execute("DELETE FROM discovery_provider_jobs WHERE created_at < now() - interval '90 days' AND status='complete' AND pilot_id IS NULL")
        self.db.execute("DELETE FROM discovery_items WHERE updated_at < now() - interval '90 days' AND NOT EXISTS (SELECT 1 FROM discovery_observations o WHERE o.item_id=discovery_items.id AND o.verified_at > now() - interval '90 days')")
