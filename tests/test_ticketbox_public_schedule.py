import unittest
from unittest.mock import Mock

from trending.adapters import Ticketbox
from trending.http import FetchError
from trending.model import Candidate, CONFIRMED_SCHEDULE_CONFLICT, PUBLISHER_CONFIRMED_CANCELLATION


class TicketboxPublicSchedule(unittest.TestCase):
    def setUp(self):
        self.adapter = Ticketbox("ticketbox", {"hosts": ["ticketbox.vn"]})
        self.candidate = Candidate("ticketbox", "Ticketbox", "https://ticketbox.vn/workshop-23330", "Art", "event")
        self.client = Mock()

    def enrich(self, rows, event_id=23330, status=None, **fields):
        self.client.get.return_value = {"data": {"result": {
            "id": event_id, "status": status, "showings": rows, "categoriesV2": ["seminarsworkshops"], **fields
        }}}
        return self.adapter.enrich(self.candidate, None, self.client, None)

    def test_two_workshops_one_week_apart(self):
        rows = [{"startTime": f"2026-11-{day}T02:30:00Z", "endTime": f"2026-11-{day}T04:30:00Z"}
                for day in (22, 29)]
        candidate = self.enrich(rows)
        self.assertEqual(len(candidate.occurrences), 2)
        self.assertEqual(candidate.occurrences[0].ends_at, "2026-11-22T04:30:00+00:00")
        self.assertEqual(candidate.category, "workshop")

    def test_multi_day_booking_window_is_not_a_fifth_fashion_show(self):
        def row(start, end):
            return {"startTime": start, "endTime": end}

        opening = row("2026-11-26T11:00:00Z", "2026-11-26T16:00:00Z")
        closing = row("2026-11-28T18:00:00+07:00", "2026-11-28T23:00:00+07:00")
        span = row(opening["startTime"], "2026-11-28T16:00:00Z")
        shows = [opening, span, row("2026-11-27T12:00:00Z", "2026-11-27T13:30:00Z"),
                 row("2026-11-27T14:00:00Z", "2026-11-27T15:00:00Z"), closing]
        candidate = self.enrich(shows)
        self.assertEqual(len(candidate.occurrences), 4)
        self.assertNotIn(("2026-11-26T11:00:00+00:00", "2026-11-28T16:00:00+00:00"),
                         [(slot.starts_at, slot.ends_at) for slot in candidate.occurrences])

    def test_overnight_and_unbracketed_showtimes_stay_available(self):
        rows = [
            {"startTime": "2026-11-26T15:30:00Z", "endTime": "2026-11-26T18:00:00Z"},
            {"startTime": "2026-11-26T15:30:00Z", "endTime": "2026-11-28T22:00:00Z"},
            {"startTime": "2026-11-28T16:00:00Z", "endTime": "2026-11-28T21:00:00Z"},
        ]
        self.assertEqual(len(self.enrich(rows).occurrences), 3)

    def test_daily_pass_windows_are_held_when_activities_have_separate_start_times(self):
        fields = {'categoriesV2': ['attractionsexperiences'], 'description': (
            '<strong>Giờ hoạt động của công viên:</strong> 09:00 – 20:00. '
            'Hãy kiểm tra thời điểm bắt đầu trải nghiệm trên bảng thông báo điện tử.')}
        candidate = self.enrich([{'startTime': '2026-11-24T17:00:00Z',
                                  'endTime': '2026-11-25T16:59:00Z'}], **fields)
        self.assertEqual(candidate.occurrences, [])
        self.assertIn('unresolved_admission_session_times', candidate.reasons)
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, candidate.reasons)
        self.assertEqual(candidate.status, 'active')

    def test_timed_attraction_with_real_start_and_end_is_retained(self):
        rows = [{'startTime': '2026-11-27T17:00:00+07:00', 'endTime': '2026-11-27T19:00:00+07:00'}]
        candidate = self.enrich(rows, categoriesV2=['attractionsexperiences'], description=(
            'Giờ hoạt động của công viên: 09:00 – 20:00. '
            'Hãy kiểm tra thời điểm bắt đầu trải nghiệm tại quầy.'))
        self.assertEqual(len(candidate.occurrences), 1)
        self.assertNotIn(CONFIRMED_SCHEDULE_CONFLICT, candidate.reasons)

    def test_flexible_check_in_is_held_even_when_shown_as_a_timed_window(self):
        rows = [{'startTime': '2026-11-27T10:00:00Z', 'endTime': '2026-11-27T14:00:00Z'}]
        candidate = self.enrich(rows, categoriesV2=['attractionsexperiences'], description=(
            'Vé trải nghiệm kéo dài 2 tiếng, bắt đầu tính từ thời điểm <b>check-in</b> tại quầy vé.'))
        self.assertEqual(candidate.occurrences, [])
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, candidate.reasons)
        self.assertNotIn(PUBLISHER_CONFIRMED_CANCELLATION, candidate.reasons)

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

    def test_public_listing_requires_first_party_event_links(self):
        self.client.get.return_value = {"data": {"results": [
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/art-23330?utm_source=home"},
            {"saleStage": "on_sale", "deeplink": "https://example.org/art-23330"},
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/search-23330"},
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/search"},
            {"saleStage": "on_sale", "deeplink": None},
            {"saleStage": "coming_soon", "deeplink": "https://ticketbox.vn/art-23332"},
        ]}}
        self.assertEqual(self.adapter.public_listing_links(self.client), ["https://ticketbox.vn/art-23330"])
        self.client.get.return_value = {"data": {}}
        with self.assertRaisesRegex(FetchError, "invalid_public_listing"):
            self.adapter.public_listing_links(self.client)

    def test_public_listing_city_is_a_bounded_discovery_hint(self):
        self.client.get.return_value = {"data": {"results": [
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/hcmc-1234",
             "city": {"vi": "TP.HCM", "en": "HCMC"}},
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/hanoi-1235",
             "city": {"vi": "Hà Nội", "en": "Ha Noi"}},
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/conflict-1236",
             "city": {"vi": "Đà Nẵng", "en": "Ha Noi"}},
            {"saleStage": "on_sale", "deeplink": "https://ticketbox.vn/online-1237", "city": None},
        ]}}
        self.assertEqual(self.adapter.public_listing_links(self.client, city_hint="hanoi"),
                         ["https://ticketbox.vn/hanoi-1235"])
        self.assertEqual(self.adapter.public_listing_links(self.client, city_hint="hcmc"),
                         ["https://ticketbox.vn/hcmc-1234"])
        self.assertEqual(len(self.adapter.public_listing_links(self.client)), 4)
