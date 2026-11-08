# Bounded social pilot — coverage-20261108

Routine social collection stays disabled. This exploratory CLI uses the existing
provider ledger and an isolated feed database. Never copy an empty quota table
into a new preview and treat that as a fresh allowance.

## Before running

1. Apply `20261109080000_discovery_pilots.sql` to the **existing canonical quota
   database**, preserving all earlier jobs and reservations. The isolated feed
   database receives the full discovery migration sequence.
2. Set `QUOTA_DATABASE_URL` to that existing ledger, and `DATABASE_URL` to the
   separate loopback `lo_setup_check_*` feed database. Neither value is printed.
3. Keep scraping and Finance credentials separate in ignored configuration.
   Re-inspect the same account's shared free-credit pool, promotional-only balance,
   transaction history (no deposits), and both auto-recharge controls. Update the
   existing `BRIGHTDATA_FREE_VERIFICATION_JSON` receipt only after those checks.
   `python -m trending.preflight --env-file .env` verifies billing and matching
   credential account IDs; it does not initiate scraping.
4. Provide a local JSON manifest with `queries` (at most six strings) and `posts`
   (at most nine objects containing `url` and the collected `primary` candidate
   payload). The primary must already be imported and fresh in the isolated feed.
   Only Facebook post/video, Instagram post/reel and TikTok video URLs qualify.
   Search results are **not** automatically submitted: inspect association first.
5. Run `.venv/bin/python -m trending.pilot --env-file .env --manifest /path/to/manifest.json`.
   Re-run the same command to poll known jobs. Do not delete ambiguous reservations.

The fixed pilot ID has atomic caps: nine Bright Data single-record attempts,
maximum three per platform, six SerpAPI searches. Provider/monthly locks also
preserve 4,500-credit and 200-search monthly caps and any smaller verified remainder.
Failed requests retain reservations. Unknown submissions cannot be retriggered;
known snapshots resume polling. Pilot reservations survive routine cleanup, so
recreating a preview or waiting 90 days cannot reset the pilot budget.

No free allowance evidence means no submission. SerpAPI account reads must confirm
an active zero-price free plan before search. Bright Data's receipt covers the
shared pool, including other products, not just this app.

## Endpoint audit

[Facebook post endpoints](https://docs.brightdata.com/products/scrapers/facebook/send-first-request),
[Instagram endpoints](https://docs.brightdata.com/products/scrapers/instagram/send-first-request),
[TikTok endpoints](https://docs.brightdata.com/products/scrapers/tiktok/send-first-request)
and the [async workflow](https://docs.brightdata.com/products/scrapers/scrapers-library/async-requests)
were checked. Direct post collection now sends one URL in the bare input array,
with the limit in query parameters. No profile discovery or comment expansion is
requested. The new Facebook trigger returned a snapshot and one record, unlike
the earlier HTTP 400 attempts. This does **not** establish that Instagram's prior
400 is resolved; no new Instagram job was submitted.

## Actual run, 8 November 2026

The dashboard showed 4,999/5,000 free credits, $7 entirely from two promotional
bonuses, no deposited funds, and both recharge controls off. Fresh billing reads
confirmed the two credentials belong to the same account. The six SerpAPI searches
were reserved in the existing ledger after included allowance checks.

| Platform/path | Result | Actual new usage |
|---|---|---:|
| SerpAPI discovery | Passed retrieval; poor relevant-post coverage | 6 searches |
| Facebook transport | Passed trigger, resumed polling, one record | 1 single-record attempt |
| Facebook evidence | Failed: post did not corroborate the specific event; not imported | 0 published observations |
| Instagram | Blocked: no suitable destination-specific post in this bounded discovery sample | 0 attempts |
| TikTok | Blocked: no suitable video URL in this bounded discovery sample | 0 attempts |

No extra searches or retries were used to fill the nine-record allowance. The nine
records are a ceiling, not a collection target. No subscription, deposit, recharge,
Apify fallback, proxy service, remote browser or video download was initiated.

The canonical ledger retains earlier usage (six SerpAPI reservations and three
Bright Data reservations) separately from this pilot. New reservations total six
searches and one Bright Data unit; polling did not create additional reservations.
Provider billing totals can lag and are not inferred from local job counts.

Regression tests cover concurrent platform-cap reservations, durable replay,
exhausted allowance, zero credentials, ambiguous submission and resumed snapshot
polling. The live result remains a failed quality pilot; social publication is not
ready to enable. First improve organizer/venue URL discovery, then authorize a
new bounded pilot rather than silently resetting this ID's caps.
