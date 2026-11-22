from __future__ import annotations

import json
import re
from datetime import date, timedelta
from itertools import zip_longest
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .dates import iso_occurrence, plain, schedule_occurrences, ticketbox_sessions, weekly
from .http import FetchError, PublicClient, fetch_failure_reason
from .model import (
    CONFIRMED_SCHEDULE_CONFLICT, ICT, Candidate, canonical, city_from_address, folded,
    outside_supported_cities, parse_time,
)


def structured(soup):
    def walk(value):
        if isinstance(value, list):
            for v in value:
                yield from walk(v)
        elif isinstance(value, dict):
            yield value
            if "@graph" in value:
                yield from walk(value["@graph"])
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(node.string or node.get_text()))
        except (TypeError, ValueError):
            continue


def is_type(obj, *types):
    value = obj.get("@type", [])
    return any(t in (value if isinstance(value, list) else [value]) for t in types)


def meta(soup, key):
    node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return node.get("content", "") if node else ""


def category(text):
    value = folded(text)
    if re.search(r"\b(giai chay|marathon|bong ro|bong da|the thao|watch party|pickleball|quan vot|co vua)\b", value): return "sports"
    if re.search(r"\b(pop up|popup|cho phien|phien cho|hoi cho|cho giang sinh|local brand market)\b", value): return "market"
    if re.search(r"\b(book club|cau lac bo doc sach|clb doc sach)\b", value): return "culture"
    for name, pattern in [
        ("workshop", r'workshop|lop hoc|lam gom'),
        ("cafe", r'ca phe|cafe|coffee|brunch'),
        ("restaurant", r'\b(?:quan an|nha hang|am thuc|restaurants?|eatery|quan pho|quan bun|banh mi|bot chien|banh cuon|buffet)\b'),
        ("nightlife", r'club|nightlife|night club'),
        ("bar", r'\bbar\b|cocktail|beer|bia'),
        ("music", r'concert|nhac|music|live show|birthday show|dj|jazz'),
        ("culture", r'trien lam|exhibition|gallery|bao tang|museum|film|phim|nha hat|theater|le hoi|festival|phong doc|thap sang cay thong|nghe thuat|trung bay|kich thieu nhi|\b(?:san khau kich|vo kich|kich noi|ballet)\b|dance|ecstatic'),
        ("experience", r'trai nghiem|experience|walking tour|city tour|tham quan|fanmeeting')]:
        if re.search(pattern, value):
            return name
    return ""


def location_fields(obj):
    location = obj.get("location") or obj.get("contentLocation") or {}
    if isinstance(location, list):
        return "", ""  # multi-city tours need separate event pages/sessions
    if isinstance(location, str):
        return "", location
    address = location.get("address", {})
    if isinstance(address, dict):
        address = ", ".join(str(address[k]) for k in ["streetAddress", "addressLocality", "addressRegion"] if address.get(k))
    return str(location.get("name", "")), str(address)


