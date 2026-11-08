# LoScraper

Collects source-verified local events and places for Lô’s **What’s Trending** feed in HCMC, Hanoi, and Da Nang. Python website adapters feed PostgreSQL; Encore serves the feed; the Expo app renders it.

- **[Teammate setup, step by step](docs/teammate-setup.md)** — clone all three repositories, create an isolated database, collect without provider keys, start the app, and test.
- **[Tool and provider status](docs/tool-status.md)** — implemented, passed, failed, and blocked paths, with next steps.
- **[Pipeline, workflow diagram, and validation evidence](docs/trending.md)** — validation rules, quota controls, and future rollout.

## Quick read-only website check

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending --browser --pilot --limit 5
```

Requires installed Chrome. This does not import records or use optional providers. HTTP-only collection can omit `--browser`; browser-dependent sources will be skipped. Follow the teammate guide for the complete preview.

## Current delivery state

Six website adapters and the local database/API/UI path passed a bounded pilot. Social publication is disabled after an unsuccessful quality pilot. Live Google search remains blocked until its free allowance is verified. Apify is an alternative, not an integrated fallback. No additional spending, production deployment, or scheduled collection is enabled. See the dated status matrix rather than treating old sample counts as permanent fixtures.

The new workflow is `.github/workflows/trending.yml`. It has a planned 06:00 Vietnam daily trigger guarded by `TRENDING_SCHEDULE_ENABLED`; leave that variable unset/false during onboarding. Manual dispatch requires the workflow on the default branch, which remains a rollout dependency.

## Legacy nightlife importer

`run.sh`, `lo_scrape_club_trending_events.py`, and `.github/workflows/scrape-events.yml` are the older **external events** pipeline, separate from `python -m trending`. Its `--write-db` calls `replace_external_events`, replacing all prior rows for that source. Do not use it to populate the new discovery feed.

The legacy workflow declares Monday/Friday 05:00 Vietnam collection but was last observed as `disabled_inactivity`; it has not been re-enabled. Do not run a broad `supabase db push` or the legacy replacement importer as part of teammate setup. The isolated setup guide applies the required local schema without touching shared infrastructure.
