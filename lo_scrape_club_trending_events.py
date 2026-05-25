"""
lo_scrape_events.py
-------------------
Scrapes upcoming nightlife events from vietnamnightlife.com for Lo! content seeding.

Source  : https://vietnamnightlife.com/en/upcoming-events-1-11.html
Coverage: HCMC + Hanoi (default). Pass --city to filter to one city.
Output  : JSON (default). Pass --csv to also write a CSV.

Usage
-----
  pip install requests beautifulsoup4

  python lo_scrape_events.py                      # both cities -> events.json
  python lo_scrape_events.py --city hcmc          # HCMC only
  python lo_scrape_events.py --city hanoi         # Hanoi only
  python lo_scrape_events.py --csv                # also write events.csv
  python lo_scrape_events.py --out my_file.json   # custom output path
  python lo_scrape_events.py --delay 1.5          # polite crawl delay (seconds)

How city detection works
------------------------
  ALL city pages are scraped (HCMC, Hanoi, Da Nang, Nha Trang, etc.) to build
  a complete venue -> city lookup. This prevents mislabelling: a Da Nang event
  page might contain sidebar links to HCMC venues, and without the full lookup
  those events would be incorrectly tagged as HCMC.

  For each event:
    1. Check event URL directly against city event lookups
    2. Check venue URL from listing page against venue lookup
    3. Fetch detail page, find venue URL, check venue lookup
    4. If still unknown -> city = None (filtered out when --city is used)

Output fields per event
-----------------------
  event_name    Name of the event
  venue_name    Venue where it takes place
  venue_url     Link to the venue page on vietnamnightlife.com
  schedule      Recurrence string e.g. "Every Wednesday", "Monday to Thursday"
  music         Music genre(s) e.g. "EDM", "Hiphop, Top 40"
  city          "hcmc" | "hanoi" | None
  description   Event description text
  image_url     Event poster image URL
  event_url     Source URL

Notes for Khanh
---------------
- All events are recurring weekly nights. Store schedule as plain text.
- city = None means the venue city could not be determined.
- Crawl delay defaults to 1.0s. Do not set below 0.5s.
- Use --workers to fetch pages concurrently. Pass --no-description to skip
  detail pages for events with a known city (faster, no description text).
"""

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://vietnamnightlife.com"
LISTING_PAGE_1 = "/en/upcoming-events-1-11.html"
LISTING_PAGE_N = "/en/upcoming-events-trang-{n}-1-11.html"
TOTAL_PAGES = 5

# ALL city pages — not just HCMC and Hanoi.
# Including other cities prevents their events being mislabelled as HCMC/Hanoi
# due to sidebar venue links appearing on event detail pages.
ALL_CITY_PAGES = {
    "hcmc": "/en/ho-chi-minh-city-nightlife-sl17-2.html",
    "hanoi": "/en/ha-noi-nightlife-sl18-2.html",
    "danang": "/en/da-nang-nightlife-sl10-2.html",
    "nhatrang": "/en/nha-trang-nightlife-sl5-2.html",
    "hoian": "/en/hoi-an-nightlife-sl48-2.html",
    "phuquoc": "/en/phu-quoc-nightlife-sl11-2.html",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Lo-ContentBot/1.0; +https://lo-app.vn/bot)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_FIELDS = [
    "event_name",
    "venue_name",
    "venue_url",
    "schedule",
    "music",
    "city",
    "description",
    "image_url",
    "event_url",
]

EVENT_HREF_RE = re.compile(r"-\d+-15\.html$")
VENUE_HREF_RE = re.compile(r"-\d+-16\.html$")

EVENT_SOURCE_SLUG = "vietnamnightlife"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, delay):
        self.delay = delay
        self.lock = threading.Lock()
        self.last_request = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            sleep_for = self.delay - (now - self.last_request)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self.last_request = time.monotonic()


