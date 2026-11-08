import unittest
from datetime import datetime,timezone,timedelta
from trending.announcements import social_sessions
from trending.intent import queries
from trending.model import city_from_address
from trending.adapters import category
from trending.discover import discover
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