class Adapter:
    content_selector = "article"
    link_pattern = r"."
    kind = "event"

    def __init__(self, slug, config):
        self.slug, self.config = slug, config
        self.hosts = set(config["hosts"])

    def links(self, soup, base):
        seen = set()
        for a in soup.select('a[href]'):
            try:
                url = canonical(urljoin(base, a["href"]))
            except ValueError:
                continue
            if urlsplit(url).hostname in self.hosts and re.search(self.link_pattern, urlsplit(url).path) and url not in seen:
                seen.add(url)
                yield url

    def fetch(self, client, url):
        return client.get(url, self.hosts, render=self.slug == "ticketbox")

    def parse_many(self, soup, url, now):
        if self.config.get('roundups'):
            from .entries import sections
            return sections(self,soup,url,now)
        return [self.parse(soup,url,now)]

    def parse(self, soup, url, now):
        body = soup.select_one(self.content_selector)
        objects = list(structured(soup))
        event = next((o for o in objects if is_type(o, "Event", "MusicEvent", "ExhibitionEvent", "FoodEvent", "TheaterEvent")), {})
        article = next((o for o in objects if is_type(o, "NewsArticle", "Article", "BlogPosting")), {})
        place = next((o for o in objects if is_type(o, "Restaurant", "CafeOrCoffeeShop", "BarOrPub", "LocalBusiness")), {})
        h1 = soup.select_one("h1")
        title = (event.get("name") or (h1.get_text(" ", strip=True) if h1 else "")).removeprefix("TicketBox | ")
        text = body.get_text("\n", strip=True) if body else ""
        paragraphs = [p.get_text(' ', strip=True) for p in body.select('p,li')] if body else []
        venue, address = location_fields(event or article)
        if place:
            venue, address = location_fields({"location": place})
        published = article.get("datePublished") or meta(soup, "article:published_time")
        time_node = soup.select_one('time[datetime]')
        if not published and time_node:
            published = time_node.get("datetime")
        c = Candidate(self.slug, self.config["name"], url, title, self.kind,
                      venue_name=venue, address=address, category=category(title) or category(text[:300]),
                      original_text=text[:2000], published_at=published or None,
                      verified_at=now.isoformat(), image_url=meta(soup, "og:image") or None,
                      image_permitted=False)
        images=event.get('image',[]) if event else []
        if not isinstance(images,list):images=[images]
        images=[i.get('url') if isinstance(i,dict) else i for i in images]
        if body:images += [urljoin(url,img['src']) for img in body.select('img[src]')]
        c.image_association_verified=bool(c.image_url and c.image_url in images)
        if body is None and not event:
            c.reasons.append("missing_primary_content")
        if event:
            offers=event.get('offers',[])
            offers=offers if isinstance(offers,list) else [offers]
            prices=[]
            for offer in offers:
                if not isinstance(offer,dict) or offer.get('priceCurrency')!='VND':
                    continue
                for key in ['price','lowPrice','highPrice']:
                    try:
                        value=float(offer[key])
                        if 0<=value<=10**10:prices.append(round(value))
                    except (KeyError,TypeError,ValueError):
                        continue
            if prices:
                amounts=[f'{value:,}'.replace(',','.') for value in sorted(set([min(prices),max(prices)]))]
                c.price_text='Giá niêm yết: '+' – '.join(amounts)+' ₫'
            occ = iso_occurrence(str(event.get("startDate", "")), event.get("endDate"))
            c.occurrences = [occ] if occ else []
            if event.get("eventStatus", "").endswith(("EventCancelled", "EventPostponed")):
                c.status = "cancelled"
        # Only address-labelled lines in the primary article; never the footer/sidebar.
        if not address:
            lines = paragraphs or [line.strip() for line in text.splitlines() if line.strip()]
            for index, line in enumerate(lines):
                if re.match(r"^(Địa chỉ|Address|Địa điểm|Venue|Location)\s*:", line, re.I):
                    value = line.split(":", 1)[-1].strip()
                    if city_from_address(value):
                        c.address = value
                        # A venue name must be explicitly supplied, not inferred from an article headline.
                        named = next((l.split(":", 1)[-1].strip() for l in lines[max(0, index-3):index]
                                      if re.match(r"^(Quán|Nhà hàng|Tên quán|Venue|Địa điểm)\s*:", l, re.I)), "")
                        if not named and re.match(r'^(Địa điểm|Venue|Location)\s*:',line,re.I):
                            named = re.split(r',|\s+[–-]\s+',value)[0].strip()
                            if re.search(r'\bvà\b|\band\b',named,re.I):
                                named = ''
                        c.venue_name = c.venue_name or named
                        break
        c.city_slug = city_from_address(c.address)
        c.location_evidence = url if c.address and c.venue_name else ""
        if c.kind == "event" and not c.occurrences:
            blocks = [line for line in (paragraphs or text.splitlines()) if re.match(r"^(Thời gian|Time|Date|Ngày diễn)\s*:", line, re.I)]
            c.occurrences = schedule_occurrences("\n".join(blocks), now)
        if re.search(r"\b(da huy|huy su kien|event cancelled|dong cua vinh vien)\b", folded(title)):
            c.status = "cancelled"
        return c


