import unittest
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from trending.adapters import Nightlife


class NightlifeLocation(unittest.TestCase):
    def parse(self, extra=''):
        html = '''<div class="p-detail-1"><h1>ABG Ladies Night</h1>
        <ul><li>Time: Every Wednesday</li><li>Place: Ciné Saigon</li></ul>
        <p>Ciné Saigon – Everyday Festival<br>Address: 148 Công Quỳnh, Bến Thành Ward, HCMC<br>Hotline: 0901 866 336</p>'''+extra+'''<div class="p_other"><p>Address: 10 Test, Hanoi</p>
        <li>Place: Unrelated venue</li><li>Time: Every Friday</li></div></div>'''
        return Nightlife('vietnamnightlife', {'name':'Vietnam Nightlife','hosts':['vietnamnightlife.com']}).parse(
            BeautifulSoup(html,'html.parser'), 'https://vietnamnightlife.com/en/abg-ladies-night-906-15.html',datetime(2026,11,21,tzinfo=timezone.utc))

    def test_plain_venue_and_br_address_without_related_contamination(self):
        c=self.parse()
        self.assertEqual(c.venue_name,'Ciné Saigon')
        self.assertEqual(c.city_slug,'hcmc')
        self.assertEqual(c.address,'148 Công Quỳnh, Bến Thành Ward, HCMC')
        self.assertNotIn('Unrelated venue',c.original_text)
        self.assertTrue(c.occurrences)
        self.assertTrue(all(datetime.fromisoformat(o.starts_at).weekday()==2 for o in c.occurrences))

    def test_multiple_primary_addresses_are_held(self):
        c=self.parse('<p>Address: 10 Other Street, Hanoi</p>')
        self.assertIn('ambiguous_event_addresses',c.reasons)
