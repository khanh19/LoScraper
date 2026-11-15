"""Optional providers. Fail closed on unknown billing state; never auto-retry submissions."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from datetime import timedelta, timezone
from urllib.parse import urlsplit

import requests

from .model import canonical, city_from_address, folded, parse_time


class ProviderDisabled(Exception):
    pass


def api_json(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(10, 30), allow_redirects=False, **kwargs)
        if response.status_code not in (200, 201, 202):
            raise ProviderDisabled(f"provider_http_{response.status_code}")
        return response.json()
    except (requests.RequestException, ValueError):
        raise ProviderDisabled("provider_unavailable") from None


def serp_allowance(account):
    if not isinstance(account,dict):
        return 0
    # Do not consume prepaid extra credits or silently use an existing paid plan.
    if account.get('account_status') != 'Active' or account.get('plan_monthly_price') != 0:
        return 0
    if str(account.get('plan_id', '')).lower() not in {'free', 'free_plan'}:
        return 0
    value = account.get('plan_searches_left')
    return min(200, value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def bright_allowance(balance, verification, now):
    if not isinstance(balance,dict) or not isinstance(verification,dict):
        return 0
    # Bright Data explicitly has NO API for free allowance or auto-recharge status.
    # Require a recent control-panel receipt; a zero cash balance alone proves neither.
    verified = parse_time(verification.get('verified_at'))
    if not verified or not now - timedelta(hours=24) <= verified <= now:
        return 0
    if verified.astimezone(timezone.utc).strftime('%Y-%m') != now.astimezone(timezone.utc).strftime('%Y-%m'):
        return 0
    if verification.get('unfunded') is not True or verification.get('auto_recharge') is not False:
        return 0
    # A saved card is verification only, per the provider's free-tier contract.
    # A positive balance is acceptable ONLY when fully reconciled to promotional
    # transactions inspected in the dashboard. Never infer this from its amount.
    promo = verification.get('promotional_balance_usd', 0)
    values = [promo] + [balance.get(k) for k in ['balance', 'credit', 'prepayment', 'pending_costs']]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        return 0
    if promo and verification.get('deposits_checked') is not True:
        return 0
    if balance['balance'] != promo or any(balance[k] != 0 for k in ['credit', 'prepayment', 'pending_costs']):
        return 0
    remaining = verification.get('free_credits_remaining')
    return min(4500, remaining) if isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 0 else 0


def bright_preflight(now, request=api_json):
    """Free account reads only; never reserves quota or launches a scraping job."""
    token = os.environ.get('BRIGHTDATA_API_KEY') or os.environ.get('BRIGHT_DATA_API_KEY')
    billing_token = os.environ.get('BRIGHTDATA_BILLING_API_KEY') or token
    if not token:
        raise ProviderDisabled('brightdata_not_configured')
    try:
        balance = request('GET', 'https://api.brightdata.com/customer/balance',
                          headers={'Authorization': 'Bearer ' + billing_token})
    except ProviderDisabled as exc:
        if str(exc) == 'provider_http_403':
            raise ProviderDisabled('brightdata_billing_permission_required') from None
        raise
    try:
        verification = json.loads(os.environ.get('BRIGHTDATA_FREE_VERIFICATION_JSON', '{}'))
    except ValueError:
        raise ProviderDisabled('invalid_free_verification') from None
    remaining = bright_allowance(balance, verification, now)
    if remaining < 1:
        raise ProviderDisabled('brightdata_no_verified_free_allowance')
    # Bind the manually verified dashboard to the actual credentials, including
    # a separate Finance credential if supplied. Unknown identities fail closed.
    account = verification.get('account_id')
    if not isinstance(account, str) or not account.startswith('hl_'):
        raise ProviderDisabled('brightdata_account_verification_required')
    for key in dict.fromkeys([token, billing_token]):
        status = request('GET', 'https://api.brightdata.com/status', headers={'Authorization': 'Bearer ' + key})
        if not isinstance(status, dict) or status.get('customer') != account:
            raise ProviderDisabled('brightdata_account_mismatch')
    return remaining, verification['verified_at']


def post_platform(url):
    try:
        p = urlsplit(canonical(url))
    except ValueError:
        return None
    host = (p.hostname or '').removeprefix('www.')
    if host == 'tiktok.com' and re.fullmatch(r'/@[^/]+/video/\d+', p.path):
        return 'tiktok'
    if host == 'instagram.com' and re.fullmatch(r'/(p|reel)/[A-Za-z0-9_-]+', p.path):
        return 'instagram'
    if host == 'facebook.com' and re.fullmatch(r'/[^/]+/(posts|videos)/(?:[^/]+/)?[^/]+', p.path):
        return 'facebook'
    return None


class SerpDiscovery:
    def __init__(self, store, request=api_json, pilot_id=None):
        self.store, self.request, self.pilot_id = store, request, pilot_id

    def search(self, query, now):
        key = os.environ.get('SERPAPI_API_KEY')
        if not key or not self.store:
            raise ProviderDisabled('serpapi_not_configured')
        job_key = 'serpapi:' + (self.pilot_id or now.date().isoformat()) + ':' + hashlib.sha256(query.encode()).hexdigest()
        old = self.store.job(job_key)
        if old:
            if old['status'] == 'complete':
                return old['input_data'].get('result', [])
            raise ProviderDisabled('serpapi_submission_already_reserved')
        account = self.request('GET', 'https://serpapi.com/account.json', params={'api_key': key})
        remaining = serp_allowance(account)
        job = self.store.reserve('serpapi', job_key, 1, 200, remaining, {'query': query}, now, pilot_id=self.pilot_id) if remaining else None
        if not job or not job['created_now']:
            raise ProviderDisabled('serpapi_no_verified_free_allowance')
        # Mark unknown before sending. A crash/time-out cannot trigger a second paid request.
        self.store.update_job(job_key, 'unknown')
        data = self.request('GET', 'https://serpapi.com/search.json', params={
            'api_key': key, 'engine': 'google', 'q': query, 'hl': 'vi', 'gl': 'vn', 'tbs': 'qdr:w', 'num': 10})
        if not isinstance(data,dict) or data.get('error'):
            raise ProviderDisabled('serpapi_search_failed')
        urls = []
        for result in data.get('organic_results', []):
            if not isinstance(result,dict):
                continue
            try:
                urls.append(canonical(result.get('link', '')))
            except ValueError:
                continue
        self.store.update_job(job_key, 'complete', result=urls)
        return urls


class BrightSocial:
    DATASETS = {'tiktok': 'gd_lu702nij2f790tmv9h', 'instagram': 'gd_lk5ns7kz21pck8jpis', 'facebook':'gd_lyclm1571iy3mv57zw'}

    def __init__(self, store, request=api_json, pilot_id=None):
        self.store, self.request, self.pilot_id = store, request, pilot_id

    def collect(self, url, now):
        platform = post_platform(url)
        token = os.environ.get('BRIGHTDATA_API_KEY') or os.environ.get('BRIGHT_DATA_API_KEY')
        if not platform or not token or not self.store:
            raise ProviderDisabled('brightdata_not_configured')
        headers = {'Authorization': 'Bearer ' + token}
        key = 'brightdata:' + (self.pilot_id or now.date().isoformat()) + ':' + hashlib.sha256(url.encode()).hexdigest()
        job = self.store.pending('brightdata', url) or self.store.job(key)
        if not job and self.pilot_id:
            existing = self.store.pilot_job_for_url('brightdata', url, self.pilot_id)
            if isinstance(existing, dict): job = existing
        if job:
            key = job['job_key']
        if job and job['status'] == 'complete':
            return job['input_data'].get('result', [])
        if not job:
            remaining, verified_at = bright_preflight(now, self.request)
            dataset = ('gd_lyclm20il4r5helnj' if platform == 'instagram' and urlsplit(url).path.startswith('/reel/')
                       else self.DATASETS.get(platform))
            if not dataset:
                raise ProviderDisabled('unsupported_dataset')
            job = self.store.reserve('brightdata', key, 1, 4500, remaining,
                                     {'url': url, 'platform': platform}, now, verified_at=verified_at, pilot_id=self.pilot_id)
            if not job or not job['created_now']:
                raise ProviderDisabled('brightdata_monthly_cap')
            self.store.update_job(key, 'unknown')
            result = self.request('POST', 'https://api.brightdata.com/datasets/v3/trigger', headers=headers,
                params={'dataset_id': dataset, 'format': 'json', 'limit_per_input': 1},
                json=[{'url': url}])
            snapshot = result.get('snapshot_id') if isinstance(result,dict) else None
            if not snapshot or not re.fullmatch(r'sd?_[A-Za-z0-9_-]+', snapshot):
                raise ProviderDisabled('brightdata_unknown_submission')
            self.store.update_job(key, 'submitted', provider_id=snapshot)
            job = self.store.job(key)
        if job['status'] != 'submitted' or not job['provider_job_id']:
            raise ProviderDisabled('brightdata_submission_already_reserved')
        snapshot = job['provider_job_id']
        progress = self.request('GET', f'https://api.brightdata.com/datasets/v3/progress/{snapshot}', headers=headers)
        if not isinstance(progress,dict):
            raise ProviderDisabled('invalid_job_response')
        if progress.get('status') in {'failed','canceled'}:
            self.store.update_job(key, 'failed')
            raise ProviderDisabled('brightdata_job_failed')
        if progress.get('status') != 'ready':
            raise ProviderDisabled('brightdata_job_pending')
        rows = self.request('GET', f'https://api.brightdata.com/datasets/v3/snapshot/{snapshot}', headers=headers, params={'format':'json'})
        if not isinstance(rows, list) or len(rows) > 1 or any(not isinstance(row,dict) for row in rows):
            raise ProviderDisabled('unexpected_result_count')
        # Media references are evidence inputs, NOT downloads or reuse permission.
        fields = {'url','description','content','date_posted','create_time','date','likes','num_comments',
                  'digg_count','share_count','comment_count','profile_url','user_posted','user_url','num_likes','num_shares',
                  'user_profile_url','thumbnail','images','video_url','audio_url','transcript','alt_text'}
        result = [{k:v for k,v in row.items() if k in fields} for row in rows]
        self.store.update_job(key, 'complete', result=result)
        return result


def social_evidence(primary, row, platform, now):
    text = str(row.get('description') or row.get('content') or '')
    # A searched creator's city does not identify a destination. Require a named known venue.
    if not folded(primary.venue_name) or folded(primary.venue_name) not in folded(text):
        return None
    # A campaign roundup naming a museum does not corroborate every event at it.
    if primary.kind == 'event' and folded(primary.title) not in folded(text):
        return None
    # A chain name alone cannot associate a post with this city's destination.
    if city_from_address(text) != primary.city_slug:
        return None
    url = row.get('url', '')
    if post_platform(url) != platform:
        return None
    c = copy.deepcopy(primary)
    c.source_slug, c.source_name, c.source_url = platform, platform.title(), canonical(url)
    c.platform = platform
    c.authority_type = "supporting"
    c.verified_venue_id = ""
    c.original_text = text[:2000]
    c.published_at = row.get('date_posted') or row.get('create_time') or row.get('date')
    published = parse_time(c.published_at)
    if not published or not now - timedelta(days=7) <= published <= now:
        return None
    c.verified_at = now.isoformat()
    c.owner_key = str(row.get('profile_url') or row.get('user_url') or row.get('user_posted') or '')
    if not c.owner_key:
        return None
    values = [row.get(k) for k in ['likes','num_comments','digg_count','share_count','comment_count','num_likes','num_shares']]
    c.metrics = {'engagement': sum(int(v) for v in values if isinstance(v, (int,float)) and 0 <= v <= 10**12)}
    c.image_url, c.image_permitted = None, False
    return c
