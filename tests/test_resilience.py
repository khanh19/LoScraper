import copy
import os
import unittest
from argparse import Namespace
from unittest.mock import Mock, patch
from trending.resilience import ProviderCircuit, deterministic_evidence
from trending.providers import ProviderDisabled
from trending.engine import run, degraded
from trending.engine_providers import OpenAI, EXTRACTOR
from test_multimodal import package, FakeLedger

class ResilienceTests(unittest.TestCase):
    def test_exhausted_provider_stops_but_other_explicit_provider_continues(self):
        for reason in ('provider_http_402','provider_http_429','provider_http_503','campaign_budget_exhausted','youtube_quota_exhausted','fresh_allowance_receipt_required','openai_not_configured'):
            circuit=ProviderCircuit();request=Mock(side_effect=ProviderDisabled(reason))
            for _ in range(3):
                with self.assertRaises(ProviderDisabled):circuit.call('openai',request)
            self.assertEqual(request.call_count,1)
            self.assertEqual(circuit.call('youtube',lambda:['result']),['result'])
            self.assertEqual(circuit.blocked,{'openai':reason})

    def test_malformed_response_is_sanitized_and_isolated(self):
        circuit=ProviderCircuit()
        with self.assertRaisesRegex(ProviderDisabled,'^invalid_provider_response$'):
            circuit.call('youtube',lambda:(_ for _ in ()).throw(ValueError('key=private')))
        self.assertEqual(circuit.call('apify',lambda:[]),[])
        self.assertNotIn('private',str(circuit.blocked))

    def test_bad_post_does_not_disable_entire_provider(self):
        circuit=ProviderCircuit()
        with self.assertRaises(ProviderDisabled):circuit.call('apify',lambda:(_ for _ in ()).throw(ProviderDisabled('provider_http_400')))
        self.assertEqual(circuit.call('apify',lambda:1),1)

    def test_completed_cache_usable_without_key_no_new_reservation(self):
        ledger=FakeLedger();payload={'model':EXTRACTOR,'input':'caption'}
        row,_=ledger.reserve('openai','extract',payload,100)
        ledger.update(row['id'],'complete',result={'status':'completed'})
        request=Mock()
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(OpenAI(ledger,request).call('extract',payload),{'status':'completed'})
        request.assert_not_called();self.assertEqual(len(ledger.rows),1)

    def test_deterministic_review_keeps_provenance_and_never_publishes(self):
        p=package();p['verified_venues']=[{'name':'Nhà Gốm','address':'12 phố Huế, Hà Nội','city_slug':'hanoi','evidence_url':'https://example.com/venue'}]
        original=copy.deepcopy(p);a=deterministic_evidence(p);b=deterministic_evidence(p)
        self.assertEqual(a,b);self.assertEqual(p,original)
        self.assertEqual(len(a['matched_destinations']),1)
        self.assertFalse(a['published']);self.assertFalse(a['media_analyzed'])
        self.assertIn('human_fact_review_required',a['reasons'])
        self.assertEqual(a['source_verified_at'],str(p['fetched_at']))
        p['verified_venues'][0]['address']='99 phố Huế, Hà Nội'
        self.assertEqual(deterministic_evidence(p)['matched_destinations'],[])

    def test_lost_accounting_still_discovers_websites_zero_provider_calls(self):
        args=Namespace(city=None,live=True,health=False,providers=['openai','youtube','apify'],websites=False,category=None,queries_per_city=1)
        discovery={'pages':[],'posts':[]}
        with patch.dict(os.environ,{},clear=True),patch('trending.engine.local_store',side_effect=ValueError('private DSN')), \
             patch('trending.engine.PublicClient') as client,patch('trending.engine.discover',return_value=discovery) as websites, \
             patch('trending.engine.OpenAI') as ai,patch('trending.engine.YouTube') as youtube:
            result=run(args)
        self.assertEqual(websites.call_count,3);ai.assert_not_called();youtube.assert_not_called()
        client.return_value.close.assert_called_once()
        self.assertTrue(degraded(result));self.assertEqual(len(result['cities']),3)
        self.assertNotIn('private DSN',str(result))

    def test_retrieved_post_survives_missing_openai_key_as_review_only(self):
        args=Namespace(city='hanoi',live=True,health=False,providers=['youtube'],websites=False,
            category=None,queries_per_city=1,youtube_channels=False,snapshots=None,web_evidence=False,
            max_candidates=1,media_permissions=None,images=False)
        ledger=Mock();ledger.get.return_value=None;ledger.health.return_value={}
        row={'url':'https://www.youtube.com/watch?v=abcdefghijk','description':'Workshop tại Hà Nội',
             'date_posted':'2026-11-15T00:00:00Z'}
        with patch.dict(os.environ,{},clear=True),patch('trending.engine.local_store'), \
             patch('trending.engine.EngineStore',return_value=ledger),patch('trending.engine.PublicClient'), \
             patch('trending.engine.discover',return_value={'pages':[],'posts':[]}), \
             patch('trending.engine.YouTube') as youtube,patch('requests.request') as network:
            youtube.return_value.search.return_value=[row]
            result=run(args)
        outcome=result['cities']['hanoi']['results'][0]
        self.assertEqual(outcome['extraction_status'],'deterministic_review_only')
        self.assertFalse(outcome['fallback']['published'])
        self.assertTrue(degraded(result));network.assert_not_called()

    def test_fallback_reports_partial_execution(self):
        self.assertTrue(degraded({'cities':{'hanoi':{'results':[{'extraction_status':'deterministic_review_only'}]}}}))
        self.assertFalse(degraded({'cities':{'hanoi':{'results':[]}}}))
