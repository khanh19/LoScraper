"""Controlled failures only: never present these responses as live feed evidence."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
API=os.environ.get('LO_QA_API_URL','http://localhost:4104');APP=os.environ.get('LO_QA_APP_URL','http://localhost:8086');OUT=Path(os.environ.get('LO_QA_OUT','pilot-output/journey-faults'))
async def main():
 OUT.mkdir(parents=True,exist_ok=True);checks=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='chrome',headless=True);page=await browser.new_page(viewport={'width':430,'height':932});page.set_default_timeout(20000);page.set_default_navigation_timeout(120000)
  await page.goto(APP+'/tabs/explore');await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible(timeout=90000)
  await page.get_by_role('button',name='Change location',exact=True).click();await page.get_by_role('button',name='Hanoi',exact=True).click()
  search=page.get_by_role('textbox',name='Tìm gợi ý đã xác minh')
  async def fail(route):await route.fulfill(status=503,json={'code':'unavailable','message':'controlled test'},headers={'Access-Control-Allow-Origin':'*'})
  await page.route(API+'/discover/search**',fail);await search.fill('vinh loi');await expect(page.get_by_text('Chưa tìm được. Thử lại',exact=True)).to_be_visible()
  await page.unroute(API+'/discover/search**',fail);await page.get_by_text('Chưa tìm được. Thử lại',exact=True).click();await expect(page.get_by_role('button',name='Tiệm bánh mì Vĩnh Lợi',exact=False)).to_be_visible()
  checks.append({'path':'controlled-search-outage-retry-to-real-result','status':'passed'})
  async def slow(route):
   if 'q=slow' in route.request.url:
    await asyncio.sleep(2)
    try:await route.fulfill(json={'results':[{'id':'not-real','type':'discovery','title':'CONTROLLED STALE RESULT','address':'test','city_slug':'hanoi','category':'cafe'}]},headers={'Access-Control-Allow-Origin':'*'})
    except Exception:pass # An aborted obsolete fetch is expected.
   else:await route.continue_()
  await page.route(API+'/discover/search**',slow);await search.fill('slow');await page.wait_for_timeout(400);await search.fill('vinh loi');await expect(page.get_by_role('button',name='Tiệm bánh mì Vĩnh Lợi',exact=False)).to_be_visible();await page.wait_for_timeout(2200);await expect(page.get_by_text('CONTROLLED STALE RESULT',exact=True)).to_have_count(0)
  await search.fill('slow');await page.wait_for_timeout(400);await page.get_by_role('button',name='Xóa tìm kiếm',exact=True).click();await page.wait_for_timeout(2200);await expect(page.get_by_text('CONTROLLED STALE RESULT',exact=True)).to_have_count(0)
  checks.append({'path':'controlled-late-response-change-and-clear','status':'passed'})
  await page.goto(APP+'/discovery/11111111-1111-1111-1111-111111111111');await expect(page.get_by_text('Gợi ý này không còn đủ điều kiện hiển thị.',exact=True)).to_be_visible();await expect(page.get_by_role('button',name='Đăng nhập để lưu',exact=True)).to_have_count(0)
  checks.append({'path':'actual-unavailable-detail-no-save','status':'passed'})
  await page.screenshot(path=str(OUT/'unavailable.png'),full_page=True);await browser.close()
 (OUT/'results.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks))
if __name__=='__main__':asyncio.run(main())
