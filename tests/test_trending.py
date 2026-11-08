import copy
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch
from argparse import Namespace
import io
from contextlib import redirect_stdout

from bs4 import BeautifulSoup

from trending.adapters import CLASSES, load_sources
from trending.dates import schedule_occurrences, ticketbox_sessions, weekly
from trending.model import Candidate, Occurrence, city_from_address, ICT
from trending.providers import bright_allowance, bright_preflight, serp_allowance, SerpDiscovery, BrightSocial, ProviderDisabled, social_evidence, post_platform

NOW = datetime(2026,11,7,12,tzinfo=timezone.utc)


def candidate(kind='event', city='hanoi'):
    return Candidate('ticketbox','Ticketbox','https://ticketbox.vn/test-event-12345','Workshop thử nghiệm',kind,
        venue_name='Xưởng Mây',address='12 Tràng Tiền, Hà Nội',city_slug=city,category='workshop',
        published_at=NOW.isoformat(),verified_at=NOW.isoformat(),location_evidence='https://ticketbox.vn/test-event-12345',
        occurrences=[Occurrence((NOW+timedelta(days=1)).isoformat(),(NOW+timedelta(days=1,hours=2)).isoformat())] if kind=='event' else [])


class DatesAndValidation(unittest.TestCase):
    def test_sessions_are_not_continuous(self):
        text='14:00, 10 Tháng 11, 2026 - 24 Tháng 11, 2026\nLịch diễn\n14:00 - 16:00, 10 Tháng 11, 2026\n14:00 - 16:00, 17 Tháng 11, 2026\nBan tổ chức'
        sessions=ticketbox_sessions(text)
        self.assertEqual(len(sessions),2)
        self.assertEqual(datetime.fromisoformat(sessions[0].ends_at).day,10)
        self.assertEqual(datetime.fromisoformat(sessions[1].starts_at).day,17)

    def test_exhibition_opening_days_and_hours(self):
        sessions=schedule_occurrences('10:00 – 18:00, thứ Ba – Chủ nhật, 07/11 – 27/12/2026',NOW)
        self.assertGreater(len(sessions),0)
        self.assertTrue(all(datetime.fromisoformat(s.starts_at).weekday()!=0 for s in sessions))
        self.assertTrue(all(datetime.fromisoformat(s.starts_at).hour==10 for s in sessions))
        self.assertTrue(all(datetime.fromisoformat(s.ends_at).hour==18 for s in sessions))

    def test_explicit_sessions_keep_published_hours(self):
        sessions=schedule_occurrences('09:00 – 10:30, ngày 01/11/2026 và 08/11/2026',NOW)
        self.assertEqual(len(sessions),2)
        self.assertTrue(all(datetime.fromisoformat(x.starts_at).hour==9 for x in sessions))
        self.assertTrue(all(datetime.fromisoformat(x.ends_at).hour==10 for x in sessions))

    def test_recurring_is_explicit(self):
        self.assertEqual(weekly('This is a popular event',NOW),[])
        self.assertTrue(all(datetime.fromisoformat(x.starts_at).weekday()==4 for x in weekly('Every Friday',NOW)))
        self.assertEqual({datetime.fromisoformat(x.starts_at).weekday() for x in weekly('Every Friday - Monday',NOW)},{4,5,6,0})

    def test_city_is_unambiguous_and_local(self):
        self.assertEqual(city_from_address('123 Nguyễn Huệ, TP. HCM'),'hcmc')
        self.assertIsNone(city_from_address('Hội An, Đà Nẵng'))
        self.assertIsNone(city_from_address('Hà Nội và TP HCM'))
        self.assertIsNone(city_from_address('Berlin'))

    def test_fresh_place_and_expiry(self):
        c=candidate('place')
        self.assertEqual(c.validate(NOW),[])
        c.published_at=(NOW-timedelta(days=8)).isoformat()
        self.assertIn('no_recent_evidence',c.validate(NOW))
        c.verified_at=(NOW-timedelta(hours=73)).isoformat()
        self.assertIn('stale_verification',c.validate(NOW))

    def test_window_timezone_cancellation_missing_image(self):
        c=candidate()
        self.assertEqual(c.validate(NOW),[])
        self.assertIsNone(c.payload()['image_url'])
        c.occurrences=[Occurrence((NOW+timedelta(days=8)).isoformat(),(NOW+timedelta(days=9)).isoformat())]
        self.assertIn('no_upcoming_occurrence',c.validate(NOW))
        c.status='cancelled'
        self.assertIn('cancelled',c.validate(NOW))

    def test_no_image_permission_inferred(self):
        c=candidate();c.image_url='https://example.org/poster.jpg'
        self.assertIsNone(c.payload()['image_url'])
        c.image_permitted=True
        self.assertEqual(c.payload()['image_url'],c.image_url)


