"""Conservative schedule parsing. Publication dates never become event dates."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from .model import ICT, Occurrence, folded, parse_time

MONTHS = {name.lower(): i for i, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def plain(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower().replace('đ', 'd')) if not unicodedata.combining(c)).replace('–', '-').replace('—', '-')


def schedule_occurrences(text: str, now: datetime) -> list[Occurrence]:
    """Parse a publisher's schedule block, never a whole page with related articles."""
    text = plain(text)
    text = re.sub(r'(?<=\d)\.(?=\d)', '/', text)
    for month, number in MONTHS.items():
        text = re.sub(rf'\b{month}\b', f'/{number}/', text)
    range_match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\s*(?:-|den|to|until)\s*(\d{1,2})/(\d{1,2})/(20\d{2})', text)
    if range_match:
        ad, am, ay, bd, bm, by = range_match.groups()
        try:
            a = datetime(int(ay or by), int(am), int(ad), tzinfo=ICT)
            b = datetime(int(by), int(bm), int(bd), tzinfo=ICT)
        except ValueError:
            return []
        if b < a or (b - a).days > 366:
            return []
        recurring = weekly(text, now)
        if recurring:
            hours = re.search(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', text)
            result = []
            for o in recurring:
                day = parse_time(o.starts_at)
                if not a <= day <= b:
                    continue
                if hours:
                    ah, amin, bh, bmin = map(int, hours.groups())
                    try:
                        start = day.replace(hour=ah, minute=amin)
                        end = day.replace(hour=bh, minute=bmin)
                    except ValueError:
                        return []
                    if end <= start:
                        end += timedelta(days=1)
                    result.append(Occurrence(start.isoformat(), end.isoformat()))
                else:
                    result.append(o)
            return result
        return [Occurrence(a.isoformat(), (b + timedelta(days=1)).isoformat(), 'date')]
    # Incomplete range must not degrade into its end date as a single event.
    if re.search(r'\d{1,2}/\d{1,2}\s*-', text):
        return []
    values = []
    for d, m, y in re.findall(r'(\d{1,2})\s*(?:/|\.|thang)\s*(\d{1,2})\s*(?:/|\.|,?\s*nam\s*|,?\s+)\s*(20\d{2})', text):
        try:
            start = datetime(int(y), int(m), int(d), tzinfo=ICT)
            hours = re.search(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})',text)
            if hours:
                ah, amin, bh, bmin = map(int,hours.groups())
                a,b=start.replace(hour=ah,minute=amin),start.replace(hour=bh,minute=bmin)
                if b<=a:
                    b+=timedelta(days=1)
                values.append(Occurrence(a.isoformat(),b.isoformat()))
            else:
                values.append(Occurrence(start.isoformat(), (start + timedelta(days=1)).isoformat(), 'date'))
        except ValueError:
            continue
    return list({o.starts_at: o for o in values}.values())


def iso_occurrence(start: str, end: str | None = None) -> Occurrence | None:
    a, b = parse_time(start), parse_time(end)
    if not a:
        return None
    precision = "date" if len(start) == 10 else "time"
    # When the publisher gives only a start, keep the day's precision, not a made-up duration.
    if not b:
        b = (a.astimezone(ICT) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        precision = "date"
    elif end and len(end) == 10:
        b += timedelta(days=1)
    if b <= a:
        return None
    return Occurrence(a.isoformat(), b.isoformat(), precision)


def ticketbox_sessions(text: str) -> list[Occurrence]:
    # The hero and Event JSON-LD aggregate ALL sessions. Only use “Lịch diễn”.
    section = text.split("Lịch diễn", 1)[-1] if "Lịch diễn" in text else ""
    section = section.split("Ban tổ chức", 1)[0]
    pattern = r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2}),?\s*(\d{1,2})\s+Tháng\s+(\d{1,2}),?\s+(\d{4})"
    results = []
    for match in re.finditer(pattern, section, re.I):
        ah, am, bh, bm, day, month, year = map(int, match.groups())
        try:
            a = datetime(year, month, day, ah, am, tzinfo=ICT)
            b = datetime(year, month, day, bh, bm, tzinfo=ICT)
            if b <= a:
                b += timedelta(days=1)
            results.append(Occurrence(a.isoformat(), b.isoformat()))
        except ValueError:
            continue
    return list({o.starts_at: o for o in results}.values())


def weekly(schedule: str, now: datetime) -> list[Occurrence]:
    """Used only for an explicit recurring schedule on a live venue/event page."""
    text = folded(schedule)
    if not re.search(r"every|hang (tuan|ngay)|thu|daily|monday|tuesday|wednesday|thursday|friday|saturday|sunday", text):
        return []
    weekdays = [r"monday|thu 2|thu hai", r"tuesday|thu 3|thu ba", r"wednesday|thu 4|thu tu",
                r"thursday|thu 5|thu nam", r"friday|thu 6|thu sau", r"saturday|thu 7|thu bay", r"sunday|chu nhat"]
    days = [i for i, p in enumerate(weekdays) if re.search(rf"\b({p})\b", text)]
    if re.search(r"daily|every day|hang ngay", text):
        days = list(range(7))
    if len(days) == 2 and (re.search(r"\b(to|through|den)\b", text) or re.search(r'(?:thu\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*-\s*(?:thu|chu nhat|monday|tuesday|wednesday|thursday|friday|saturday|sunday)', plain(schedule))):
        ordered = sorted(days,key=lambda i: re.search(rf'\b({weekdays[i]})\b',text).start())
        first,last=ordered
        days=[(first+i)%7 for i in range((last-first)%7+1)]
    base = now.astimezone(ICT).replace(hour=0, minute=0, second=0, microsecond=0)
    return [Occurrence((base + timedelta(days=i)).isoformat(), (base + timedelta(days=i+1)).isoformat(), "date")
            for i in range(8) if (base + timedelta(days=i)).weekday() in days]
