"""Real atomic-budget tests; never use the durable live accounting database."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta

from trending.engine_store import EngineStore
from trending.store import Store
from trending.providers import ProviderDisabled
from test_multimodal import package,NOW

URL=os.environ.get('TRENDING_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'set TRENDING_TEST_DATABASE_URL for PostgreSQL')
class EnginePersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_postgres import Persistence
        Persistence.setUpClass()
        cls.store=Persistence.store;cls.engine=EngineStore(cls.store)

    @classmethod
    def tearDownClass(cls):cls.store.close()

    def setUp(self):self.store.db.execute('TRUNCATE discovery_engine_requests,discovery_engine_evidence')

    def test_concurrent_campaign_cap(self):
        def attempt(n):
            s=Store(URL)
            try:
                EngineStore(s).reserve('openai','extract',{'n':n},10_000_000)
                return True
            except ProviderDisabled:return False
            finally:s.close()
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(attempt,range(6)))
        self.assertEqual(sum(results),3)

    def test_replay_preserves_unknown_and_full_reservation(self):
        a,created=self.engine.reserve('openai','extract',{'x':1},1_000_000)
        self.engine.update(a['id'],'unknown')
        b,created=self.engine.reserve('openai','extract',{'x':1},1_000_000)
        self.assertFalse(created);self.assertEqual(b['status'],'unknown')
        self.assertEqual(b['reserved_usd_micros'],1_000_000)

    def test_lifetime_limit_survives_campaign_changes(self):
        row,_=self.engine.reserve('openai','old',{},1)
        self.store.db.execute("UPDATE discovery_engine_requests SET campaign='previous',reserved_usd_micros=250000000 WHERE id=%s",(row['id'],))
        with self.assertRaisesRegex(ProviderDisabled,'lifetime'):self.engine.reserve('openai','new',{},1)

    def test_youtube_searches_have_separate_twelve_request_cap(self):
        for n in range(12):self.engine.reserve('youtube','search',{'q':n},0)
        with self.assertRaisesRegex(ProviderDisabled,'operation'):self.engine.reserve('youtube','search',{'q':13},0)
        self.assertTrue(self.engine.reserve('youtube','videos',{'id':'x'},0)[1])

    def test_allowance_counts_completed_since_receipt_and_unresolved_older(self):
        at=datetime.now(timezone.utc)-timedelta(hours=1)
        row,_=self.engine.reserve('youtube','search',{'q':1},0,remaining=2,verified_at=at)
        self.engine.update(row['id'],'complete',result={})
        self.engine.reserve('youtube','search',{'q':2},0,remaining=2,verified_at=at)
        with self.assertRaisesRegex(ProviderDisabled,'allowance'):self.engine.reserve('youtube','search',{'q':3},0,remaining=2,verified_at=at)

    def test_overrun_blocks_future_spending(self):
        row,_=self.engine.reserve('openai','extract',{},10)
        self.engine.update(row['id'],'complete',actual=11)
        with self.assertRaisesRegex(ProviderDisabled,'overrun'):self.engine.reserve('openai','judge',{},10)

    def test_evidence_cache_preserves_original_verification_and_expires_content(self):
        p=package();identity=self.engine.evidence(p,{'title':'one'},{'verdict':'reject'},['held'])
        self.engine.evidence(p)
        preserved=self.store.db.execute('SELECT judgment,reasons FROM discovery_engine_evidence WHERE id=%s',(identity,)).fetchone()
        self.assertEqual(preserved['judgment']['verdict'],'reject')
        self.assertEqual(preserved['reasons'],['held'])
        p['fetched_at']=NOW+timedelta(days=1)
        self.engine.evidence(p,{'title':'two'})
        row=self.store.db.execute('SELECT * FROM discovery_engine_evidence WHERE id=%s',(identity,)).fetchone()
        self.assertEqual(row['fetched_at'],NOW)
        self.assertEqual(row['extraction']['title'],'two')
        request,_=self.engine.reserve('openai','extract',{},10)
        self.engine.update(request['id'],'complete',result={'text':'source'})
        self.engine.expire_content(datetime.now(timezone.utc)+timedelta(days=31))
        self.assertIsNone(self.engine.get(request['id'])['result'])
        self.assertEqual(self.engine.get(request['id'])['reserved_usd_micros'],10)
        self.assertFalse(self.store.db.execute('SELECT 1 FROM discovery_engine_evidence').fetchone())

    def test_readonly_health_never_changes_receipts(self):
        row,_=self.engine.reserve('openai','extract',{},10)
        before=self.engine.get(row['id'])
        with self.store.db.transaction():
            self.store.db.execute('SET TRANSACTION READ ONLY')
            report=self.engine.health()
        self.assertEqual(before,self.engine.get(row['id']))
        self.assertFalse(report['routine_social_publication'])
