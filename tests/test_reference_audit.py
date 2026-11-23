import unittest
from datetime import date,timedelta
from trending.intent import queries
from trending.reference_audit import inventory,post_identity


class ReferenceAuditTests(unittest.TestCase):
 def test_query_rotation_is_repeatable_and_coverage_first(self):
  day=date(2026,11,21)
  for city in ('hanoi','hcmc','danang'):
   first=queries(city,{'restaurant':100,'cafe':100},day)
   self.assertEqual(first,queries(city,{'restaurant':100,'cafe':100},day))
   self.assertNotIn(first[0]['category'],('restaurant','cafe'))
   self.assertNotEqual(first[0]['query'],queries(city,{'restaurant':100,'cafe':100},day+timedelta(days=1))[0]['query'])
 def test_cross_url_identity_preserves_rows(self):
  rows=[{'A':'001','C':'https://www.instagram.com/p/ABC/?igsh=x'},
        {'A':'002','C':'https://www.instagram.com/reel/ABC/'}]
  report=inventory(rows,{})
  self.assertEqual(2,report['sample_count'])
  self.assertEqual(1,report['resolved_post_count'])
  self.assertEqual(['002'],report['samples'][0]['duplicate_sample_ids'])
 def test_shortlinks_are_unresolved(self):
  self.assertIsNone(post_identity('https://vt.tiktok.com/abc/'))
  self.assertIsNone(post_identity('https://evil.example/video/123'))
 def test_caption_does_not_claim_video_review_or_reject_age(self):
  url='https://www.tiktok.com/@a/video/123'
  report=inventory([{'A':'001','C':url}],{url:{'caption':'old cafe','published':'2024-01-01'}})
  item=report['samples'][0]
  self.assertEqual('retrieved',item['coverage']['caption'])
  self.assertEqual('not_reviewed',item['coverage']['video'])
  self.assertEqual('unassessed',item['reference_usefulness'])
  self.assertEqual(['tiktok:123'],report['holdout_exclusions'])
