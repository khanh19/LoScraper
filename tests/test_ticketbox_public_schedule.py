import unittest
from unittest.mock import Mock

from trending.adapters import Ticketbox
from trending.model import Candidate, PUBLISHER_CONFIRMED_CANCELLATION


class TicketboxPublicSchedule(unittest.TestCase):
    def setUp(self):
        self.adapter = Ticketbox("ticketbox", {"hosts": ["ticketbox.vn"]})
        self.candidate = Candidate("ticketbox", "Ticketbox", "https://ticketbox.vn/workshop-23330", "Art", "event")
        self.client = Mock()

    def enrich(self, rows, event_id=23330, status=None):
        self.client.get.return_value = {"data": {"result": {
            "id": event_id, "status": status, "showings": rows, "categoriesV2": ["seminarsworkshops"]
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

    def test_confirmation_uses_the_same_event_and_current_api_status(self):
        self.candidate.status = "cancelled"
        self.candidate.reasons = [PUBLISHER_CONFIRMED_CANCELLATION]
        postponed = self.enrich([], status="postponed")
        self.assertEqual(postponed.status, "cancelled")
        self.assertNotIn(PUBLISHER_CONFIRMED_CANCELLATION, postponed.reasons)
        confirmed = self.enrich([], status="cancelled")
        self.assertEqual(confirmed.reasons.count(PUBLISHER_CONFIRMED_CANCELLATION), 1)
