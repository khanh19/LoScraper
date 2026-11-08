"""Real Postgres tests; run only against our dedicated disposable local database."""
import copy
from datetime import timedelta
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg

from trending.store import Store
from trending.providers import BrightSocial, SerpDiscovery, ProviderDisabled
from test_trending import candidate, NOW

URL=os.environ.get('TRENDING_TEST_DATABASE_URL')
BACKEND=Path(os.environ.get('LO_BACKEND_ROOT','../LoAppBackend'))


@unittest.skipUnless(URL and BACKEND.exists(),'set TRENDING_TEST_DATABASE_URL for local Postgres integration tests')
class Persistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=urlsplit(URL)
        if p.hostname not in {'127.0.0.1','localhost'} or p.path not in {'/lo_trending_test','/lo_trending_guards_test'}:
            raise RuntimeError('Tests require the disposable local lo_trending_test database')
        cls.store=Store(URL)
        cls.store.db.execute('DROP TABLE IF EXISTS discovery_provider_jobs,discovery_ingestion_runs,discovery_occurrences,discovery_observations,discovery_items,discovery_sources CASCADE')
        # Use the existing parent-table DDL, not a mock of the new migration.
        baseline=(BACKEND/'supabase/migrations/20260523000001_onboarding.sql').read_text()
        for name in ['cities','places']:
            ddl=re.search(r'CREATE TABLE IF NOT EXISTS public\.'+name+r' \([\s\S]*?\n\);',baseline).group()
            cls.store.db.execute(ddl)
        cls.store.db.execute('DROP FUNCTION IF EXISTS public.discovery_evaluate(timestamptz,text)')
        for migration in sorted((BACKEND/'supabase/migrations').glob('*_discovery_*.sql')):
            cls.store.db.execute(migration.read_text())
        cls.sql=(BACKEND/'discovery/trending.sql').read_text()

    @classmethod
    def tearDownClass(cls): cls.store.close()

    def setUp(self):
        self.store.db.execute('TRUNCATE discovery_items,discovery_provider_jobs,discovery_ingestion_runs CASCADE')
        self.store.register('ticketbox','Ticketbox',True)

    def feed(self,now=NOW,city='hanoi',kind='all',limit=10):
        values=[now,city,kind,limit];args=[]
        def sub(m): args.append(values[int(m[1])-1]);return '%s'
        sql=re.sub(r'\$(\d)',sub,self.sql)
        rows=self.store.db.execute(sql,args).fetchall()
        return [list(row.values())[0] for row in rows]

    def test_stable_ids_cross_source_dedupe_and_partial_import(self):
        c=candidate();first=self.store.upsert(c,NOW)
        c.title='Workshop thử nghiệm (cập nhật)'
        self.assertEqual(self.store.upsert(c,NOW),first)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_name='TicketGo';d.source_url='https://ticketgo.vn/event/test'
        # Restore matching identity; the original fingerprint survives a source title edit.
        d.title='Workshop thử nghiệm'
        self.store.register('ticketgo','TicketGo',True)
        self.assertEqual(self.store.upsert(d,NOW),first)
        bad=candidate();bad.city_slug='invalid'
        with self.assertRaises(ValueError):self.store.upsert(bad,NOW)
        self.assertEqual(len(self.feed()),1)
        self.assertEqual(len(self.feed()[0]['sources']),2)

    def test_city_kind_expiry_and_window(self):
        self.store.upsert(candidate(),NOW)
        p=candidate('place');p.source_url='https://ticketbox.vn/place-12345'
        self.store.upsert(p,NOW)
        self.assertEqual([i['kind'] for i in self.feed()],['event','place'])
        self.assertEqual(len(self.feed(kind='event')),1)
        self.assertEqual(self.feed(city='danang'),[])
        self.assertEqual(self.feed(now=NOW+timedelta(hours=73)),[])
        self.assertEqual(self.feed(now=NOW+timedelta(days=3),kind='event'),[])

    def test_cancel_immediate_and_disabled_source_hidden(self):
        c=candidate();self.store.upsert(c,NOW)
        self.store.cancel(c.source_slug,c.source_url,NOW)
        self.assertEqual(self.feed(),[])
        self.store.upsert(c,NOW)
        self.store.register('ticketbox','Ticketbox',False)
        self.assertEqual(self.feed(),[])

    def test_conflicting_source_dates_are_not_published(self):
        c=candidate();self.store.upsert(c,NOW)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/test'
        self.store.register('ticketgo','TicketGo',True)
        for o in d.occurrences:
            from datetime import datetime
            o.starts_at=(datetime.fromisoformat(o.starts_at)+timedelta(days=2)).isoformat()
            o.ends_at=(datetime.fromisoformat(o.ends_at)+timedelta(days=2)).isoformat()
        self.store.upsert(d,NOW)
        self.assertEqual(self.feed(),[])

    def test_reservations_persist_no_refund_and_monthly_cap(self):
        first=self.store.reserve('serpapi','search-a',1,2,10,{},NOW)
        self.assertTrue(first['created_now'])
        retry=self.store.reserve('serpapi','search-a',1,2,10,{},NOW)
        self.assertFalse(retry['created_now'])
        self.store.update_job('search-a','unknown')
        self.assertTrue(self.store.reserve('serpapi','search-b',1,2,10,{},NOW))
        self.assertIsNone(self.store.reserve('serpapi','search-c',1,2,10,{},NOW))
        self.assertEqual(self.store.job('search-a')['status'],'unknown')

    def test_interrupted_social_job_found_across_days(self):
        url='https://www.tiktok.com/@lo/video/123'
        self.store.reserve('brightdata','yesterday',1,4500,20,{'url':url},NOW)
        self.store.update_job('yesterday','submitted',provider_id='sd_example')
        self.assertEqual(self.store.pending('brightdata',url)['provider_job_id'],'sd_example')
        calls=[]
        def request(method,url,**kwargs):
            calls.append((method,url))
            return {'status':'ready'} if '/progress/' in url else []
        with patch.dict(os.environ,{'BRIGHTDATA_API_KEY':'test-placeholder'}):
            result=BrightSocial(self.store,request).collect(url,NOW+timedelta(days=1))
        self.assertEqual(result,[])
        self.assertTrue(all(method=='GET' for method,url in calls))
        self.assertEqual(self.store.job('yesterday')['status'],'complete')

    def test_dashboard_allowance_counts_completed_and_old_unresolved_jobs(self):
        verified_at=NOW.isoformat()
        self.store.reserve('brightdata','completed',1,4500,2,{},NOW,verified_at=verified_at)
        self.store.update_job('completed','complete')
        # A request predating the receipt may still be awaiting a charge. It
        # must count even when it was launched in a prior billing month.
        self.store.reserve('brightdata','old-pending',1,4500,10,{},NOW-timedelta(days=35))
        self.store.db.execute("UPDATE discovery_provider_jobs SET created_at=%s WHERE job_key='old-pending'",
                              (NOW-timedelta(days=35),))
        self.assertIsNone(self.store.reserve('brightdata','overrun',1,4500,2,{},NOW,verified_at=verified_at))

    def test_concurrent_dashboard_reservations_cannot_reuse_last_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def reserve(key):
            store=Store(URL)
            try:
                barrier.wait(timeout=10)
                job=store.reserve('brightdata',key,1,4500,1,{},NOW,verified_at=NOW.isoformat())
                if job:
                    store.update_job(key,'complete')
                return bool(job)
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve,['parallel-a','parallel-b'])),1)

    def test_exhausted_provider_allowance_does_not_trigger_search(self):
        calls=[]
        def request(method,url,**kwargs):
            calls.append(url)
            return dict(account_status='Active',plan_id='free',plan_monthly_price=0,plan_searches_left=0)
        with patch.dict(os.environ,{'SERPAPI_API_KEY':'test-placeholder'}):
            with self.assertRaises(ProviderDisabled):SerpDiscovery(self.store,request).search('Hà Nội',NOW)
        self.assertEqual(calls,['https://serpapi.com/account.json'])
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM discovery_provider_jobs').fetchone()['n'],0)

    def test_syndicated_mentions_do_not_inflate_popularity(self):
        c=candidate('place');c.original_text='Same syndicated story'
        self.store.upsert(c,NOW)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/place'
        self.store.register('ticketgo','TicketGo',True)
        self.store.upsert(d,NOW)
        self.assertEqual(self.feed()[0]['evidence_label'],'Mới được nhắc đến')
        d.original_text='An independently authored review with new evidence'
        self.store.upsert(d,NOW)
        self.assertEqual(self.feed()[0]['evidence_label'],'Đang được quan tâm')

    def test_observation_facts_control_every_display_field_and_social_cannot_replace(self):
        from psycopg.types.json import Jsonb
        c=candidate();c.price_text='100.000đ';c.image_permitted=True;c.image_url='https://ticketbox.vn/a.jpg'
        item_id=self.store.upsert(c,NOW)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_name='TicketGo';d.source_url='https://ticketgo.vn/event/test'
        self.store.register('ticketgo','TicketGo',True)
        self.store.upsert(d,NOW)
        d.title='Tên mới';d.venue_name='Địa điểm mới';d.address='20 Tràng Tiền, Hà Nội';d.price_text='200.000đ'
        d.verified_at=(NOW+timedelta(minutes=1)).isoformat();d.image_url='https://ticketgo.vn/b.jpg'
        self.assertEqual(self.store.upsert(d,NOW),item_id)
        row=self.feed()[0]
        for field in ['title_vi','description_vi','venue_name','address','price_text','image_url']:
            self.assertEqual(row[field],d.payload()[field])
        self.assertEqual(row['image_source']['url'],d.source_url)
        self.assertEqual(row['sources'][0]['url'],d.source_url)
        from datetime import datetime
        self.assertEqual(datetime.fromisoformat(row['next_occurrence']['starts_at']),datetime.fromisoformat(d.occurrences[0].starts_at))
        self.assertIsNone(row['place_id'])
        social=copy.deepcopy(c);social.source_slug='tiktok';social.platform='tiktok';social.source_url='https://www.tiktok.com/@test/video/123'
        self.store.register('tiktok','TikTok',True,'tiktok')
        self.store.upsert(social,NOW)
        before=self.feed()[0]
        self.store.db.execute("UPDATE discovery_observations SET facts=%s,verified_at=%s WHERE source_slug='tiktok'",
            (Jsonb(dict(version=1,title_vi='Wrong social title')),NOW+timedelta(minutes=2)))
        self.assertEqual(self.feed()[0]['title_vi'],before['title_vi'])
        # A missing/invalid snapshot falls back to a complete website observation.
        self.store.db.execute("UPDATE discovery_observations SET facts=facts-'address' WHERE source_slug='ticketgo'")
        self.assertEqual(self.feed()[0]['title_vi'],c.payload()['title_vi'])

    def test_equal_verification_tie_and_legacy_facts_are_withheld(self):
        c=candidate();self.store.upsert(c,NOW)
        self.store.register('aaa','First',True)
        d=copy.deepcopy(c);d.source_slug='aaa';d.source_url='https://ticketgo.vn/event/tie'
        self.store.upsert(d,NOW)
        d.price_text='Tie winner';self.store.upsert(d,NOW)
        self.assertEqual(self.feed()[0]['price_text'],'Tie winner')
        self.store.db.execute("UPDATE discovery_observations SET facts='{}'")
        self.assertEqual(self.feed(),[])
        self.assertEqual(self.store.db.execute('SELECT reason FROM discovery_evaluate(%s,%s)',(NOW,'hanoi')).fetchone()['reason'],'incomplete_facts')
        self.store.upsert(c,NOW)
        self.assertEqual(len(self.feed()),1)

    def test_identity_conflict_does_not_change_existing_verification(self):
        c=candidate();item=self.store.upsert(c,NOW)
        c.kind='place';c.occurrences=[];c.verified_at=(NOW+timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'identity_conflict'):self.store.upsert(c,NOW)
        c.kind='event';c.occurrences=candidate().occurrences;c.city_slug='danang';c.address='10 Hải Phòng, Đà Nẵng'
        with self.assertRaisesRegex(ValueError,'identity_conflict'):self.store.upsert(c,NOW)
        row=self.store.db.execute('SELECT verified_at FROM discovery_observations WHERE item_id=%s',(item,)).fetchone()
        self.assertEqual(row['verified_at'],NOW)
        self.assertEqual(len(self.feed()),1)

    def test_whole_schedule_requires_symmetric_coverage(self):
        from trending.model import Occurrence
        c=candidate();second=Occurrence((NOW+timedelta(days=2)).isoformat(),(NOW+timedelta(days=2,hours=2)).isoformat())
        c.occurrences.append(second);self.store.upsert(c,NOW)
        self.store.register('ticketgo','TicketGo',True)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/test'
        d.occurrences=d.occurrences[:1];self.store.upsert(d,NOW)
        self.assertEqual(self.feed(),[])
        self.assertEqual(self.store.db.execute('SELECT reason FROM discovery_evaluate(%s,%s)',(NOW,'hanoi')).fetchone()['reason'],'unresolved_sessions')
        d.occurrences.append(copy.deepcopy(second));self.store.upsert(d,NOW)
        self.assertEqual(len(self.feed()),1)
        d.occurrences[1].ends_at=(NOW+timedelta(days=2,hours=3)).isoformat();self.store.upsert(d,NOW)
        self.assertEqual(self.feed(),[])
        # An empty relevant set cannot corroborate a nonempty one.
        self.store.db.execute("DELETE FROM discovery_occurrences WHERE observation_id IN (SELECT id FROM discovery_observations WHERE source_slug='ticketgo')")
        self.assertEqual(self.feed(),[])

    def test_date_only_must_contain_full_timed_session_and_equivalent_timezones(self):
        from datetime import datetime, timezone
        from trending.model import ICT, Occurrence
        c=candidate();self.store.upsert(c,NOW)
        self.store.register('ticketgo','TicketGo',True)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/test'
        for o in d.occurrences:
            o.starts_at=datetime.fromisoformat(o.starts_at).astimezone(ICT).isoformat()
            o.ends_at=datetime.fromisoformat(o.ends_at).astimezone(ICT).isoformat()
        self.store.upsert(d,NOW);self.assertEqual(len(self.feed()),1)
        day=datetime.fromisoformat(d.occurrences[0].starts_at).replace(hour=0,minute=0)
        d.occurrences=[Occurrence(day.isoformat(),(day+timedelta(days=1)).isoformat(),'date')]
        self.store.upsert(d,NOW);self.assertEqual(len(self.feed()),1)
        # date evidence ending during a timed session is insufficient.
        d.occurrences[0].ends_at=(NOW+timedelta(days=1,hours=1)).isoformat()
        self.store.upsert(d,NOW);self.assertEqual(self.feed(),[])

    def test_health_agrees_with_api_and_is_read_only(self):
        from trending.health import report
        self.store.upsert(candidate('place'),NOW)
        run=self.store.start_run(['ticketbox'],['hanoi'],'ticketbox')
        self.store.db.execute('UPDATE discovery_ingestion_runs SET heartbeat_at=%s WHERE id=%s',(NOW-timedelta(minutes=31),run))
        health=report(self.store.db,['hanoi','hcmc','danang'],NOW+timedelta(hours=49))
        self.assertEqual(health['cities']['hanoi']['eligible_total'],len(self.feed(now=NOW+timedelta(hours=49))))
        self.assertEqual(len(health['cities']['hanoi']['losing_last_fresh_evidence_within_24h']),1)
        self.assertTrue(health['cities']['danang']['empty'])
        self.assertEqual(health['runs'][0]['status'],'interrupted')
        self.assertEqual(self.store.db.execute('SELECT status FROM discovery_ingestion_runs WHERE id=%s',(run,)).fetchone()['status'],'running')
        self.assertIn('NOT a live',health['provider_accounting']['label'])

    def test_transaction_failure_rolls_back_observation_and_keeps_other_items(self):
        c=candidate();self.store.upsert(c,NOW)
        old=self.store.db.execute('SELECT verified_at,facts FROM discovery_observations').fetchone()
        self.store.db.execute("""CREATE FUNCTION pg_temp.reject_occurrence() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected failure'; END $$""")
        self.store.db.execute('CREATE TRIGGER reject_occurrence BEFORE INSERT ON discovery_occurrences FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_occurrence()')
        try:
            c.verified_at=(NOW+timedelta(minutes=1)).isoformat();c.price_text='should roll back'
            with self.assertRaises(psycopg.Error):self.store.upsert(c,NOW)
        finally:
            self.store.db.execute('DROP TRIGGER reject_occurrence ON discovery_occurrences')
        self.assertEqual(self.store.db.execute('SELECT verified_at,facts FROM discovery_observations').fetchone(),old)
        self.assertEqual(len(self.feed()),1)

    def test_connection_loss_reconnects_once_without_retrying_write(self):
        from trending.progress import Progress
        progress=Progress(self.store,['ticketbox'],['hanoi'])
        progress.start_source('ticketbox')
        self.store.db.close()
        with patch.object(self.store,'upsert',wraps=self.store.upsert) as upsert:
            ok,_=progress.call('upsert',candidate(),NOW)
            self.assertFalse(ok);self.assertEqual(upsert.call_count,1)
        self.assertTrue(progress.available);self.assertTrue(progress.reconnect_attempted)
        self.assertTrue(progress.call('upsert',candidate(),NOW)[0])
        self.store.db.close()
        self.assertFalse(progress.call('upsert',candidate(),NOW)[0])
        self.assertFalse(progress.available)
        self.store.reconnect()  # restore the test fixture only, not the run
        self.assertEqual(len(self.feed()),1)

    def test_run_continues_after_bad_candidate_failed_write_and_source(self):
        from argparse import Namespace
        from contextlib import redirect_stdout
        from datetime import datetime
        import io
        from trending.__main__ import run
        args=Namespace(sources='ticketbox,ticketgo',city=None,pilot=True,write_db=True,browser=False,
                       supplemental=False,providers=False,limit=12,out=None)
        class Clock:
            @staticmethod
            def now(tz):return NOW
        good=candidate();bad=candidate();bad.title=None
        write_bad=candidate();write_bad.source_url='https://ticketbox.vn/failed'
        other=candidate('place');other.source_url='https://ticketbox.vn/other'
        calls=[]
        real_upsert=self.store.upsert
        def upsert(c,now):
            calls.append(c.source_url)
            if c.source_url.endswith('/failed'):raise psycopg.DataError('secret must never be printed')
            return real_upsert(c,now)
        def collect(slug,*args,**kwargs):
            kwargs['heartbeat']()
            # Receipts already exist while collection is in progress.
            self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM discovery_ingestion_runs WHERE status='running'").fetchone()['n'],2)
            if slug=='ticketgo':raise RuntimeError('parser exception with secret')
            return [good,bad,write_bad,other],[]
        output=io.StringIO()
        with patch.dict(os.environ,{'DATABASE_URL':URL}),patch('trending.__main__.datetime',Clock),\
             patch('trending.__main__.Store',return_value=self.store),patch.object(self.store,'close'),\
             patch('trending.__main__.PublicClient'),patch('trending.__main__.collect_source',side_effect=collect),\
             patch.object(self.store,'upsert',side_effect=upsert),redirect_stdout(output):
            result=run(args)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['sources']['ticketbox']['accepted'],2)
        self.assertEqual(result['sources']['ticketbox']['failed'],2)
        self.assertEqual(result['sources']['ticketgo']['status'],'failed')
        self.assertEqual(len(self.feed()),2)
        self.assertEqual(calls.count(write_bad.source_url),1)
        self.assertNotIn('secret',output.getvalue())
        self.assertEqual(self.store.db.execute('SELECT status FROM discovery_ingestion_runs WHERE id=%s',(result['run_id'],)).fetchone()['status'],'partial')

    def test_primary_place_match_and_price_follow_selected_observation(self):
        c=candidate();self.store.upsert(c,NOW)
        self.store.register('ticketgo','TicketGo',True)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/test'
        self.store.upsert(d,NOW)
        city=self.store.db.execute("INSERT INTO cities(slug,name,country_code) VALUES ('hanoi','Hanoi','VN') ON CONFLICT(slug) DO UPDATE SET name=excluded.name RETURNING id").fetchone()['id']
        place=self.store.db.execute("INSERT INTO places(city_id,source,name,address) VALUES (%s,'curated','New venue','20 Tràng Tiền, Hà Nội') RETURNING id",(city,)).fetchone()['id']
        try:
            d.venue_name='New venue';d.address='20 Tràng Tiền, Hà Nội';d.price_text='250.000đ'
            d.verified_at=(NOW+timedelta(minutes=1)).isoformat();self.store.upsert(d,NOW)
            row=self.feed()[0]
            self.assertEqual(row['place_id'],str(place));self.assertEqual(row['price_text'],d.price_text)
            self.assertEqual(row['venue_name'],d.venue_name)
            c.verified_at=(NOW+timedelta(minutes=2)).isoformat();self.store.upsert(c,NOW)
            row=self.feed()[0]
            self.assertIsNone(row['place_id']);self.assertIsNone(row['price_text'])
            self.assertEqual(row['venue_name'],c.venue_name)
        finally:
            self.store.db.execute('DELETE FROM places WHERE id=%s',(place,))

    def test_health_detects_publication_expiry_even_with_new_verification(self):
        from trending.health import report
        c=candidate('place');c.published_at=(NOW-timedelta(days=6,hours=12)).isoformat()
        self.store.upsert(c,NOW)
        health=report(self.store.db,['hanoi'],NOW)
        self.assertEqual(len(health['cities']['hanoi']['losing_last_fresh_evidence_within_24h']),1)
        self.assertEqual(self.feed(now=NOW+timedelta(hours=13)),[])

    def test_expired_sessions_do_not_conflict_with_the_upcoming_window(self):
        from trending.model import Occurrence
        c=candidate();self.store.upsert(c,NOW)
        self.store.register('ticketgo','TicketGo',True)
        d=copy.deepcopy(c);d.source_slug='ticketgo';d.source_url='https://ticketgo.vn/event/test'
        d.occurrences.append(Occurrence((NOW-timedelta(days=2)).isoformat(),(NOW-timedelta(days=1)).isoformat()))
        self.store.upsert(d,NOW)
        self.assertEqual(len(self.feed()),1)

    def test_roundup_entries_replay_disappearance_and_scoped_cancellation(self):
        c=candidate();c.entry_key='anchor:a';first=self.store.upsert(c,NOW)
        d=copy.deepcopy(c);d.entry_key='anchor:b';d.title='Second workshop';second=self.store.upsert(d,NOW)
        self.assertNotEqual(first,second)
        self.assertEqual(self.store.upsert(d,NOW),second)
        self.assertEqual(len(self.feed()),2)
        self.store.cancel(c.source_slug,c.source_url,NOW,c.entry_key)
        self.assertEqual([x['id'] for x in self.feed()],[second])


    def test_roundup_publication_cannot_rejuvenate_old_place(self):
        c=candidate('place');c.entry_key='anchor:a';self.store.upsert(c,NOW)
        c.published_at=(NOW+timedelta(days=8)).isoformat()
        c.verified_at=c.published_at
        with self.assertRaisesRegex(ValueError,'stale_roundup_evidence'):
            self.store.upsert(c,NOW+timedelta(days=8))
        row=self.store.db.execute('SELECT verified_at FROM discovery_observations').fetchone()
        self.assertEqual(row['verified_at'],NOW)


    def test_roundup_same_destination_dedupes_source_links(self):
        c=candidate();c.entry_key='anchor:a';first=self.store.upsert(c,NOW)
        c.entry_key='anchor:b';self.assertEqual(self.store.upsert(c,NOW),first)
        self.assertEqual(len(self.feed()[0]['sources']),1)

