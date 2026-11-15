import copy
import unittest
from trending.images import authorize
from test_trending import candidate, NOW

class Permissions(unittest.TestCase):
    def test_scope_association_revocation_and_review(self):
        c=candidate();c.image_url='https://images.example.com/event.jpg'
        p=dict(id='test',scope='asset',source_slug=c.source_slug,image_url=c.image_url,
               reviewed_at=NOW.isoformat(),creator='Publisher',license_url='https://example.com/license',evidence_url='https://example.com/permission')
        authorize(c,NOW,[p]);self.assertFalse(c.image_permitted)
        c.image_association_verified=True
        authorize(c,NOW,[p]);self.assertTrue(c.image_permitted)
        for change in [dict(revoked=True),dict(source_slug='other'),dict(image_url='https://images.example.com/other.jpg'),dict(reviewed_at='2099-01-01')]:
            authorize(c,NOW,[dict(p,**change)]);self.assertFalse(c.image_permitted)
        authorize(c,NOW,[]);self.assertFalse(c.image_permitted)
        p.update(scope='publisher',asset_host='images.example.com')
        authorize(c,NOW,[p]);self.assertTrue(c.image_permitted)
        c.image_url='https://images.example.com.evil.test/event.jpg'
        authorize(c,NOW,[p]);self.assertFalse(c.image_permitted)