class Ticketbox(Adapter):
    def public_listing_links(self, client):
        host = "api-v2.ticketbox.vn"
        url = f"https://{host}/gin/api/v2/discovery/onsale-sections/newly-on-sale"
        data = client.get(url, {host}, json_response=True).get("data")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise FetchError("invalid_public_listing")
        links = []
        for item in results:
            if not isinstance(item, dict) or item.get("saleStage") != "on_sale":
                continue
            raw_url = item.get("deeplink")
            if not isinstance(raw_url, str):
                continue
            try:
                event_url = canonical(raw_url)
            except ValueError:
                continue
            parts = urlsplit(event_url)
            if parts.hostname in self.hosts and re.fullmatch(self.link_pattern, parts.path):
                links.append(event_url)
        return links

    def fetch(self, client, url):
        # Event details are server-rendered even when homepage hydration fails.
        page = client.get(url, self.hosts)
        if any(is_type(obj, 'Event') for obj in structured(page)):
            return page
        return client.get(url, self.hosts, render=True)

    content_selector = "main"
    link_pattern = r"^/(?!search|customer|organizer)[a-z0-9-]+-\d{4,}$"

    def enrich(self, c, soup, client, now):
        match = re.search(r"-(\d+)/?$", urlsplit(c.source_url).path)
        if not match:
            c.reasons.append("unresolved_individual_sessions")
            return c
        event_id = match[1]
        api = "https://api-v2.ticketbox.vn/gin/api/v2/events/" + event_id
        data = client.get(api, {"api-v2.ticketbox.vn"}, json_response=True)["data"]["result"]
        if str(data.get("id")) != event_id:
            c.reasons.append("event_identity_conflict")
            return c
        if data.get("status") in {"cancelled", "canceled", "postponed"}:
            c.status = "cancelled"
            if data["status"] != "postponed":
                c.reasons.append("publisher_confirmed_cancellation")
            return c
        venue = data.get("venue") or c.venue_name
        address = data.get("address") or ""
        if folded(venue) in {"online event", "su kien truc tuyen", "truc tuyen"}:
            c.reasons.append("online_only_event")
        elif outside_supported_cities(f"{venue}, {address}") or outside_supported_cities(f"{c.venue_name}, {c.address}"):
            c.reasons.append("outside_supported_cities")
        elif (api_city := city_from_address(address)) and c.city_slug and api_city != c.city_slug:
            c.reasons.append("venue_city_conflict")
        sessions = []
        for row in data.get("showings") or []:
            start, end = row.get("startTime"), row.get("endTime")
            occurrence = iso_occurrence(start, end) if start and end else None
            if not occurrence or row.get("status") in {"cancelled", "canceled", "postponed"}:
                c.reasons.append("unresolved_individual_sessions")
                return c
            sessions.append(occurrence)
        if not sessions:
            c.reasons.append("unresolved_individual_sessions")
            return c
        c.occurrences = sessions
        categories = {"music": "music", "sport": "sports", "theatersandart": "culture",
                      "attractionsexperiences": "experience", "seminarsworkshops": "workshop"}
        if not c.category:
            c.category = next((categories[value] for value in (data.get("categoriesV2") or [])
                               if value in categories), "")
        return c

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        # Ticketbox fills addressLocality/Region with HCMC even on Hanoi
        # events. A complete streetAddress containing an explicit supported
        # city is the more precise location field; do not use URL/title guesses.
        for obj in structured(soup):
            if not is_type(obj, 'Event'):continue
            loc=obj.get('location') or {}
            addr=loc.get('address') if isinstance(loc,dict) else None
            street=addr.get('streetAddress','') if isinstance(addr,dict) else ''
            if city_from_address(street):
                c.address=street;c.city_slug=city_from_address(street)
                c.location_evidence=url
            break
        text = soup.get_text("\n", strip=True)
        c.venue_name = re.sub(r'^Địa điểm\s*:\s*','',c.venue_name,flags=re.I).strip()
        c.venue_name = re.split(r'\s+-\s+(?=\d)',c.venue_name,maxsplit=1)[0]
        c.address = re.sub(r'^Địa điểm\s*:\s*','',c.address,flags=re.I).strip()
        sessions = ticketbox_sessions(text)
        if sessions:
            c.occurrences = sessions
        elif re.search(r"\+\s*\d+\s*ngày khác|\d+\s*suất diễn", text, re.I):
            c.reasons.append("unresolved_individual_sessions")
        # Only the event's own intro, not recommendations/footer.
        intro = text.split("Giới thiệu", 1)[-1].split("Lịch diễn", 1)[0] if "Giới thiệu" in text else ""
        c.original_text = intro[:2000]
        c.category = category(c.title) or category(intro[:300])
        return c


class Grapevine(Adapter):
    content_selector = ".td-post-text-content"
    link_pattern = r"/(?:vi/)?20\d{2}/\d{2}/[^/]+/?$"

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        body = soup.select_one(self.content_selector)
        if not body:
            return c
        # Grapevine's first paragraph is an editorial schedule/venue/address block.
        block = next((p for p in body.select('h4,h3,p') if re.search(r'\d{1,2}/\d{1,2}', p.get_text())), None)
        if block:
            lines = [s.strip() for s in block.get_text('\n', strip=True).splitlines() if s.strip()]
            addresses = [line for line in lines[1:] if city_from_address(line) and re.search(r'\d',line)]
            if len(addresses) > 1:
                c.reasons.append('unresolved_multiple_destinations')
            schedule = lines[0]
            for i, line in enumerate(lines[1:], 1):
                if city_from_address(line) and re.search(r'\d', line) and i > 1:
                    c.address = line
                    c.venue_name = lines[i-1]
                    c.city_slug = city_from_address(line)
                    c.location_evidence = url
                    c.occurrences = schedule_occurrences(schedule, now)
                    break
        c.category = c.category or category(soup.select_one('title').get_text() if soup.title else '')
        return c


class Fantasticity(Adapter):
    def parse(self,soup,url,now):
        c=super().parse(soup,url,now)
        if not c.occurrences and not re.search(r'lễ hội|sự kiện|festival|event|workshop|triển lãm',c.title,re.I) and c.category in {'restaurant','cafe','bar','experience'}:
            scoped=VnExpress(self.slug,self.config)
            scoped.content_selector=self.content_selector
            place=scoped.parse(soup,url,now)
            if place.venue_name and place.address:return place
        return c

    content_selector = ".entry-content, article, .detail-content, .post-content, .article-content, .news-detail-content"
    link_pattern = r"/(?:vi|en)/(?:le-hoi-su-kien|ket-noi-nghe-thuat[^/]*|kham-pha|am-thuc|trai-nghiem|festivals-events|local-food|experiences)/[^/?]{12,}$"

    def links(self, soup, base):
        links = list(super().links(soup, base))
        # Event coverage before evergreen resort/attraction pages.
        return iter(sorted(links, key=lambda u: 0 if any(t in u for t in ['su-kien','ket-noi-nghe','le-hoi','festival']) else 1))


