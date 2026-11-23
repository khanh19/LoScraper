from datetime import datetime, timedelta, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup

from trending.http import FetchError
from trending.instagram_public import instagram_profile, review, review_profile


POST = 'https://www.instagram.com/reel/Abc123'
NOW = datetime(2026, 11, 22, 20, tzinfo=timezone.utc)  # November 23 in Vietnam.
PROFILE = 'https://www.instagram.com/sample.account/'


def post_page(*descriptions, canonical=POST, og_url=POST):
    markup = '<html><head>'
    if canonical:
        markup += f'<link rel="canonical" href="{canonical}">'
    if og_url:
        markup += f'<meta property="og:url" content="{og_url}">'
    for description in descriptions:
        markup += f'<meta property="og:description" content="{escape(description)}">'
    return BeautifulSoup(markup + '</head></html>', 'html.parser')


def profile_page(*media, username='sample.account', link=PROFILE):
    context = {'type': 'Profile', 'username': username, 'profile_link': link, 'owner_id': 123,
               'graphql_media': [{'shortcode_media': item} for item in media]}
    config = {'isProfileEmbed': True, 'contextJSON': json.dumps({'context': context})}
    payload = {'require': [['PolarisEmbedSimple@' + 'a' * 32, 'init', [], [config]]]}
    html = '<script>var s = {}; s.handle(' + json.dumps(payload) + ');</script>'
    return BeautifulSoup(html, 'html.parser')


def media(code='Abc123', hour=2):
    return {
        'shortcode': code, 'taken_at_timestamp': int((NOW - timedelta(hours=hour)).timestamp()),
        'is_video': True, 'owner': {'id': '123', 'username': 'Sample.Account',
                                   'is_private': False, 'is_unpublished': False},
        'edge_media_to_caption': {'edges': [{'node': {'text': 'Sự kiện tại Hà Nội ngày 28/11'}}]},
        'edge_liked_by': {'count': 48}, 'edge_media_to_comment': {'count': 0},
        'like_and_view_counts_disabled': False, 'coauthor_producers': [],
    }


