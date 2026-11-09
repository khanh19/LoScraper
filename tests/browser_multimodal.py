"""Unmocked compatibility checks; no provider or Google calls and no fake cards."""
import asyncio,json,os
from pathlib import Path
import requests
from playwright.async_api import async_playwright,expect

API=os.environ.get('LO_QA_API_URL','http://localhost:4101')
APP=os.environ.get('LO_QA_APP_URL','http://localhost:8083')
OUT=Path(os.environ.get('LO_QA_OUT','pilot-output/multimodal-browser'))


async def main():
    OUT.mkdir(parents=True,exist_ok=True);results=[];errors=[];failed=[]
    cities=requests.get(API+'/cities',timeout=15).json()['cities']
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':430,'height':932})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('requestfailed',lambda r:failed.append(r.url.split('?')[0]))
        await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded',timeout=120000)
        await expect(page.get_by_text('Tuần này có gì?',exact=True)).to_be_visible(timeout=90000)
        for city in cities:
            await page.get_by_role('button',name='Change location',exact=True).click()
            label={'hanoi':'Hà Nội','hcmc':'TP. Hồ Chí Minh','danang':'Đà Nẵng'}[city['slug']]
            await page.get_by_role('button').filter(has_text=label).last.click()
            for kind,label in [('all','Tất cả'),('event','Sự kiện'),('place','Địa điểm')]:
                response=requests.get(API+'/discover/trending',params={'city_slug':city['slug'],'kind':kind,'limit':10},timeout=15)
                response.raise_for_status();items=response.json()['items']
                await page.get_by_role('button',name=label,exact=True).click()
                if items:
                    for item in items:
                        assert item['city_slug']==city['slug']
                        await expect(page.get_by_text(item['title_vi'],exact=True).first).to_be_attached(timeout=20000)
                    detail=requests.get(API+'/discover/items/'+items[0]['id'],timeout=15)
                    detail.raise_for_status();assert detail.json()['title_vi']==items[0]['title_vi']
                else:
                    await expect(page.get_by_text('Chưa có gợi ý phù hợp',exact=True).first).to_be_visible(timeout=20000)
                results.append({'city':city['slug'],'filter':kind,'items':len(items),'status':'passed'})
            await page.get_by_role('button',name='Tất cả',exact=True).click()
            await page.screenshot(path=str(OUT/(city['slug']+'-mobile.png')),full_page=True)
            await page.set_viewport_size({'width':1280,'height':900})
            await page.screenshot(path=str(OUT/(city['slug']+'-desktop.png')),full_page=True)
            await page.set_viewport_size({'width':430,'height':932})
            planning=requests.get(API+'/discover/planning',params={'city_slug':city['slug'],'limit':10},timeout=15)
            planning.raise_for_status()
            results.append({'city':city['slug'],'section':'planning','items':len(planning.json()['items']),'status':'passed'})
        assert not errors,errors
        report={'checks':results,'page_errors':errors,'failed_requests':failed,'responses_mocked':False,
                'social_publication':'blocked_pending_calibration'}
        (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False))
        await browser.close()


if __name__=='__main__':asyncio.run(main())