class VnExpress(Adapter):
    content_selector = ".fck_detail"
    link_pattern = r"-\d{6,}\.html$"
    kind = "place"

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        body = soup.select_one(self.content_selector)
        if not body:
            return c
        # Restrict prose extraction to the article's opening paragraphs. Related
        # stories, bylines, captions and site footers cannot supply an address.
        paragraphs = [p.get_text(' ', strip=True) for p in body.select(':scope > p')][:8]
        for paragraph in paragraphs:
            match = re.match(r'^((?:Tiệm|Quán|Nhà hàng|Cà phê|Bánh mì|Cafe|Coffee)\s+[^,.;]{2,100}?),?\s+(?:(?:nằm|tọa lạc|có địa chỉ)\s+)?(?:trên|tại|ở)\s+(.+)', paragraph, re.I)
            if not match:
                continue
            name, location = match.groups()
            location = re.split(r',?\s+(?:là địa chỉ|là điểm|được|nổi tiếng|mở cửa)',location,maxsplit=1)[0].rstrip(' ,.')
            city = city_from_address(paragraph)
            if not city or len(location) > 200 or not re.search(r'phố|đường|phường|quận|số\s+\d',location,re.I):
                continue
            if not city_from_address(location):
                from .model import CITIES
                location += ', ' + CITIES[city]
            c.venue_name, c.address, c.city_slug = name.strip(), location, city
            c.location_evidence = url
            break
        c.published_at = c.published_at or meta(soup,'pubdate') or None
        return c

    def fetch(self, client, url):
        # The Vietnamese site serves a 404 shell to plain HTTP clients.
        return client.get(url,self.hosts,render=urlsplit(url).hostname=='vnexpress.net')

    def links(self, soup, base):
        # Avoid navigation/sidebar articles and prioritize the actual food listings.
        container = BeautifulSoup('<main></main>','html.parser')
        for a in soup.select('h3.title-news a[href],h2.title-news a[href],.title_news a[href]'):
            container.main.append(BeautifulSoup(str(a),'html.parser'))
        return super().links(container,base)


class TicketGo(Adapter):
    content_selector = ".ticket_info_box, .event-content, .event-detail, .event-description, article, main"
    link_pattern = r"/(?:event|su-kien)/[^/?]+/?$"

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        # TicketGo sometimes puts the full street address in location.name and
        # only the city in PostalAddress. Preserve the actual visitable address.
        if city_from_address(c.venue_name) and len(c.venue_name) > len(c.address):
            c.address = c.venue_name
            c.venue_name = c.venue_name.split(',')[0].strip()
            c.city_slug = city_from_address(c.address)
        # TicketGo also uses JSON-LD dates for an entire ticket-sales season.
        # A multi-month show is not a continuous performance. Until its session
        # selector is parsed, hold it out rather than publish invented hours.
        from .model import parse_time
        from datetime import timedelta
        if any(parse_time(o.ends_at) - parse_time(o.starts_at) > timedelta(hours=36)
               for o in c.occurrences):
            c.reasons.append('unresolved_individual_sessions')
        return c


class Nightlife(Adapter):
    content_selector = ".p-detail-1"
    link_pattern = r"-\d+-15\.html$"

    def parse(self, soup, url, now):
        # Related-event cards share the outer container. They are not evidence
        # for this event's destination, schedule, or images.
        from copy import deepcopy
        soup = deepcopy(soup)
        for related in soup.select('.p-detail-1 .p_other, .p-detail-1 .p_social'):
            related.decompose()
        c = super().parse(soup, url, now)
        c.category = "nightlife"
        body = soup.select_one(self.content_selector)
        if not body:
            c.reasons.append("missing_primary_content")
            return c
        text = body.get_text("\n", strip=True)
        schedule = ""
        for p in body.select("li,p"):
            value = p.get_text(" ", strip=True)
            if re.match(r"Time\s*:", value, re.I):
                schedule = value.split(":", 1)[-1].strip()
            elif re.match(r"Place\s*:", value, re.I):
                a = p.select_one('a[href]')
                c.venue_name = a.get_text(" ", strip=True) if a else value.split(':', 1)[-1].strip()
        # Publishers often put Address after a venue heading and <br>, so the
        # entire paragraph does not start with Address. Use explicit lines only.
        addresses = set()
        for line in body.get_text('\n', strip=True).splitlines():
            if re.match(r'^Address\s*:', line, re.I):
                address = line.split(':', 1)[-1].strip()
                if city_from_address(address):
                    addresses.add(address)
        if len(addresses) == 1:
            c.address = addresses.pop()
            c.city_slug = city_from_address(c.address)
            c.location_evidence = url
        elif len(addresses) > 1:
            c.reasons.append('ambiguous_event_addresses')
        c.occurrences = schedule_occurrences(schedule, now) or weekly(schedule, now)
        return c

    def enrich(self, c, soup, client, now):
        body = soup.select_one(self.content_selector)
        if not body:
            return c
        for p in body.select("li,p"):
            if not re.match(r"Place\s*:", p.get_text(" ", strip=True), re.I):
                continue
            link = p.find('a', href=re.compile(r'-\d+-16\.html$'))
            if not link:
                continue
            venue_url = urljoin(c.source_url, link['href'])
            venue = client.get(venue_url, self.hosts)
            for obj in structured(venue):
                if is_type(obj, "LocalBusiness", "NightClub", "BarOrPub", "Restaurant"):
                    name, address = location_fields({"location": obj})
                    if name and city_from_address(address):
                        c.venue_name, c.address = c.venue_name or name, address
                        break
            main = venue.select_one('.p-detail-1')
            if main and not c.address:
                for item in main.select('li,p'):
                    text = item.get_text(' ', strip=True)
                    if re.match(r'Address\s*:', text, re.I):
                        c.address = text.split(':', 1)[-1].strip()
                        break
            c.city_slug = city_from_address(c.address)
            c.location_evidence = venue_url if c.city_slug else ""
            break
        return c


