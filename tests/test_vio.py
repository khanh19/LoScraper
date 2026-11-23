import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from bs4 import BeautifulSoup

from trending.adapters import Vio, collect_source, load_sources
from trending.model import CONFIRMED_SCHEDULE_CONFLICT, PUBLISHER_CONFIRMED_CANCELLATION


NOW = datetime(2026, 11, 23, 20, tzinfo=timezone.utc)
SCHEDULED = 'https://schema.org/EventScheduled'
CONFIG = load_sources()['vio']
WINE, _, ESTELLA, VINHOMES = CONFIG['reviewed_detail_pages']


def page(url, slots, buttons, details='Đón Giáng sinh', *, status=SCHEDULED,
         different_title=None, wrong_branch=False):
    review = CONFIG['reviewed_detail_pages'][url]
    title = different_title or review['title']
    organizer = {'name': review['organizer']}
    location = {'name': review['venue'], 'address': {
        'streetAddress': review['booking_street'], 'addressRegion': 'Thành phố Hồ Chí Minh',
    }}
    children = [
        {'@type': 'Event', '@id': f'{url}#showtime-{index}', 'startDate': start, 'endDate': end,
         'organizer': organizer, 'location': location if not wrong_branch else {'name': 'Khác'},
         'eventStatus': SCHEDULED}
        for index, (start, end) in enumerate(slots)
    ]
    payload = {'@type': 'Event', 'url': url, 'name': title, 'organizer': organizer,
               'location': location, 'eventStatus': status, 'subEvent': children}
    times = ''.join(f'<button aria-expanded="true">{button}</button>' for button in buttons)
    return BeautifulSoup(
        f'<h1>{title}</h1><script type="application/ld+json">{json.dumps(payload)}</script>'
        f'<section id="info">{details}</section><section id="tickets">{times}</section>',
        'html.parser',
    )


class VioSchedule(unittest.TestCase):
    def setUp(self):
        self.adapter = Vio('vio', CONFIG)
        self._estella_slots = [('2026-11-29T06:00:00Z', '2026-11-29T08:00:00Z'),
                               ('2026-11-29T08:00:00Z', '2026-11-29T10:00:00Z')]

    def test_discovery_fetches_reviewed_pages_and_keeps_individual_sessions(self):
        slots = [(f'2026-12-{day}T12:00:00+07:00', f'2026-12-{day}T22:00:00+07:00') for day in (19, 20)]
        client = Mock()
        client.get.return_value = page(WINE, slots, [
            'T7, 19/12/2026 12:00 - 22:00 Mua vé', 'CN, 20/12/2026 12:00 - 22:00 Mua vé',
        ])
        rows, errors = collect_source('vio', CONFIG, client, NOW, limit=1)
        self.assertEqual(errors, [])
        self.assertEqual([call.args[0] for call in client.get.call_args_list], [WINE])
        event, = rows
        self.assertEqual(event.validate(NOW), [])
        self.assertEqual((event.city_slug, event.category, event.owner_key), ('hcmc', 'market', 'saigon-outcast'))
        self.assertEqual([(row.starts_at, row.ends_at) for row in event.occurrences], slots)

    def test_same_day_slots_require_all_times_and_agree_with_description(self):
        buttons = ['CN, 29/11/2026 13:00 - 15:00 | 2 suất']
        accurate = 'Ngày: 29/11/2026. Ca 1: 13:00 - 15:00. Ca 2: 15:00 - 17:00.'
        event = self.adapter.parse(page(ESTELLA, self._estella_slots, buttons, accurate), ESTELLA, NOW)
        self.assertEqual(event.validate(NOW), [])
        self.assertEqual([row.starts_at for row in event.occurrences],
                         ['2026-11-29T13:00:00+07:00', '2026-11-29T15:00:00+07:00'])
        for text in (accurate.replace('15:00 - 17:00', '16:00 - 18:00'),
                     accurate.replace('29/11/2026', '30/11/2026'),
                     accurate.split('Ca 2:')[0]):
            with self.subTest(text=text):
                event = self.adapter.parse(page(ESTELLA, self._estella_slots, buttons, text), ESTELLA, NOW)
                self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, event.validate(NOW))
                self.assertEqual(event.occurrences, [])
        unmatched = self.adapter.parse(page(ESTELLA, self._estella_slots, buttons), ESTELLA, NOW)
        self.assertIn('unresolved_individual_sessions', unmatched.validate(NOW))

    def test_venue_change_and_reused_source_identity_do_not_publish(self):
        buttons = ['CN, 29/11/2026 13:00 - 15:00 | 2 suất']
        event = self.adapter.parse(page(ESTELLA, self._estella_slots, buttons, wrong_branch=True), ESTELLA, NOW)
        self.assertIn('unresolved_individual_sessions', event.validate(NOW))
        reused = self.adapter.parse(
            page(ESTELLA, self._estella_slots, buttons, different_title='Chương trình khác'), ESTELLA, NOW,
        )
        self.assertIn('event_identity_conflict', reused.validate(NOW))
        cancelled = self.adapter.parse(
            page(ESTELLA, [], [], status='https://schema.org/EventCancelled'), ESTELLA, NOW,
        )
        self.assertEqual(cancelled.status, 'cancelled')
        self.assertIn(PUBLISHER_CONFIRMED_CANCELLATION, cancelled.validate(NOW))

    def test_booking_and_description_conflict_holds_vinhomes(self):
        event = self.adapter.parse(
            page(VINHOMES, [('2026-11-28T20:00:00+07:00', '2026-11-28T22:00:00+07:00')],
                 ['T7, 28/11/2026 20:00 - 22:00 Mua vé'],
                 'Thời gian: 19:00 - 21:00, thứ Bảy, 28/11/2026.'),
            VINHOMES, NOW,
        )
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, event.validate(NOW))
        self.assertEqual(event.occurrences, [])
