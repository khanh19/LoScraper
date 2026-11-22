import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from trending.social_links import extract_posts, remember_lead
from trending.providers import BrightSocial, ProviderDisabled

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)

class SocialDiscoveryTests(unittest.TestCase):
    def test_nested_embeds_freshness_and_dedup(self):
        recent = {'link':'https://www.instagram.com/p/example/', 'timestamp':'2026-11-07T01:00:00Z', 'description':'A local festival'}
        stale = dict(recent, link='https://www.instagram.com/p/old/', timestamp='2025-11-07T00:00:00Z')
        future = dict(recent, link='https://www.instagram.com/p/future/', timestamp='2027-11-07T00:00:00Z')
        html = '<script type="application/json">'+json.dumps({'items':[recent,stale,future,recent]})+'</script>'
        html += '<a href="https://www.instagram.com/organizer/">Profile</a>'
        html += '<a href="https://www.instagram.com/p/old/">Old embedded post</a>'
        html += '<a href="https://www.tiktok.com/@venue/video/123">Video</a>'
        rows = extract_posts(html,'https://example.com/event',NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['text'],'A local festival')
        self.assertTrue(all(r['requires_provider_validation'] for r in rows))
        self.assertIsNone(rows[1]['published_at'])

    def test_original_links_from_embed_markup_and_platform_aliases(self):
        markup = """
        <blockquote class="instagram-media" data-instgrm-permalink="https://instagram.com/venue/reel/fresh/?igsh=xyz">Poster</blockquote>
        <iframe src="https://www.instagram.com/p/photo/embed/captioned/"></iframe>
        <iframe src="https://instagram.com.evil.example/reel/fresh/embed/"></iframe>
        <blockquote class="tiktok-embed" cite="https://tiktok.com/@venue/video/123?refer=embed" data-video-id="123">Show</blockquote>
        <blockquote class="tiktok-embed" cite="https://www.tiktok.com/@venue/video/456" data-video-id="457">Wrong ID</blockquote>
        <iframe src="https://www.tiktok.com/player/v1/789"></iframe>
        <a href="https://www.instagram.com/p/fresh/">Same post</a>
        """
        rows = extract_posts(markup, 'https://example.com/event', NOW)
        self.assertEqual({row['url'] for row in rows}, {
            'https://www.instagram.com/reel/fresh', 'https://www.instagram.com/p/photo',
            'https://www.tiktok.com/@venue/video/123',
        })
        self.assertTrue(all(row['requires_provider_validation'] for row in rows))

    def test_embedded_alias_cannot_reintroduce_stale_record(self):
        post = {'url': 'https://www.instagram.com/p/example/', 'datePublished': '2025-11-07T00:00:00Z'}
        markup = '<script type="application/json">' + json.dumps(post) + '</script>'
        markup += '<blockquote class="instagram-media" data-instgrm-permalink="https://www.instagram.com/venue/reel/example/"></blockquote>'
        self.assertEqual(extract_posts(markup, 'https://example.com/event', NOW), [])

    def test_repeated_post_prefers_dated_page_and_reel_link(self):
        links = {}
        embed, = extract_posts('<a href="https://www.instagram.com/venue/reel/valid/">Reel</a>',
                              'https://example.com/first', NOW)
        post = {'link': 'https://www.instagram.com/p/valid/', 'datePublished': '2026-11-07T00:00:00Z'}
        dated, = extract_posts('<script type="application/json">' + json.dumps(post) + '</script>',
                               'https://example.com/second', NOW)
        for row in (embed, dated):
            remember_lead(links, row)
        merged, = links.values()
        self.assertEqual(merged['url'], embed['url'])
        self.assertEqual(merged['discovered_on'], dated['discovered_on'])
        self.assertEqual(merged['published_at'], dated['published_at'])

    def test_reels_and_posts_use_distinct_datasets(self):
        for path,dataset in [('p','gd_lk5ns7kz21pck8jpis'),('reel','gd_lyclm20il4r5helnj')]:
            store=Mock();store.pending.return_value=None
            store.job.side_effect=[None,{'status':'submitted','provider_job_id':'sd_sample'}]
            store.reserve.return_value={'created_now':True}
            request=Mock(side_effect=[{'snapshot_id':'sd_sample'},{'status':'running'}])
            with patch.dict(os.environ,{'BRIGHTDATA_API_KEY':'test'}),patch('trending.providers.bright_preflight',return_value=(3,NOW.isoformat())):
                with self.assertRaisesRegex(ProviderDisabled,'job_pending'):
                    BrightSocial(store,request).collect(f'https://www.instagram.com/{path}/example/',NOW)
            self.assertEqual(request.call_args_list[0].kwargs['params']['dataset_id'],dataset)
            self.assertEqual(request.call_args_list[0].kwargs['json'],[{'url':f'https://www.instagram.com/{path}/example/'}])

if __name__ == '__main__':unittest.main()
