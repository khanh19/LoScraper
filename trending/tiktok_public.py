"""Review public TikTok metadata on original posts and reviewed organizer profiles."""
import argparse
from datetime import datetime, timedelta, timezone
from itertools import islice
import json
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .adapters import is_type, meta, structured
from .discover import canonical_tiktok_profile, reviewed_tiktok_profiles
from .http import FetchError, PublicClient, fetch_failure_reason
from .model import CITIES, canonical
from .social_links import extract_posts, original_post_url

HOST = 'www.tiktok.com'
MAX_PROFILES_PER_CITY = 4
MAX_POSTS_PER_PROFILE = 2
MAX_DIRECT_POSTS = 6


def post_permalink(url):
    post = original_post_url(url)
    if not post:
        return None
    profile, kind, post_id = post.rsplit('/', 2)
    if (kind in {'video', 'photo'} and post_id.isascii() and post_id.isdecimal()
            and canonical_tiktok_profile(profile)):
        return post
    return None


def player_matches(url, video_id):
    if not isinstance(url, str):
        return False
    try:
        player = urlsplit(canonical(url))
    except ValueError:
        return False
    return player.hostname == HOST and player.path == '/player/v1/' + video_id


def page_post_data(page, profile, kind, post_id):
    # TikTok's public HTML can omit its canonical tag and JSON-LD while still
    # declaring the original post, author and creation time in page data.
    script = page.select_one('script#__UNIVERSAL_DATA_FOR_REHYDRATION__[type="application/json"]')
    if script is None:
        return None
    try:
        detail = json.loads(script.string or '')['__DEFAULT_SCOPE__']['webapp.video-detail']
        if str(detail['statusCode']) != '0':
            return None
        item = detail['itemInfo']['itemStruct']
        if str(item['id']) != post_id or item['author']['uniqueId'] != profile.rsplit('/@', 1)[1]:
            return None
        media = item.get('imagePost') if kind == 'photo' else item.get('video')
        if not isinstance(media, dict) or not media or (kind == 'video' and item.get('imagePost')):
            return None
        stamp = str(item['createTime'])
        if stamp.isascii() and stamp.isdecimal() and len(stamp) <= 11:
            return datetime.fromtimestamp(int(stamp), timezone.utc), item
    except (KeyError, TypeError, ValueError, OverflowError, OSError, RecursionError):
        return None
    return None


def post_evidence(page, url):
    canonical_link = page.select_one('link[rel="canonical"][href]')
    identities = [identity for identity in (
        meta(page, 'og:url'), canonical_link['href'] if canonical_link else '',
    ) if identity]
    if any(original_post_url(identity) != url for identity in identities):
        return None, {}

    profile, kind, post_id = url.rsplit('/', 2)
    page_date, item = page_post_data(page, profile, kind, post_id) or (None, {})
    if not identities:
        return page_date, item
    dates = {page_date} if page_date is not None else set()
    entry_type, fields = ('VideoObject', ('uploadDate', 'datePublished')) if kind == 'video' else (
        'SocialMediaPosting', ('datePublished',),
    )
    for entry in structured(page):
        if not is_type(entry, entry_type):
            continue
        declared = entry.get('url') or entry.get('mainEntityOfPage')
        if isinstance(declared, dict):
            declared = declared.get('@id') or declared.get('url')
        if declared:
            if original_post_url(declared) != url:
                continue
        elif kind != 'video' or not player_matches(entry.get('embedUrl'), post_id):
            continue
        for field in fields:
            date = entry.get(field)
            if not isinstance(date, str):
                continue
            try:
                published = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except ValueError:
                continue
            if published.tzinfo is not None:
                dates.add(published.astimezone(timezone.utc))
    return (next(iter(dates)), item) if len(dates) == 1 else (None, {})


def publication_time(page, url):
    return post_evidence(page, url)[0]


def review_post(url, client, now):
    try:
        published, item = post_evidence(client.get(url, {HOST}), url)
    except (FetchError, ValueError) as error:
        return {'url': url, 'status': 'public_post_unavailable', 'reason': fetch_failure_reason(error)}
    status = ('publication_time_unverified' if published is None else
              'fresh_needs_venue_review' if now - timedelta(days=7) <= published <= now else
              'outside_fresh_window')
    report = {'url': url, 'status': status, 'published_at': published.isoformat() if published else None}
    stats = item.get('stats')
    if status == 'fresh_needs_venue_review' and isinstance(stats, dict):
        counts = {}
        for key, name in (('playCount', 'views'), ('diggCount', 'likes'),
                          ('commentCount', 'comments'), ('shareCount', 'shares')):
            count = stats.get(key)
            if type(count) is int and count >= 0:
                counts[name] = count
        if counts:
            report['engagement_snapshot'] = {
                **counts, 'source': 'verified_original_tiktok_post',
                'account': item['author']['uniqueId'], 'evaluated_at': now.isoformat(),
            }
    return report


