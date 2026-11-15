"""Vietnam-time schedule policy; emits a GitHub output without contacting providers."""
from datetime import datetime, date, timezone
from .model import ICT

START = date(2026, 12, 1)

def scheduled_mode(now):
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    local = now.astimezone(ICT)
    if local.date() < START:
        return 'disabled'
    return 'full' if local.weekday() in {1, 4} else 'refresh'

if __name__ == '__main__':
    print('mode=' + scheduled_mode(datetime.now(timezone.utc)))
