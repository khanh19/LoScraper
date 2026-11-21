"""Provider metric normalization and popularity triage, never publication approval.

Thresholds are explicit retrieval heuristics, not a scientific definition of viral.
Missing/hidden metrics stay unknown; plays and views remain separate measurements.
"""
import math
from datetime import timedelta


def in_review_window(row, now, days=35):
    """Discovery review window only; does not change seven-day feed eligibility."""
    from .model import parse_time
    try:
        published = parse_time(row.get('timestamp') or row.get('date_posted'))
    except (ValueError, TypeError):
        return False
    return bool(published and now - timedelta(days=days) <= published <= now)

FIELDS = {
    'likes': ('digg_count', 'diggCount', 'likesCount', 'likes'),
    'comments': ('comment_count', 'commentCount', 'commentsCount'),
    'shares': ('share_count', 'shareCount', 'sharesCount'),
    'saves': ('collect_count', 'collectCount', 'savesCount'),
    'plays': ('play_count', 'playCount', 'videoPlayCount'),
    'views': ('videoViewCount', 'views'),
}


def metrics(row):
    result = {}
    for name, aliases in FIELDS.items():
        result[name] = next((row[k] for k in aliases if k in row
                            and type(row[k]) in (int, float)
                            and math.isfinite(row[k]) and row[k] >= 0), None)
    return result


def assess(row):
    counts = metrics(row)
    # Do not sum views and plays: they can describe the same viewing activity.
    reach = max((counts[k] for k in ('plays', 'views') if counts[k] is not None), default=0)
    reasons = []
    if (counts['likes'] or 0) >= 1000:
        reasons.append('at_least_1000_likes')
    if reach >= 50000:
        reasons.append('at_least_50000_views_or_plays')
    if (counts['shares'] or 0) >= 100 or (counts['saves'] or 0) >= 100:
        reasons.append('at_least_100_shares_or_saves')
    return {'counts': counts, 'popularity_candidate': bool(reasons), 'reasons': reasons,
            'viral_status': 'unverified', 'growth_status': 'requires_repeat_observations',
            'comment_content_status': 'requires_separate_review', 'publishable': False}


def instagram_record(row, fetched_at):
    """Adapt an API post without treating comments as authoritative venue facts.

    Preserve only bounded comment text/timestamps, not commenter profiles or
    signed media URLs. A provider's latestComments sample is not a census.
    """
    from .providers import post_platform
    url = row.get('url', '')
    if post_platform(url) != 'instagram':
        raise ValueError('instagram_post_url_required')
    c = metrics(row)
    comments = row.get('latestComments')
    samples = [{'text': v['text'][:1000], 'published_at': v.get('timestamp')}
               for v in (comments if isinstance(comments, list) else [])[:20]
               if isinstance(v, dict) and isinstance(v.get('text'), str)]
    return {'url': url, 'platform': 'instagram',
            'description': str(row.get('caption') or '')[:12000],
            'date_posted': row.get('timestamp'),
            '_source_verified_at': fetched_at,
            'profile_url': 'https://www.instagram.com/' + str(row.get('ownerUsername') or ''),
            'digg_count': c['likes'], 'comment_count': c['comments'],
            'share_count': c['shares'], 'collect_count': c['saves'],
            'play_count': c['plays'], 'videoViewCount': c['views'],
            'comment_samples': samples, 'comment_sample_scope': 'provider_sample_not_all_comments',
            'format': row.get('type'), 'is_sponsored': row.get('isSponsored')}


def priority(row):
    """Use only within a platform, after relevance/location triage."""
    evidence = assess(row)
    c = evidence['counts']
    return (not evidence['popularity_candidate'], -(c['likes'] or 0),
            -(c['comments'] or 0), -(c['shares'] or 0), -(c['saves'] or 0))
