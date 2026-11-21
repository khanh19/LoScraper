# Coverage validation — 21 November 2026

Goal: approximately 15 Hanoi, 15 HCMC and 5–10 Da Nang discoveries, with mixed
sources. These are soft collection targets across weekly and planning sections,
not permission to bypass freshness, session, venue or cancellation checks.

## Changes

- App requests up to 20 results per section instead of 10; obsolete weekly-feed
  requests now receive the query cancellation signal.
- Multi-listing collectors share the detail-page budget across their listing
  pages, rather than allowing the first listing to consume every slot.
- Three consecutive fetch failures stop that source's detail loop; other sources
  continue. TLS failures receive a sanitized diagnostic code.
- Health reports unique eligible counts, sections, categories, supporting
  platforms, missing Instagram/TikTok coverage, and target shortfalls.

## Live results and limits

The isolated preview `lo_setup_check_coverage_20261121` was copied from the existing
local preview; the original preview and canonical accounting ledger were preserved.
Fresh website collection used Life of Da Nang, TicketGo, and Vietnam Nightlife.
Hanoi Go was tested in local pilot mode. Reimports retain existing stable IDs.

Final shared-evaluator counts: **Hanoi 11** (8 weekly, 3 planning), **HCMC 4**
(3 weekly, 1 planning), **Da Nang 8** (weekly). These totals include still-eligible
existing records as well as this run's imports. All eligible supporting sources
in this database are websites. Mixed social coverage and the Hanoi/HCMC targets
are **not achieved**.

Hanoi Grapevine failed TLS negotiation. Ticketbox did not yield usable rendered
listings. The longer rendered-source run was interrupted during VnExpress;
its partial stdout is not treated as a completed collection receipt. Danang
Fantasticity candidates in that run did not pass validation.

Apify's read-only account check confirmed an active FREE plan, $5 monthly limit,
and approximately $0.381 used. The existing campaign ledger already reserved
126 of 132 outputs; the current TikTok adapter reserves 30 per discovery run.
No new social jobs were submitted and no historical reservation was reset.
Bright Data's local allowance receipt is dated 8 November and needs renewal.

## Validation

- 170 scraper tests passed, including real PostgreSQL integration tests against
  the dedicated `lo_trending_guards_test` database.
- Frontend TypeScript check and lint of the changed query module passed.
- Shared database evaluator and health coverage counts were checked directly.
- HTTP API and browser validation are **blocked**: Encore's Go dependency
  extraction exhausted local disk space. No native-device validation claimed.
- No deployment, merge, schedule change, paid scraping, or Drive upload.

Inspect coverage with:

```sh
DATABASE_URL=postgresql://macbook@127.0.0.1:55443/lo_setup_check_coverage_20261121 \
  .venv/bin/python -m trending.health --json
```

Remaining: restore sufficient build space, validate real API/UI output, resolve
rendered-source failures and HCMC session extraction, and run bounded social
collection only after fresh allowance checks and explicit output reservations.