class LifeOfDaNang(Adapter):
    content_selector = 'main'
    link_pattern = r'^/(?:vi/)?(?:danang/[^/]+|weekly(?:/[^/]+)?)$'

    def links(self,soup,base):
        links=list(super().links(soup.select_one('main') or soup,base))
        if urlsplit(base).path.rstrip('/') in {'/weekly','/vi/weekly'}:
            links.insert(0,base)
        return iter(dict.fromkeys(links))

    def calendar_seeds(self, now):
        today = now.astimezone(ICT).date()
        end = today + timedelta(days=30)
        month = today.replace(day=1)
        while month <= end:
            yield f'https://lifeofdanang.com/vi/danang/thang/{month:%Y-%m}'
            month = (month + timedelta(days=32)).replace(day=1)

    def calendar_links(self, soup, url, now):
        match = re.fullmatch(r'/vi/danang/thang/(\d{4})-(\d{2})/?', urlsplit(url).path)
        if not match:
            return None
        year, month = map(int, match.groups())
        today = now.astimezone(ICT).date()
        week, planning, other = [], [], []
        found_calendar = False
        for section in soup.select('main section:has(> h2)'):
            heading = folded(section.find('h2', recursive=False).get_text(' ', strip=True))
            day_match = re.fullmatch(r'(?:thu \w+|chu nhat) (\d{1,2}) thang (\d{1,2})', heading)
            if day_match and int(day_match[2]) == month:
                try:
                    day = date(year, month, int(day_match[1]))
                except ValueError:
                    continue
                found_calendar = True
                days = (day - today).days
                if days > 30:
                    continue
                bucket = other if days < 0 else week if days < 7 else planning
                bucket.extend(self.links(section, url))
            elif heading.startswith('hang tuan trong thang'):
                other.extend(self.links(section, url))
        if not found_calendar:
            return None
        ordered = [link for pair in zip_longest(week, planning) for link in pair if link]
        return list(dict.fromkeys(ordered + other))

    def parse_many(self,soup,url,now):
        if urlsplit(url).path.rstrip('/') in {'/weekly','/vi/weekly'}:
            from .entries import life_weekly
            return life_weekly(self,soup,url,now)
        c=self.parse(soup,url,now)
        if re.search(r'\band (?:the )?(?:Da Nang|Museum|Gallery)\b',c.venue_name,re.I):
            c.reasons.append('multiple_destinations_unresolved')
        # The publisher emits one Event object per occurrence of the same event.
        events=[e for e in structured(soup) if is_type(e,'Event')]
        if events and all(e.get('name')==events[0].get('name') and e.get('location')==events[0].get('location') for e in events):
            c.occurrences=[o for e in events if (o:=iso_occurrence(str(e.get('startDate','')),e.get('endDate')))]
            # Related-event cards in <main> must not supply the primary category
            # or text evidence. Use only this event's structured description.
            c.original_text = str(events[0].get('description') or '')
            c.category = category(c.title) or category(c.original_text)
            # Some pages put the street in the Place name and only the city in PostalAddress.
            # Require a single, numbered street suffix in this event's own location.
            parts = [part.strip() for part in c.venue_name.split(',')]
            if c.city_slug and not re.search(r'\d', c.address):
                for index, street in enumerate(parts[1:], start=1):
                    if not re.fullmatch(r'\d+[A-Za-z]?(?:[-/]\d+)*\s+[^,;]+', street):
                        continue
                    districts = parts[index + 1:]
                    if (not re.search(r'\b(?:và|and)\b|\d+\s', street.split(' ', 1)[-1], re.I)
                            and all(re.match(r'^(?:phuong|quan|huyen|thanh pho|tp) \S', folded(part)) for part in districts)):
                        c.venue_name = ', '.join(parts[:index])
                        c.address = ', '.join([street, *districts, c.address])
                    break
            if not re.search(r'\d', c.address):
                # City-only structured addresses do not resolve a branch or
                # distinguish a single destination from a citywide listing.
                c.reasons.append('unverified_street_address')
        return [c]

    def enrich(self, c, soup, client, now):
        review = self.config.get('reviewed_events', {}).get(canonical(c.source_url))
        if not review or c.status != 'active' or c.kind != 'event':
            return c
        event_id = urlsplit(c.source_url).path.rstrip('/').rsplit('/', 1)[-1]
        venue_links = [
            canonical(urljoin(c.source_url, link['href']))
            for link in soup.select('main a[data-ev=venue][data-ev-id][href]')
            if link['data-ev-id'] == event_id
        ]
        address = review['address']
        if (venue_links != [review['venue_url']]
                or folded(c.venue_name) != folded(review['location'])
                or city_from_address(address) != c.city_slug):
            c.reasons.append('unresolved_reviewed_venue')
            return c
        if 'unverified_street_address' in c.reasons:
            evidence = review['address_url']
            page = client.get(evidence, {urlsplit(evidence).hostname})
            address_text = folded(address)
            if not any(folded(p.get_text(' ', strip=True)).removesuffix(' viet nam') == address_text
                       for p in page.select('p, address')):
                c.reasons.append('unresolved_reviewed_address')
                return c
            c.address, c.location_evidence = address, evidence
            c.reasons.remove('unverified_street_address')
        elif folded(c.address) != folded(address):
            c.reasons.append('unresolved_reviewed_address')
            return c
        schedule, conflict = self._corroborated_schedule(c, review, client, now)
        if schedule:
            c.occurrences = schedule
        else:
            c.reasons.append('unresolved_cross_source_session_times')
            if conflict:
                c.reasons.append(CONFIRMED_SCHEDULE_CONFLICT)
        return c

    def _corroborated_schedule(self, c, review, client, now):
        evidence = review['schedule_url']
        page = client.get(evidence, {urlsplit(evidence).hostname})
        # These reviewed listings have one dated row per venue. Administrative
        # or related-event text elsewhere on either page must not supply times.
        rows = [
            cells for row in page.select('tr')
            if len(cells := [cell.get_text(' ', strip=True) for cell in row.select(':scope > td')]) == 3
            and folded(cells[1]) == folded(review['venue_name'])
        ]
        publisher_text = c.original_text.partition('\n')[0]
        ranges = re.findall(r'\b(\d{1,2})h(\d{2})?\s+(?:den|toi)\s+(\d{1,2})h(\d{2})?\b', plain(publisher_text))
        if (len(rows), len(ranges), len(c.occurrences)) != (1, 1, 1):
            return [], False
        day, _, time_text = rows[0]
        start_hour, start_minute, end_hour, end_minute = ranges[0]
        publisher_time = f'{int(start_hour):02}:{start_minute or "00"}-{int(end_hour):02}:{end_minute or "00"}'
        listed_time = re.match(r'\d{2}:\d{2}\s*-\s*\d{2}:\d{2}\b', plain(time_text))
        if not listed_time or not re.fullmatch(r'\d{2}/\d{2}/20\d{2}', day):
            return [], False
        previous = c.occurrences[0]
        bounds = parse_time(previous.starts_at), parse_time(previous.ends_at)
        source_day = bounds[0].astimezone(ICT).strftime('%d/%m/%Y')
        source_sessions = schedule_occurrences(f'{source_day} {publisher_time}', now)
        listed_sessions = schedule_occurrences(f'{day} {listed_time[0]}', now)
        if len(source_sessions) != 1 or len(listed_sessions) != 1:
            return [], False
        start, end = parse_time(source_sessions[0].starts_at), parse_time(source_sessions[0].ends_at)
        if previous.precision == 'date' and not bounds[0] <= start < end <= bounds[1]:
            return [], False
        if previous.precision == 'time' and (start, end) != bounds:
            return [], False
        if source_sessions != listed_sessions:
            return [], True
        return source_sessions, False


