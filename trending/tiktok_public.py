"""Review public TikTok metadata linked from reviewed organizers' sites."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from .adapters import is_type, meta, structured
from .discover import reviewed_tiktok_profile
from .http import FetchError, PublicClient, fetch_failure_reason
from .model import CITIES, canonical
from .social_links import extract_posts, original_post_url

HOST = 'www.tiktok.com'
MAX_POSTS_PER_PROFILE = 2


def publication_time(page, url):
    canonical_link = page.select_one('link[rel="canonical"][href]')
    identities = [identity for identity in (
        meta(page, 'og:url'), canonical_link['href'] if canonical_link else '',
    ) if identity]
    if not identities or any(original_post_url(identity) != url for identity in identities):
        return None

    dates = set()
    player_path = '/player/v1/' + urlsplit(url).path.rsplit('/', 1)[-1]
    for entry in structured(page):
        if not is_type(entry, 'VideoObject'):
            continue
        declared = entry.get('url') or entry.get('mainEntityOfPage')
        if isinstance(declared, dict):
            declared = declared.get('@id') or declared.get('url')
        if declared:
            if original_post_url(declared) != url:
                continue
        else:
            embed = entry.get('embedUrl')
            if not isinstance(embed, str):
                continue
            try:
                player = urlsplit(canonical(embed))
            except ValueError:
                continue
            if player.hostname != HOST or player.path != player_path:
                continue
        date = entry.get('uploadDate') or entry.get('datePublished')
        if not isinstance(date, str):
            continue
        try:
            published = datetime.fromisoformat(date.replace('Z', '+00:00'))
        except ValueError:
            continue
        if published.tzinfo is not None:
            dates.add(published.astimezone(timezone.utc))
    return next(iter(dates)) if len(dates) == 1 else None


def owned_video_urls(pages, profile_url, now):
    prefix = urlsplit(profile_url).path.rstrip('/') + '/video/'
    return dict.fromkeys(
        post['url'] for page in pages for post in extract_posts(str(page), profile_url, now)
        if post['platform'] == 'tiktok' and urlsplit(post['url']).path.startswith(prefix)
    )


def review_profile(profile, client, now, browser=False):
    url = profile['url']
    report = {**profile, 'posts': []}
    stage = 'profile_oembed'
    try:
        endpoint = f'https://{HOST}/oembed?' + urlencode({'url': url})
        embed = client.get(endpoint, {HOST}, json_response=True)
        author = embed.get('author_url') if isinstance(embed, dict) else None
        if not isinstance(author, str) or author.rstrip('/') != url.rstrip('/'):
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

    post_urls = owned_video_urls([BeautifulSoup(html, 'html.parser'), profile_page], url, now)
    if not post_urls and browser:
        try:
            rendered = client.get(url, {HOST}, render=True)
            post_urls = owned_video_urls([rendered], url, now)
        except (FetchError, ValueError) as error:
            return {**report, 'status': 'public_profile_unavailable', 'stage': 'profile_browser',
                    'reason': fetch_failure_reason(error)}
    for post_url in list(post_urls)[:MAX_POSTS_PER_PROFILE]:
        try:
            published = publication_time(client.get(post_url, {HOST}), post_url)
            status = ('publication_time_unverified' if published is None else
                      'fresh_needs_venue_review' if now - timedelta(days=7) <= published <= now else
                      'outside_fresh_window')
            report['posts'].append({'url': post_url, 'status': status,
                                    'published_at': published.isoformat() if published else None})
        except (FetchError, ValueError) as error:
            report['posts'].append({'url': post_url, 'status': 'public_post_unavailable',
                                    'reason': fetch_failure_reason(error)})
    return {**report, 'status': 'reviewed' if report['posts'] else 'no_original_video_links'}


def audit(client, now, browser=False):
    profiles = {}
    missing = []
    for city in CITIES:
        identity = reviewed_tiktok_profile(city, client)
        if identity is None:
            missing.append(city)
            continue
        url = identity['url']
        profiles.setdefault(url, {key: value for key, value in identity.items() if key != 'city_hint'})
        profiles[url].setdefault('city_hints', []).append(city)
    return {'evaluated_at': now.isoformat(), 'cities_without_reviewed_profile': missing,
            'profiles': [review_profile(profile, client, now, browser) for profile in profiles.values()],
            'metered_provider_requests': 0, 'published': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Render the public profile when its initial HTML has no original video links')
    args = parser.parse_args()
    client = PublicClient(browser=args.browser)
    try:
        result = audit(client, datetime.now(timezone.utc), args.browser)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
