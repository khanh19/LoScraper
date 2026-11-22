"""Coverage discovery uses current Vietnam month and primary-event evidence."""
import json
import unittest
from unittest.mock import patch
from datetime import timedelta
from bs4 import BeautifulSoup
from trending.adapters import HoGuomOpera, LifeOfDaNang, category, collect_source, load_sources
from test_trending import NOW, candidate
from trending.model import city_from_address
from trending.http import FetchError

class WeeklyCoverage(unittest.TestCase):
    def test_repeated_fetch_failures_stop_source_without_erasing_success(self):
        fetched=[]
        class Adapter:
            hosts={'example.com'}
            def __init__(self,*args):pass
            def fetch(self,client,url):
                fetched.append(url)
                if '/detail' in url:raise FetchError('http_503')
                return BeautifulSoup('<main></main>','html.parser')
            def links(self,*args):return [f'https://example.com/detail{i}' for i in range(10)]
            def parse_many(self,*args):return []
        with patch.dict('trending.adapters.CLASSES',{'test':Adapter}):
            candidates,failures=collect_source('test',{'seeds':['https://example.com/']},None,NOW,10)
        self.assertEqual(len(fetched),4)
        self.assertEqual(candidates,[])
        self.assertEqual(failures[-1]['reason'],'source_fetch_circuit_open')

    def test_multiple_listings_share_detail_budget(self):
        fetched=[]
        class Adapter:
            hosts={'example.com'}
            def __init__(self,*args):pass
            def fetch(self,client,url):
                fetched.append(url)
                return BeautifulSoup('<main></main>','html.parser')
            def links(self,soup,base):
                return [base+'/one',base+'/two']
            def parse_many(self,*args):return []
        config={'seeds':['https://example.com/food','https://example.com/culture']}
        with patch.dict('trending.adapters.CLASSES',{'test':Adapter}):
            collect_source('test',config,None,NOW,2)
        self.assertEqual(fetched[2:],['https://example.com/food/one','https://example.com/culture/one'])

    def test_conflicting_publisher_default_city_is_rejected(self):
        self.assertIsNone(city_from_address('Phường Yên Tử, Tỉnh Quảng Ninh, Ho Chi Minh'))

    def test_vietnamese_stage_play_has_a_category(self):
        self.assertEqual(category('Sân khấu kịch huyền ảo: Nguyễn Du – Hồ Xuân Hương Ngoại Truyện'), 'culture')

    def test_opera_uses_individual_program_days_and_primary_venue(self):
        url = 'https://hoguomopera.vn/chuong-trinh-bieu-dien/don-quixote-2099'
        html = '''<h1>Ballet Cuba: Don Quixote</h1>
        <div class="ck-content"><p>
        <span>🕗 Thời gian: 20h00, ngày 11 và 13/11/2026</span><br>
        <span>📍 Địa điểm: Nhà hát Hồ Gươm, 40 Hàng Bài, phường Cửa Nam, Hà Nội.</span>
        </p></div>
        <aside>Thời gian: 19h00, ngày 12/11/2026 Địa điểm: 28 Nguyễn Huệ, TP.HCM</aside>'''
        adapter = HoGuomOpera('hoguomopera', load_sources()['hoguomopera'])
        candidate = adapter.parse(BeautifulSoup(html, 'html.parser'), url, NOW)
        self.assertEqual(candidate.validate(NOW), [])
        self.assertEqual(candidate.city_slug, 'hanoi')
        self.assertEqual(candidate.category, 'culture')
        self.assertEqual([(o.starts_at[:10], o.precision) for o in candidate.occurrences], [
            ('2026-11-11', 'date'), ('2026-11-13', 'date'),
        ])
        conflict = html.replace('</p>', '<br>Thời gian: 21h00, ngày 11 và 13/11/2026</p>')
        candidate = adapter.parse(BeautifulSoup(conflict, 'html.parser'), url, NOW)
        self.assertIn('unresolved_individual_sessions', candidate.validate(NOW))

    def test_seven_day_verification_boundary(self):
        c=candidate('place')
        c.verified_at=(NOW-timedelta(hours=167)).isoformat()
        self.assertNotIn('stale_verification',c.validate(NOW))
        c.verified_at=(NOW-timedelta(hours=168)).isoformat()
        self.assertIn('stale_verification',c.validate(NOW))

    def test_vietnam_months_cover_the_planning_window(self):
        urls=[]
        class Client:
            def get(self,url,*args,**kwargs):
                urls.append(url)
                return BeautifulSoup('<main></main>','html.parser')
        collect_source('lifeofdanang',load_sources()['lifeofdanang'],Client(),NOW,1)
        self.assertEqual(urls[:2], [
            'https://lifeofdanang.com/vi/danang/thang/2026-11',
            'https://lifeofdanang.com/vi/danang/thang/2026-12',
        ])

    def test_month_calendar_prioritizes_both_windows_and_ignores_navigation(self):
        origin = 'https://lifeofdanang.com'
        soup = BeautifulSoup('''<main>
            <a href="/vi/danang/navigation">Danh mục</a>
            <section><h2>Thứ Năm, 5 tháng 11</h2><a href="/vi/danang/ongoing">Triển lãm</a></section>
            <section><h2>Chủ Nhật, 8 tháng 11</h2><a href="/vi/danang/weekly-first">Nhạc sống</a></section>
            <section><h2>Thứ Hai, 9 tháng 11</h2><a href="/vi/danang/weekly-next">Nhạc sống</a></section>
            <section><h2>Thứ Sáu, 20 tháng 11</h2><a href="/vi/danang/planning">Workshop</a></section>
            <section><h2>Hằng tuần trong tháng 11/2026</h2><a href="/vi/danang/recurring">Cờ vua</a></section>
        </main>''', 'html.parser')
        adapter = LifeOfDaNang('lifeofdanang', load_sources()['lifeofdanang'])
        self.assertEqual(adapter.calendar_links(soup, origin + '/vi/danang/thang/2026-11', NOW), [
            origin + '/vi/danang/' + slug for slug in ('weekly-first', 'planning', 'weekly-next', 'ongoing', 'recurring')
        ])
        december = BeautifulSoup('''<main>
            <section><h2>Thứ Ba, 1 tháng 12</h2><a href="/vi/danang/in-range">Triển lãm</a></section>
            <section><h2>Thứ Ba, 8 tháng 12</h2><a href="/vi/danang/out-of-range">Workshop</a></section>
        </main>''', 'html.parser')
        self.assertEqual(adapter.calendar_links(december, origin + '/vi/danang/thang/2026-12', NOW),
                         [origin + '/vi/danang/in-range'])

    def test_primary_event_not_related_cards_and_city_only_address_held(self):
        event={'@type':'Event','name':'Workshop làm gốm',
               'description':'Làm gốm cùng bạn bè.',
               'startDate':(NOW+timedelta(days=1)).isoformat(),
               'endDate':(NOW+timedelta(days=1,hours=2)).isoformat(),
               'location':{'name':'Xưởng Mây','address':{'streetAddress':'12 Trần Phú','addressLocality':'Da Nang'}}}
        adapter=LifeOfDaNang('lifeofdanang',load_sources()['lifeofdanang'])
        def parse():
            soup=BeautifulSoup('<h1>Workshop làm gốm</h1><main>Giải chạy marathon tại quán bar</main><script type="application/ld+json">'+json.dumps(event)+'</script>','html.parser')
            return adapter.parse_many(soup,'https://lifeofdanang.com/vi/danang/workshop',NOW)[0]
        c=parse()
        self.assertEqual(c.category,'workshop')
        self.assertNotIn('marathon',c.original_text)
        self.assertEqual(c.validate(NOW),[])
        event['location']['address'].pop('streetAddress')
        self.assertIn('unverified_street_address',parse().validate(NOW))
        event['location']['name'] = 'Xưởng Mây, 12 Trần Phú, phường Hải Châu'
        c = parse()
        self.assertEqual(c.venue_name, 'Xưởng Mây')
        self.assertEqual(c.address, '12 Trần Phú, phường Hải Châu, Da Nang')
        self.assertEqual(c.validate(NOW), [])
        event['location']['name'] = 'Xưởng Mây, 12 Trần Phú, 16 Lê Duẩn'
        self.assertIn('unverified_street_address', parse().validate(NOW))
