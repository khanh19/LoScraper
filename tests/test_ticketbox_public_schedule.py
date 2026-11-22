import unittest
from unittest.mock import Mock

from trending.adapters import Ticketbox
from trending.model import Candidate


class TicketboxPublicSchedule(unittest.TestCase):
    def setUp(self):
        self.adapter = Ticketbox("ticketbox", {"hosts": ["ticketbox.vn"]})
        self.candidate = Candidate("ticketbox", "Ticketbox", "https://ticketbox.vn/workshop-23330", "Art", "event")
        self.client = Mock()

    def enrich(self, rows, event_id=23330):
        self.client.get.return_value = {"data": {"result": {
            "id": event_id, "showings": rows, "categoriesV2": ["seminarsworkshops"]
        }}}
        return self.adapter.enrich(self.candidate, None, self.client, None)

    def test_two_workshops_one_week_apart(self):
        rows = [{"startTime": f"2026-11-{day}T02:30:00Z", "endTime": f"2026-11-{day}T04:30:00Z"}
                for day in (22, 29)]
        candidate = self.enrich(rows)
        self.assertEqual(len(candidate.occurrences), 2)
        self.assertEqual(candidate.occurrences[0].ends_at, "2026-11-22T04:30:00+00:00")
        self.assertEqual(candidate.category, "workshop")

    def test_unresolved_sessions_and_wrong_identity_are_held(self):
        for rows in ([], [{"startTime": "2026-11-22T02:30:00Z"}]):
            with self.subTest(rows=rows):
                self.assertIn("unresolved_individual_sessions", self.enrich(rows).reasons)
        self.assertIn("event_identity_conflict", self.enrich([], 9876).reasons)

    def test_conflicting_and_nonlocal_venues_are_rejected(self):
        examples = [
            ("VINPALACE OCEAN CITY", "Vincom Mega Mall, Thành phố Hà Nội", "hanoi", "outside_supported_cities"),
            ("VINHOMES OCEAN PARK 3", "Xã Nghĩa Trụ, Tỉnh Hưng Yên", "hcmc", "outside_supported_cities"),
            ("Online Event", "", "hcmc", "online_only_event"),
            ("Garden Art", "12 Tràng Tiền, Hà Nội", "hcmc", "venue_city_conflict"),
        ]
        for venue, address, city, reason in examples:
            with self.subTest(venue=venue, reason=reason):
                candidate = Candidate("ticketbox", "Ticketbox", self.candidate.source_url, "Workshop", "event",
                                      venue_name="Venue from listing", address="Address from listing", city_slug=city)
                self.client.get.return_value = {"data": {"result": {
                    "id": 23330, "venue": venue, "address": address,
                    "showings": [{"startTime": "2026-11-22T02:30:00Z", "endTime": "2026-11-22T04:30:00Z"}],
                }}}
                result = self.adapter.enrich(candidate, None, self.client, None)
                self.assertIn(reason, result.reasons)
                self.assertNotEqual(result.status, "cancelled")
