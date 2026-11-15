"""Actual local API/browser journey. No mocked responses in the normal pass.
Synthetic fault injection lives in a separate test. No login tokens or providers.
"""
import asyncio,json,os
from pathlib import Path
from urllib.parse import urlsplit
import requests
from playwright.async_api import async_playwright,expect
API=os.environ.get('LO_QA_API_URL','http://localhost:4104')
APP=os.environ.get('LO_QA_APP_URL','http://localhost:8086')
OUT=Path(os.environ.get('LO_QA_OUT','pilot-output/journey-browser'))
async def main():
 OUT.mkdir(parents=True,exist_ok=True);checks=[];errors=[];failures=[];responses=[];console=[]
 cities=requests.get(API+'/cities',timeout=15).json()['cities']
 feeds={(c['slug'],k):requests.get(API+'/discover/trending',params={'city_slug':c['slug'],'kind':k},timeout=15).json()['items'] for c in cities for k in ['all','event','place']}
 for (city,kind),items in feeds.items():
  for i in items:
   detail=requests.get(API+'/discover/items/'+i['id'],timeout=15);assert detail.status_code==200
   assert detail.json()==i,(detail.json(),i)
   assert i['city_slug']==city and (kind=='all' or i['kind']==kind)
  checks.append({'path':f'api/{city}/{kind}','status':'passed','count':len(items)})
 assert requests.get(API+'/me/library/bookmarks/discoveries',timeout=15).status_code==401
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='chrome',headless=True)
  ctx=await browser.new_context(viewport={'width':int(os.environ.get('LO_QA_WIDTH','430')),'height':932},record_video_dir=str(OUT/'video'),record_video_size={'width':430,'height':932},permissions=['clipboard-read','clipboard-write'])
  page=await ctx.new_page();page.set_default_timeout(20000);page.set_default_navigation_timeout(120000)
  page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('requestfailed',lambda r:failures.append({'path':urlsplit(r.url).path,'failure':r.failure}))
  page.on('response',lambda r:responses.append({'path':urlsplit(r.url).path,'status':r.status}) if r.url.startswith(API) else None)
  await page.goto(APP+'/tabs/explore',wait_until='domcontentloaded')
  await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible(timeout=90000)
  for city in cities:
   await page.get_by_role('button',name='Change location',exact=True).click();await page.get_by_role('button',name={'hanoi':'Hà Nội','hcmc':'TP. Hồ Chí Minh','danang':'Đà Nẵng'}[city['slug']],exact=True).click()
   for kind,label in [('all','Tất cả'),('event','Sự kiện'),('place','Địa điểm')]:
    await page.get_by_text(label,exact=True).last.click()
    items=feeds[(city['slug'],kind)]
    if items:
     await expect(page.get_by_text(items[0]['title_vi'],exact=True).first).to_be_visible()
     await page.get_by_role('button',name='Xem chi tiết · Lưu · Chia sẻ',exact=True).first.click()
     await page.wait_for_url('**/discovery/*')
     await expect(page.get_by_text(items[0]['description_vi'],exact=True)).to_be_visible()
     await expect(page.get_by_text('Đăng nhập để lưu',exact=True)).to_be_visible()
     await page.screenshot(path=str(OUT/f'{city["slug"]}-{kind}-detail.png'),full_page=True)
     if kind=='all':
      async with ctx.expect_page() as popup_info:
       await page.get_by_role('link').filter(has_text='Nguồn:').first.click()
      popup=await popup_info.value
      await popup.wait_for_url(lambda url: urlsplit(url).hostname==urlsplit(items[0]['sources'][0]['url']).hostname and urlsplit(url).path.rstrip('/').split('/')[-1]==urlsplit(items[0]['sources'][0]['url']).path.rstrip('/').split('/')[-1],wait_until='commit')
      await popup.close()
      async with ctx.expect_page() as map_info:
       await page.get_by_role('link',name='Chỉ đường',exact=True).click()
      maps=await map_info.value
      await maps.wait_for_url(lambda url: 'google.com/maps' in str(url),wait_until='commit')
      await maps.close()
     await page.bring_to_front()
     await page.get_by_role('button',name='Chia sẻ',exact=True).click()
     # Chrome desktop uses clipboard when Web Share is unavailable.
     await expect(page.get_by_text('Đã sao chép liên kết',exact=True)).to_be_visible()
     assert await page.evaluate('navigator.clipboard.readText()')==items[0]['sources'][0]['url']
     await page.get_by_role('button',name='← Khám phá',exact=True).click()
     await expect(page.get_by_text(items[0]['title_vi'],exact=True).first).to_be_visible()
    else:
     await expect(page.get_by_text('Chưa có gợi ý phù hợp',exact=True)).to_be_visible();await page.get_by_text('Làm mới ↻',exact=True).click()
    print('passed',city['slug'],kind,flush=True)
    checks.append({'path':f'mobile/{city["slug"]}/{kind}/detail-return-share','status':'passed'})
   await page.screenshot(path=str(OUT/f'{city["slug"]}-feed.png'),full_page=True)
  await page.get_by_role('button',name='Change location',exact=True).click();await page.get_by_role('button',name='Hà Nội',exact=True).click()
  search=page.get_by_role('textbox',name='Tìm gợi ý đã xác minh')
  await search.fill('vinh loi');await expect(page.get_by_role('button',name='Tiệm bánh mì Vĩnh Lợi',exact=False)).to_be_visible()
  await search.fill('something absent');await search.fill('VĨNH LỢI');await expect(page.get_by_role('button',name='Tiệm bánh mì Vĩnh Lợi',exact=False)).to_be_visible()
  await page.get_by_role('button',name='Tiệm bánh mì Vĩnh Lợi',exact=False).click()
  await page.wait_for_url('**/tabs/venue/*');await page.get_by_role('button',name='Giờ mở cửa',exact=True).click()
  await expect(page.get_by_text('Chưa có giờ mở cửa',exact=True).last).to_be_visible()
  await expect(page.get_by_text('Chưa có số điện thoại',exact=True)).to_be_visible()
  await page.screenshot(path=str(OUT/'venue.png'),full_page=True)
  await page.get_by_role('button',name='Back',exact=True).click()
  await page.wait_for_url('**/tabs/explore')
  await page.get_by_role('button',name='Xóa tìm kiếm',exact=True).click()
  await expect(search).to_have_value('')
  await page.get_by_role('button',name='Gợi ý đã lưu →',exact=True).click()
  await expect(page.get_by_text('Đăng nhập để xem gợi ý đã lưu',exact=True)).to_be_visible()
  await page.screenshot(path=str(OUT/'saved-login.png'),full_page=True)
  checks.append({'path':'local-accent-search-venue-hours-saved-auth-gate','status':'passed'})
  await page.set_viewport_size({'width':1280,'height':900});await page.goto(APP+'/tabs/explore');await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible()
  await page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
  assert not errors,errors
  assert not [r for r in responses if r['path'].startswith('/discover/') and r['status']>=400],responses
  checks.extend([{'path':'real-authenticated-browser-save','status':'blocked','reason':'real test login and preview callback allowance not supplied'},{'path':'physical-iphone','status':'blocked','reason':'no physical iPhone/development build'},{'path':'google-live','status':'blocked','reason':'free capacity unverified; requests disabled'}])
  await ctx.close();await browser.close()
 (OUT/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'console_errors':console,'failed_requests':failures,'api_responses':responses},ensure_ascii=False,indent=2))
 print(json.dumps({'checks':checks,'page_errors':errors},ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
