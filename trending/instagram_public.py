"""Verify day-precision evidence on public Instagram post and reel pages."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import re

from .http import FetchError, PublicClient, fetch_failure_reason
from .model import ICT
from .social_links import lead_identity, original_post_url

HOSTS = {'www.instagram.com', 'instagram.com'}
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
