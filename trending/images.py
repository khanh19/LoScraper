"""Explicit, reviewable image permissions; accessible URLs are never permission."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from .model import canonical, parse_time


def permissions(now):
    rows=json.loads(Path(__file__).with_name('image_permissions.json').read_text())
    for p in rows:
        if p['scope'] not in {'asset','publisher'} or not p['id'] or not p['creator'] or not p.get('license_name'):
            raise ValueError('invalid_image_permission')
        for key in ('license_url','evidence_url'):
            canonical(p[key])
        reviewed=parse_time(p['reviewed_at'])
        if not reviewed or reviewed>now:raise ValueError('invalid_permission_review_date')
        if p['scope']=='asset':canonical(p['image_url'])
        elif not p.get('asset_host'):raise ValueError('missing_asset_host')
    return rows


def authorize(c,now,records=None):
    c.image_permission=None
    c.image_permitted=False
    if not c.image_url or not c.image_association_verified:return
    for p in permissions(now) if records is None else records:
        if p.get('revoked') or p.get('source_slug')!=c.source_slug:continue
        reviewed=parse_time(p.get('reviewed_at'))
        if not reviewed or reviewed>now:continue
        matches=(p['scope']=='asset' and p.get('image_url')==c.image_url) or (
            p['scope']=='publisher' and p.get('asset_host')==urlsplit(c.image_url).hostname)
        if matches:
            c.image_permission=dict(p)
            c.image_permitted=True
            return
