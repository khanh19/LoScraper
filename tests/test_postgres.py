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
        if p.hostname not in {'127.0.0.1','localhost'} or p.path!='/lo_trending_test':
            raise RuntimeError('Tests require the disposable local lo_trending_test database')
        cls.store=Store(URL)
        cls.store.db.execute('DROP TABLE IF EXISTS discovery_provider_jobs,discovery_ingestion_runs,discovery_occurrences,discovery_observations,discovery_items,discovery_sources CASCADE')
        # Use the existing parent-table DDL, not a mock of the new migration.
        baseline=(BACKEND/'supabase/migrations/20260523000001_onboarding.sql').read_text()
        for name in ['cities','places']:
            ddl=re.search(r'CREATE TABLE IF NOT EXISTS public\.'+name+r' \([\s\S]*?\n\);',baseline).group()
            cls.store.db.execute(ddl)
        cls.store.db.execute((BACKEND/'supabase/migrations/20261108060000_discovery_trending.sql').read_text())
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
