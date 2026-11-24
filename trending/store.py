from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .model import CONFIRMED_SCHEDULE_CONFLICT, Candidate, parse_time


SOURCE_UPSERT = """INSERT INTO discovery_sources(slug,name,enabled,platform) VALUES (%s,%s,%s,%s)
ON CONFLICT(slug) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,platform=excluded.platform"""

IMAGE_PERMISSIONS_REVOKE = 'UPDATE discovery_image_permissions SET revoked=true WHERE NOT (id=ANY(%s::text[]))'

IMAGE_PERMISSION_UPSERT = """INSERT INTO discovery_image_permissions(id,policy,revoked) VALUES (%s,%s,%s)
ON CONFLICT(id) DO UPDATE SET policy=excluded.policy,revoked=excluded.revoked"""

REFRESH_TARGETS = """SELECT o.source_url,o.entry_key,i.city_slug,o.verified_at
FROM discovery_observations o JOIN discovery_items i ON i.id=o.item_id
JOIN discovery_sources s ON s.slug=o.source_slug
WHERE o.source_slug=%s AND s.platform='web' AND s.enabled AND o.status='active'
AND (%s::text IS NULL OR i.city_slug=%s)
AND ((i.kind='place' AND o.published_at BETWEEN %s::timestamptz-interval '7 days' AND %s)
  OR (i.kind='event' AND (o.schedule_held_at > %s::timestamptz-interval '7 days'
       OR EXISTS (SELECT 1 FROM discovery_occurrences x
       WHERE x.observation_id=o.id AND x.ends_at>%s AND x.starts_at<%s::timestamptz+interval '30 days'))))
ORDER BY GREATEST(o.verified_at,o.schedule_held_at),o.source_url,o.entry_key"""

PLACE_MATCH = """SELECT p.id FROM places p JOIN cities c ON c.id=p.city_id
WHERE p.is_active AND c.slug=%s AND lower(trim(p.name))=lower(trim(%s))
  AND lower(trim(p.address))=lower(trim(%s)) LIMIT 2"""

ITEM_UPDATE = """UPDATE discovery_items SET kind=%s,city_slug=%s,category=%s,title_vi=%s,
description_vi=%s,original_title=%s,venue_name=%s,address=%s,place_id=%s,updated_at=now() WHERE id=%s"""

ITEM_INSERT = """INSERT INTO discovery_items(kind,city_slug,category,title_vi,description_vi,
original_title,venue_name,address,place_id,fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id"""

OBSERVATION_UPSERT = """INSERT INTO discovery_observations
(item_id,source_slug,source_url,entry_key,owner_key,content_hash,original_text,location_evidence,published_at,verified_at,status,image_url,metrics,facts)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
ON CONFLICT(source_slug,source_url,entry_key) DO UPDATE SET
    owner_key=excluded.owner_key,content_hash=excluded.content_hash,original_text=excluded.original_text,
    location_evidence=excluded.location_evidence,published_at=excluded.published_at,
    previous_metrics=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
        THEN discovery_observations.metrics ELSE discovery_observations.previous_metrics END,
    previous_observed_at=CASE WHEN discovery_observations.verified_at < excluded.verified_at - interval '1 hour'
        THEN discovery_observations.verified_at ELSE discovery_observations.previous_observed_at END,
    metrics=excluded.metrics,verified_at=excluded.verified_at,status='active',schedule_held_at=NULL,
    image_url=excluded.image_url,facts=excluded.facts
RETURNING id"""

SESSION_DELETE = "DELETE FROM discovery_occurrences WHERE observation_id=%s"

SESSION_INSERT = """INSERT INTO discovery_occurrences(observation_id,starts_at,ends_at,precision)
SELECT %s, starts_at, ends_at, precision
FROM unnest(%s::timestamptz[], %s::timestamptz[], %s::text[])
    AS sessions(starts_at, ends_at, precision)
ON CONFLICT DO NOTHING"""

RUN_INSERT = """INSERT INTO discovery_ingestion_runs
(id,source_slug,city_slug,status,heartbeat_at,requested_cities,requested_sources,diagnostics)
VALUES (%s,%s,%s,'running',now(),%s,%s,%s)"""

RUN_PROGRESS = """UPDATE discovery_ingestion_runs SET heartbeat_at=now(),
accepted=%s,rejected=%s,failed=%s,diagnostics=%s,status=%s,
finished_at=CASE WHEN %s='running' THEN NULL ELSE COALESCE(finished_at,now()) END WHERE id=%s"""

RUN_CLEANUP = "DELETE FROM discovery_ingestion_runs WHERE started_at < now() - interval '30 days'"

ITEM_CLEANUP = "DELETE FROM discovery_items WHERE updated_at < now() - interval '90 days' AND NOT EXISTS (SELECT 1 FROM discovery_observations o WHERE o.item_id=discovery_items.id AND o.verified_at > now() - interval '90 days')"