class HoGuomOpera(Adapter):
    content_selector = '.ck-content'
    link_pattern = r'^/chuong-trinh-bieu-dien/[^/]+-\d+$'

    def parse(self, soup, url, now):
        candidate = super().parse(soup, url, now)
        body = soup.select_one(self.content_selector)
        if body is None:
            return candidate
        address_lines = []
        schedule_lines = []
        for line in body.get_text('\n', strip=True).splitlines():
            if 'Địa điểm:' in line:
                address_lines.append(line.split('Địa điểm:', 1)[1].strip())
            if 'Thời gian:' in line:
                schedule_lines.append(line.split('Thời gian:', 1)[1].strip())
        candidate.location_evidence = ''
        if len(set(address_lines)) == 1:
            venue, _, address = address_lines[0].partition(',')
            if city_from_address(address) == 'hanoi' and folded(venue) == 'nha hat ho guom':
                candidate.venue_name = venue.strip()
                candidate.address = address.strip().rstrip('.')
                candidate.city_slug = 'hanoi'
                candidate.location_evidence = url
        candidate.occurrences = []
        if len(set(schedule_lines)) != 1:
            candidate.reasons.append('unresolved_individual_sessions')
            return candidate
        match = re.fullmatch(
            r'(?:[01]?\d|2[0-3])(?:h|:)[0-5]\d,?\s*ngay '
            r'(\d{1,2}(?:,\s*\d{1,2})*(?:\s+va\s+\d{1,2})?)/(\d{1,2})/(20\d{2})',
            plain(schedule_lines[0]).rstrip('.'),
        )
        if not match:
            candidate.reasons.append('unresolved_individual_sessions')
            return candidate
        days, month, year = match.groups()
        try:
            dates = {date(int(year), int(month), int(day)).isoformat() for day in re.findall(r'\d{1,2}', days)}
        except ValueError:
            candidate.reasons.append('unresolved_individual_sessions')
            return candidate
        # The program promises these days and a start time, with no end time.
        candidate.occurrences = [iso_occurrence(day, day) for day in sorted(dates)]
        return candidate