def fetch_soup(url, session, limiter):
    limiter.wait()
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print("  [WARN] {}: {}".format(url, e), file=sys.stderr)
        return None


def fetch_many(urls, session, limiter, workers):
    results = {}

    def worker(url):
        return url, fetch_soup(url, session, limiter)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, url) for url in urls]
        for future in as_completed(futures):
            url, soup = future.result()
            results[url] = soup

    return results


def clean(text):
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None


def listing_url(page):
    if page == 1:
        return urljoin(BASE_URL, LISTING_PAGE_1)
    return urljoin(BASE_URL, LISTING_PAGE_N.format(n=page))


def absolute_image_url(src):
    if not src:
        return None
    return urljoin(BASE_URL, src) if src.startswith("/") else src


def extract_poster_image_url(soup):
    """Return the event poster from the detail page, not site logo or related events."""
    img = soup.select_one(".p-detail-1 .p_thumb img")
    if not img:
        img = soup.select_one(".p_thumb img")
    if not img:
        img = soup.find("img", src=re.compile(r"single_product\d"))
    if not img:
        return None
    return absolute_image_url(img.get("src", ""))


# ---------------------------------------------------------------------------
# Step 1: Build city lookups from ALL city pages
# ---------------------------------------------------------------------------


def build_city_lookups(session, limiter, workers):
    """
    Scrape all city pages and return:
      event_city  { event_url -> city }
      venue_city  { venue_url -> city }

    Including Da Nang and other cities is critical — without them, Da Nang
    events get mislabelled as HCMC because their detail pages contain sidebar
    links to HCMC venues.
    """
    event_city = {}
    venue_city = {}

    urls = {urljoin(BASE_URL, path): city for city, path in ALL_CITY_PAGES.items()}
    print("  Fetching {} city pages...".format(len(urls)))
    pages = fetch_many(urls.keys(), session, limiter, workers)

    for url, city in urls.items():
        soup = pages.get(url)
        if not soup:
            continue

        ev_count = 0
        for a in soup.find_all("a", href=EVENT_HREF_RE):
            event_url = urljoin(BASE_URL, a["href"])
            if event_url not in event_city:
                event_city[event_url] = city
                ev_count += 1

        vn_count = 0
        for a in soup.find_all("a", href=VENUE_HREF_RE):
            venue_url = urljoin(BASE_URL, a["href"])
            if venue_url not in venue_city:
                venue_city[venue_url] = city
                vn_count += 1

        print("  {}: {} events, {} venues".format(city, ev_count, vn_count))

    print(
        "  Total: {} event URLs, {} venue URLs across all cities".format(
            len(event_city), len(venue_city)
        )
    )
    return event_city, venue_city


# ---------------------------------------------------------------------------
# Step 2: Scrape listing pages
# ---------------------------------------------------------------------------


def find_venue_link(node):
    if not node:
        return None
    venue_a = node.find("a", href=VENUE_HREF_RE)
    if venue_a:
        return urljoin(BASE_URL, venue_a["href"])
    parent = node.find_parent()
    if parent:
        venue_a = parent.find("a", href=VENUE_HREF_RE)
        if venue_a:
            return urljoin(BASE_URL, venue_a["href"])
    return None


def scrape_listing_page(soup):
    stubs, seen = [], set()

    for block in soup.select(".b-event"):
        event_a = block.find("a", href=EVENT_HREF_RE)
        if not event_a:
            continue

        url = urljoin(BASE_URL, event_a["href"])
        if url in seen:
            continue
        seen.add(url)

        title = block.select_one(".b_title")
        name = clean(title.get_text(separator=" ") if title else event_a.get_text(separator=" "))
        if not name:
            continue

        venue_el = block.select_one(".b_address")
        venue_name = clean(venue_el.get_text(separator=" ")) if venue_el else None
        venue_url = find_venue_link(block)

        schedule_el = block.select_one(".date")
        music_el = block.select_one(".cat")
        img = block.select_one(".b_thumb img")

        stubs.append(
            {
                "event_name": name,
                "event_url": url,
                "venue_name": venue_name,
                "venue_url": venue_url,
                "schedule": clean(schedule_el.get_text(separator=" ")) if schedule_el else None,
                "music": clean(music_el.get_text(separator=" ")) if music_el else None,
                "image_url": absolute_image_url(img.get("src", "")) if img else None,
            }
        )

    return stubs