# Use the collector's statements to check its grants without executing writes.
WEBSITE_COLLECTION_PLANS = (
    ('source_registration', SOURCE_UPSERT),
    ('image_permission_revoke', IMAGE_PERMISSIONS_REVOKE),
    ('image_permission_upsert', IMAGE_PERMISSION_UPSERT),
    ('refresh_selection', REFRESH_TARGETS),
    ('place_match', PLACE_MATCH),
    ('item_update', ITEM_UPDATE),
    ('item_insert', ITEM_INSERT),
    ('observation_upsert', OBSERVATION_UPSERT),
    ('session_replace', SESSION_DELETE),
    ('session_insert', SESSION_INSERT),
    ('receipt_insert', RUN_INSERT),
    ('receipt_update', RUN_PROGRESS),
    ('receipt_cleanup', RUN_CLEANUP),
    ('item_cleanup', ITEM_CLEANUP),
)


class DatabaseTargetError(ValueError):
    pass


def validate_expected_target(expected):
    if not expected:
        raise DatabaseTargetError('missing_database_target')
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise DatabaseTargetError('invalid_database_target')


def database_target(db, expected=None):
    """Identify the connected endpoint and login without exposing connection values."""
    info = db.info
    identity = ['lo-discovery-target-v1', info.host.lower().rstrip('.'), info.port, info.dbname, info.user]
    fingerprint = sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
    if expected is not None and fingerprint != expected:
        raise DatabaseTargetError('database_target_mismatch')
    return fingerprint


