"""Live API/image rendering, followed by separately labelled image-network faults."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
APP=os.environ.get('LO_QA_APP_URL','http://localhost:8085')
API=os.environ.get('LO_QA_API_URL','http://localhost:4103')
OUT=Path(os.environ.get('LO_QA_OUT','/tmp/lo-coverage-browser'))
async def main():
 OUT.mkdir(parents=True,exist_ok=True);checks=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='chrome',headless=True)
  for layout,width,height in [('mobile',430,932),('desktop',1440,1000)]:
   page=await browser.new_page(viewport=dict(width=width,height=height))
   await page.goto(APP+'/tabs/explore');await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible(timeout=90000)
   for city,name in [('hanoi','Hanoi'),('hcmc','Ho Chi Minh City'),('danang','Da Nang City')]:
    await page.get_by_role('button',name='Change location',exact=True).click()
    await expect(page.get_by_text('Choose your city',exact=True)).to_be_visible()
    await page.get_by_role('button',name=name,exact=True).click()
    await expect(page.get_by_text('Choose your city',exact=True)).not_to_be_visible()
    image=page.locator('img[alt^="Ảnh minh họa:"]').first
    await expect(image).to_be_visible(timeout=20000)
    await page.wait_for_function('()=>{const i=document.querySelector(\'img[alt^="Ảnh minh họa:"]\');return i&&i.complete&&i.naturalWidth>0}')
    await expect(page.get_by_text('Ảnh minh họa',exact=True).first).to_be_visible()
    await expect(page.get_by_role('link').filter(has_text='/ Unsplash').first).to_be_attached()
    await page.screenshot(path=str(OUT/f'images-{layout}-{city}.png'),full_page=True)
    checks.append(dict(path=f'live-images/{layout}/{city}',status='passed'))
   await page.close()
  # Controlled publisher-image failure; preserve real item facts but override image fields.
  page=await browser.new_page(viewport=dict(width=430,height=932))
  async def broken_publisher(route):
   response=await route.fetch();payload=await response.json()
   for item in payload['items']:
    item['image_url']='https://example.invalid/publisher.jpg'
    item['image_source']=item['sources'][0]
   await route.fulfill(response=response,json=payload)
  await page.route(API+'/discover/trending**',broken_publisher)
  await page.route('https://example.invalid/**',lambda route:route.abort())
  await page.goto(APP+'/tabs/explore')
  await expect(page.locator('img[alt^="Ảnh minh họa:"]').first).to_be_visible(timeout=30000)
  await page.wait_for_function('()=>{const i=document.querySelector(\'img[alt^="Ảnh minh họa:"]\');return i&&i.complete&&i.naturalWidth>0}')
  checks.append(dict(path='controlled-publisher-image-failure/category-photo',status='passed'))
  await page.close()
  # Explicit fault injection: no discovery or other backend response is replaced.
  page=await browser.new_page(viewport=dict(width=430,height=932))
  await page.route('**/assets/**',lambda route:route.abort() if 'trending' in route.request.url else route.continue_())
  await page.goto(APP+'/tabs/explore');await expect(page.get_by_text('Có gì mới tuần này?',exact=True)).to_be_visible(timeout=90000)
  await expect(page.locator('img[alt^="Ảnh minh họa:"]')).to_have_count(0,timeout=20000)
  await expect(page.get_by_role('link').filter(has_text='Nguồn:').first).to_be_attached()
  await expect(page.get_by_text('✦',exact=True).first).to_be_attached()
  await page.screenshot(path=str(OUT/'fault-illustration.png'),full_page=True)
  checks.append(dict(path='controlled-image-failure/neutral-placeholder',status='passed'))
  await browser.close()
 (OUT/'image-results.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks))
if __name__=='__main__':asyncio.run(main())
