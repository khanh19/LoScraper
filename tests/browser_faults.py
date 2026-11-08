"""Controlled timing/network failures against the isolated preview, no providers."""
import asyncio
import json
import os
from pathlib import Path
import requests
from playwright.async_api import async_playwright, expect
API=os.environ.get('LO_QA_API_URL','http://localhost:4101')
APP=os.environ.get('LO_QA_APP_URL','http://localhost:8083')
OUT=Path(os.environ.get('LO_QA_OUT','/tmp/lo-e2e-20261108'))

async def main():
    expect.set_options(timeout=25000)
    cities=requests.get(API+'/cities',timeout=10).json()['cities']
    city=next(c for c in cities if c['slug']=='hanoi')
    feeds=requests.get(API+'/discover/trending?city_slug=hanoi',timeout=10).json()['items']
    place=next(i for i in feeds if i['place_id'])
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':430,'height':932})
        page.set_default_navigation_timeout(120000)
        await page.add_init_script('localStorage.setItem("lo.location.city.v1",'+json.dumps(json.dumps({**city,'citySlug':'hanoi','label':city['name'],'source':'manual'}))+')')
        gate=asyncio.Event();mode={'value':'loading'}
        async def fault(route):
            if mode['value']=='loading':
                await asyncio.wait_for(gate.wait(),30)
                return await route.continue_()
            if mode['value']=='timeout':return await route.abort('timedout')
            return await route.continue_()
        await page.route(API+'/discover/trending**',fault)
        await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded',timeout=90000)
        await expect(page.get_by_label('Đang tải gợi ý')).to_be_visible()
        await page.screenshot(path=str(OUT/'fault-loading.png'))
        mode['value']='live';gate.set()
        await expect(page.get_by_text(feeds[0]['title_vi'],exact=True).first).to_be_visible()
        print('loading passed',flush=True)
        mode['value']='timeout';await page.reload(wait_until='domcontentloaded')
        retry=page.get_by_text('Chưa cập nhật được gợi ý. Nhấn để thử lại.',exact=True)
        await expect(retry).to_be_visible()
        mode['value']='live';await retry.click()
        await expect(page.get_by_text(feeds[0]['title_vi'],exact=True).first).to_be_visible()
        print('trending timeout/retry passed',flush=True)
        async def venue_fault(route):
            if mode['value']=='venue_error':return await route.fulfill(status=503,json={'message':'Controlled outage'},headers={'Access-Control-Allow-Origin':'*'})
            return await route.continue_()
        await page.route(API+'/places/'+place['place_id'],venue_fault)
        mode['value']='venue_error'
        await page.get_by_text('Địa điểm',exact=True).click()
        await page.get_by_text('Khám phá địa điểm ↗',exact=True).click()
        await expect(page.get_by_text('Chưa tải được địa điểm.',exact=True)).to_be_visible()
        mode['value']='live';await page.get_by_role('button',name='Thử lại',exact=True).click()
        await expect(page.get_by_text(place['venue_name'],exact=True).last).to_be_visible()
        await browser.close()
    result={'controlled_loading':'passed','controlled_trending_timeout_retry':'passed','controlled_venue_outage_retry':'passed'}
    (OUT/'fault-extra-results.json').write_text(json.dumps(result,indent=2));print(result)
if __name__=='__main__':asyncio.run(main())
