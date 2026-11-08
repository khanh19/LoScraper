"""Unmocked discovery-only regression for the reliability migration.

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
    if os.environ.get('DATABASE_URL'):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from trending.store import Store
        from trending.health import report
        store=Store(os.environ['DATABASE_URL'])
        try:
            health=report(store.db,[c['slug'] for c in cities],now)
            for city in cities:
                for kind in ['all','event','place']:
                    eligible=health['cities'][city['slug']]
                    count=eligible['eligible_total'] if kind=='all' else eligible['eligible'].get(kind,0)
                    assert len(feeds[(city['slug'],kind)])==min(count,10)
            checks.append({'path':'health_api_eligibility','status':'passed'})
        finally:
            store.close()
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
        item=next((i for i in feeds[('hanoi','place')] if i['place_id']),None)
        if item:
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
        else:
            checks.append({'path':'live_cached_venue_navigation','status':'blocked','reason':'No confidently matched Hanoi place in fresh local data'})
        await page.set_viewport_size({'width':1280,'height':900})
        await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded')
        if feeds[('hanoi','all')]:
            await expect(page.get_by_text(feeds[('hanoi','all')][0]['title_vi'],exact=True).first).to_be_visible()
        else:
            await expect(page.get_by_text('Chưa có gợi ý phù hợp',exact=True)).to_be_visible()
        await page.screenshot(path=str(OUT/'live-desktop.png'),full_page=True)
        # The normal pass above has NO response routes/interception.
        assert not errors,errors
        live={'checks':list(checks),'page_errors':list(errors),'console_errors':list(console),'failed_requests':list(failures),'api_responses':list(responses)}
        (OUT/'live-results.json').write_text(json.dumps(live,ensure_ascii=False,indent=2))
        print(json.dumps(live,ensure_ascii=False,indent=2))
        await browser.close()

if __name__=='__main__': asyncio.run(main())