# ---------------------------------------------------------------------------
# Step 3: Scrape event detail pages
# ---------------------------------------------------------------------------


def scrape_event_detail(soup):
    detail = {
        "schedule": None,
        "music": None,
        "place": None,
        "description": None,
        "image_url": None,
        "venue_url": None,
    }

    for element in soup.find_all(["li", "p"]):
        text = element.get_text(separator=" ")
        if "Time:" in text:
            detail["schedule"] = clean(text.replace("Time:", "").strip())
        elif "Place:" in text:
            detail["place"] = clean(text.replace("Place:", "").strip())
        elif "Kind of music:" in text:
            detail["music"] = clean(text.replace("Kind of music:", "").strip())

    content = (
        soup.find("div", class_=re.compile(r"content|detail|description", re.I))
        or soup.find("article")
        or soup.find("main")
    )
    if content:
        paras = [
            clean(p.get_text(separator=" "))
            for p in content.find_all("p")
            if clean(p.get_text())
        ]
        detail["description"] = " ".join(paras) if paras else None

    detail["image_url"] = extract_poster_image_url(soup)

    venue_url = None
    for element in soup.find_all(["li", "p", "div", "span"]):
        text = element.get_text(separator=" ")
        if "Place:" in text:
            venue_a = element.find("a", href=VENUE_HREF_RE)
            if venue_a:
                venue_url = urljoin(BASE_URL, venue_a["href"])
                break

    detail["venue_url"] = venue_url
    return detail


def resolve_city(stub, event_city, venue_city):
    city = event_city.get(stub["event_url"])
    if not city and stub.get("venue_url"):
        city = venue_city.get(stub["venue_url"])
    return city


