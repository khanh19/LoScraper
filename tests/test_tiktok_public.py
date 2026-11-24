from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from trending.discover import review_tiktok_leads
from trending.http import FetchError
from trending.tiktok_public import audit, direct_post_review, post_permalink, publication_time, review_profile

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
PROFILE = 'https://www.tiktok.com/@organizer'
POST = PROFILE + '/video/123'
PHOTO = PROFILE + '/photo/456'


def post_page(url, *entries):
    markup = f'<link rel="canonical" href="{url}">'
    markup += '<script type="application/ld+json">' + json.dumps(entries) + '</script>'
    return BeautifulSoup(markup, 'html.parser')


def detail_page(item, *, page=None, status=0):
    detail = {'statusCode': status, 'itemInfo': {'itemStruct': item}}
    state = {'__DEFAULT_SCOPE__': {'webapp.video-detail': detail}}
    markup = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
    return BeautifulSoup(str(page or '') + markup + json.dumps(state) + '</script>', 'html.parser')


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

    def test_permalink_normalizes_only_original_tiktok_video_and_photo_urls(self):
        for post in (POST, PHOTO):
            self.assertEqual(post_permalink(post.replace('www.', '') + '/?utm_medium=example'), post)
        for url in (PROFILE, POST.replace('/video/', '/story/'), 'https://vm.tiktok.com/sample/',
                    POST.replace('tiktok.com', 'tiktok.com.example'), POST[:-3] + '１２３'):
            with self.subTest(url=url):
                self.assertIsNone(post_permalink(url))

    def test_direct_video_returns_verified_original_date_without_oembed(self):
        client = Mock()
        client.get.return_value = post_page(POST, {
            '@type': 'VideoObject', 'url': POST, 'datePublished': '2026-11-22T12:00:00Z',
        })
        result = direct_post_review(POST, client, NOW)
        self.assertEqual(result, {'url': POST, 'status': 'fresh_needs_venue_review',
                                  'published_at': '2026-11-22T12:00:00+00:00'})
        client.get.assert_called_once_with(POST, {'www.tiktok.com'})

    def test_matching_fresh_original_keeps_engagement_on_the_lead(self):
        published = NOW - timedelta(hours=8)
        item = {'id': '123', 'author': {'uniqueId': 'organizer'}, 'video': {'id': '123'},
                'createTime': int(published.timestamp()),
                'stats': {'playCount': 1102, 'diggCount': 31, 'commentCount': 0, 'shareCount': True}}
        post = {'platform': 'tiktok', 'url': POST, 'published_at': None}
        client = Mock()
        client.get.return_value = detail_page(item)
        leads, reviews = review_tiktok_leads([post], client, NOW)
        self.assertEqual(leads[0]['published_at'], published.isoformat())
        self.assertEqual(leads[0]['engagement_snapshot'], {
            'source': 'verified_original_tiktok_post', 'account': 'organizer',
            'evaluated_at': NOW.isoformat(), 'views': 1102, 'likes': 31, 'comments': 0,
        })
        self.assertEqual(leads[0]['engagement_snapshot'], reviews[0]['engagement_snapshot'])
        client.get.return_value = detail_page({**item, 'id': '124'})
        no_match, reviews = review_tiktok_leads([post], client, NOW)
        self.assertEqual(reviews[0]['status'], 'publication_time_unverified')
        self.assertNotIn('engagement_snapshot', no_match[0])

    def test_photo_date_requires_explicit_original_post_evidence(self):
        entry = {'@type': 'SocialMediaPosting', 'url': PHOTO, 'datePublished': '2026-11-22T12:00:00Z'}
        client = Mock()
        client.get.return_value = post_page(PHOTO, entry)
        result = direct_post_review(PHOTO, client, NOW)
        self.assertEqual(result, {'url': PHOTO, 'status': 'fresh_needs_venue_review',
                                  'published_at': '2026-11-22T12:00:00+00:00'})
        variants = (
            {**entry, '@type': 'ImageObject'},
            {**entry, 'url': PHOTO.replace('@organizer', '@another')},
            {**entry, 'url': None, 'embedUrl': 'https://www.tiktok.com/player/v1/456'},
            {**entry, 'datePublished': '2026-11-22'},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                client.reset_mock()
                client.get.return_value = post_page(PHOTO, variant)
                result = direct_post_review(PHOTO, client, NOW)
                self.assertEqual(result['status'], 'publication_time_unverified')
                self.assertIsNone(result['published_at'])
                client.get.assert_called_once_with(PHOTO, {'www.tiktok.com'})

    def test_public_page_data_can_date_the_exact_post_without_canonical_markup(self):
        item = {'id': '123', 'author': {'uniqueId': 'organizer'},
                'createTime': '1794562976', 'video': {'id': '123'}}
        expected = datetime(2026, 11, 13, 9, 42, 56, tzinfo=timezone.utc)
        self.assertEqual(publication_time(detail_page(item), POST), expected)
        photo = {**item, 'id': '456', 'imagePost': {'images': [{}]}}
        self.assertEqual(publication_time(detail_page(photo), PHOTO), expected)
        self.assertIsNone(publication_time(detail_page({**item, 'id': '124'}), POST))
        self.assertIsNone(publication_time(detail_page({**item, 'author': {'uniqueId': 'another'}}), POST))
        self.assertIsNone(publication_time(detail_page({**item, 'createTime': '2026-11-23'}), POST))
        self.assertIsNone(publication_time(detail_page(item, status=10204), POST))
        self.assertIsNone(publication_time(detail_page({**item, 'id': '456'}), PHOTO))

    def test_conflicting_public_page_bindings_and_dates_block_the_post(self):
        item = {'id': '123', 'author': {'uniqueId': 'organizer'},
                'createTime': '1794562976', 'video': {'id': '123'}}
        entry = {'@type': 'VideoObject', 'url': POST, 'uploadDate': '2026-11-23T08:00:00Z'}
        self.assertIsNone(publication_time(detail_page(item, page=post_page(POST, entry)), POST))
        self.assertIsNone(publication_time(detail_page(item, page=post_page(POST + '4')), POST))

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
                result = direct_post_review(POST, client, NOW)
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
                result = direct_post_review(POST, client, NOW)
                self.assertEqual(result['oembed'], status)
                self.assertIsNone(result['published_at'])

    def test_profile_audit_checks_at_most_two_original_posts_from_same_account(self):
        urls = [PROFILE + '/photo/123', PHOTO, PROFILE + '/video/124']
        html = ''.join(f'<a href="{url}">Post</a>' for url in urls)
        html += '<a href="https://www.tiktok.com/@organizer2/photo/999">Related</a>'
        client = Mock()
        client.get.side_effect = [
            {'author_url': PROFILE, 'html': '<blockquote></blockquote>'},
            BeautifulSoup(html, 'html.parser'),
            post_page(urls[2], {'@type': 'VideoObject', 'url': urls[2], 'uploadDate': '2026-11-22T08:00:00Z'}),
            post_page(PHOTO, {'@type': 'SocialMediaPosting', 'url': PHOTO, 'datePublished': '2026-11-12T08:00:00Z'}),
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

    def test_creator_oembed_400_does_not_discard_owned_public_photo_link(self):
        client = Mock()
        client.get.side_effect = [
            FetchError('http_400'),
            BeautifulSoup(f'<a href="{PHOTO}">Photo</a>', 'html.parser'),
            post_page(PHOTO, {'@type': 'SocialMediaPosting', 'url': PHOTO, 'datePublished': '2026-11-22T08:00:00Z'}),
        ]
        result = review_profile({'url': PROFILE}, client, NOW, browser=True)
        self.assertEqual(result['profile_oembed'], 'http_400')
        self.assertEqual(result['posts'][0]['url'], PHOTO)
        self.assertEqual(result['posts'][0]['status'], 'fresh_needs_venue_review')
        self.assertEqual(client.get.call_count, 3)
        client.render_tiktok_creator.assert_not_called()

    def test_creator_oembed_access_or_throttle_errors_stop_the_audit(self):
        for reason in ('http_401', 'http_403', 'http_429'):
            with self.subTest(reason=reason):
                client = Mock()
                client.get.side_effect = FetchError(reason)
                result = review_profile({'url': PROFILE}, client, NOW, browser=True)
                self.assertEqual(result['reason'], reason)
                self.assertEqual(client.get.call_count, 1)
                self.assertEqual(result['posts'], [])
                client.render_tiktok_creator.assert_not_called()

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
        client.render_tiktok_creator.assert_not_called()

    def test_official_creator_widget_can_discover_an_original_post(self):
        client = Mock()
        html = f'<blockquote data-embed-type="creator" data-unique-id="organizer" cite="{PROFILE}"></blockquote>'
        client.get.side_effect = [
            {'author_url': PROFILE, 'html': html},
            BeautifulSoup('<main></main>', 'html.parser'),
            BeautifulSoup('<main></main>', 'html.parser'),
            post_page(POST, {'@type': 'VideoObject', 'url': POST, 'uploadDate': '2026-11-22T08:00:00Z'}),
        ]
        client.render_tiktok_creator.return_value = BeautifulSoup(
            f'<a href="{POST}">Video</a><a href="{PROFILE}/video/not-a-video">Invalid</a>'
            '<a href="https://www.tiktok.com/@another/video/999">Other artist</a>', 'html.parser',
        )
        result = review_profile({'url': PROFILE}, client, NOW, browser=True)
        client.render_tiktok_creator.assert_called_once_with(PROFILE)
        self.assertEqual(result['creator_embed'], 'original_links_found')
        self.assertEqual([post['url'] for post in result['posts']], [POST])
        self.assertEqual(result['posts'][0]['status'], 'fresh_needs_venue_review')

    def test_mismatched_creator_widget_is_not_rendered(self):
        client = Mock()
        client.get.side_effect = [
            {'author_url': PROFILE, 'html': f'<blockquote data-embed-type="creator" '
             f'data-unique-id="unrelated" cite="{PROFILE}"></blockquote>'},
            BeautifulSoup('<main></main>', 'html.parser'),
            BeautifulSoup('<main></main>', 'html.parser'),
        ]
        result = review_profile({'url': PROFILE}, client, NOW, browser=True)
        self.assertEqual(result['creator_embed'], 'identity_unverified')
        self.assertEqual(result['posts'], [])
        client.render_tiktok_creator.assert_not_called()
