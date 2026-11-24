"""Free discovery of original social posts embedded on public organizer pages.

This reads website HTML only. It never calls a provider or publishes evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlsplit
from bs4 import BeautifulSoup
from .http import PublicClient, FetchError, fetch_failure_reason
from .model import canonical, parse_time
from .providers import post_platform

TIKTOK_MAIN_HOSTS = {'tiktok.com', 'www.tiktok.com'}
TIKTOK_SHORT_HOSTS = {'vm.tiktok.com', 'vt.tiktok.com'}
MAX_SHARE_LINKS = 3
FLIGHT_ROW_ID = re.compile(rb'[0-9a-f]+:')
FLIGHT_ROW_LENGTH = re.compile(rb'[0-9a-f]{1,16},')
FLIGHT_LENGTH_TAGS = b'TAOoUSsLlGgMmV'


def tiktok_share_url(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(canonical(url))
    except ValueError:
        return None
    if any(value.lower() == 'tiktokshop' for value in parse_qs(parts.query).get('page', [])):
        return None
    if parts.hostname in TIKTOK_SHORT_HOSTS:
        path = r'/[A-Za-z0-9_-]{1,64}'
    elif parts.hostname in TIKTOK_MAIN_HOSTS:
        path = r'/t/[A-Za-z0-9_-]{1,64}'
    else:
        return None
    if re.fullmatch(path, parts.path):
        return f'https://{parts.hostname}{parts.path}/'
    return None


class TikTokShareResolver:
    def __init__(self, client):
        self.client = client
        self.results = {}

    def resolve(self, url):
        share = tiktok_share_url(url)
        if not share:
            return None
        if share in self.results:
            return self.results[share].get('post_url')
        if len(self.results) >= MAX_SHARE_LINKS:
            return None
        try:
            target = share
            for _ in range(2):
                target = self.client.get(target, TIKTOK_MAIN_HOSTS | TIKTOK_SHORT_HOSTS, redirect_only=True)
                post = original_post_url(target)
                if post and post_platform(post) == 'tiktok':
                    self.results[share] = {'post_url': post, 'status': 'original_post_found'}
                    return post
                target = tiktok_share_url(target)
                if not target or target == share:
                    break
            status = 'no_original_post'
        except (FetchError, ValueError) as error:
            status = fetch_failure_reason(error)
        self.results[share] = {'status': status}
        return None


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
    published = parse_time(row['published_at'])
    previous_published = parse_time(previous['published_at'])
    corroborated_profile = (row.get('publication_evidence') == 'verified_profile_embed'
                            and previous.get('publication_evidence') != 'verified_profile_embed'
                            and published == previous_published)
    # When the dates agree, retain the source whose post attribution was
    # checked. The original website link remains in the page discovery report.
    chosen = row if published and (not previous_published or corroborated_profile) else previous
    if row['platform'] == 'instagram':
        reel = next((r['url'] for r in (previous, row) if '/reel/' in urlsplit(r['url']).path), None)
        if reel:
            chosen = {**chosen, 'url': reel}
    leads[identity] = chosen


def inline_records(soup):
    flight_prefix = 'self.__next_f.push('
    chunks = []
    for script in soup.find_all('script'):
        content = (script.string or '').strip().removesuffix(';')
        streamed = content.startswith(flight_prefix) and content.endswith(')')
        try:
            record = json.loads(content[len(flight_prefix):-1] if streamed else content)
        except (ValueError, RecursionError):
            continue
        if not streamed:
            yield record
        elif (isinstance(record, list) and len(record) == 2
              and record[0] == 1 and isinstance(record[1], str)):
            chunks.append(record[1])

    # These literal chunks can split a row. Text frames use a UTF-8 byte
    # length instead of a newline and can contain text that resembles a row.
    stream = ''.join(chunks).encode('utf-8', errors='surrogatepass')
    offset = 0
    while offset < len(stream):
        header = FLIGHT_ROW_ID.match(stream, offset)
        if header and header.end() < len(stream) and stream[header.end()] in FLIGHT_LENGTH_TAGS:
            length = FLIGHT_ROW_LENGTH.match(stream, header.end() + 1)
            if not length:
                return
            offset = length.end() + int(length.group()[:-1], 16)
            if offset > len(stream):
                return
            continue
        newline = stream.find(b'\n', offset)
        end = len(stream) if newline == -1 else newline
        payload = stream[header.end():end] if header else b''
        offset = end + 1
        if payload.startswith((b'{', b'[')):
            try:
                yield json.loads(payload)
            except (ValueError, RecursionError):
                continue


def extract_posts(html, source_url, now, limit=30, resolve_share=None):
    source_url = canonical(source_url)
    found = {}
    excluded = set()

    def add(url, text='', timestamp=None):
        url = original_post_url(url) or (resolve_share(url) if resolve_share else None)
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
    for record in inline_records(soup):
        walk(record)
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
    resolver = TikTokShareResolver(client)
    report = {'provider_requests': 0, 'published': 0, 'pages': []}
    for url in args.url:
        try:
            soup = client.get(url, {urlsplit(canonical(url)).hostname})
            report['pages'].append({'url': url, 'status': 'complete',
                                   'posts': extract_posts(str(soup), url, now, resolve_share=resolver.resolve)})
        except (FetchError, ValueError) as exc:
            report['pages'].append({'status': 'failed', 'reason': str(exc)})
    report['tiktok_share_links'] = resolver.results
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if any(p['status'] == 'failed' for p in report['pages']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