class Saigoneer(VnExpress):
    content_selector = 'article.content'
    link_pattern = r'^/(?:vn/)?(?:saigon-street-food-restaurants|hanoi-street-food-restaurants|vietnam-street-food-restaurants|an-uong)/\d+[^/]+$'

    def fetch(self,client,url):
        return client.get(url,self.hosts)

    def links(self,soup,base):
        return Adapter.links(self,soup,base)

    def parse(self,soup,url,now):
        c=super().parse(soup,url,now)
        body=soup.select_one(self.content_selector)
        # Publisher's closing venue/address block, not article headline or sidebar.
        if body and not c.city_slug:
            lines=[p.get_text(' ',strip=True) for p in body.select('p')]
            for i,line in enumerate(lines):
                city=city_from_address(line)
                if city and re.match(r'^\d+[\w/-]*\s+',line) and i>0:
                    name=lines[i-1]
                    if len(name)<120 and not city_from_address(name):
                        c.venue_name,c.address,c.city_slug=name,line,city
                        c.location_evidence=url
                        c.category=c.category or category(name)
        return c


class HanoiGo(Adapter):
    """Official city listings; only primary venue and explicit individual sessions."""
    content_selector = '[data-testid="article-section-intro"]'
    link_pattern = r'^/event/[^/?]+$'

    def parse(self, soup, url, now):
        from datetime import datetime, timedelta
        from .model import ICT, Occurrence
        title=soup.select_one('h1')
        intro=soup.select_one(self.content_selector)
        venue=soup.select_one('[data-testid="detail-info-venue"]')
        timing=soup.select_one('[data-testid="detail-info-time"]')
        extras=soup.select_one('[data-testid="article-section-extras"]')
        text=intro.get_text(' ',strip=True) if intro else ''
        name=title.get_text(' ',strip=True) if title else ''
        location=re.sub(r'^Địa điểm\s*','',venue.get_text(' ',strip=True)) if venue else ''
        c=Candidate(self.slug,self.config['name'],url,name,'event',
            category=category(name) or category(text[:500]),original_text=text[:12000],
            verified_at=now.isoformat())
        # Prefer the explicit location field. Otherwise take a short address
        # sentence from this event's introduction, never related-event cards.
        address=location if city_from_address(location) else ''
        if not address:
            for match in re.finditer(r'(?:Địa điểm\s*:|\btại\s+)([^.!?]{5,240}Hà\s+Nội)',text,re.I):
                proposed=match[1].strip()
                if folded(location) in folded(proposed):
                    address=proposed;break
        c.venue_name=location
        c.address=address
        c.city_slug=city_from_address(address)
        c.location_evidence=url if c.city_slug and location else ''
        if re.search(r'\b(da huy|huy su kien|cancelled)\b',folded(name+' '+text[:500])):
            c.status='cancelled'
        time_text=timing.get_text(' ',strip=True) if timing else ''
        full=re.search(r'(\d{1,2})/(\d{1,2})/(20\d{2})',time_text)
        if not full:return c
        year=int(full[3])
        session_text=extras.get_text(' ',strip=True) if extras else time_text
        pattern=r'(\d{1,2})/(\d{1,2})\s*·\s*(\d{2}):(\d{2})\s*[–-]\s*(\d{2}):(\d{2})'
        sessions=set()
        for d,m,ah,am,bh,bm in re.findall(pattern,session_text):
            a=datetime(year,int(m),int(d),int(ah),int(am),tzinfo=ICT)
            b=a.replace(hour=int(bh),minute=int(bm))
            if b<=a:b+=timedelta(days=1)
            sessions.add((a,b))
        # Publisher all-day exhibitions use a single first-day ticket entry
        # and an explicit inclusive date range in their primary facts panel.
        # This is date-only evidence, not inferred daily performance hours.
        if '00:00' in time_text and '23:59' in time_text and folded(name).startswith('trien lam'):
            ranges=[]
            for dt in soup.select('dt'):
                if dt.get_text(' ',strip=True) != 'Thời gian':continue
                dd=dt.find_next_sibling('dd')
                if not dd:continue
                match=re.search(r'(\d{1,2})\s*[–-]\s*(\d{1,2})/(\d{1,2})/(20\d{2})',dd.get_text(' ',strip=True))
                if match:
                    d1,d2,m,y=map(int,match.groups())
                    ranges.append((datetime(y,m,d1,tzinfo=ICT),datetime(y,m,d2,tzinfo=ICT)+timedelta(days=1)))
            if len(set(ranges)) == 1:
                a,b=ranges[0]
                c.occurrences=[Occurrence(a.isoformat(),b.isoformat(),'date')]
                return c
        more=re.search(r'\+(\d+)\s*suất khác',time_text)
        expected=int(more[1])+1 if more else 1
        # A streamed preview can truncate the schedule to three sessions.
        # Never turn its overall date range into invented daily performances.
        if len(sessions)<expected:
            c.reasons.append('unresolved_individual_sessions')
        c.occurrences=[Occurrence(a.isoformat(),b.isoformat()) for a,b in sorted(sessions)]
        return c

CLASSES = {"hanoigo": HanoiGo, "vietnamnightlife": Nightlife, "ticketbox": Ticketbox, "hanoigrapevine": Grapevine,
           "danangfantasticity": Fantasticity, "vnexpress": VnExpress, "ticketgo": TicketGo, "lifeofdanang": LifeOfDaNang,
           "hoguomopera": HoGuomOpera, "saigoneer": Saigoneer}


