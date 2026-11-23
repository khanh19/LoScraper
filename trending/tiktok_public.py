"""Review public TikTok metadata on original videos and reviewed organizer profiles."""
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
MAX_DIRECT_VIDEOS = 6


def video_permalink(url):
    post = original_post_url(url)
    if not post:
        return None
    profile, separator, video_id = post.rpartition('/video/')
    if separator and video_id.isascii() and video_id.isdecimal() and canonical_tiktok_profile(profile):
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


def publication_time(page, url):
    canonical_link = page.select_one('link[rel="canonical"][href]')
    identities = [identity for identity in (
        meta(page, 'og:url'), canonical_link['href'] if canonical_link else '',
    ) if identity]
    if not identities or any(original_post_url(identity) != url for identity in identities):
        return None

    dates = set()
    video_id = urlsplit(url).path.rsplit('/', 1)[-1]
    for entry in structured(page):
        if not is_type(entry, 'VideoObject'):
            continue
        declared = entry.get('url') or entry.get('mainEntityOfPage')
        if isinstance(declared, dict):
            declared = declared.get('@id') or declared.get('url')
        if declared:
            if original_post_url(declared) != url:
                continue
        elif not player_matches(entry.get('embedUrl'), video_id):
            continue
        for field in ('uploadDate', 'datePublished'):
            date = entry.get(field)
            if not isinstance(date, str):
                continue
            try:
                published = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except ValueError:
                continue
            if published.tzinfo is not None:
                dates.add(published.astimezone(timezone.utc))
    return next(iter(dates)) if len(dates) == 1 else None


def review_video(url, client, now):
    try:
        published = publication_time(client.get(url, {HOST}), url)
    except (FetchError, ValueError) as error:
        return {'url': url, 'status': 'public_post_unavailable', 'reason': fetch_failure_reason(error)}
    status = ('publication_time_unverified' if published is None else
              'fresh_needs_venue_review' if now - timedelta(days=7) <= published <= now else
              'outside_fresh_window')
    return {'url': url, 'status': status, 'published_at': published.isoformat() if published else None}


def direct_video_review(url, client, now):
    report = review_video(url, client, now)
    if report.get('published_at'):
        return report

    endpoint = f'https://{HOST}/oembed?' + urlencode({'url': url})
    try:
        embed = client.get(endpoint, {HOST}, json_response=True)
    except (FetchError, ValueError) as error:
        return {**report, 'oembed': fetch_failure_reason(error)}
    profile, _, video_id = url.rpartition('/video/')
    html = embed.get('html') if isinstance(embed, dict) else None
    if isinstance(html, str):
        markup = BeautifulSoup(html, 'html.parser')
        if (embed.get('embed_type') == 'video' and embed.get('embed_product_id') == video_id
                and any(player_matches(frame['src'], video_id) for frame in markup.select('iframe[src]'))):
            return {**report, 'oembed': 'video_id_verified'}
        blocks = markup.select('blockquote[cite][data-video-id]')
        if (canonical_tiktok_profile(embed.get('author_url')) == profile
                and any(video_permalink(b['cite']) == url and b['data-video-id'] == video_id for b in blocks)):
            return {**report, 'oembed': 'identity_verified'}
    return {**report, 'oembed': 'identity_unverified'}


def owned_video_urls(pages, profile_url, now):
    prefix = urlsplit(profile_url).path.rstrip('/') + '/video/'
    urls = {}
    for page in pages:
        candidates = [post['url'] for post in extract_posts(str(page), profile_url, now)]
        candidates.extend(original_post_url(urljoin(profile_url, link['href']))
                          for link in page.select('a[href^="/@"]'))
        for candidate in candidates:
            url = video_permalink(candidate)
            if url and urlsplit(url).hostname == HOST and urlsplit(url).path.startswith(prefix):
                urls[url] = None
    return urls


def review_profile(profile, client, now, browser=False):
    url = profile['url']
    report = {**profile, 'posts': []}
    stage = 'profile_oembed'
    try:
        endpoint = f'https://{HOST}/oembed?' + urlencode({'url': url})
        embed = client.get(endpoint, {HOST}, json_response=True)
        author = embed.get('author_url') if isinstance(embed, dict) else None
        if canonical_tiktok_profile(author) != url:
            return {**report, 'status': 'profile_identity_unverified'}
        html = embed.get('html')
        if not isinstance(html, str):
            return {**report, 'status': 'profile_embed_unavailable'}
        # The supported embed often returns just the profile link. Never run embed scripts.
        stage = 'profile_document'
        profile_page = client.get(url, {HOST})
    except (FetchError, ValueError) as error:
        return {**report, 'status': 'public_profile_unavailable', 'stage': stage,
                'reason': fetch_failure_reason(error)}

    markup = BeautifulSoup(html, 'html.parser')
    post_urls = owned_video_urls([markup, profile_page], url, now)
    if not post_urls and browser:
        try:
            rendered = client.get(url, {HOST}, render=True)
            post_urls = owned_video_urls([rendered], url, now)
        except (FetchError, ValueError) as error:
            return {**report, 'status': 'public_profile_unavailable', 'stage': 'profile_browser',
                    'reason': fetch_failure_reason(error)}
    if not post_urls and browser and markup.select_one('blockquote[data-embed-type="creator"]'):
        creator = markup.select_one('blockquote[data-embed-type="creator"][cite][data-unique-id]')
        if (creator is not None and canonical_tiktok_profile(creator['cite']) == url
                and creator['data-unique-id'] == urlsplit(url).path[2:]):
            try:
                widget = client.render_tiktok_creator(url)
                post_urls = owned_video_urls([widget], url, now)
                report['creator_embed'] = 'original_links_found' if post_urls else 'no_owned_links'
            except (FetchError, ValueError) as error:
                report['creator_embed'] = fetch_failure_reason(error)
        else:
            report['creator_embed'] = 'identity_unverified'
    report['posts'] = [review_video(post_url, client, now) for post_url in islice(post_urls, MAX_POSTS_PER_PROFILE)]
    return {**report, 'status': 'reviewed' if report['posts'] else 'no_original_video_links'}


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
    modes.add_argument('--browser', action='store_true', help='Render the public profile when its initial HTML has no original video links')
    modes.add_argument('--url', action='append', help='Original TikTok video permalink; at most six')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    videos = [video_permalink(url) for url in args.url or []]
    if len(videos) > MAX_DIRECT_VIDEOS or None in videos:
        parser.error(f'provide at most {MAX_DIRECT_VIDEOS} valid original TikTok video URLs')
    client = PublicClient(browser=args.browser)
    try:
        if videos:
            result = {'evaluated_at': now.isoformat(), 'videos': [
                direct_video_review(url, client, now) for url in dict.fromkeys(videos)
            ], 'metered_provider_requests': 0, 'published': 0}
        else:
            result = audit(client, now, args.browser)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
