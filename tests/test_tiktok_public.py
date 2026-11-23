from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from trending.http import FetchError
from trending.tiktok_public import audit, direct_video_review, publication_time, review_profile, video_permalink

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
PROFILE = 'https://www.tiktok.com/@organizer'
POST = PROFILE + '/video/123'


def post_page(url, *entries):
    markup = f'<link rel="canonical" href="{url}">'
    markup += '<script type="application/ld+json">' + json.dumps(entries) + '</script>'
    return BeautifulSoup(markup, 'html.parser')


class TikTokPublicAuditTests(unittest.TestCase):
    def test_date_requires_exact_page_and_post_binding(self):
        video = {'@type': 'VideoObject', 'uploadDate': '2026-11-22T00:00:00+07:00'}
        self.assertIsNone(publication_time(post_page(POST, video), POST))
        entry = {**video, 'embedUrl': 'https://www.tiktok.com/player/v1/123?autoplay=0'}
        self.assertEqual(publication_time(post_page(POST, entry), POST).isoformat(), '2026-11-21T17:00:00+00:00')
        self.assertIsNone(publication_time(post_page(POST + '4', entry), POST))
        self.assertIsNone(publication_time(post_page(POST, {**entry, 'uploadDate': '2026-11-22'}), POST))
        self.assertIsNone(publication_time(post_page(POST, entry, {**entry, 'uploadDate': '2026-11-21T20:00:00Z'}), POST))
        self.assertIsNone(publication_time(post_page(POST, {**entry, 'datePublished': '2026-11-22T00:00:00Z'}), POST))

    def test_direct_video_normalizes_only_original_tiktok_video_urls(self):
        self.assertEqual(video_permalink(POST.replace('www.', '') + '/?utm_medium=example'), POST)
        for url in (PROFILE, POST.replace('/video/', '/photo/'), 'https://vm.tiktok.com/sample/',
                    POST.replace('tiktok.com', 'tiktok.com.example'), POST[:-3] + '１２３'):
            with self.subTest(url=url):
                self.assertIsNone(video_permalink(url))

    def test_direct_video_returns_verified_original_date_without_oembed(self):
        client = Mock()
        client.get.return_value = post_page(POST, {
            '@type': 'VideoObject', 'url': POST, 'datePublished': '2026-11-22T12:00:00Z',
        })
        result = direct_video_review(POST, client, NOW)
        self.assertEqual(result, {'url': POST, 'status': 'fresh_needs_venue_review',
                                  'published_at': '2026-11-22T12:00:00+00:00'})
        client.get.assert_called_once_with(POST, {'www.tiktok.com'})

    def test_video_oembed_confirms_identity_but_cannot_supply_freshness(self):
        client = Mock()
        for author, video, number, status in (
            (PROFILE, POST, '123', 'identity_verified'),
            (PROFILE + '2', POST, '123', 'identity_unverified'),
            (PROFILE, POST + '4', '123', 'identity_unverified'),
            (PROFILE, POST, '1234', 'identity_unverified'),
        ):
            with self.subTest(author=author, video=video, number=number):
                client.get.side_effect = [
                    post_page(POST),
                    {'author_url': author, 'html': f'<blockquote cite="{video}" data-video-id="{number}"></blockquote>',
                     'uploadDate': '2026-11-22T12:00:00Z'},
                ]
                result = direct_video_review(POST, client, NOW)
                self.assertEqual(result['status'], 'publication_time_unverified')
                self.assertIsNone(result['published_at'])
                self.assertEqual(result['oembed'], status)

    def test_current_oembed_player_matches_only_an_exact_official_video_id(self):
        client = Mock()
        player = 'https://www.tiktok.com/player/v1/123?embed_from=oembed'
        for product, src, status in (
            ('123', player, 'video_id_verified'),
            ('1234', player, 'identity_unverified'),
            ('123', player.replace('/123?', '/1234?'), 'identity_unverified'),
            ('123', player.replace('tiktok.com', 'tiktok.com.example'), 'identity_unverified'),
        ):
            with self.subTest(product=product, src=src):
                client.get.side_effect = [
                    post_page(POST),
                    {'embed_product_id': product, 'embed_type': 'video', 'html': f'<iframe src="{src}"></iframe>'},
                ]
                result = direct_video_review(POST, client, NOW)
                self.assertEqual(result['oembed'], status)
                self.assertIsNone(result['published_at'])

    def test_profile_audit_checks_at_most_two_original_posts_from_same_account(self):
        urls = [PROFILE + '/video/' + str(i) for i in range(123, 126)]
        html = ''.join(f'<a href="{url}">Video</a>' for url in urls)
        html += '<a href="https://www.tiktok.com/@another/video/999">Related</a>'
        client = Mock()
        client.get.side_effect = [
            {'author_url': PROFILE, 'html': '<blockquote></blockquote>'},
            BeautifulSoup(html, 'html.parser'),
            post_page(urls[2], {'@type': 'VideoObject', 'url': urls[2], 'uploadDate': '2026-11-22T08:00:00Z'}),
            post_page(urls[1], {'@type': 'VideoObject', 'url': urls[1], 'uploadDate': '2026-11-12T08:00:00Z'}),
        ]
        result = review_profile({'url': PROFILE}, client, NOW)
        self.assertEqual([row['url'] for row in result['posts']], [urls[2], urls[1]])
        self.assertEqual([row['status'] for row in result['posts']], ['fresh_needs_venue_review', 'outside_fresh_window'])
        self.assertEqual(client.get.call_count, 4)

    def test_duplicate_city_profiles_make_one_request_on_transport_failure(self):
        client = Mock()
        client.get.side_effect = FetchError('tls_handshake_failed')
        identity = {'url': PROFILE, 'publisher_id': 'organizer'}
        with patch('trending.tiktok_public.reviewed_tiktok_profiles', side_effect=[
            [identity], [identity], [],
        ]):
            result = audit(client, NOW)
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(result['profiles'][0]['reason'], 'tls_handshake_failed')
        self.assertEqual(result['metered_provider_requests'], 0)
        self.assertEqual(result['published'], 0)
        self.assertEqual(len(result['profiles'][0]['city_hints']), 2)

    def test_browser_is_only_used_when_direct_profile_has_no_original_links(self):
        client = Mock()
        client.get.side_effect = [
            {'author_url': PROFILE, 'html': '<blockquote></blockquote>'},
            BeautifulSoup('<main></main>', 'html.parser'),
            BeautifulSoup('<a href="/@organizer/video/123">Video</a>', 'html.parser'),
            post_page(POST, {'@type': 'VideoObject', 'url': POST, 'uploadDate': '2026-11-22T08:00:00Z'}),
        ]
        result = review_profile({'url': PROFILE}, client, NOW, browser=True)
        self.assertEqual(result['posts'][0]['status'], 'fresh_needs_venue_review')
        self.assertEqual(client.get.call_args_list[2].kwargs, {'render': True})
        self.assertEqual(client.get.call_count, 4)
