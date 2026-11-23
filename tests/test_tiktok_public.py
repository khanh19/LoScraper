from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from trending.http import FetchError
from trending.tiktok_public import audit, publication_time, review_profile

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
        with patch('trending.tiktok_public.reviewed_tiktok_profile', side_effect=[
            {'url': PROFILE, 'publisher_id': 'organizer'}, {'url': PROFILE, 'publisher_id': 'organizer'}, None,
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
            BeautifulSoup(f'<a href="{POST}">Video</a>', 'html.parser'),
            post_page(POST, {'@type': 'VideoObject', 'url': POST, 'uploadDate': '2026-11-22T08:00:00Z'}),
        ]
        result = review_profile({'url': PROFILE}, client, NOW, browser=True)
        self.assertEqual(result['posts'][0]['status'], 'fresh_needs_venue_review')
        self.assertEqual(client.get.call_args_list[2].kwargs, {'render': True})
        self.assertEqual(client.get.call_count, 4)
