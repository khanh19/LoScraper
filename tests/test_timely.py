import json
import unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from trending.announcements import social_sessions
from trending.intent import queries
from trending.model import city_from_address
from trending.adapters import category
from trending.discover import discover
from trending.http import FetchError
from bs4 import BeautifulSoup

NOW=datetime(2026,11,8,12,tzinfo=timezone.utc)
class Timely(unittest.TestCase):
    def test_relative_and_overnight(self):
        sessions,reason=social_sessions('DJ tối nay 22:00 - 02:00',NOW.isoformat())
        self.assertIsNone(reason);self.assertTrue(sessions[0].ends_at.startswith('2026-11-09'))
        self.assertEqual(social_sessions('Show cuối tuần này',NOW.isoformat())[1],'ambiguous_weekend')
        self.assertEqual(social_sessions('Show 14/11 20:00 - 22:00',NOW.isoformat())[1],'missing_event_year')
        self.assertEqual(social_sessions('Recap show 07/11/2026',NOW.isoformat())[1],'past_recap')
    def test_individual_sessions_and_equivalent_timezone(self):
        a,e=social_sessions('Festival 14-15/11/2026 12:00 - 23:00',NOW.isoformat())
        self.assertIsNone(e);self.assertEqual(len(a),2)
        b,e=social_sessions('Festival 14-15/11/2026 12:00 - 23:00','2026-11-08T19:00:00+07:00')
        self.assertEqual(a,b)
    def test_full_date_range_is_not_two_sessions(self):
        for separator in ['-', 'đến', 'tới']:
            sessions,reason=social_sessions(f'Triển lãm 07/11/2026 {separator} 27/12/2026 09:00 - 17:00',NOW.isoformat())
            self.assertEqual(sessions,[])
            self.assertEqual(reason,'unresolved_individual_sessions')
    def test_intents_are_not_location_evidence(self):
        q=queries('hcmc',{'music':5})
        self.assertNotEqual(q[0]['category'],'music');self.assertTrue(q[0]['variants'])
        self.assertEqual(city_from_address('182 Nguyễn Văn Hưởng, HCM'),'hcmc')
        self.assertIsNone(city_from_address('Hà Nội và Đà Nẵng'))
        self.assertEqual(category('giải chạy cuối tuần'),'sports')
        self.assertEqual(category('chợ phiên local brand'),'market')
    def test_automatic_discovery_needs_no_provider(self):
        class Client:
            def get(self,*a,**k):return BeautifulSoup('<a href="https://www.tiktok.com/@venue/video/123">Show</a>','html.parser')
        result=discover('hanoi',Client(),NOW,limit=1)
        self.assertEqual(result['provider_requests'],0)
        self.assertEqual(len(result['posts']),1)
        self.assertEqual(result['posts'][0]['city_hint'],'hanoi')
        self.assertTrue(result['posts'][0]['requires_provider_validation'])

    def test_website_detail_budget_skips_calendar_files_and_locale_switches(self):
        life = 'https://lifeofdanang.com'
        nightlife = 'https://vietnamnightlife.com'
        sources = [
            {'id': 'lifeofdanang', 'publisher_id': 'life', 'cities': ['danang'], 'categories': [], 'url': life + '/weekly'},
            {'id': 'vietnamnightlife', 'publisher_id': 'nightlife', 'cities': ['danang'], 'categories': [],
             'url': nightlife + '/en/upcoming-events-1-11.html'},
        ]
        pages = {
            sources[0]['url']: '<main><a href="/api/event-ics/city-show">Calendar</a><a href="/vi/danang/city-show">Details</a></main>',
            sources[1]['url']: '<a href="/ko/su-kien-1-11.html">Switch language</a><a href="/en/nightlife-show-115-15.html">Details</a>',
            life + '/vi/danang/city-show': '<iframe src="https://www.instagram.com/reel/example/embed/"></iframe>',
            nightlife + '/en/nightlife-show-115-15.html': '<main></main>',
        }
        requested = []

        class Client:
            def get(self, url, hosts):
                requested.append(url)
                return BeautifulSoup(pages[url], 'html.parser')

        with patch('trending.discover.DIRECTORY') as directory:
            directory.read_text.return_value = json.dumps(sources)
            result = discover('danang', Client(), NOW)
        self.assertEqual(requested, [sources[0]['url'], life + '/vi/danang/city-show',
                                     sources[1]['url'], nightlife + '/en/nightlife-show-115-15.html'])
        post, = result['posts']
        self.assertEqual(post['url'], 'https://www.instagram.com/reel/example')

    def test_social_discovery_reuses_publisher_tls_fallback_in_browser_mode(self):
        root = 'https://hanoigrapevine.com/vi/'
        detail = 'https://hanoigrapevine.com/vi/2026/11/di-xem-trien-lam'
        source = {'id': 'hanoigrapevine', 'publisher_id': 'grapevine',
                  'cities': ['hanoi'], 'categories': [], 'url': root}
        pages = {
            root: '<a href="' + detail + '">Event</a>',
            detail: '<blockquote class="instagram-media" data-instgrm-permalink="https://www.instagram.com/reel/example/"></blockquote>',
        }
        requested = []

        class Client:
            browser_enabled = True

            def get(self, url, hosts, render=False):
                requested.append((url, render))
                if not render:
                    raise FetchError('tls_handshake_failed')
                return BeautifulSoup(pages[url], 'html.parser')

        with patch('trending.discover.DIRECTORY') as directory:
            directory.read_text.return_value = json.dumps([source])
            result = discover('hanoi', Client(), NOW)
        self.assertEqual(requested, [(root, False), (root, True), (detail, False), (detail, True)])
        self.assertEqual([p['status'] for p in result['pages']], ['complete', 'complete'])
        post, = result['posts']
        self.assertEqual(post['url'], 'https://www.instagram.com/reel/example')
        self.assertIsNone(post['published_at'])
        self.assertEqual(result['provider_requests'], 0)
class DottedSocialDateTests(unittest.TestCase):
    def test_dotted_without_full_year_cannot_fall_back_to_weekday(self):
        published = '2026-11-23T03:00:04+00:00'
        for date in ('29.11', '6.12', '06.12.26'):
            with self.subTest(date=date):
                self.assertEqual(
                    social_sessions(f'Chủ Nhật, {date} | 10:00 – 11:30', published),
                    ([], 'missing_event_year'),
                )

    def test_full_dotted_date_preserves_the_original_session_day(self):
        sessions, reason = social_sessions(
            'Chủ Nhật, 𝟎𝟔.𝟏𝟐.𝟐𝟎𝟐𝟔 | 14:00 – 15:30', '2026-11-23T03:00:04+00:00')
        self.assertIsNone(reason)
        self.assertEqual([(slot.starts_at, slot.ends_at) for slot in sessions], [
            ('2026-12-06T14:00:00+07:00', '2026-12-06T15:30:00+07:00'),
        ])

    def test_foundation_date_is_not_an_anniversary_session(self):
        published = '2026-11-22T14:17:10+00:00'
        slots, reason = social_sessions(
            '1900 x Hennessy Night | Friday 27.11.2026\nĐược thành lập vào ngày 29/11/2019.',
            published,
        )
        self.assertIsNone(reason)
        self.assertEqual([s.starts_at for s in slots], ['2026-11-27T00:00:00+07:00'])
        self.assertEqual(social_sessions('Show 29/11/2019', published), ([], 'past_recap'))
        self.assertEqual(
            social_sessions('Show 29/11/2019 và 27/11/2026', published), ([], 'ambiguous_schedule'))