def needs_detail_fetch(stub, city, city_filter, with_description):
    if with_description:
        return True
    if city is None:
        return True
    if city_filter and city != city_filter:
        return False
    return False


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(city_filter, delay, workers, with_description):
    session = requests.Session()
    limiter = RateLimiter(delay)

    # Step 1: build full city lookups
    print("Building city lookups from all city pages...")
    event_city, venue_city = build_city_lookups(session, limiter, workers)

    # Step 2: collect all stubs from listing pages
    listing_urls = [listing_url(page) for page in range(1, TOTAL_PAGES + 1)]
    print("\nScraping {} listing pages...".format(len(listing_urls)))
    listing_pages = fetch_many(listing_urls, session, limiter, workers)

    stubs = []
    for url in listing_urls:
        soup = listing_pages.get(url)
        if not soup:
            continue
        page_stubs = scrape_listing_page(soup)
        print("  {} -> {} events".format(url, len(page_stubs)))
        stubs.extend(page_stubs)

    seen, unique = set(), []
    for s in stubs:
        if s["event_url"] not in seen:
            seen.add(s["event_url"])
            unique.append(s)
    print("\nUnique events: {}".format(len(unique)))

    # Step 3: fetch detail pages only when needed
    detail_urls = []
    for stub in unique:
        city = resolve_city(stub, event_city, venue_city)
        if city_filter and city and city != city_filter:
            continue
        if needs_detail_fetch(stub, city, city_filter, with_description):
            detail_urls.append(stub["event_url"])

    print(
        "\nFetching {} detail pages (skipped {})...".format(
            len(detail_urls), len(unique) - len(detail_urls)
        )
    )
    detail_pages = fetch_many(detail_urls, session, limiter, workers) if detail_urls else {}

    events = []
    for i, stub in enumerate(unique, 1):
        event_url = stub["event_url"]
        city = resolve_city(stub, event_city, venue_city)
        detail = {}

        if event_url in detail_pages:
            soup = detail_pages.get(event_url)
            detail = scrape_event_detail(soup) if soup else {}
            if not city and detail.get("venue_url"):
                city = venue_city.get(detail["venue_url"])

        if city_filter and city != city_filter:
            continue

        venue_url = stub.get("venue_url") or detail.get("venue_url")

        record = {
            "event_name": stub["event_name"],
            "event_url": event_url,
            "venue_name": detail.get("place") or stub.get("venue_name"),
            "venue_url": venue_url,
            "schedule": stub.get("schedule") or detail.get("schedule"),
            "music": stub.get("music") or detail.get("music"),
            "city": city,
            "description": detail.get("description"),
            "image_url": stub.get("image_url") or detail.get("image_url"),
        }

        print(
            "  [{}/{}] {} -> city: {}".format(
                i, len(unique), stub["event_name"], city or "unknown"
            )
        )
        events.append(record)

    print("\nEvents collected ({}): {}".format(city_filter or "all", len(events)))
    return events


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_json(events, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print("JSON written -> {}".format(path))


def write_csv(events, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(events)
    print("CSV written  -> {}".format(path))


def get_database_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def write_db(events, source_slug=EVENT_SOURCE_SLUG):
    """Replace all scraped events for this source via stored procedure."""
    db_url = get_database_url()
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL or SUPABASE_DB_URL is required for --write-db"
        )

    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "psycopg is required for --write-db. Run: pip install -r requirements.txt"
        ) from e

    payload = json.dumps(events, ensure_ascii=False)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_slug, deleted_count, inserted_count, imported_at "
                "FROM public.replace_external_events(%s, %s::jsonb)",
                (source_slug, payload),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("replace_external_events returned no rows")

    source_slug, deleted_count, inserted_count, imported_at = row
    print(
        "DB import -> source: {}, deleted: {}, inserted: {}, at: {}".format(
            source_slug, deleted_count, inserted_count, imported_at
        )
    )
    return {
        "source_slug": source_slug,
        "deleted_count": deleted_count,
        "inserted_count": inserted_count,
        "imported_at": imported_at,
    }


def print_summary(events):
    print("\n--- Summary ---")
    by_city = {}
    for e in events:
        c = e.get("city") or "unknown"
        by_city[c] = by_city.get(c, 0) + 1
    for city, n in sorted(by_city.items()):
        print("  {}: {}".format(city, n))
    print("  Total: {}".format(len(events)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape nightlife events from vietnamnightlife.com for Lo! seeding."
    )
    parser.add_argument(
        "--city",
        choices=["hcmc", "hanoi"],
        default=None,
        help="Filter to one city. Omit to include both.",
    )
    parser.add_argument(
        "--out",
        default="events.json",
        help="Output JSON file path (default: events.json).",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also write a CSV file.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1.0, min enforced: 0.5).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent fetch workers (default: 4).",
    )
    parser.add_argument(
        "--no-description",
        action="store_true",
        help="Skip detail pages for events with a known city (faster, no descriptions).",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Write scraped events to Postgres via replace_external_events().",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    delay = max(0.5, args.delay)
    workers = max(1, args.workers)

    events = run(
        city_filter=args.city,
        delay=delay,
        workers=workers,
        with_description=not args.no_description,
    )

    if not events:
        print("No events found. Check filters or site structure.", file=sys.stderr)
        sys.exit(1)

    write_json(events, args.out)

    if args.csv:
        csv_path = (
            args.out.replace(".json", ".csv")
            if args.out.endswith(".json")
            else args.out + ".csv"
        )
        write_csv(events, csv_path)

    if args.write_db:
        try:
            write_db(events)
        except Exception as e:
            print("DB write failed: {}".format(e), file=sys.stderr)
            sys.exit(1)

    print_summary(events)


if __name__ == "__main__":
    main()
