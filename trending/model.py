from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
CITIES = {"hcmc": "TP. Hồ Chí Minh", "hanoi": "Hà Nội", "danang": "Đà Nẵng"}
CATEGORIES = {"restaurant", "cafe", "bar", "nightlife", "workshop", "culture", "music", "experience"}


def folded(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def canonical(url: str) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("unsafe_url")
    # Keep semantic query parameters; remove tracking only.
    from urllib.parse import parse_qsl, urlencode
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_") and k not in {"fbclid", "gclid"}))
    return urlunsplit(("https", p.hostname.lower(), p.path.rstrip("/") or "/", query, ""))


def parse_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=ICT) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def city_from_address(address: str) -> str | None:
    text = folded(address)
    # These nearby destinations are not the three urban destinations in this feed.
    if re.search(r"\b(hoi an|vung tau|binh duong|nha trang|phu quoc)\b", text) or text == 'hue' or text.endswith(' hue'):
        return None
    aliases = {"hcmc": r"\b(ho chi minh|hcmc|tp hcm|tphcm|sai gon|saigon)\b",
               "hanoi": r"\b(ha noi|hanoi)\b", "danang": r"\b(da nang|danang)\b"}
    matches = [city for city, pattern in aliases.items() if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else None


@dataclass
class Occurrence:
    starts_at: str
    ends_at: str
    precision: str = "time"


@dataclass
class Candidate:
    source_slug: str
    source_name: str
    source_url: str
    title: str
    kind: str
    venue_name: str = ""
    address: str = ""
    city_slug: str | None = None
    category: str = ""
    original_text: str = ""
    published_at: str | None = None
    verified_at: str = ""
    occurrences: list[Occurrence] = field(default_factory=list)
    image_url: str | None = None
    price_text: str | None = None
    image_permitted: bool = False
    location_evidence: str = ""
    status: str = "active"
    reasons: list[str] = field(default_factory=list)
    platform: str = "web"
    owner_key: str = ""
    metrics: dict[str, int] = field(default_factory=dict)

    def validate(self, now: datetime) -> list[str]:
        reasons = list(self.reasons)
        if not self.title.strip() or len(self.title) > 500:
            reasons.append("invalid_title")
        if self.kind not in {"event", "place"}:
            reasons.append("invalid_kind")
        if self.city_slug not in CITIES or city_from_address(self.address) != self.city_slug:
            reasons.append("unverified_city")
        if not self.venue_name.strip() or not self.location_evidence:
            reasons.append("unverified_destination")
        if re.match(r'^\d+[\d\s/-]*\s',self.venue_name) and re.search(r'\b(street|road|duong|pho|ward|district)\b',folded(self.venue_name)):
            reasons.append("address_without_venue_name")
        if self.category not in CATEGORIES:
            reasons.append("irrelevant_category")
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10**15 for v in self.metrics.values()):
            reasons.append("invalid_metrics")
        try:
            self.source_url = canonical(self.source_url)
        except ValueError:
            reasons.append("invalid_source_url")
        if self.location_evidence:
            try:
                canonical(self.location_evidence)
            except ValueError:
                reasons.append('invalid_location_evidence')
        if self.image_permitted and self.image_url:
            try:
                canonical(self.image_url)
            except ValueError:
                self.image_url = None  # Missing/unsafe artwork never prevents publication.
        verified = parse_time(self.verified_at)
        if not verified or not now - timedelta(hours=72) <= verified <= now + timedelta(minutes=5):
            reasons.append("stale_verification")
        if self.status != "active":
            reasons.append(self.status)
        if self.kind == "event":
            valid = []
            for occurrence in self.occurrences:
                start, end = parse_time(occurrence.starts_at), parse_time(occurrence.ends_at)
                if not start or not end or end <= start or occurrence.precision not in {'date','time'}:
                    reasons.append("invalid_occurrence")
                elif start < now + timedelta(days=7) and end > now:
                    valid.append(occurrence)
            if not valid:
                reasons.append("no_upcoming_occurrence")
        elif self.kind == "place":
            published = parse_time(self.published_at)
            if not published or not now - timedelta(days=7) <= published <= now + timedelta(minutes=5):
                reasons.append("no_recent_evidence")
        return sorted(set(reasons))

    def payload(self) -> dict:
        p = asdict(self)
        # Exact destination/title matches only. Never merge branches by name alone.
        identity = [self.kind, self.city_slug or "", folded(self.venue_name), folded(self.address)]
        if self.kind == "event":
            identity.append(folded(self.title))
        p["fingerprint"] = hashlib.sha256("|".join(identity).encode()).hexdigest()
        p["content_hash"] = hashlib.sha256(folded(self.original_text or self.title).encode()).hexdigest()
        p["owner_key"] = self.owner_key or self.source_slug
        p["title_vi"] = self.title if self.kind == "event" else self.venue_name
        noun = "Sự kiện" if self.kind == "event" else "Địa điểm mới được nhắc đến"
        p["description_vi"] = f"{noun} tại {self.venue_name}, {CITIES.get(self.city_slug, '')}. Xem nguồn để biết chi tiết."
        p["original_text"] = self.original_text[:2000]
        # Extraction of an OG URL does not itself grant image reuse permission.
        p["image_url"] = self.image_url if self.image_permitted else None
        return p
