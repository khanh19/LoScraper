"""Free discovery of original social posts embedded on public organizer pages.

This reads website HTML only. It never calls a provider or publishes evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .http import PublicClient, FetchError
from .model import canonical, parse_time
from .providers import post_platform


def original_post_url(url):
    if not isinstance(url, str):
        return None
    try:
        url = canonical(url)
    except ValueError:
        return None
    parts = urlsplit(url)
    if parts.hostname in {'instagram.com', 'www.instagram.com'}:
        match = re.fullmatch(r'/(?:[A-Za-z0-9_.]+/)?(p|reel)/([A-Za-z0-9_-]+)(?:/embed(?:/captioned)?)?', parts.path)
        if match:
            kind, shortcode = match.groups()
            return f'https://www.instagram.com/{kind}/{shortcode}'
    platform = post_platform(url)
    if platform == 'tiktok':
        return 'https://www.tiktok.com' + parts.path
    return url if platform else None


def lead_identity(url):
    platform = post_platform(url)
    if platform in {'instagram', 'tiktok'}:
        return platform, urlsplit(url).path.rsplit('/', 1)[-1]
    return platform, url


def remember_lead(leads, row):
    identity = lead_identity(row['url'])
    previous = leads.get(identity)
    if not previous:
        leads[identity] = row
        return
    chosen = row if row['published_at'] and not previous['published_at'] else previous
    if row['platform'] == 'instagram':
        reel = next((r['url'] for r in (previous, row) if '/reel/' in urlsplit(r['url']).path), None)
        if reel:
            chosen = {**chosen, 'url': reel}
    leads[identity] = chosen


def extract_posts(html, source_url, now, limit=30):
    source_url = canonical(source_url)
    found = {}
    excluded = set()

    def add(url, text='', timestamp=None):
        url = original_post_url(url)
        if not url:
            return
        identity = lead_identity(url)
        date = parse_time(timestamp)
        if timestamp and (not date or not now - timedelta(days=7) <= date <= now):
            excluded.add(identity)
            found.pop(identity, None)
            return
        if identity in excluded:
            return
        row = {'url': url, 'platform': post_platform(url), 'discovered_on': source_url,
               'text': str(text)[:2000], 'published_at': date.isoformat() if date else None,
               'requires_provider_validation': True}
        remember_lead(found, row)

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
    for block in soup.select('blockquote.instagram-media[data-instgrm-permalink]'):
        url = original_post_url(block['data-instgrm-permalink'])
        if url and post_platform(url) == 'instagram':
            add(url, block.get_text(' ', strip=True))
    for block in soup.select('blockquote.tiktok-embed[cite][data-video-id]'):
        url = original_post_url(block['cite'])
        if url and lead_identity(url) == ('tiktok', block['data-video-id']):
            add(url, block.get_text(' ', strip=True))
    for frame in soup.select('iframe[src]'):
        url = original_post_url(frame['src'])
        if url and post_platform(url) == 'instagram':
            add(url)
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
