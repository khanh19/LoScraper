"""Unmocked local discovery UI plus separately labelled search fault injection.

Use a fully isolated Encore database and LO_DISABLE_GOOGLE_REQUESTS=1.
No live Google requests are permitted by this test.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests
from playwright.async_api import async_playwright, expect

API = os.environ.get('LO_QA_API_URL', 'http://localhost:4101')
APP = os.environ.get('LO_QA_APP_URL', 'http://localhost:8083')
OUT = Path(os.environ.get('LO_QA_OUT', '/tmp/lo-e2e-20261108'))

async def main():
    expect.set_options(timeout=20000)
    OUT.mkdir(parents=True, exist_ok=True)
    cities=requests.get(API+'/cities',timeout=15).json()['cities']
    feeds={};checks=[];now=datetime.now(timezone.utc)
    for city in cities:
        for kind in ['all','event','place']:
            response=requests.get(API+'/discover/trending',params={'city_slug':city['slug'],'kind':kind,'limit':10},timeout=15)
            response.raise_for_status();items=response.json()['items'];feeds[(city['slug'],kind)]=items
            assert len({i['id'] for i in items})==len(items)
            for item in items:
                assert item['city_slug']==city['slug']
                assert kind=='all' or item['kind']==kind
                assert item['sources'] and all(s['url'].startswith('https://') for s in item['sources'])
                assert datetime.fromisoformat(item['verified_at'])>now-timedelta(hours=72)
                if item['kind']=='event':
                    o=item['next_occurrence'];assert datetime.fromisoformat(o['starts_at'])<now+timedelta(days=7)
                    assert datetime.fromisoformat(o['ends_at'])>now
            checks.append({'path':'api/'+city['slug']+'/'+kind,'status':'passed','items':len(items)})
    for params in [{'city_slug':'unknown'},{'city_slug':'hanoi','kind':'bad'},{'city_slug':'hanoi','limit':1001}]:
        assert requests.get(API+'/discover/trending',params=params,timeout=15).status_code==400
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':430,'height':932})
        page.set_default_timeout(20000)
        page.set_default_navigation_timeout(120000)
        errors=[];console=[];failures=[];responses=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:console.append({'message':m.text,'location':m.location}) if m.type=='error' else None)
        page.on('requestfailed',lambda r:failures.append({'path':urlsplit(r.url).path,'failure':r.failure}))
        page.on('response',lambda r:responses.append({'path':urlsplit(r.url).path,'status':r.status}) if r.url.startswith(API) else None)
        await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded')
        await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible(timeout=90000)
        for city in cities:
            await page.get_by_role('button',name='Change location',exact=True).click()
            await page.get_by_role('button',name=city['name'],exact=True).click()
            for kind,label in [('all','Tất cả'),('event','Sự kiện'),('place','Địa điểm')]:
                await page.get_by_text(label,exact=True).click()
                items=feeds[(city['slug'],kind)]
                if items:
                    await expect(page.get_by_text(items[0]['title_vi'],exact=True).first).to_be_visible()
                    for item in items:
                        await expect(page.get_by_text(item['title_vi'],exact=True).first).to_be_attached()
                    if len(items)>1:
                        await page.get_by_text(items[-1]['title_vi'],exact=True).first.scroll_into_view_if_needed()
                        await expect(page.get_by_text(items[-1]['title_vi'],exact=True).first).to_be_visible()
                else:
                    await expect(page.get_by_text('Chưa có gợi ý phù hợp',exact=True)).to_be_visible()
                    await page.get_by_text('Làm mới ↻',exact=True).click()
                checks.append({'path':'live_ui/'+city['slug']+'/'+kind,'status':'passed'})
                print('passed',city['slug'],kind,flush=True)
            await page.get_by_text('Tất cả',exact=True).click()
            await page.screenshot(path=str(OUT/('live-'+city['slug']+'.png')),full_page=True)
        await page.get_by_role('button',name='Change location',exact=True).click()
        await page.get_by_role('button',name='Hanoi',exact=True).click()
        await page.get_by_text('Địa điểm',exact=True).click()
        item=next(i for i in feeds[('hanoi','place')] if i['place_id'])
        await expect(page.get_by_text(item['title_vi'],exact=True).first).to_be_visible()
        await page.evaluate('window.__source=null;window.open=(url)=>{window.__source=url;return null}')
        await page.get_by_role('link').filter(has_text='Nguồn:').first.click()
        assert await page.evaluate('window.__source')==item['sources'][0]['url']
        await page.get_by_text('Khám phá địa điểm ↗',exact=True).click()
        await page.wait_for_url(lambda url:urlsplit(url).path.endswith('/venue/'+item['place_id']))
        await expect(page.get_by_text(item['venue_name'],exact=True).last).to_be_visible()
        await expect(page.get_by_text('Chưa có giờ mở cửa',exact=True)).to_be_visible()
        await page.screenshot(path=str(OUT/'live-venue.png'),full_page=True)
        checks.append({'path':'live_cached_venue_and_source_action','status':'passed'})
        await page.set_viewport_size({'width':1280,'height':900})
        await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded')
        await expect(page.get_by_text(feeds[('hanoi','all')][0]['title_vi'],exact=True).first).to_be_visible()
        await page.screenshot(path=str(OUT/'live-desktop.png'),full_page=True)
        # The normal pass above has NO response routes/interception.
        assert not errors,errors
        live={'checks':list(checks),'page_errors':list(errors),'console_errors':list(console),'failed_requests':list(failures),'api_responses':list(responses)}
        (OUT/'live-results.json').write_text(json.dumps(live,ensure_ascii=False,indent=2))
        # Exercise the real blocked Google path before controlled provider fixtures.
        await page.goto(APP+'/tabs',wait_until='domcontentloaded')
        await page.get_by_placeholder('Search venues, friends, plans...').click()
        search=page.get_by_placeholder('Search...',exact=True)
        await search.fill('cafe Hanoi')
        await expect(page.get_by_text('Search unavailable right now.',exact=True)).to_be_visible()
        checks.append({'path':'google_live','status':'blocked','reason':'free allowance unverified; outbound calls disabled'})
        await search.fill('')
        await expect(page.get_by_text('Search for a place to get started',exact=True)).to_be_visible()
        # Only these controlled autocomplete/resolve responses are simulated.
        seen=[]
        async def autocomplete(route):
            d=route.request.post_data_json;seen.append(d);q=d['input']
            if q=='slow': await asyncio.sleep(1.8)
            if q=='timeout':return await route.abort('timedout')
            rows=[] if q=='empty' else [{'google_place_id':'qa-cached-venue','label':'QA '+q,'secondary':d.get('city_slug','')}]
            await route.fulfill(json={'predictions':rows},headers={'Access-Control-Allow-Origin':'*'})
        await page.route(API+'/places/autocomplete',autocomplete)
        await search.fill('slow');await page.wait_for_timeout(450);await search.fill('latest')
        await expect(page.get_by_text('QA latest',exact=True)).to_be_visible()
        await page.wait_for_timeout(2000)
        await expect(page.get_by_text('QA slow',exact=True)).to_have_count(0)
        await search.fill('slow');await page.wait_for_timeout(450);await search.fill('')
        await page.wait_for_timeout(2000)
        await expect(page.get_by_text('QA slow',exact=True)).to_have_count(0)
        for city in cities:
            await page.get_by_role('button',name='Change search location',exact=True).click()
            await page.get_by_role('button',name=city['name'],exact=True).click()
            await search.fill('coffee '+city['slug'])
            await expect(page.get_by_text('QA coffee '+city['slug'],exact=True)).to_be_visible()
            assert seen[-1]['city_slug']==city['slug']
        await page.get_by_role('button',name='Search filters',exact=True).click()
        await page.get_by_role('button',name='Cafe',exact=True).click()
        await page.get_by_role('button',name='Apply filters',exact=True).click()
        await search.fill('filtered')
        await expect(page.get_by_text('QA filtered',exact=True)).to_be_visible()
        assert seen[-1]['included_types']==['cafe']
        await search.fill('empty')
        await expect(page.get_by_text('No places found',exact=False)).to_be_visible()
        await search.fill('timeout')
        await expect(page.get_by_text('Search unavailable right now.',exact=True)).to_be_visible()
        await page.screenshot(path=str(OUT/'fault-search-timeout.png'),full_page=True)
        # Resolve fixture returns the real local cached venue, then GET is unmocked.
        cached=requests.get(API+'/places/'+item['place_id'],timeout=15).json()['place']
        await page.route(API+'/places/resolve',lambda route:route.fulfill(json={'place_id':item['place_id'],'place':cached},headers={'Access-Control-Allow-Origin':'*'}))
        await search.fill('cached')
        await page.get_by_text('QA cached',exact=True).click()
        await page.wait_for_url(lambda url:urlsplit(url).path.endswith('/venue/'+item['place_id']))
        await expect(page.get_by_text('Chưa có giờ mở cửa',exact=True).last).to_be_visible()
        checks.append({'path':'controlled_search_race_clear_city_category_empty_timeout_resolve','status':'passed'})
        (OUT/'browser-results.json').write_text(json.dumps({'checks':checks,'search_requests':seen,'page_errors':errors},ensure_ascii=False,indent=2))
        assert not errors,errors
        print(json.dumps({'checks':checks,'page_errors':errors},ensure_ascii=False,indent=2))
        await browser.close()

if __name__=='__main__': asyncio.run(main())
