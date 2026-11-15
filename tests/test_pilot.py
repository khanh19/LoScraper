import unittest
from trending.pilot import validate_manifest

class Manifest(unittest.TestCase):
    def test_budget_and_post_only_inputs(self):
        with self.assertRaisesRegex(ValueError,'budget'):validate_manifest({'queries':['q']*7})
        with self.assertRaisesRegex(ValueError,'platform'):validate_manifest({'posts':[{'url':'https://tiktok.com/discover/cafe'}]})
        with self.assertRaisesRegex(ValueError,'platform'):validate_manifest({'posts':[{'url':f'https://instagram.com/p/{i}'} for i in range(4)]})
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_manifest({'posts':[{'url':'https://instagram.com/p/test'}]*2})
