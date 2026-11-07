from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .dates import iso_occurrence, schedule_occurrences, ticketbox_sessions, weekly
from .http import FetchError, PublicClient
from .model import Candidate, canonical, city_from_address, folded


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
    text = folded(text)
    for name, pattern in [
        ("workshop", r'workshop|lop hoc|lam gom'),
        ("cafe", r'ca phe|cafe|coffee|brunch'),
        ("restaurant", r'quan an|nha hang|am thuc|restaurant|eatery|quan pho|quan bun|banh mi|bot chien|banh cuon'),
        ("nightlife", r'club|nightlife|night club'),
        ("bar", r'\bbar\b|cocktail|beer|bia'),
        ("music", r'concert|nhac|music|live show|dj|jazz'),
        ("culture", r'trien lam|exhibition|gallery|bao tang|museum|film|phim|nha hat|theater|le hoi|festival|phong doc|nghe thuat|trung bay'),
        ("experience", r'trai nghiem|experience|walking tour|city tour|tham quan')]:
        if re.search(pattern, text):
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
                      venue_name=venue, address=address, category=category(title + " " + text[:300]),
                      original_text=text[:2000], published_at=published or None,
                      verified_at=now.isoformat(), image_url=meta(soup, "og:image") or None,
                      image_permitted=self.config.get("image_permission", False))
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
    content_selector = "main"
    link_pattern = r"^/(?!search|customer|organizer)[a-z0-9-]+-\d{4,}$"

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        text = soup.get_text("\n", strip=True)
        c.venue_name = re.sub(r'^Địa điểm\s*:\s*','',c.venue_name,flags=re.I).strip()
        c.venue_name = re.split(r'\s+-\s+(?=\d)',c.venue_name,maxsplit=1)[0]
        c.address = re.sub(r'^Địa điểm\s*:\s*','',c.address,flags=re.I).strip()
        sessions = ticketbox_sessions(text)
        if sessions:
            c.occurrences = sessions
        elif re.search(r"\+\s*\d+\s*ngày khác", text, re.I):
            c.reasons.append("unresolved_individual_sessions")
        # Only the event's own intro, not recommendations/footer.
        intro = text.split("Giới thiệu", 1)[-1].split("Lịch diễn", 1)[0] if "Giới thiệu" in text else ""
        c.original_text = intro[:2000]
        c.category = category(c.title + " " + intro[:300])
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
    content_selector = ".entry-content, article, .detail-content, .post-content, .article-content, .news-detail-content"
    link_pattern = r"/(?:vi|en)/(?:le-hoi-su-kien|ket-noi-nghe-thuat[^/]*|kham-pha|festivals-events)/[^/?]{12,}$"

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
        paragraphs = [p.get_text(' ', strip=True) for p in body.select(':scope > p')][:4]
        for paragraph in paragraphs:
            match = re.match(r'^((?:Tiệm|Quán|Nhà hàng|Cà phê|Bánh mì)\s+[^,.;]{2,100}),?\s+(?:nằm|tọa lạc)\s+(?:trên|tại|ở)\s+(.+)', paragraph, re.I)
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
    content_selector = ".event-content, .event-detail, .event-description, article, main"
    link_pattern = r"/(?:event|su-kien)/[^/?]+/?$"

    def parse(self, soup, url, now):
        c = super().parse(soup, url, now)
        # TicketGo sometimes puts the full street address in location.name and
        # only the city in PostalAddress. Preserve the actual visitable address.
        if city_from_address(c.venue_name) and len(c.venue_name) > len(c.address):
            c.address = c.venue_name
            c.venue_name = c.venue_name.split(',')[0].strip()
            c.city_slug = city_from_address(c.address)
        return c


class Nightlife(Adapter):
    content_selector = ".p-detail-1"
    link_pattern = r"-\d+-15\.html$"

    def parse(self, soup, url, now):
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
                if a:
                    c.venue_name = a.get_text(" ", strip=True)
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


CLASSES = {"vietnamnightlife": Nightlife, "ticketbox": Ticketbox, "hanoigrapevine": Grapevine,
           "danangfantasticity": Fantasticity, "vnexpress": VnExpress, "ticketgo": TicketGo}


def load_sources():
    return json.loads(Path(__file__).with_name('sources.json').read_text())


def collect_source(slug, config, client, now, limit=12, extra_urls=()):
    adapter = CLASSES[slug](slug, config)
    links = list(extra_urls)
    failures = []
    for seed in config['seeds']:
        try:
            links.extend(adapter.links(adapter.fetch(client, seed), seed))
        except FetchError as exc:
            failures.append({"stage": "listing", "url": seed, "reason": str(exc)})
    links = list(dict.fromkeys(links))[:limit]
    if not links:
        failures.append({'stage':'listing','reason':'no_detail_links'})
    candidates = []
    for url in links:
        try:
            soup = adapter.fetch(client, url)
            # Official campaign pages link to individual activities. Discover
            # those pages within the same total detail-page budget.
            if slug == 'danangfantasticity':
                for child in adapter.links(soup,url):
                    if child not in links and len(links) < limit:
                        links.append(child)
            c = adapter.parse(soup, url, now)
            if hasattr(adapter, 'enrich'):
                c = adapter.enrich(c, soup, client, now)
            candidates.append(c)
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            failures.append({"stage": "detail", "url": url, "reason": str(exc) if isinstance(exc, FetchError) else type(exc).__name__})
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
