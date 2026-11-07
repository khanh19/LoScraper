"""Local browser QA: real discovery API; unrelated app services are isolated.

Run after a local pilot import, with Expo at 8082 and Encore at 4100.
No provider requests, database writes, or externally uploaded screenshots.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright, expect

API = 'http://localhost:4100'
APP = 'http://localhost:8082'
OUT = Path('/tmp/lo-trending-qa')
CITIES = [
    dict(slug='hcmc',name='TP Hồ Chí Minh',latitude=10.776,longitude=106.7,sw_lat=10.3,sw_lng=106.3,ne_lat=11.2,ne_lng=107.1,search_radius_m=20000),
    dict(slug='hanoi',name='Hà Nội',latitude=21.028,longitude=105.834,sw_lat=20.7,sw_lng=105.4,ne_lat=21.5,ne_lng=106.1,search_radius_m=20000),
    dict(slug='danang',name='Đà Nẵng',latitude=16.05,longitude=108.2,sw_lat=15.9,sw_lng=107.9,ne_lat=16.2,ne_lng=108.4,search_radius_m=20000),
]


def main():
    OUT.mkdir(exist_ok=True)
    feeds={}
    for city in CITIES:
        r=requests.get(API+'/discover/trending',params={'city_slug':city['slug']},timeout=15)
        r.raise_for_status();feeds[city['slug']]=r.json()
        assert feeds[city['slug']]['items'], 'Run a fresh local pilot before browser QA'
        assert all(i['city_slug']==city['slug'] for i in feeds[city['slug']]['items'])
    sample=feeds['hanoi']['items'][0]
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':430,'height':932})
        mode={'value':'live'}
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'Query data cannot be undefined' in m.text else None)

        def route_api(route):
            path=urlsplit(route.request.url).path
            if path=='/discover/trending':
                if mode['value']=='live':return route.continue_()
                if mode['value']=='error':return route.fulfill(status=503,json={'message':'QA outage'},headers={'Access-Control-Allow-Origin':'*'})
                data=copy.deepcopy(feeds['hanoi'])
                if mode['value']=='empty':data['items']=[]
                if mode['value']=='image':
                    data['items']=[copy.deepcopy(sample)]
                    data['items'][0]['image_url']='http://localhost:8082/qa-missing-poster.png'
                return route.fulfill(json=data,headers={'Access-Control-Allow-Origin':'*'})
            route.fulfill(json={'cities':CITIES} if path=='/cities' else {'lists':[],'plans':[],'places':[],'items':[]},headers={'Access-Control-Allow-Origin':'*'})

        page.route(API+'/**',route_api)
        page.route('**/qa-missing-poster.png',lambda r:r.fulfill(status=404))
        page.goto(APP+'/tabs/explore',wait_until='domcontentloaded',timeout=120000)
        page.get_by_text('Có gì mới tuần này?',exact=True).wait_for(timeout=90000)
        for city in CITIES:
            page.evaluate('(city)=>localStorage.setItem("lo.location.city.v1",JSON.stringify({...city,citySlug:city.slug,label:city.name,source:"manual"}))',city)
            page.reload(wait_until='domcontentloaded')
            first=feeds[city['slug']]['items'][0]
            expect(page.get_by_text(first['title_vi'],exact=True).first).to_be_visible(timeout=30000)
            page.get_by_text('Sự kiện',exact=True).click()
            expect(page.get_by_text('Sắp diễn ra',exact=True).first).to_be_visible()
            page.get_by_text('Địa điểm',exact=True).click()
            places=[x for x in feeds[city['slug']]['items'] if x['kind']=='place']
            expect(page.get_by_text(places[0]['title_vi'] if places else 'Chưa có gợi ý phù hợp',exact=True).first).to_be_visible()
            page.get_by_text('Tất cả',exact=True).click()
            page.screenshot(path=str(OUT/(city['slug']+'.png')),full_page=True)
            results.append({'city':city['slug'],'live_items':len(feeds[city['slug']]['items']),'filters':'passed'})

        mode['value']='empty';page.reload(wait_until='domcontentloaded')
        expect(page.get_by_text('Chưa có gợi ý phù hợp',exact=True)).to_be_visible()
        mode['value']='error';page.reload(wait_until='domcontentloaded')
        retry=page.get_by_text('Chưa cập nhật được gợi ý. Nhấn để thử lại.',exact=True)
        expect(retry).to_be_visible(timeout=15000)
        mode['value']='image';retry.click()
        expect(page.get_by_text(sample['title_vi'],exact=True).first).to_be_visible()
        expect(page.get_by_text('Ảnh:',exact=False)).to_have_count(0)
        source=page.get_by_role('link').filter(has_text='Nguồn:').first
        expect(source).to_be_visible()
        # Capture navigation without fetching an external publisher during UI QA.
        page.evaluate('window.__openedSource=null;window.open=(url)=>{window.__openedSource=url;return null}')
        source.click()
        assert page.evaluate('window.__openedSource')==sample['sources'][0]['url']
        page.set_viewport_size({'width':1280,'height':900})
        page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
        assert not errors, errors
        browser.close()
    result={'cities':results,'empty_retry_image_source':'passed','page_errors':errors}
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
