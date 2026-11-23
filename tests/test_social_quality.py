import unittest
from trending.social_quality import triage,parse_vtt
from trending.intent import queries
class QualityTests(unittest.TestCase):
 def test_weather_demotion_not_exclusion(self):
  self.assertEqual(0,triage('Dự báo thời tiết Đà Nẵng')['priority'])
  self.assertEqual(2,triage('Thời tiết mưa nhưng workshop tại cafe')['priority'])
  self.assertEqual(1,triage('Giờ mới đổ bộ')['priority'])
 def test_subtitle_timestamps_and_unknown_relevance(self):
  cues=parse_vtt('WEBVTT\n\n00:00:01.250 --> 00:00:03.500\nĐịa chỉ ở cuối video\n\n00:00:05.000 --> 00:00:04.000\nbad','vi')
  self.assertEqual(1,len(cues));self.assertEqual(1.25,cues[0]['start_seconds']);self.assertEqual('unassessed',cues[0]['relevance'])
 def test_all_intents_have_variants(self):
  for city in ['hcmc','hanoi','danang']:
   q=queries(city);self.assertTrue(any('photobooth' in x['query'] for x in q));self.assertTrue(any('food tour' in v for x in q for v in x['variants']))
