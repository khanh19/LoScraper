"""Coverage discovery uses current Vietnam month and primary-event evidence."""
import json
import unittest
from unittest.mock import patch
from datetime import timedelta
from bs4 import BeautifulSoup
from trending.adapters import HoGuomOpera, LifeOfDaNang, category, collect_source, load_sources
from test_trending import NOW, candidate
from trending.model import CONFIRMED_SCHEDULE_CONFLICT, city_from_address
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

    def test_named_fitness_activities_use_sports_category(self):
        for title in (
            'HYROX 90: buổi tập theo cặp sáng thứ Bảy',
            'CrossFit cho người mới',
            'Hướng dẫn padel ở Padel Xtra',
            'Lớp Muay Thái cho người mới',
        ):
            with self.subTest(title=title):
                self.assertEqual(category(title), 'sports')
        self.assertEqual(category('Hướng dẫn tìm phòng tập'), '')

    def test_hyrox_listing_keeps_venue_and_dated_sessions(self):
        adapter = LifeOfDaNang('lifeofdanang', load_sources()['lifeofdanang'])
        location = {
            'name': 'Engine Room, 05-07 Dương Khuê',
            'address': {'addressLocality': 'Da Nang'},
        }
        sessions = [{
            '@type': 'Event',
            'name': 'HYROX 90: buổi tập theo cặp sáng thứ Bảy ở Engine Room',
            'location': location,
            'startDate': f'2026-11-{day}T09:00:00+07:00',
            'endDate': f'2026-11-{day}T10:30:00+07:00',
        } for day in (14, 21)]
        html = f'<script type="application/ld+json">{json.dumps(sessions)}</script>'
        event, = adapter.parse_many(
            BeautifulSoup(html, 'html.parser'),
            'https://lifeofdanang.com/vi/danang/weekly-engine-room-hyrox-90',
            NOW,
        )
        self.assertEqual(event.validate(NOW), [])
        self.assertEqual((event.category, event.city_slug, event.address),
                         ('sports', 'danang', '05-07 Dương Khuê, Da Nang'))
        self.assertEqual([session.starts_at for session in event.occurrences],
                         [session['startDate'] for session in sessions])

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

    def test_opera_rechecks_each_visible_slot_against_its_booking(self):
        adapter = HoGuomOpera('hoguomopera', load_sources()['hoguomopera'])
        legacy = 'https://hoguomopera.vn/chuong-trinh-bieu-dien/st-petersburg-night-2088'
        path = '/chuong-trinh-bieu-dien/st-petersburg-night-2088'
        title = 'ST PETERSBURG NIGHT'

        def page(data, body=''):
            node = {'props': {'pageProps': {'data': data}}}
            return BeautifulSoup(f'<script id="__NEXT_DATA__">{json.dumps(node)}</script>{body}', 'html.parser')

        slots = [
            {'showId': show, 'articleId': 2088, 'isAvailFS': True,
             'startTime': f'2026-11-{day}T20:00:00Z', 'endTime': f'2026-11-{day}T23:00:00Z'}
            for show, day in [(126, 14), (127, 15)]
        ]
        programme = {'slug': 'st-petersburg-night-2088', 'articleId': 2088, 'isShow': True,
                     'name': title, 'shortDescription': 'Hai đêm hòa nhạc', 'showSches': slots}
        catalogue = page({'items': [programme]}, f'''
          <div><section><a href="{path}">{title}</a>
          <img alt="calendar"><p>20:00 - 23:00, 14/11/2026</p>
          <img alt="calendar"><p>20:00 - 23:00, 15/11/2026</p></section>
          <section><a href="/adjacent">Chương trình khác</a><p>20:00 - 23:00, 16/11/2026</p></section></div>
        ''')

        class Client:
            def __init__(self, wrong_article=False):
                self.wrong_article = wrong_article

            def get(self, url, hosts, **kwargs):
                if url == legacy:
                    raise FetchError('http_404')
                if url == adapter.config['seeds'][0]:
                    return catalogue
                slot = next(slot for slot in slots if url.endswith(f'/dat-ve/{slot["showId"]}'))
                article_id = 2099 if self.wrong_article and slot['showId'] == 127 else 2088
                return page({
                    'id': slot['showId'], 'article': {'id': article_id}, 'articleName': title,
                    'isAvailFS': True, 'startTime': slot['startTime'], 'endTime': slot['endTime'],
                }, '<span>Địa chỉ: 40 Hàng Bài, Phường Cửa Nam, TP. Hà Nội</span>')

        client = Client()
        candidate, = adapter.parse_many(adapter.fetch(client, legacy), legacy, NOW)
        adapter.enrich(candidate, catalogue, client, NOW)
        self.assertEqual(candidate.validate(NOW), [])
        self.assertEqual(candidate.entry_key, 'program-2088')
        self.assertEqual(candidate.replaces_source_url, legacy)
        self.assertEqual([s.starts_at for s in candidate.occurrences],
                         ['2026-11-14T20:00:00+07:00', '2026-11-15T20:00:00+07:00'])
        broken, = adapter.parse_many(catalogue, adapter.config['seeds'][0], NOW)
        adapter.enrich(broken, catalogue, Client(wrong_article=True), NOW)
        self.assertIn('unresolved_individual_sessions', broken.validate(NOW))
        self.assertEqual(broken.occurrences, [])

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

    def test_da_nang_visible_session_starts_prevent_an_aggregate_time_window(self):
        url = 'https://lifeofdanang.com/vi/danang/pickleball'
        adapter = LifeOfDaNang('lifeofdanang', load_sources()['lifeofdanang'])
        event = {
            '@type': 'Event',
            'name': 'Giao lưu pickleball',
            'location': {'name': 'Sân Pickleball', 'address': {
                'streetAddress': '84 Chế Lan Viên', 'addressLocality': 'Da Nang',
            }},
            'startDate': '2026-11-09T14:30:00+07:00',
            'endDate': '2026-11-09T17:30:00+07:00',
        }

        def parse(agenda, events):
            html = (f'<main><dl><div><dt>Thời gian</dt><dd><span>Thứ Hai, 9 tháng 11</span>'
                    f'<span>{agenda}</span></dd></div></dl></main>'
                    f'<script type="application/ld+json">{json.dumps(events)}</script>')
            return adapter.parse_many(BeautifulSoup(html, 'html.parser'), url, NOW)[0]

        starts = '14h30, 17h30 và 19h30'
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, parse(starts, [event]).reasons)
        next_sessions = [
            dict(event, startDate=f'2026-11-09T{start}:00+07:00', endDate=f'2026-11-09T{end}:00+07:00')
            for start, end in [('17:30', '19:15'), ('19:30', '21:00')]
        ]
        self.assertNotIn(CONFIRMED_SCHEDULE_CONFLICT, parse(starts, [event, *next_sessions]).reasons)
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, parse('14h30, 17h30', [event, *next_sessions]).reasons)
        self.assertNotIn(CONFIRMED_SCHEDULE_CONFLICT, parse('14h30 đến 17h30', [event]).reasons)

    def test_reviewed_da_nang_event_requires_matching_venue_and_complete_session(self):
        config = load_sources()['lifeofdanang']
        url, review = next(iter(config['reviewed_events'].items()))
        adapter = LifeOfDaNang('lifeofdanang', config)
        event = {
            '@type': 'Event',
            'name': 'Lễ thắp sáng cây thông Giáng sinh',
            'description': 'Lễ thắp sáng từ 17h30 đến 19h.\nTiệc tối riêng từ 18h30 đến 22h.',
            'startDate': '2026-12-03',
            'endDate': '2026-12-03',
            'location': {'name': review['location'], 'address': {'addressLocality': 'Da Nang'}},
        }
        venue_link = (f'<a data-ev="venue" data-ev-id="{url.rsplit("/", 1)[-1]}" '
                      f'href="{review["venue_url"]}">Địa điểm</a>')
        address_html = f'<p>{review["address"]}, Việt Nam</p>'
        row = '<tr><td>03/12/2026</td><td>Furama Resort Danang</td><td>17:30–19:00 in the main lobby</td></tr>'

        class Client:
            def __init__(self, address, schedule):
                self.pages = {review['address_url']: address, review['schedule_url']: f'<table>{schedule}</table>'}

            def get(self, url, hosts):
                return BeautifulSoup(self.pages[url], 'html.parser')

        def enrich(links=venue_link, address=address_html, schedule=row):
            soup = BeautifulSoup(f'<main>{links}</main><script type="application/ld+json">{json.dumps(event)}</script>',
                                 'html.parser')
            parsed = adapter.parse_many(soup, url, NOW)[0]
            return adapter.enrich(parsed, soup, Client(address, schedule), NOW)

        c = enrich()
        self.assertEqual(c.validate(NOW), [])
        self.assertEqual(c.address, review['address'])
        self.assertEqual(c.location_evidence, review['address_url'])
        self.assertEqual([(o.starts_at, o.ends_at, o.precision) for o in c.occurrences],
                         [('2026-12-03T17:30:00+07:00', '2026-12-03T19:00:00+07:00', 'time')])
        self.assertIn('unresolved_reviewed_venue', enrich(links=venue_link + venue_link).reasons)
        self.assertIn('unresolved_reviewed_address', enrich(address='<p>Đà Nẵng</p>').reasons)
        for conflicting in (row.replace('19:00', '20:00'), row.replace('03/12', '04/12')):
            with self.subTest(schedule=conflicting):
                self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, enrich(schedule=conflicting).reasons)
        for incomplete in (row + row, row.replace('19:00', '99:00'), ''):
            with self.subTest(schedule=incomplete):
                reasons = enrich(schedule=incomplete).reasons
                self.assertIn('unresolved_cross_source_session_times', reasons)
                self.assertNotIn(CONFIRMED_SCHEDULE_CONFLICT, reasons)
        event['description'] = 'Lễ thắp sáng cây thông.\nTiệc tối riêng từ 17h30 đến 19h.'
        self.assertNotIn(CONFIRMED_SCHEDULE_CONFLICT, enrich().reasons)

    def test_reviewed_jazz_requires_both_sessions_and_an_exact_organizer_link(self):
        config = load_sources()['lifeofdanang']
        event_id = 'city-da-nang-jazz-festival-2026-at-the-furama-2026-11-27'
        url = f'https://lifeofdanang.com/vi/danang/{event_id}'
        review = config['reviewed_events'][url]
        adapter = LifeOfDaNang('lifeofdanang', config)
        event = {
            '@type': 'Event',
            'name': 'Lễ hội Jazz Đà Nẵng 2026 tại Furama',
            'description': 'Nhạc jazz sống từ 17h đến 23h cả hai tối.',
            'startDate': '2026-11-27',
            'endDate': '2026-11-28',
            'location': {'name': review['location'], 'address': {'addressLocality': 'Da Nang'}},
        }
        link = (f'<a data-ev="organiser" data-ev-id="{event_id}" '
                f'href="{review["schedule_url"].rstrip("/")}">Nguồn chính thức</a>')
        schedule = '''<header class="hero"><div class="when">
        <p class="day">Friday 27 and Saturday 28 November 2026</p>
        <p class="time">5 pm to 11 pm, both nights</p>
        <p class="place">Lounge Bar, Furama Danang</p>
        </div></header>'''

        def enrich(publisher=event, source=schedule, official_link=link):
            class Client:
                def get(self, url, hosts):
                    pages = {
                        review['schedule_url']: source,
                        review['address_url']: f'<p>{review["address"]}, Việt Nam</p>',
                    }
                    return BeautifulSoup(pages[url], 'html.parser')

            html = f'<main>{official_link}</main><script type="application/ld+json">{json.dumps(publisher)}</script>'
            soup = BeautifulSoup(html, 'html.parser')
            now = NOW + timedelta(days=14)
            candidate, = adapter.parse_many(soup, url, now)
            return adapter.enrich(candidate, soup, Client(), now)

        result = enrich()
        self.assertEqual(result.validate(NOW + timedelta(days=14)), [])
        self.assertEqual(result.address, review['address'])
        self.assertEqual([(o.starts_at, o.ends_at, o.precision) for o in result.occurrences], [
            (f'2026-11-{day}T17:00:00+07:00', f'2026-11-{day}T23:00:00+07:00', 'time')
            for day in (27, 28)
        ])
        self.assertIn('unresolved_reviewed_venue', enrich(official_link=link.replace(event_id, 'another-event')).reasons)
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, enrich(source=schedule.replace('11 pm', '10 pm')).reasons)
        self.assertIn(CONFIRMED_SCHEDULE_CONFLICT, enrich(publisher=dict(event, endDate='2026-11-27')).reasons)
        for incomplete in (schedule.replace('both nights', 'Friday only'),
                           schedule.replace('Lounge Bar', 'Main Lobby'), schedule + schedule):
            self.assertIn('unresolved_cross_source_session_times', enrich(source=incomplete).reasons)