def load_sources():
    return json.loads(Path(__file__).with_name('sources.json').read_text())


def collect_source(slug, config, client, now, limit=12, extra_urls=(), heartbeat=lambda: None, metrics=None, existing_only=False):
    adapter = CLASSES[slug](slug, config)
    metrics = metrics if metrics is not None else {}
    metrics.update(listing_pages=0,detail_pages=0,extracted_entries=0)
    links = list(extra_urls)
    failures = []
    seeds = [] if existing_only else list(config['seeds'])
    if slug == 'ticketbox' and not existing_only:
        heartbeat()
        try:
            public_links = adapter.public_listing_links(client)
            metrics['listing_pages'] += 1
            if public_links:
                links.extend(public_links)
                seeds = []
        except Exception as exc:
            failures.append({'stage': 'listing', 'reason': fetch_failure_reason(exc)})
    if slug == 'lifeofdanang' and not existing_only:
        seeds = [*adapter.calendar_seeds(now), *seeds]
    seed_groups = []
    for seed in seeds:
        heartbeat()
        try:
            listing=adapter.fetch(client,seed)
            metrics['listing_pages']+=1
            ordered = adapter.calendar_links(listing, seed, now) if slug == 'lifeofdanang' else None
            if ordered is None:
                ordered = list(adapter.links(listing, seed))
                if slug != 'danangfantasticity':
                    # Dated listing entries first; undated links retain publisher order.
                    dated = []
                    for node in listing.select('article:has(time), [data-published]'):
                        dated.extend(adapter.links(node, seed))
                        parent = node.find_parent('a', href=True)
                        if parent:
                            dated.extend(adapter.links(BeautifulSoup(str(parent), 'html.parser'), seed))
                    ordered = dated + ordered
            seed_groups.append(ordered)
            links.extend(ordered)
            next_page=listing.select_one('a[rel="next"][href]')
            if next_page and len(seeds)<len(config['seeds'])*2:
                target=canonical(urljoin(seed,next_page['href']))
                if urlsplit(target).hostname in adapter.hosts and target not in seeds:seeds.append(target)
        except Exception as exc:
            failures.append({"stage": "listing", "reason": fetch_failure_reason(exc)})
        heartbeat()
    if len(seed_groups)>1 and slug!='danangfantasticity' and not existing_only:
        # Give category listings a share of the bounded detail-page budget.
        # Homepage ordering must not consume every slot before sports/workshops.
        links = list(extra_urls) + [u for row in zip_longest(*seed_groups) for u in row if u]
    links = list(dict.fromkeys(links))[:limit]
    if slug == 'danangfantasticity' and not existing_only:
        # Reserve detail capacity for the individual activities linked by campaigns.
        links = links[:max(1,limit-3)]
    if not links and not existing_only:
        failures.append({'stage':'listing','reason':'no_detail_links'})
    candidates = []
    consecutive_fetch_failures = 0
    for url in links:
        heartbeat()
        try:
            soup = adapter.fetch(client, url)
            consecutive_fetch_failures = 0
            metrics['detail_pages']+=1
            # Official campaign pages link to individual activities. Discover
            # those pages within the same total detail-page budget.
            if slug == 'danangfantasticity' and not existing_only:
                for child in adapter.links(soup,url):
                    if child not in links and len(links) < limit:
                        links.append(child)
            for c in adapter.parse_many(soup,url,now):
                if isinstance(c,dict) and c.get('extraction_failure'):
                    failures.append({'stage':'entry','reason':c['extraction_failure']})
                    continue
                try:
                    if hasattr(adapter,'enrich'):c=adapter.enrich(c,soup,client,now)
                    if reason := config.get('review_holds', {}).get(canonical(c.source_url)):
                        c.reasons.append(reason)
                        if reason in {'unresolved_cross_source_session_times', 'unresolved_cross_source_end_time'}:
                            c.reasons.append(CONFIRMED_SCHEDULE_CONFLICT)
                    from .images import authorize
                    authorize(c,now)
                    candidates.append(c)
                    metrics['extracted_entries']+=1
                except Exception as exc:
                    failures.append({'stage':'entry','reason':fetch_failure_reason(exc)})
        except Exception as exc:
            failures.append({"stage": "detail", "reason": fetch_failure_reason(exc)})
            if isinstance(exc,FetchError):
                consecutive_fetch_failures += 1
                if consecutive_fetch_failures >= 3:
                    failures.append({'stage':'detail','reason':'source_fetch_circuit_open'})
                    break
        heartbeat()
    return candidates, failures


def supplemental_links(client, configs):
    """Only use supplemental sites to discover links to dedicated collectors."""
    result = {slug: [] for slug in CLASSES}
    for slug, config in configs.items():
        if not config.get('discovery_only'):
            continue
        for seed in config['seeds']:
            try:
                soup = client.get(seed, set(config['hosts']))
            except FetchError:
                continue
            for target in CLASSES:
                result[target].extend(CLASSES[target](target, configs[target]).links(soup, seed))
    return result
