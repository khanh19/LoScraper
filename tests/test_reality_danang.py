from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from bs4 import BeautifulSoup

from trending.adapters import RealityDaNang, load_sources
from trending.model import CONFIRMED_SCHEDULE_CONFLICT, PUBLISHER_CONFIRMED_CANCELLATION


class RealitySeriesTests(unittest.TestCase):
    def setUp(self):
        config = load_sources()['realitydanang']
        self.adapter = RealityDaNang('realitydanang', config)
        self.url, review = next(iter(config['reviewed_detail_pages'].items()))
        self.now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        self.location = {'@id': self.adapter.venue_id, 'name': 'REALITY',
                         'address': {'streetAddress': '86 Mai Thúc Lân', 'addressLocality': 'Đà Nẵng'}}
        self.sessions = []
        for index, day in enumerate(('2026-11-26', '2026-12-03'), start=1):
            self.sessions.append({
                '@type': 'Event', 'name': review['publisher_title'], 'location': self.location,
                'startDate': day + 'T11:00:00+07:00', 'endDate': day + 'T13:00:00+07:00',
                'eventStatus': self.adapter.scheduled, 'superEvent': {'url': self.url},
                'url': f'https://app.realitydn.com/events/00000000-0000-0000-0000-{index:012d}',
            })
        self.series = {'@type': 'EventSeries', 'url': self.url, 'name': review['publisher_title'],
                       'location': self.location, 'subEvent': self.sessions}
        self.details = {row['url']: deepcopy(row) for row in self.sessions}

    @staticmethod
    def page(data, html=''):
        return BeautifulSoup(f'{html}<script type="application/ld+json">{json.dumps(data)}</script>', 'html.parser')

    def get(self, url, hosts):
        self.assertIn('app.realitydn.com', hosts)
        return self.page(self.details[url])

    def parse(self, link_second=True):
        links = [f'<a href="{row["url"].removeprefix("https://app.realitydn.com")}">{label}</a>'
                 for row, label in zip(self.sessions, ('Thứ 5 26.11 · 11:00 →', 'Thứ 5 3.12 · 11:00 →'))]
        outside_main = f'<div hidden>{links[1]}</div>' if link_second else ''
        page = self.page(self.series, f'<main><h1>{self.series["name"]}</h1>{links[0]}</main>{outside_main}')
        return self.adapter.enrich(self.adapter.parse(page, self.url, self.now), page, self, self.now)

    def test_requires_all_dates_and_preserves_exact_slots(self):
        self.details[self.sessions[1]['url']]['startDate'] = '2026-12-03T04:00:00Z'
        candidate = self.parse()
        self.assertEqual(candidate.validate(self.now), [])
        self.assertEqual([(o.starts_at, o.ends_at) for o in candidate.occurrences], [
            (row['startDate'], row['endDate']) for row in self.sessions
        ])
        missing = self.parse(link_second=False)
        self.assertIn('unresolved_individual_sessions', missing.validate(self.now))
        self.assertFalse(missing.occurrences)

    def test_conflicting_second_session_holds_the_whole_series(self):
        self.details[self.sessions[1]['url']]['endDate'] = '2026-12-03T14:00:00+07:00'
        candidate = self.parse()
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, candidate.validate(self.now))
        self.assertFalse(candidate.occurrences)

    def test_respects_confirmed_cancellations_and_rejects_wrong_venue(self):
        second = self.sessions[1]
        second['eventStatus'] = self.details[second['url']]['eventStatus'] = self.adapter.cancelled
        self.assertEqual(len(self.parse().occurrences), 1)
        first = self.sessions[0]
        first['eventStatus'] = self.details[first['url']]['eventStatus'] = self.adapter.cancelled
        candidate = self.parse()
        self.assertEqual(candidate.status, 'cancelled')
        self.assertIn(PUBLISHER_CONFIRMED_CANCELLATION, candidate.reasons)
        self.details[second['url']]['location']['address']['streetAddress'] = '1 Mai Thúc Lân'
        self.assertIn('unresolved_individual_sessions', self.parse().validate(self.now))