def direct_post_review(url, client, now):
    report = review_post(url, client, now)
    profile, kind, video_id = url.rsplit('/', 2)
    if report.get('published_at') or kind != 'video':
        return report

    endpoint = f'https://{HOST}/oembed?' + urlencode({'url': url})
    try:
        embed = client.get(endpoint, {HOST}, json_response=True)
    except (FetchError, ValueError) as error:
        return {**report, 'oembed': fetch_failure_reason(error)}
    html = embed.get('html') if isinstance(embed, dict) else None
    if isinstance(html, str):
        markup = BeautifulSoup(html, 'html.parser')
        if (embed.get('embed_type') == 'video' and embed.get('embed_product_id') == video_id
                and any(player_matches(frame['src'], video_id) for frame in markup.select('iframe[src]'))):
            return {**report, 'oembed': 'video_id_verified'}
        blocks = markup.select('blockquote[cite][data-video-id]')
        if (canonical_tiktok_profile(embed.get('author_url')) == profile
                and any(post_permalink(b['cite']) == url and b['data-video-id'] == video_id for b in blocks)):
            return {**report, 'oembed': 'identity_verified'}
    return {**report, 'oembed': 'identity_unverified'}


def owned_post_urls(pages, profile_url, now):
    urls = {}
    for page in pages:
        candidates = [post['url'] for post in extract_posts(str(page), profile_url, now)]
        candidates.extend(original_post_url(urljoin(profile_url, link['href']))
                          for link in page.select('a[href^="/@"]'))
        for candidate in candidates:
            url = post_permalink(candidate)
            if url and url.rsplit('/', 2)[0] == profile_url:
                urls[url] = None
    return urls


def review_profile(profile, client, now, browser=False):
    url = profile['url']
    report = {**profile, 'posts': []}
    html = ''
    try:
        endpoint = f'https://{HOST}/oembed?' + urlencode({'url': url})
        embed = client.get(endpoint, {HOST}, json_response=True)
        if not isinstance(embed, dict) or canonical_tiktok_profile(embed.get('author_url')) != url:
            return {**report, 'status': 'profile_identity_unverified'}
        if not isinstance(embed.get('html'), str):
            return {**report, 'status': 'profile_embed_unavailable'}
        html = embed['html']
    except (FetchError, ValueError) as error:
        reason = fetch_failure_reason(error)
        if reason != 'http_400':
            return {**report, 'status': 'public_profile_unavailable', 'stage': 'profile_oembed',
                    'reason': reason}
        # The organizer's website confirmed this account. An oEmbed format
        # rejection can still leave the ordinary public profile available.
        report['profile_oembed'] = reason

    markup = BeautifulSoup(html, 'html.parser')
    try:
        profile_page = client.get(url, {HOST})
    except (FetchError, ValueError) as error:
        return {**report, 'status': 'public_profile_unavailable', 'stage': 'profile_document',
                'reason': fetch_failure_reason(error)}
    post_urls = owned_post_urls([markup, profile_page], url, now)
    if not post_urls and browser:
        try:
            rendered = client.get(url, {HOST}, render=True)
            post_urls = owned_post_urls([rendered], url, now)
        except (FetchError, ValueError) as error:
            return {**report, 'status': 'public_profile_unavailable', 'stage': 'profile_browser',
                    'reason': fetch_failure_reason(error)}
    if not post_urls and browser and markup.select_one('blockquote[data-embed-type="creator"]'):
        creator = markup.select_one('blockquote[data-embed-type="creator"][cite][data-unique-id]')
        if (creator is not None and canonical_tiktok_profile(creator['cite']) == url
                and creator['data-unique-id'] == urlsplit(url).path[2:]):
            try:
                widget = client.render_tiktok_creator(url)
                post_urls = owned_post_urls([widget], url, now)
                report['creator_embed'] = 'original_links_found' if post_urls else 'no_owned_links'
            except (FetchError, ValueError) as error:
                report['creator_embed'] = fetch_failure_reason(error)
        else:
            report['creator_embed'] = 'identity_unverified'
    report['posts'] = [review_post(post_url, client, now) for post_url in islice(post_urls, MAX_POSTS_PER_PROFILE)]
    return {**report, 'status': 'reviewed' if report['posts'] else 'no_original_post_links'}


def audit(client, now, browser=False):
    profiles = {}
    missing = []
    for city in CITIES:
        identities = list(islice(reviewed_tiktok_profiles(city, client), MAX_PROFILES_PER_CITY))
        if not identities:
            missing.append(city)
        for identity in identities:
            url = identity['url']
            profiles.setdefault(url, {key: value for key, value in identity.items() if key != 'city_hint'})
            profiles[url].setdefault('city_hints', []).append(city)
    return {'evaluated_at': now.isoformat(), 'cities_without_reviewed_profile': missing,
            'profiles': [review_profile(profile, client, now, browser) for profile in profiles.values()],
            'metered_provider_requests': 0, 'published': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--browser', action='store_true', help='Render the public profile when its initial HTML has no original post links')
    modes.add_argument('--url', action='append', help='Original TikTok video or photo permalink; at most six')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    posts = [post_permalink(url) for url in args.url or []]
    if len(posts) > MAX_DIRECT_POSTS or None in posts:
        parser.error(f'provide at most {MAX_DIRECT_POSTS} valid original TikTok post URLs')
    client = PublicClient(browser=args.browser)
    try:
        if posts:
            result = {'evaluated_at': now.isoformat(), 'videos': [], 'photos': [],
                      'metered_provider_requests': 0, 'published': 0}
            for url in dict.fromkeys(posts):
                section = 'photos' if url.rsplit('/', 2)[1] == 'photo' else 'videos'
                result[section].append(direct_post_review(url, client, now))
        else:
            result = audit(client, now, args.browser)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
