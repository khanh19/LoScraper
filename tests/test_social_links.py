import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
from trending.discover import reviewed_tiktok_profile
from trending.social_links import TikTokShareResolver, extract_posts, remember_lead
from trending.http import FetchError
from trending.providers import BrightSocial, ProviderDisabled

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)

class SocialDiscoveryTests(unittest.TestCase):
    def test_shared_tiktok_link_keeps_publication_evidence_and_deduplicates(self):
        client = Mock()
        post = 'https://www.tiktok.com/@venue/video/123'
        client.get.side_effect = ['https://www.tiktok.com/t/second/', post + '?share=1']
        resolver = TikTokShareResolver(client)
        record = {'link': 'https://vt.tiktok.com/first/?utm_medium=share',
                  'datePublished': '2026-11-07T07:00:00+07:00'}
        markup = '<script type="application/json">' + json.dumps(record) + '</script>'
        markup += f'<a href="{post}">Full URL</a><a href="https://vt.tiktok.com/first/">Share</a>'
        row, = extract_posts(markup, 'https://example.com/event', NOW, resolve_share=resolver.resolve)
        self.assertEqual(row['url'], post)
        self.assertEqual(row['published_at'], '2026-11-07T07:00:00+07:00')
        self.assertTrue(row['requires_provider_validation'])
        self.assertEqual([call.args[0] for call in client.get.call_args_list],
                         ['https://vt.tiktok.com/first/', 'https://www.tiktok.com/t/second/'])
        self.assertTrue(all(call.kwargs['redirect_only'] for call in client.get.call_args_list))

    def test_short_links_hold_nonposts_and_stop_after_three_inputs(self):
        client = Mock()
        client.get.side_effect = ['https://www.tiktok.com/shop/pdp/123', FetchError('redirect_not_allowed'),
                                  'https://www.tiktok.com/@venue/photo/789']
        resolver = TikTokShareResolver(client)
        self.assertIsNone(resolver.resolve('https://vt.tiktok.com.evil.example/one/'))
        self.assertIsNone(resolver.resolve('https://vt.tiktok.com/shop/?page=TikTokShop'))
        self.assertIsNone(resolver.resolve('https://vm.tiktok.com/one/'))
        self.assertIsNone(resolver.resolve('https://vt.tiktok.com/two/'))
        self.assertIsNone(resolver.resolve('https://vt.tiktok.com/two/?utm_source=other'))
        self.assertEqual(resolver.resolve('https://vt.tiktok.com/three/'), 'https://www.tiktok.com/@venue/photo/789')
        self.assertIsNone(resolver.resolve('https://vt.tiktok.com/four/'))
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual([row['status'] for row in resolver.results.values()],
                         ['no_original_post', 'redirect_not_allowed', 'original_post_found'])

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
            self.assertEqual(request.call_args_list[0].kwargs['json'], {
                'input': [{'url': f'https://www.instagram.com/{path}/example/'}], 'limit_per_input': 1,
            })

    def test_profile_requires_current_ownership_link(self):
        client = Mock()
        client.get.return_value = BeautifulSoup('<a href="https://www.tiktok.com/@danangfantasic/">TikTok</a>', 'html.parser')
        self.assertEqual(reviewed_tiktok_profile('danang', client)['publisher_id'], 'danang-tourism')
        client.get.return_value = BeautifulSoup('<a href="https://www.tiktok.com/tag/danangfantasic">TikTok</a>', 'html.parser')
        self.assertIsNone(reviewed_tiktok_profile('danang', client))
        account = {'@type': 'Organization', 'url': 'https://ticketbox.vn/',
                   'sameAs': ['https://www.tiktok.com/@ticketbox.vn']}
        client.get.return_value = BeautifulSoup(
            '<script type="application/ld+json">' + json.dumps(account) + '</script>', 'html.parser')
        self.assertEqual(reviewed_tiktok_profile('hanoi', client)['publisher_id'], 'ticketbox')
        account['url'] = 'https://elsewhere.example/'
        client.get.return_value = BeautifulSoup(
            '<script type="application/ld+json">' + json.dumps(account) + '</script>', 'html.parser')
        self.assertIsNone(reviewed_tiktok_profile('hanoi', client))

    def test_tiktok_profile_reserves_one_and_keeps_only_fresh_matching_posts(self):
        profile = 'https://www.tiktok.com/@verified_venue'
        post = profile + '/photo/123'
        original = {'url': post + '?share=x', 'post_id': '123', 'create_time': NOW.isoformat(),
                    'description': 'Bài ảnh của địa điểm', 'video_url': 'https://example.com/signed-media'}
        store = Mock()
        store.pending.return_value = None
        store.job.side_effect = [None, {'status': 'submitted', 'provider_job_id': 'sd_sample'}]
        store.reserve.return_value = {'created_now': True}
        request = Mock(side_effect=[{'snapshot_id': 'sd_sample'}, {'status': 'ready'}, [original]])
        with patch.dict(os.environ, {'BRIGHTDATA_API_KEY': 'test'}, clear=True), patch(
            'trending.providers.bright_preflight', return_value=(3, NOW.isoformat())
        ):
            social = BrightSocial(store, request, pilot_id='coverage-20261108')
            row, = social.collect_tiktok_profile(profile, NOW)
            self.assertEqual(row['url'], post)
            self.assertNotIn('video_url', row)
            self.assertEqual(store.reserve.call_args.args[2], 1)
            self.assertEqual(request.call_args_list[0].kwargs['params']['dataset_id'], social.TIKTOK_PROFILE_DATASET)
            self.assertEqual(request.call_args_list[0].kwargs['json'], {
                'input': [{'url': profile, 'num_of_posts': 1, 'start_date': '2026-11-01', 'end_date': '2026-11-08'}],
                'limit_per_input': 1,
            })
            store.pending.return_value = {'job_key': 'existing', 'status': 'complete', 'input_data': {'result': [row]}}
            self.assertEqual(social.collect_tiktok_profile(profile, NOW + timedelta(days=8)), [])
            store.pending.return_value['input_data']['result'] = [{**row, 'url': 'https://www.tiktok.com/@other/photo/123'}]
            with self.assertRaisesRegex(ProviderDisabled, 'invalid_tiktok_profile_post'):
                social.collect_tiktok_profile(profile, NOW)
        self.assertEqual(request.call_count, 3)

if __name__ == '__main__':unittest.main()
