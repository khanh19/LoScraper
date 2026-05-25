#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate

args=()
if [[ $# -gt 0 && "$1" != --* ]]; then
  args=(--city "$1")
  shift
fi

python lo_scrape_club_trending_events.py "${args[@]}" "$@"