class Parsers(unittest.TestCase):
    def parse(self,slug,html):
        return CLASSES[slug](slug,load_sources()[slug]).parse(BeautifulSoup(html,'html.parser'),f'https://{load_sources()[slug]["hosts"][0]}/test',NOW)

    def test_grapevine_scoped_venue(self):
        c=self.parse('hanoigrapevine','''<h1>Triển lãm Mây</h1><time datetime="2026-11-06T15:00:00Z"></time>
            <div class="td-post-text-content"><h4>10:00 – 18:00, thứ Ba – Chủ nhật, 07/11 – 27/12/2026<br>
            Sóng Mây Gallery.S<br>48 Đường 5, An Dương, Hà Nội</h4></div><footer>Đà Nẵng</footer>''')
        self.assertEqual(c.city_slug,'hanoi');self.assertEqual(c.validate(NOW),[])

    def test_ticketbox_sessions_override_aggregate(self):
        event={'@type':'Event','name':'Baking Workshop','startDate':'2026-11-10T07:00:00Z','endDate':'2026-11-24T09:00:00Z',
            'offers':{'@type':'Offer','price':300000,'priceCurrency':'VND'},
            'location':{'name':'Garden Art','address':{'streetAddress':'386/17C Lê Văn Sỹ','addressLocality':'Hồ Chí Minh'}}}
        c=self.parse('ticketbox',f'''<h1>Baking Workshop</h1><script type="application/ld+json">{json.dumps(event)}</script>
          <main>Giới thiệu Workshop nấu ăn<br>Lịch diễn<br>14:00 - 16:00, 10 Tháng 11, 2026<br>
          14:00 - 16:00, 17 Tháng 11, 2026<br>Ban tổ chức</main>''')
        self.assertEqual(len(c.occurrences),2);self.assertEqual(c.validate(NOW),[])
        self.assertEqual(c.price_text,'Giá niêm yết: 300.000 ₫')
        self.assertEqual(datetime.fromisoformat(c.occurrences[0].ends_at).day,10)

    def test_article_publication_is_not_an_event(self):
        c=self.parse('danangfantasticity','''<h1>Lễ hội ẩm thực</h1><article><time datetime="2026-11-07"></time>
           Địa điểm: Nhà văn hóa<br>Địa chỉ: 12 Trần Phú, Đà Nẵng</article>''')
        self.assertIn('no_upcoming_occurrence',c.validate(NOW))

    def test_news_footer_cannot_supply_location(self):
        c=self.parse('vnexpress','''<h1>Quán ăn tại Paris</h1><div class="fck_detail">Địa chỉ: Paris</div>
           <footer>Địa chỉ: 12 Nguyễn Huệ, Hồ Chí Minh</footer>''')
        self.assertIsNone(c.city_slug)

    def test_vnexpress_prose_keeps_explicit_street_and_publication(self):
        c=self.parse('vnexpress','''<h1>Tiệm bánh mì lâu năm</h1><meta name="pubdate" content="2026-11-07T07:00:00+07:00">
            <div class="fck_detail"><p>Tiệm bánh mì Vĩnh Lợi, nằm trên phố Hàng Gà, phường Hàng Bồ, là địa chỉ quen thuộc nhiều người Hà Nội từ năm 1949.</p>
            <aside>Nhà hàng ở TP HCM</aside></div>''')
        self.assertEqual(c.venue_name,'Tiệm bánh mì Vĩnh Lợi')
        self.assertEqual(c.address,'phố Hàng Gà, phường Hàng Bồ, Hà Nội')
        self.assertEqual(c.validate(NOW),[])

    def test_fantasticity_label_markup_and_daily_schedule(self):
        c=self.parse('danangfantasticity','''<h1>Phòng đọc mở Điểm tương quan</h1><div class="entry-content">
            <p><strong>Thời gian:</strong> Từ ngày 31/10 đến 08/11/2026, hằng ngày 08:00 – 16:30</p>
            <p><strong>Địa điểm:</strong> Bảo tàng Đà Nẵng</p></div>''')
        self.assertEqual(c.validate(NOW),[])
        self.assertTrue(all(datetime.fromisoformat(x.starts_at).hour==8 for x in c.occurrences))

    def test_ticketgo_and_fantasticity_structured_events(self):
        event={'@type':'Event','name':'Triển lãm nghệ thuật','startDate':'2026-11-08','endDate':'2026-11-08',
            'location':{'name':'Bảo tàng','address':{'streetAddress':'31 Trần Phú','addressLocality':'Đà Nẵng'}}}
        html=f'<h1>Triển lãm</h1><script type="application/ld+json">{json.dumps(event)}</script>'
        for slug in ['ticketgo','danangfantasticity']:
            with self.subTest(slug=slug): self.assertEqual(self.parse(slug,html).validate(NOW),[])

    def test_ticketgo_season_is_not_a_continuous_session(self):
        event={'@type':'Event','name':'Show Ca trù','startDate':'2026-09-25T20:00:00+07:00',
               'endDate':'2027-05-01T00:00:00+07:00',
               'location':{'name':'CADAO Collective','address':'66 Tô Ngọc Vân, Hà Nội'}}
        html=f'<h1>Show Ca trù</h1><script type="application/ld+json">{json.dumps(event)}</script>'
        self.assertIn('unresolved_individual_sessions',self.parse('ticketgo',html).validate(NOW))