class Store:
    def __init__(self, url, *, expected_target=None):
        self.url = url
        self.expected_target = expected_target
        if expected_target is not None:
            validate_expected_target(expected_target)
        self.initial_reconnect = False
        try:
            self.db = self._connect()
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.initial_reconnect = True
            self.db = self._connect()

    def _connect(self):
        db = psycopg.connect(self.url, connect_timeout=10, autocommit=True, row_factory=dict_row)
        try:
            if self.expected_target is not None:
                database_target(db, self.expected_target)
            # A pooled session may retain older role defaults. Set the guard for each connection.
            db.execute("SET idle_in_transaction_session_timeout = '60s'")
        except (DatabaseTargetError, psycopg.Error):
            db.close()
            raise
        return db

    def reconnect(self):
        self.db.close()
        self.db = self._connect()

    def close(self):
        self.db.close()

    def register(self, slug, name, enabled, platform="web"):
        self.db.execute(SOURCE_UPSERT,
            (slug,name,enabled,platform))

    def sync_image_permissions(self, records):
        with self.db.transaction():
            self.db.execute(IMAGE_PERMISSIONS_REVOKE,([p['id'] for p in records],))
            for p in records:
                self.db.execute(IMAGE_PERMISSION_UPSERT,
                    (p['id'],Jsonb(p),bool(p.get('revoked',False))))

    def refresh_targets(self, slug, now, city=None):
        """Existing website observations only; oldest checks first, no provider calls."""
        return self.db.execute(REFRESH_TARGETS,
            (slug,city,city,now,now,now,now,now)).fetchall()

    def upsert(self, c: Candidate, now: datetime):
        reasons = c.validate(now)
        if reasons:
            raise ValueError(",".join(reasons))
        p = c.payload()
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-discovery-import',0))")
            known = self.db.execute("""SELECT o.id,o.item_id,i.kind,i.city_slug,i.fingerprint,o.published_at,o.verified_at,o.schedule_held_at
                FROM discovery_observations o JOIN discovery_items i ON i.id=o.item_id
                WHERE source_slug=%s AND source_url=%s AND entry_key=%s""",
                                    (c.source_slug,c.source_url,c.entry_key)).fetchone()
            moving = False
            if not known and c.replaces_source_url and c.kind == 'event' and c.platform == 'web':
                known = self.db.execute("""SELECT o.id,o.item_id,i.kind,i.city_slug,i.fingerprint,
                    o.published_at,o.verified_at,o.schedule_held_at
                    FROM discovery_observations o JOIN discovery_items i ON i.id=o.item_id
                    WHERE source_slug=%s AND source_url=%s AND entry_key=''""",
                                        (c.source_slug,c.replaces_source_url)).fetchone()
                moving = known is not None
                if moving and known['fingerprint'] != p['fingerprint']:
                    raise ValueError('identity_conflict')
            if known and (known['kind'] != c.kind or known['city_slug'] != c.city_slug):
                raise ValueError('identity_conflict')
            if known:
                checked_at = parse_time(c.verified_at)
                held_at = known['schedule_held_at']
                if checked_at < known['verified_at'] or (held_at and checked_at <= held_at):
                    raise ValueError('stale_observation')
            if known and c.entry_key and c.kind == 'place' and known['published_at']:
                # A rotating roundup date cannot rejuvenate an existing entry.
                if parse_time(c.published_at) > known['published_at']:
                    from dataclasses import replace
                    c = replace(c,published_at=known['published_at'].isoformat())
                    if c.validate(now):
                        raise ValueError('stale_roundup_evidence')
            if moving:
                self.db.execute("""UPDATE discovery_observations SET source_url=%s,entry_key=%s
                    WHERE id=%s""", (c.source_url,c.entry_key,known['id']))
            existing = known or self.db.execute("SELECT id AS item_id FROM discovery_items WHERE fingerprint=%s",(p['fingerprint'],)).fetchone()
            # Only match an existing place when name AND address AND city agree.
            places = self.db.execute(PLACE_MATCH,(c.city_slug,c.venue_name,c.address)).fetchall()
            place_id = places[0]['id'] if len(places)==1 else None
            values = (c.kind,c.city_slug,c.category,p['title_vi'],p['description_vi'],c.title,c.venue_name,c.address,place_id)
            facts = dict(version=1, authority_type=c.authority_type, verified_venue_id=c.verified_venue_id, image_association_verified=c.image_association_verified, image_permission_id=(c.image_permission or {}).get('id'), evidence_locator=c.evidence_locator, kind=c.kind, city_slug=c.city_slug, category=c.category,
                         title_vi=p['title_vi'], description_vi=p['description_vi'], original_title=c.title,
                         venue_name=c.venue_name, address=c.address, price_text=c.price_text,
                         place_id=str(place_id) if place_id else None)
            if existing:
                item_id = existing['item_id']
                if c.platform == "web":
                    self.db.execute(ITEM_UPDATE,(*values,item_id))
            else:
                item_id = self.db.execute(ITEM_INSERT,
                    (*values,p['fingerprint'])).fetchone()['id']
            observation_id = self.db.execute(OBSERVATION_UPSERT,(item_id,c.source_slug,c.source_url,c.entry_key,p['owner_key'],p['content_hash'],p['original_text'],c.location_evidence,
                                 c.published_at,c.verified_at,p['image_url'],Jsonb(c.metrics),Jsonb(facts))).fetchone()['id']
            # Replace occurrences for THIS successfully parsed page only, inside its transaction.
            self.db.execute(SESSION_DELETE,(observation_id,))
            if c.occurrences:
                self.db.execute(SESSION_INSERT, (observation_id,
                    [session.starts_at for session in c.occurrences],
                    [session.ends_at for session in c.occurrences],
                    [session.precision for session in c.occurrences]))
        return str(item_id)

    def cancel(self, source_slug, url, now, entry_key="", *, confirmed=False, kind=None, city=None):
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-discovery-import',0))")
            result = self.db.execute("""UPDATE discovery_observations o SET status='cancelled',verified_at=%s,
                facts=o.facts || jsonb_build_object('publisher_confirmed_cancellation',
                    %s::boolean AND i.kind='event' AND s.platform='web')
                FROM discovery_items i, discovery_sources s
                WHERE o.item_id=i.id AND o.source_slug=s.slug AND s.enabled
                  AND o.source_slug=%s AND o.source_url=%s AND o.entry_key=%s
                  AND (%s::text IS NULL OR i.kind=%s) AND (%s::text IS NULL OR i.city_slug=%s)
                  AND o.verified_at<=%s AND (o.schedule_held_at IS NULL OR o.schedule_held_at<=%s)""",
                (now,confirmed,source_slug,url,entry_key,kind,kind,city,city,now,now))
            return result.rowcount == 1

    def hold_schedule(self, c: Candidate, now: datetime):
        if c.kind != 'event' or c.platform != 'web' or CONFIRMED_SCHEDULE_CONFLICT not in c.reasons:
            return False
        previous_identity = c.payload()['fingerprint'] if c.replaces_source_url else None
        with self.db.transaction():
            self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('lo-discovery-import',0))")
            result = self.db.execute("""UPDATE discovery_observations o SET schedule_held_at=%s
                FROM discovery_items i, discovery_sources s
                WHERE o.item_id=i.id AND i.kind='event' AND i.city_slug=%s
                  AND s.slug=o.source_slug AND s.enabled AND s.platform='web'
                  AND o.source_slug=%s AND o.status='active'
                  AND ((o.source_url=%s AND o.entry_key=%s)
                    OR (o.source_url=%s AND o.entry_key='' AND i.fingerprint=%s))
                  AND o.verified_at<=%s AND (o.schedule_held_at IS NULL OR o.schedule_held_at<%s)""",
                (now, c.city_slug, c.source_slug, c.source_url, c.entry_key,
                 c.replaces_source_url, previous_identity, now, now))
            return result.rowcount == 1

    def start_run(self, sources, cities, source='__run__', parent_id=None):
        run_id = str(uuid4())
        self.db.execute(RUN_INSERT,
            (run_id,source,cities[0] if len(cities)==1 else None,cities,sources,
             Jsonb({'parent_id':parent_id} if parent_id else {})))
        return run_id

    def progress(self, run_id, accepted, rejected, failed, diagnostics, status='running'):
        self.db.execute(RUN_PROGRESS,
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

    def cleanup(self, *, include_provider_jobs=False):
        self.db.execute(RUN_CLEANUP)
        if include_provider_jobs:
            self.db.execute("DELETE FROM discovery_provider_jobs WHERE created_at < now() - interval '90 days' AND status='complete' AND pilot_id IS NULL")
        self.db.execute(ITEM_CLEANUP)
