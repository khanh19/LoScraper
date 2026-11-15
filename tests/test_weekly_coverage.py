"""Coverage discovery uses current Vietnam month and primary-event evidence."""
import json
import unittest
from datetime import timedelta
from bs4 import BeautifulSoup
from trending.adapters import LifeOfDaNang, collect_source, load_sources
from test_trending import NOW, candidate
from trending.model import city_from_address

class WeeklyCoverage(unittest.TestCase):
    def test_conflicting_publisher_default_city_is_rejected(self):
        self.assertIsNone(city_from_address('Phường Yên Tử, Tỉnh Quảng Ninh, Ho Chi Minh'))

    def test_seven_day_verification_boundary(self):
        c=candidate('place')
        c.verified_at=(NOW-timedelta(hours=167)).isoformat()
        self.assertNotIn('stale_verification',c.validate(NOW))
        c.verified_at=(NOW-timedelta(hours=168)).isoformat()
        self.assertIn('stale_verification',c.validate(NOW))

    def test_current_month_listing_is_collected_first(self):
        urls=[]
        class Client:
            def get(self,url,*args,**kwargs):
                urls.append(url)
                return BeautifulSoup('<main></main>','html.parser')
        collect_source('lifeofdanang',load_sources()['lifeofdanang'],Client(),NOW,1)
        self.assertEqual(urls[0],'https://lifeofdanang.com/vi/danang/thang/2026-11')

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
