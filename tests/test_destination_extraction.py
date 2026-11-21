import unittest
from unittest.mock import Mock
from test_multimodal import package,claims,NOW,FakeLedger
from trending.multimodal import process_destinations,validate_extraction,normalize_record
class DestinationTests(unittest.TestCase):
 def test_partial_overlap_cannot_exceed_thirty(self):
  def stop(i):
   item=claims();item['venue_name']=str(i);return item
  pages=[{'destinations':[stop(i) for i in range(6)]},
         {'destinations':[stop(i) for i in range(5,11)]}]
  pages.extend({'destinations':[stop(i) for i in range(start,start+6)]} for start in (11,17,23,29))
  ai=Mock();ai.structured.side_effect=pages+[{}]*30
  out=process_destinations(package(),ai,FakeLedger(),NOW)
  self.assertEqual(30,len(out))
  self.assertTrue(all('destination_limit_reached' in r['reasons'] for r in out))
 def test_roundup_paginates_beyond_six(self):
  stops=[]
  for i in range(13):
   item=claims();item['venue_name']=f'Stop {i}';stops.append(item)
  ai=Mock();ai.structured.side_effect=[{'destinations':stops[:6]},
   {'destinations':stops[6:12]},{'destinations':stops[12:]}]+[{}]*13
  out=process_destinations(package(),ai,FakeLedger(),NOW)
  self.assertEqual(13,len(out))
  self.assertEqual('Stop 12',out[-1]['destination_name'])
 def test_repeated_page_holds_persisted_evidence(self):
  stops=[]
  for i in range(6):
   item=claims();item['venue_name']=str(i);stops.append(item)
  ai=Mock();ai.structured.side_effect=[{'destinations':stops},{'destinations':stops}]+[{}]*6
  ledger=FakeLedger();ledger.evidence=Mock(return_value='evidence')
  out=process_destinations(package(),ai,ledger,NOW)
  self.assertEqual(6,len(out))
  for call in ledger.evidence.call_args_list:
   self.assertIn('destination_coverage_unresolved',call.args[3])
 def test_thirty_stop_ceiling_is_explicit(self):
  pages=[]
  for page in range(5):
   stops=[]
   for i in range(6):
    item=claims();item['venue_name']=str(page*6+i);stops.append(item)
   pages.append({'destinations':stops})
  ai=Mock();ai.structured.side_effect=pages+[{}]*30
  out=process_destinations(package(),ai,FakeLedger(),NOW)
  self.assertEqual(30,len(out))
  self.assertTrue(all('destination_limit_reached' in r['reasons'] for r in out))
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