class InstagramPublicTests(unittest.TestCase):
    def test_profile_embed_returns_only_fresh_original_owned_posts(self):
        clip = media()
        unrelated = {**media('Other'), 'owner': {**clip['owner'], 'id': '124'}}
        unpublished = {**media('Private'), 'owner': {**clip['owner'], 'is_unpublished': True}}
        client = Mock()
        client.get.return_value = profile_page(
            media('Future', hour=-1), clip, unrelated, unpublished, media('Old', hour=169),
        )
        result = review_profile({'url': PROFILE}, client, NOW)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(result['posts'], [{
            'url': POST, 'published_at': '2026-11-22T18:00:00+00:00',
            'status': 'fresh_needs_venue_review', 'account': 'sample.account',
            'caption': 'Sự kiện tại Hà Nội ngày 28/11', 'likes': 48, 'comments': 0,
        }])
        client.get.assert_called_once_with(PROFILE + 'embed/', {'instagram.com', 'www.instagram.com'})

    def test_profile_embed_ignores_conflicts_and_hides_unavailable_counts(self):
        client = Mock()
        hidden = {**media('Photo'), 'is_video': False, 'like_and_view_counts_disabled': True}
        client.get.return_value = profile_page(media(), media(hour=3), hidden)
        result = review_profile({'url': PROFILE}, client, NOW)
        self.assertEqual(result['conflicting_posts'], 1)
        self.assertEqual(len(result['posts']), 1)
        self.assertEqual(result['posts'][0]['url'], 'https://www.instagram.com/p/Photo')
        self.assertNotIn('likes', result['posts'][0])

    def test_profile_embed_does_not_attribute_collaboration_to_profile_owner(self):
        client = Mock()
        collaborative = {**media(), 'coauthor_producers': [{'username': 'sample.account'}]}
        missing_attribution = media('Unknown')
        missing_attribution.pop('coauthor_producers')
        client.get.return_value = profile_page(collaborative, missing_attribution)
        result = review_profile({'url': PROFILE}, client, NOW)
        self.assertEqual(len(result['posts']), 2)
        for row in result['posts']:
            self.assertEqual(row['status'], 'coauthored_or_unknown_attribution')
            self.assertEqual(row['profile_account'], 'sample.account')
            self.assertNotIn('account', row)

    def test_profile_embed_requires_expected_module_and_profile_identity(self):
        client = Mock()
        client.get.return_value = profile_page(media(), link='https://www.instagram.com/unrelated/')
        self.assertEqual(review_profile({'url': PROFILE}, client, NOW)['status'], 'profile_identity_unverified')
        html = str(profile_page(media())).replace('PolarisEmbedSimple', 'UnrelatedWidget')
        client.get.return_value = BeautifulSoup(html, 'html.parser')
        self.assertEqual(review_profile({'url': PROFILE}, client, NOW)['status'], 'public_profile_metadata_missing')
        self.assertIsNone(instagram_profile('https://www.instagram.com.example.org/sample.account/'))
        self.assertIsNone(instagram_profile(POST))

    def test_exact_public_preview_records_day_and_engagement(self):
        client = Mock()
        client.get.return_value = post_page(
            '1,234 likes, 1 comment - Sample.Account trên November 21, 2026: Caption November 28.',
            '1,234 likes, 1 comment - sample.account on November 21, 2026: Another caption.',
            og_url='https://instagram.com/p/Abc123/?utm_source=fixture',
        )
        result = review(POST + '/?igsh=fixture', client, NOW)
        self.assertEqual(result, {
            'url': POST, 'publication_day': '2026-11-21', 'status': 'recent_day_needs_venue_review',
            'account': 'sample.account', 'likes': 1234, 'comments': 1,
        })
        client.get.assert_called_once_with(POST + '/', {'www.instagram.com', 'instagram.com'})

    def test_old_date_with_current_caption_and_future_date_stay_outside_window(self):
        client = Mock()
        for day, status in ((16, 'outside_review_window'), (17, 'recent_day_needs_venue_review'),
                            (23, 'recent_day_needs_venue_review'), (24, 'outside_review_window')):
            with self.subTest(day=day):
                client.get.return_value = post_page(
                    f'0 likes, 0 comments - sample on November {day}, 2026: Event on November 23.',
                )
                result = review(POST, client, NOW)
                self.assertEqual(result['status'], status)
                self.assertEqual(result['publication_day'], f'2026-11-{day}')
                self.assertEqual(result['likes'], 0)

    def test_no_identity_or_contradictory_identity_holds_the_evidence(self):
        client = Mock()
        for canonical, og_url in ((None, None), (POST, POST + '4'), (POST, 'https://www.instagram.com/accounts/login/')):
            with self.subTest(canonical=canonical, og_url=og_url):
                client.get.return_value = post_page('5 likes, 1 comment - sample on November 21, 2026: Test',
                                                   canonical=canonical, og_url=og_url)
                result = review(POST, client, NOW)
                self.assertEqual(result['status'], 'post_identity_unverified')
                self.assertIsNone(result['publication_day'])

    def test_unrecognized_or_conflicting_previews_do_not_invent_metrics(self):
        client = Mock()
        client.get.return_value = post_page('Workshop on November 21, 2026')
        self.assertEqual(review(POST, client, NOW)['status'], 'public_metadata_missing')
        client.get.return_value = post_page('5 likes, 1 comment - sample on November 21, 2026: One',
                                          '5 likes, 1 comment - sample on November 20, 2026: Other')
        result = review(POST, client, NOW)
        self.assertEqual(result['status'], 'public_metadata_conflict')
        self.assertNotIn('likes', result)

    def test_transport_failure_and_bad_input_are_bounded(self):
        client = Mock()
        client.get.side_effect = FetchError('http_429')
        result = review(POST, client, NOW)
        self.assertEqual(result['status'], 'public_post_unavailable')
        self.assertEqual(result['reason'], 'http_429')
        with self.assertRaisesRegex(ValueError, 'invalid_instagram_permalink'):
            review('https://instagram.com/sample/', client, NOW)
        client.get.assert_called_once()
