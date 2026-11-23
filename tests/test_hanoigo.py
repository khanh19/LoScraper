import unittest
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from trending.adapters import HanoiGo, load_sources

class HanoiGoChecks(unittest.TestCase):
    def parse(self, title='Triển lãm thử nghiệm', schedule='00:00 – 23:59 • 11/11/2026', extras='', text=''):
        html=f'<h1>{title}</h1><div data-testid="article-section-intro">{text}</div><div data-testid="detail-info-venue">Địa điểm 12 Tràng Tiền, Hà Nội</div><div data-testid="detail-info-time">{schedule}</div><div data-testid="article-section-extras">{extras}</div><dl><dt>Thời gian</dt><dd>11 – 20/11/2026</dd></dl>'
        return HanoiGo('hanoigo',load_sources()['hanoigo']).parse(BeautifulSoup(html,'html.parser'),'https://hanoigo.com.vn/event/test',datetime(2026,11,15,tzinfo=timezone.utc))
    def test_inclusive_exhibition_end(self):
        c=self.parse();self.assertEqual(c.city_slug,'hanoi');self.assertEqual(c.occurrences[0].precision,'date');self.assertTrue(c.occurrences[0].ends_at.startswith('2026-11-21'))
    def test_cancelled_range_never_active(self):
        self.assertEqual(self.parse(text='Đã hủy').status,'cancelled')
    def test_incomplete_sessions_held(self):
        c=self.parse(title='Đêm nhạc',schedule='19:00 – 21:00 • 15/11/2026 +2 suất khác',extras='15/11 · 19:00 – 21:00')
        self.assertIn('unresolved_individual_sessions',c.reasons)
    def test_overnight_complete_session(self):
        c=self.parse(title='Đêm nhạc',schedule='22:00 – 02:00 • 15/11/2026',extras='15/11 · 22:00 – 02:00')
        self.assertEqual(c.reasons,[]);self.assertTrue(c.occurrences[0].ends_at.startswith('2026-11-16'))
