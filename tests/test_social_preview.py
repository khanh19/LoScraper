import unittest
from trending.social_preview import preview_record,media_references

class PreviewTests(unittest.TestCase):
    def test_facts_and_permission_separate(self):
        raw={'caption':'Indoor Coffee\n🏠 50 ngõ 28 Xuân La','likesCount':600,'displayUrl':'https://example.com/a'}
        row=preview_record(raw,{'platform':'instagram','url':'https://instagram.com/p/ABC/'},'2026-11-15')
        self.assertEqual(row['engagement']['likes'],600)
        self.assertEqual(row['address_excerpt'],'🏠 50 ngõ 28 Xuân La')
        self.assertEqual(row['publication'],'held')
        self.assertNotIn('image_url',row)
    def test_image_candidates_bounded(self):
        self.assertEqual(len(media_references({'childPosts':[{'displayUrl':f'https://example.com/{i}'} for i in range(20)]})),6)

    def test_caption_stays_intact_but_title_is_bounded(self):
        caption='Địa điểm mới ' * 50
        row=preview_record({'caption':caption},{'platform':'instagram','url':'https://instagram.com/p/ABC/'},'2026-11-15')
        self.assertLessEqual(len(row['title']),80)
        self.assertEqual(row['description'],caption)
