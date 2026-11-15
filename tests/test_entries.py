from datetime import timedelta
import unittest
from bs4 import BeautifulSoup
from trending.adapters import VnExpress, LifeOfDaNang
from test_trending import NOW


class Entries(unittest.TestCase):
    def test_roundup_fields_are_section_scoped_and_keys_survive_reordering(self):
        a='<h2 id="may">Quán Mây</h2><p>Quán Mây nằm tại 12 phố Tràng Tiền, Hà Nội.</p>'
        b='<h2 id="nang">Cafe Nắng</h2><p>Cafe Nắng có địa chỉ tại 20 đường Hải Phòng, Đà Nẵng.</p>'
        adapter=VnExpress('vnexpress',{'name':'VnExpress','hosts':['vnexpress.net'],'roundups':True})
        def parse(body):return adapter.parse_many(BeautifulSoup('<meta property="article:published_time" content="'+NOW.isoformat()+'"><div class="fck_detail">'+body+'</div>','html.parser'),'https://vnexpress.net/test-123456.html',NOW)
        first=parse(a+b);second=parse(b+a)
        self.assertEqual({c.entry_key:c.address for c in first},{c.entry_key:c.address for c in second})
        self.assertEqual({c.city_slug for c in first},{'hanoi','danang'})
        self.assertTrue(all(not c.image_url for c in first))
        self.assertEqual(first[0].venue_name,'Quán Mây')
        self.assertNotIn('Hải Phòng',first[0].original_text)

    def test_ambiguous_sibling_cannot_borrow_address(self):
        adapter=VnExpress('vnexpress',{'name':'VnExpress','hosts':['vnexpress.net'],'roundups':True})
        soup=BeautifulSoup('<div class="fck_detail"><h2>Quán Mây</h2><p>Quán Mây nằm tại 12 phố Tràng Tiền, Hà Nội.</p><h2>Cafe Không rõ</h2><p>Rất nổi tiếng.</p></div>','html.parser')
        rows=adapter.parse_many(soup,'https://vnexpress.net/test-123456.html',NOW)
        self.assertEqual(rows[1].address,'')
        self.assertIn('unverified_city',rows[1].validate(NOW))

    def test_weekly_entries_have_independent_sessions_and_locations(self):
        soup=BeautifulSoup('''<main>Da Nang Weekly · November 4, 2026
        <h2>This Weekend In Da Nang, 6 To 8 November</h2><div><p>Sunday</p>
        <div><p>9am to 10am: Museum tour at Museum.</p><a href="https://www.google.com/maps/search/?query=Museum%2C+31+Tran+Phu%2C+Da+Nang">Map</a></div>
        <div><p>6pm to 8pm: Jazz music at Cafe.</p><a href="https://www.google.com/maps/search/?query=Cafe%2C+12+Nguyen+Van+Thoai%2C+Da+Nang">Map</a></div></div></main>''','html.parser')
        rows=LifeOfDaNang('lifeofdanang',{'name':'Life','hosts':['lifeofdanang.com']}).parse_many(soup,'https://lifeofdanang.com/weekly',NOW)
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0].entry_key,rows[1].entry_key)
        self.assertTrue(all(not c.validate(NOW) for c in rows))
        self.assertEqual(rows[0].occurrences[0].starts_at,'2026-11-08T09:00:00+07:00')
        self.assertEqual(rows[1].venue_name,'Cafe')

    def test_bad_section_parser_does_not_discard_valid_sibling(self):
        from unittest.mock import patch
        adapter=VnExpress('vnexpress',{'name':'VnExpress','hosts':['vnexpress.net'],'roundups':True})
        from test_trending import candidate
        soup=BeautifulSoup('<div class="fck_detail"><h2>Bad</h2><p>x</p><h2>Good</h2><p>y</p></div>','html.parser')
        with patch.object(VnExpress,'parse',side_effect=[ValueError('malformed date'),candidate('place')]):
            rows=adapter.parse_many(soup,'https://vnexpress.net/test-123456.html',NOW)
        self.assertEqual(rows[0],{'extraction_failure':'ValueError'})
        self.assertEqual(rows[1].venue_name,candidate('place').venue_name)

    def test_fallback_key_ignores_session_time_and_price(self):
        from trending.entries import identify
        from test_trending import candidate
        a=candidate();b=candidate();b.price_text='200.000đ';b.occurrences=[]
        node=BeautifulSoup('<h2>Event</h2>','html.parser').h2
        self.assertEqual(identify(a,node).entry_key,identify(b,node).entry_key)

    def test_contextual_weekday_does_not_move_a_friday_session_to_sunday(self):
        soup=BeautifulSoup("""<main>Da Nang Weekly · November 4, 2026
        <h2>This Weekend In Da Nang, 6 To 8 November</h2><div><p>Friday</p>
        <div><p>3pm to 4:30pm: Fragments at Museum. The festival ends on Sunday.</p>
        <a href="https://www.google.com/maps/search/?query=Museum%2C+31+Tran+Phu%2C+Da+Nang">Map</a></div></div></main>""",'html.parser')
        c=LifeOfDaNang('lifeofdanang',{'name':'Life','hosts':['lifeofdanang.com']}).parse_many(soup,'https://lifeofdanang.com/weekly',NOW)[0]
        self.assertIn('2026-11-06',c.occurrences[0].starts_at)
        self.assertIn('no_upcoming_occurrence',c.validate(NOW))