class FreeProviderGuards(unittest.TestCase):
    def test_trigger_records_both_documented_snapshot_prefixes(self):
        from unittest.mock import Mock
        for snapshot in ['s_live123','sd_live123']:
            with self.subTest(snapshot=snapshot):
                store=Mock()
                store.pending.return_value=None
                store.job.side_effect=[None,{'status':'submitted','provider_job_id':snapshot}]
                store.reserve.return_value={'created_now':True}
                request=Mock(side_effect=[{'snapshot_id':snapshot},{'status':'running'}])
                with patch.dict(os.environ,{'BRIGHTDATA_API_KEY':'test-placeholder'}),patch('trending.providers.bright_preflight',return_value=(3,NOW.isoformat())):
                    with self.assertRaisesRegex(ProviderDisabled,'brightdata_job_pending'):
                        BrightSocial(store,request).collect('https://www.facebook.com/venue/posts/title/123',NOW)
                self.assertEqual(request.call_args_list[0].kwargs['params']['limit_per_input'],1)
                self.assertEqual(request.call_args_list[1].args[0],'GET')
                self.assertTrue(any(c.kwargs.get('provider_id')==snapshot for c in store.update_job.call_args_list))

    def test_facebook_slugged_post_urls(self):
        self.assertEqual(post_platform('https://www.facebook.com/venue/posts/event-description/123456'),'facebook')
        self.assertEqual(post_platform('https://www.facebook.com/venue/posts/123456'),'facebook')
        self.assertIsNone(post_platform('https://www.facebook.com/venue'))

    def test_venue_roundup_does_not_corroborate_an_individual_event(self):
        c=candidate()
        row={'url':'https://www.facebook.com/museum/posts/123','content':'Nhiều hoạt động tại Xưởng Mây, Hà Nội',
             'date_posted':NOW.isoformat(),'user_url':'https://www.facebook.com/museum'}
        self.assertIsNone(social_evidence(c,row,'facebook',NOW))

    def test_web_collection_continues_without_provider_credentials(self):
        from trending.__main__ import run
        c=candidate('place')
        current=datetime.now(timezone.utc).isoformat()
        c.verified_at=c.published_at=current
        args=Namespace(sources='ticketbox',city=None,write_db=False,pilot=True,providers=True,browser=False,supplemental=False,limit=1,out=None)
        with patch.dict(os.environ,{},clear=True),patch('trending.__main__.collect_source',return_value=([c],[])) as collect,redirect_stdout(io.StringIO()):
            result=run(args)
        collect.assert_called_once()
        self.assertEqual(len(result['accepted']),1)
        self.assertEqual(result['providers']['status'],'disabled_without_persistent_quota_store')
    def test_no_credentials_no_provider_requests(self):
        def fail(*a,**kw): self.fail('Provider called without credentials')
        with patch.dict(os.environ,{},clear=True):
            for provider in [SerpDiscovery(None,fail),BrightSocial(None,fail)]:
                with self.assertRaises(ProviderDisabled):
                    (provider.search('cafe',NOW) if isinstance(provider,SerpDiscovery) else provider.collect('https://www.tiktok.com/@lo/video/123',NOW))

    def test_serp_paid_unknown_and_empty_plans_block(self):
        free={'account_status':'Active','plan_id':'free','plan_monthly_price':0,'plan_searches_left':25}
        self.assertEqual(serp_allowance(free),25)
        for fields in [{'plan_monthly_price':25},{'plan_id':'custom'},{'plan_searches_left':0}]:
            self.assertEqual(serp_allowance({**free,**fields}),0)
        self.assertEqual(serp_allowance({}),0)
        self.assertEqual(serp_allowance([]),0)

    def test_bright_receipt_and_balance_required(self):
        balance=dict(balance=0,credit=0,prepayment=0,pending_costs=0)
        proof=dict(verified_at=NOW.isoformat(),unfunded=True,no_payment_method=True,auto_recharge=False,free_credits_remaining=40)
        self.assertEqual(bright_allowance(balance,proof,NOW),40)
        self.assertEqual(bright_allowance(balance,proof,NOW+timedelta(hours=25)),0)
        for key in balance:
            self.assertEqual(bright_allowance({**balance,key:1},proof,NOW),0)
        self.assertEqual(bright_allowance({},proof,NOW),0)
        self.assertEqual(bright_allowance(balance,[],NOW),0)
        self.assertEqual(bright_allowance(balance,{**proof,'auto_recharge':True},NOW),0)

    def test_promotional_balance_is_not_a_deposit_or_free_credit_count(self):
        proof=dict(verified_at=NOW.isoformat(),unfunded=True,auto_recharge=False,
                   deposits_checked=True,promotional_balance_usd=7,free_credits_remaining=5000)
        balance=dict(balance=7,credit=0,prepayment=0,pending_costs=0)
        self.assertEqual(bright_allowance(balance,proof,NOW),4500)
        for fields in [{'deposits_checked':False},{'unfunded':False},{'auto_recharge':True},
                       {'free_credits_remaining':0},{'free_credits_remaining':True},
                       {'promotional_balance_usd':6},{'promotional_balance_usd':float('nan')}]:
            with self.subTest(fields=fields):
                self.assertEqual(bright_allowance(balance,{**proof,**fields},NOW),0)
        for fields in [{'balance':8},{'balance':6},{'credit':1},{'prepayment':1},{'pending_costs':0.01},
                       {'pending_costs':False},{'credit':float('inf')},{'balance':'7'}]:
            with self.subTest(fields=fields):
                self.assertEqual(bright_allowance({**balance,**fields},proof,NOW),0)
        reset=datetime(2026,12,1,tzinfo=timezone.utc)
        self.assertEqual(bright_allowance(balance,{**proof,'verified_at':(reset-timedelta(minutes=1)).isoformat()},reset),0)

    def test_billing_key_separation_and_account_binding(self):
        proof=dict(verified_at=NOW.isoformat(),unfunded=True,auto_recharge=False,
                   account_id='hl_test',free_credits_remaining=10)
        env={'BRIGHTDATA_API_KEY':'scraping-test','BRIGHTDATA_BILLING_API_KEY':'finance-test',
             'BRIGHTDATA_FREE_VERIFICATION_JSON':json.dumps(proof)}
        calls=[]
        def request(method,url,**kwargs):
            calls.append((method,url,kwargs['headers']['Authorization']))
            if url.endswith('/balance'):
                return dict(balance=0,credit=0,prepayment=0,pending_costs=0)
            return {'customer':'hl_test'}
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(bright_preflight(NOW,request)[0],10)
        self.assertEqual(calls[0][2],'Bearer finance-test')
        self.assertEqual([c[2] for c in calls[1:]],['Bearer scraping-test','Bearer finance-test'])
        self.assertTrue(all(c[0]=='GET' for c in calls))
        def mismatch(method,url,**kwargs):
            return request(method,url,**kwargs) if url.endswith('/balance') else {'customer':'hl_other'}
        with patch.dict(os.environ,env,clear=True),self.assertRaisesRegex(ProviderDisabled,'account_mismatch'):
            bright_preflight(NOW,mismatch)

    def test_billing_403_and_exhausted_allowance_never_submit(self):
        from unittest.mock import Mock
        store=Mock();store.pending.return_value=None;store.job.return_value=None
        for forbidden in (True,False):
            calls=[]
            def request(method,url,**kwargs):
                calls.append((method,url))
                if forbidden:
                    raise ProviderDisabled('provider_http_403')
                return dict(balance=0,credit=0,prepayment=0,pending_costs=0)
            proof=dict(verified_at=NOW.isoformat(),unfunded=True,auto_recharge=False,free_credits_remaining=0)
            with patch.dict(os.environ,{'BRIGHTDATA_API_KEY':'test',
                            'BRIGHTDATA_FREE_VERIFICATION_JSON':json.dumps(proof)},clear=True):
                with self.assertRaises(ProviderDisabled):
                    BrightSocial(store,request).collect('https://www.tiktok.com/@lo/video/123',NOW)
            self.assertEqual(calls,[('GET','https://api.brightdata.com/customer/balance')])
        store.reserve.assert_not_called()

    def test_social_requires_known_destination_not_creator_city(self):
        c=candidate('place')
        row={'url':'https://www.instagram.com/p/test','description':'Hà Nội đẹp quá','date_posted':NOW.isoformat(),'user_posted':'local'}
        self.assertIsNone(social_evidence(c,row,'instagram',NOW))
        row['description']='Ghé Xưởng Mây hôm nay'
        self.assertIsNone(social_evidence(c,row,'instagram',NOW))
        row['description']='Ghé Xưởng Mây tại Hà Nội hôm nay'
        result=social_evidence(c,row,'instagram',NOW)
        self.assertEqual(result.location_evidence,c.source_url)
        self.assertEqual(result.city_slug,'hanoi')


if __name__ == '__main__': unittest.main()
