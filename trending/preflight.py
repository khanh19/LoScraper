"""Read-only Bright Data check: python -m trending.preflight --env-file PATH."""
import argparse
from datetime import datetime, timezone
import json

from .__main__ import load_env_files
from .providers import ProviderDisabled, bright_preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', action='append', default=[])
    args = parser.parse_args()
    load_env_files(args.env_file)
    try:
        remaining, verified_at = bright_preflight(datetime.now(timezone.utc))
    except ProviderDisabled as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc), 'scraping_started': False}))
        return 1
    print(json.dumps({'status': 'account_checks_passed', 'verified_at': verified_at,
                      'allowance_before_local_reservations': remaining,
                      'monthly_cap': 4500, 'scraping_started': False,
                      'note': 'Collection still requires a persistent quota reservation and a validated source.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
