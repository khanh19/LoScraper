"""Resolve the collection mode and local due time of a GitHub cron trigger."""
import argparse
from datetime import date, datetime, timedelta, timezone

from .model import ICT

START = date(2026, 12, 1)
FULL_CRON = '0 23 * * 1,4'
REFRESH_CRON = '0 23 * * 0,2,3,5,6'
# Weekdays here use the Vietnam calendar and Python's Monday=0 convention.
SLOTS = {
    FULL_CRON: ('full', (1, 4)),
    REFRESH_CRON: ('refresh', (0, 2, 3, 5, 6)),
}


def scheduled_collection(now: datetime, cron: str) -> tuple[str, datetime]:
    if now.utcoffset() is None:
        raise ValueError('timezone_required')
    if cron not in SLOTS:
        raise ValueError('unknown_collection_cron')
    mode, weekdays = SLOTS[cron]
    local = now.astimezone(ICT)
    due = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if due > local:
        due -= timedelta(days=1)
    due -= timedelta(days=min((due.weekday() - day) % 7 for day in weekdays))
    return ('disabled' if due.date() < START else mode), due


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cron', required=True, choices=SLOTS)
    args = parser.parse_args()
    mode, due = scheduled_collection(datetime.now(timezone.utc), args.cron)
    print(f'mode={mode}\ndue={due.isoformat()}')
