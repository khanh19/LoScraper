import json
import tempfile
import unittest
from pathlib import Path
from trending.diagnostics import safe_url, snapshot

class DiagnosticsTests(unittest.TestCase):
    def test_reviewed_examples_are_separate_and_never_expose_remote_images(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'
            p.write_text(json.dumps({'reviewed_social':[{'source_slug':'instagram',
                'source_url':'https://www.instagram.com/p/ABC123/', 'title':'Quán cà phê',
                'image_url':'https://example.com/private.jpg?token=secret',
                'engagement':{'likes':600},'description':'Nội dung thật'}]}))
            result=snapshot([p,p],None)
            self.assertEqual(len(result['reviewed_social']),1)
            item=result['reviewed_social'][0]
            self.assertEqual(item['stage'],'relevance_reviewed_not_published')
            self.assertNotIn('image_url',item)
            self.assertEqual(item['engagement']['likes'],600)

    def test_urls_strip_credentials_and_signed_parameters(self):
        self.assertEqual(safe_url('https://example.com/post?token=secret'), 'https://example.com/post')
        self.assertEqual(safe_url('https://youtube.com/watch?v=abc&key=secret'), 'https://youtube.com/watch?v=abc')
        for value in ['javascript:alert(1)', 'http://example.com', 'https://user:secret@example.com']:
            self.assertEqual(safe_url(value), '')

    def test_samples_bounded_deduplicated_and_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'
            p.write_text(json.dumps({'sources':{'ticketbox':{'status':'complete'}},'accepted':[],
                'rejected':[{'source':'ticketbox','sample':{'source_url':f'https://ticketbox.vn/{i}','title':str(i)},'reasons':['expired']} for i in range(8)]}))
            result=snapshot([p,p],None)
            g=next(x for x in result['groups'] if x['source']=='ticketbox')
            self.assertEqual(g['available_samples'],8)
            self.assertEqual(len(g['samples']),5)
            self.assertTrue(all(x['stage']=='withheld' for x in g['samples']))
            self.assertEqual(g['samples'][0]['reasons'],['expired'])
            self.assertTrue(result['read_only'])

    def test_remote_accounting_rejected(self):
        with self.assertRaisesRegex(ValueError,'local_accounting_only'):
            snapshot([], 'postgresql://user@example.com/db')
