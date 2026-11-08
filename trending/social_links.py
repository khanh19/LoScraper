"""Free discovery of original social posts embedded on public organizer pages.

This reads website HTML only. It never calls a provider or publishes evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .http import PublicClient, FetchError
from .model import canonical, parse_time
from .providers import post_platform


def extract_posts(html, source_url, now, limit=30):
    source_url = canonical(source_url)
    found = {}
    excluded = set()

    def add(url, text='', timestamp=None):
        if not isinstance(url, str) or not post_platform(url):
            return
        url = canonical(url)
        date = parse_time(timestamp)
        if timestamp and (not date or not now - timedelta(days=7) <= date <= now):
            excluded.add(url)
            found.pop(url, None)
            return
        if url in excluded:
            return
        row = {'url': url, 'platform': post_platform(url), 'discovered_on': source_url,
               'text': str(text)[:2000], 'published_at': date.isoformat() if date else None,
               'requires_provider_validation': True}
        if url not in found or (date and not found[url]['published_at']):
            found[url] = row

    def walk(obj, depth=0):
        if depth > 40:
            return
        if isinstance(obj, dict):
            for field in ('link', 'permalink', 'url'):
                add(obj.get(field), obj.get('description') or obj.get('caption') or '',
                    obj.get('timestamp') or obj.get('datePublished'))
            for value in obj.values():
                walk(value, depth+1)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth+1)

    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        try:
            walk(json.loads(script.string or ''))
        except (ValueError, RecursionError):
            continue
    for anchor in soup.select('a[href]'):
        add(anchor['href'], anchor.get_text(' ', strip=True))
    return sorted(found.values(), key=lambda r: (r['published_at'] or '', r['url']), reverse=True)[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', action='append', help='Public organizer/source page; maximum six; defaults to reviewed organizer seeds')
    args = parser.parse_args()
    if not args.url:
        args.url = ['https://www.saigonoutcast.com/']
    if len(args.url) > 6:
        parser.error('maximum six pages per run')
    now = datetime.now(timezone.utc)
    client = PublicClient()
    report = {'provider_requests': 0, 'published': 0, 'pages': []}
    for url in args.url:
        try:
            soup = client.get(url, {urlsplit(canonical(url)).hostname})
            report['pages'].append({'url': url, 'status': 'complete',
                                   'posts': extract_posts(str(soup), url, now)})
        except (FetchError, ValueError) as exc:
            report['pages'].append({'status': 'failed', 'reason': str(exc)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if any(p['status'] == 'failed' for p in report['pages']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
