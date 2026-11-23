"""Review public Instagram post previews and recent posts from public profile embeds."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit

from .http import FetchError, PublicClient, fetch_failure_reason
from .model import ICT
from .social_links import lead_identity, original_post_url

HOSTS = {'www.instagram.com', 'instagram.com'}
PROFILE_CALL = re.compile(r'\b\w+\.handle\(\s*(?=\{)')
PROFILE_MODULE = re.compile(r'PolarisEmbedSimple(?:@[0-9a-f]{32})?')
HANDLE = re.compile(r'[A-Za-z0-9_.]{1,30}')
SHORTCODE = re.compile(r'[A-Za-z0-9_-]{1,32}')
COUNT = r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)'
PREVIEW = re.compile(
    rf'^(?P<likes>{COUNT}) likes?, (?P<comments>{COUNT}) comments? - '
    r'(?P<owner>[A-Za-z0-9_.]{1,30}) (?:on|trên) '
    r'(?P<day>[A-Za-z]+ [0-9]{1,2}, [0-9]{4}):',
    re.IGNORECASE,
)


def instagram_url(url):
    post = original_post_url(url)
    return post if post and lead_identity(post)[0] == 'instagram' else None


def instagram_profile(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc.lower() not in HOSTS:
            return None
    except ValueError:
        return None
    handle = parts.path.strip('/')
    if HANDLE.fullmatch(handle) and handle.lower() not in {'p', 'reel', 'reels', 'explore', 'accounts'}:
        return 'https://www.instagram.com/' + handle.lower() + '/'
    return None


def profile_contexts(page):
    decoder = json.JSONDecoder()
    for script in page.find_all('script'):
        raw = str(script.string or '')
        if 'PolarisEmbedSimple' not in raw or 'contextJSON' not in raw:
            continue
        for match in PROFILE_CALL.finditer(raw):
            try:
                payload, end = decoder.raw_decode(raw, match.end())
                if not raw[end:].lstrip().startswith(')') or not isinstance(payload, dict):
                    continue
                require = payload.get('require')
                if not isinstance(require, list):
                    continue
                for entry in require:
                    if extracted := embed_context(entry):
                        yield extracted
            except (ValueError, RecursionError):
                continue


def embed_context(entry):
    if not (isinstance(entry, list) and len(entry) == 4 and isinstance(entry[0], str)
            and PROFILE_MODULE.fullmatch(entry[0]) and entry[1] == 'init'
            and isinstance(entry[3], list) and len(entry[3]) == 1):
        return None
    config = entry[3][0]
    if not (isinstance(config, dict) and config.get('isProfileEmbed') is True
            and isinstance(config.get('contextJSON'), str)):
        return None
    document = json.loads(config['contextJSON'])
    context = document.get('context') if isinstance(document, dict) else None
    return context if isinstance(context, dict) and context.get('type') == 'Profile' else None


def profile_post(media, handle, owner_id, now):
    if not isinstance(media, dict):
        return None
    owner = media.get('owner')
    shortcode = media.get('shortcode')
    stamp = media.get('taken_at_timestamp')
    if not (isinstance(owner, dict) and str(owner.get('id')) == owner_id
            and str(owner.get('username', '')).lower() == handle
            and owner.get('is_private') is False and owner.get('is_unpublished') is False
            and isinstance(shortcode, str) and SHORTCODE.fullmatch(shortcode)
            and type(stamp) is int and (now - timedelta(days=7)).timestamp() <= stamp <= now.timestamp()):
        return None
    published = datetime.fromtimestamp(stamp, timezone.utc)
    captions = media.get('edge_media_to_caption')
    edges = captions.get('edges') if isinstance(captions, dict) else None
    caption = ''
    if isinstance(edges, list) and edges and isinstance(edges[0], dict):
        node = edges[0].get('node')
        if isinstance(node, dict) and isinstance(node.get('text'), str):
            caption = node['text'][:2000]
    kind = 'reel' if media.get('is_video') is True else 'p'
    post = {'url': f'https://www.instagram.com/{kind}/{shortcode}', 'published_at': published.isoformat(),
            'status': 'fresh_needs_venue_review', 'account': handle, 'caption': caption}
    for field, key in (('likes', 'edge_liked_by'), ('comments', 'edge_media_to_comment')):
        metric = media.get(key)
        count = metric.get('count') if isinstance(metric, dict) else None
        if type(count) is int and count >= 0 and (field != 'likes' or media.get('like_and_view_counts_disabled') is False):
            post[field] = count
    return post


def review_profile(profile, client, now):
    url = instagram_profile(profile['url'])
    if not url:
        raise ValueError('invalid_instagram_profile')
    handle = urlsplit(url).path.strip('/')
    embed = url + 'embed/'
    report = {**profile, 'url': url, 'embed_url': embed, 'posts': []}
    try:
        page = client.get(embed, HOSTS)
    except (FetchError, ValueError) as error:
        return {**report, 'status': 'public_profile_unavailable', 'reason': fetch_failure_reason(error)}
    contexts = list(profile_contexts(page))
    if not contexts:
        return {**report, 'status': 'public_profile_metadata_missing'}
    if len(contexts) != 1:
        return {**report, 'status': 'profile_metadata_conflict'}
    context, = contexts
    owner_id = str(context.get('owner_id', ''))
    entries = context.get('graphql_media')
    if not (str(context.get('username', '')).lower() == handle and owner_id.isdecimal()
            and instagram_profile(context.get('profile_link')) == url and isinstance(entries, list)):
        return {**report, 'status': 'profile_identity_unverified'}
    posts = {}
    conflicting = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if post := profile_post(entry.get('shortcode_media'), handle, owner_id, now):
            identity = lead_identity(post['url'])
            if identity in posts and posts[identity] != post:
                conflicting.add(identity)
            posts[identity] = post
    recent = sorted((p for key, p in posts.items() if key not in conflicting),
                    key=lambda p: (p['published_at'], p['url']), reverse=True)
    return {**report, 'posts': recent[:6], 'conflicting_posts': len(conflicting),
            'status': 'reviewed' if recent else 'no_fresh_original_posts'}


def review(url, client, now):
    post = instagram_url(url)
    if not post:
        raise ValueError('invalid_instagram_permalink')
    report = {'url': post, 'publication_day': None}
    try:
        page = client.get(post + '/', HOSTS)
    except (FetchError, ValueError) as error:
        return {**report, 'status': 'public_post_unavailable', 'reason': fetch_failure_reason(error)}

    identities = [
        entry.get('href') or entry.get('content')
        for entry in page.select('head link[rel="canonical"], head meta[property="og:url"]')
    ]
    if not identities or any(
        (original := instagram_url(identity)) is None or lead_identity(original) != lead_identity(post)
        for identity in identities
    ):
        return {**report, 'status': 'post_identity_unverified'}

    previews = set()
    for tag in page.select('head meta[name="description"], head meta[property="og:description"]'):
        match = PREVIEW.match(tag.get('content', '').strip())
        if not match:
            continue
        try:
            day = datetime.strptime(match['day'], '%B %d, %Y').date()
            likes = int(match['likes'].replace(',', ''))
            comments = int(match['comments'].replace(',', ''))
        except ValueError:
            continue
        previews.add((day, match['owner'].lower(), likes, comments))
    if not previews:
        return {**report, 'status': 'public_metadata_missing'}
    if len(previews) != 1:
        return {**report, 'status': 'public_metadata_conflict'}

    day, owner, likes, comments = previews.pop()
    today = now.astimezone(ICT).date()
    # Public descriptions supply a calendar day without a clock or timezone.
    # Keep this as review evidence. Do not synthesize a publication instant.
    status = ('recent_day_needs_venue_review' if today - timedelta(days=6) <= day <= today
              else 'outside_review_window')
    return {**report, 'status': status, 'publication_day': day.isoformat(),
            'account': owner, 'likes': likes, 'comments': comments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', action='append', required=True, help='Public Instagram post/reel permalink; at most six')
    args = parser.parse_args()
    urls = [instagram_url(url) for url in args.url]
    if len(urls) > 6 or None in urls:
        parser.error('provide at most six valid Instagram post or reel URLs')
    posts = {lead_identity(post): post for post in urls}
    now = datetime.now(timezone.utc)
    client = PublicClient()
    try:
        reviews = [review(url, client, now) for url in posts.values()]
    finally:
        client.close()
    print(json.dumps({'evaluated_at': now.isoformat(), 'posts': reviews,
                      'metered_provider_requests': 0, 'published': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
