import unittest
from trending.coverage import summarize,platform


def row(identity,reason='eligible',section='weekly',urls=()):
    return dict(item_id=identity,reason=reason,payload={
        'section':section,'category':'culture','sources':[{'url':u} for u in urls]})


class CoverageTargets(unittest.TestCase):
    def test_distinct_items_not_source_counts(self):
        r=row('a',urls=['https://www.instagram.com/p/a','https://www.tiktok.com/@a/video/1'])
        result=summarize([r,r,row('held','unverified'),row('b',section='planning')],'hanoi')
        self.assertEqual(result['eligible_unique_items'],2)
        self.assertEqual(result['shortfall'],19)
        self.assertEqual(result['missing_social_platforms'],[])
        self.assertEqual(result['sections'],{'weekly':1,'planning':1})

    def test_empty_and_met_targets(self):
        self.assertEqual(summarize([],'danang')['shortfall'],17)
        self.assertFalse(summarize([row(str(i)) for i in range(25)],'hcmc')['target_met'])
        balanced=[row(str(i)) for i in range(18)]+[row('p'+str(i),section='planning') for i in range(7)]
        self.assertTrue(summarize(balanced,'hcmc')['target_met'])
        self.assertEqual(summarize(balanced,'hcmc')['section_shortfalls'],{'weekly':0,'planning':0})
        self.assertEqual(platform('https://instagram.com.evil.example/p/a'),'web')
