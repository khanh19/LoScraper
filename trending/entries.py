"""Section-scoped extraction. A roundup entry never inherits a sibling's facts."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from .dates import MONTHS, iso_occurrence
from .model import Candidate, ICT, canonical, city_from_address, folded, parse_time


def identify(c, node, locator=''):
    anchor = node.get('id') or locator
    identity = '|'.join([c.kind,c.city_slug or '',folded(c.venue_name),folded(c.address),folded(c.title) if c.kind=='event' else ''])
    c.entry_key = ('anchor:' + anchor) if anchor else 'entry:' + hashlib.sha256(identity.encode()).hexdigest()
    c.evidence_locator = anchor or c.title
    return c


def sections(adapter, soup, url, now):
    """Explicit heading-delimited entries only; no fuzzy segmentation of arbitrary prose."""
    from .adapters import meta, structured, is_type
    body=soup.select_one(adapter.content_selector)
    if not body:
        return [adapter.parse(soup,url,now)]
    headings=body.select('h2,h3')
    if len(headings)<2:
        return [adapter.parse(soup,url,now)]
    results=[]
    for heading in headings[:30]:
        fragment=BeautifulSoup('<article></article>','html.parser')
        fragment.article.append(deepcopy(heading))
        for sibling in heading.next_siblings:
            if getattr(sibling,'name',None) in {'h2','h3'}:break
            fragment.article.append(deepcopy(sibling))
        # Use an isolated copy so source selectors cannot see the original body.
        scoped=deepcopy(adapter);scoped.content_selector='article'
        fragment.insert(0,BeautifulSoup('<h1></h1>','html.parser'))
        fragment.h1.string=heading.get_text(' ',strip=True)
        published=meta(soup,'article:published_time') or meta(soup,'pubdate') or next((o.get('datePublished') for o in structured(soup) if is_type(o,'Article','NewsArticle','BlogPosting')),None)
        try:
            c=scoped.parse(fragment,url,now)
        except Exception as exc:
            results.append({'extraction_failure':type(exc).__name__})
            continue
        c.published_at=c.published_at or published or None
        c.image_url=None  # A page-wide OG image is not evidence for each entry.
        results.append(identify(c,heading))
    return results


def life_weekly(adapter,soup,url,now):
    from .adapters import category
    text=soup.get_text(' ',strip=True)
    pub=re.search(r'Da Nang Weekly\s*[·•]\s*(\w+)\s+(\d{1,2}),\s*(20\d{2})',text)
    if not pub:return []
    month,day,year=pub.groups()
    if month.lower() not in MONTHS:return []
    published=datetime(int(year),MONTHS[month.lower()],int(day),tzinfo=ICT)
    results=[]
    for heading in soup.select('h2'):
        match=re.search(r'(\d{1,2})\s+To\s+(\d{1,2})\s+(\w+)',heading.get_text(' ',strip=True),re.I)
        if not match or 'weekend' not in heading.get_text().lower():continue
        first,last,month=match.groups()
        if month.lower() not in MONTHS:continue
        start=datetime(published.year,MONTHS[month.lower()],int(first),tzinfo=ICT)
        end=datetime(published.year,MONTHS[month.lower()],int(last),tzinfo=ICT)
        if not 0<=(end-start).days<=7:continue
        container=heading.find_next_sibling('div')
        if not container:continue
        weekday=None
        for node in container.find_all(recursive=False):
            if node.name=='p':weekday=node.get_text(' ',strip=True).lower();continue
            paragraph=node.find('p')
            if not paragraph:continue
            line=paragraph.get_text(' ',strip=True)
            location=''
            for link in node.select('a[href]'):
                parts=urlsplit(link['href'])
                if parts.hostname in {'www.google.com','google.com'} and parts.path.startswith('/maps'):
                    location=parse_qs(parts.query).get('query',[''])[0]
            venue=location.split(',')[0].strip()
            title=re.sub(r'^\d{1,2}(?::\d{2})?(?:am|pm)(?:\s+to\s+\d{1,2}(?::\d{2})?(?:am|pm))?\s*:\s*','',line,flags=re.I).split('. ')[0]
            c=Candidate(adapter.slug,adapter.config['name'],url,title,'event',venue_name=venue,
                address=location,city_slug=city_from_address(location),category=category(line),original_text=line,
                published_at=published.isoformat(),verified_at=now.isoformat(),location_evidence=url)
            time=re.match(r'(\d{1,2})(?::(\d{2}))?(am|pm)(?:\s+to\s+(\d{1,2})(?::(\d{2}))?(am|pm))?',line,re.I)
            days=[start+timedelta(days=i) for i in range((end-start).days+1)]
            # The enclosing weekday owns this entry. A sentence such as
            # 'the festival ends on Sunday' is not this session's date.
            selected=[d for d in days if d.strftime('%A').lower()==weekday]
            if time:
                ah,am,ap,bh,bm,bp=time.groups()
                for d in selected:
                    a=d.replace(hour=int(ah)%12+(12 if ap.lower()=='pm' else 0),minute=int(am or 0))
                    b=d.replace(hour=int(bh)%12+(12 if bp.lower()=='pm' else 0),minute=int(bm or 0)) if bh else None
                    if b and b<=a:b+=timedelta(days=1)
                    o=iso_occurrence(a.isoformat(),b.isoformat() if b else None)
                    if o:c.occurrences.append(o)
            link=next((a['href'] for a in node.select('a[href]') if '/danang/' in a['href'] and 'lifeofdanang.com' in a['href']), '')
            results.append(identify(c,node,link))
    return results
