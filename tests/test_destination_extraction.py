import unittest
from unittest.mock import Mock
from test_multimodal import package,claims,NOW,FakeLedger
from trending.multimodal import process_destinations,validate_extraction,normalize_record
class DestinationTests(unittest.TestCase):
 def test_place_hours_never_become_sessions(self):
  c=claims();c['kind']='place'
  self.assertIn('place_has_event_sessions',validate_extraction(c,package(),NOW))
 def test_empty_bundle(self):
  ai=Mock();ai.structured.return_value={'destinations':[]}
  self.assertEqual([],process_destinations(package(),ai,FakeLedger(),NOW))
 def test_two_stops_retained(self):
  a=claims();b=claims();b['venue_name']='Second stop'
  judge={'verdict':'needs_review','checks':{},'evidence_ids':[]}
  ai=Mock();ai.structured.side_effect=[{'destinations':[a,b]},judge,judge]
  out=process_destinations(package(),ai,FakeLedger(),NOW)
  self.assertEqual([a['venue_name'],b['venue_name']],[x['destination_name'] for x in out])
  self.assertTrue(all(not x['published'] for x in out))
 def test_metrics_and_false_flags_preserved(self):
  p=normalize_record({'url':'https://www.tiktok.com/@a/video/12345','share_count':4,'collect_count':9,'is_ad':False},'tiktok','hcmc',NOW)
  self.assertEqual(4,p['engagement']['share_count']);self.assertEqual(9,p['engagement']['collect_count']);self.assertIs(p['commercial']['is_ad'],False)
