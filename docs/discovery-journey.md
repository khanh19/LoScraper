# Complete discovery journey — local validation

This collector follow-up stacks on coverage PR #2 (`stephen-trending-coverage`). Its companion backend/app branches use the same `stephen-discovery-journey` name. Existing coverage and reliability PRs remain unchanged; no merge, deployment, paid collection, or schedule activation is included.

## Collection reliability

VnExpress's Vietnamese food listing uses `h2/h3.title-news` rather than `h1/main`. The rendered-page readiness check now recognizes those headings and preserves sanitized HTTP status failures. Live verification found 32 listing links and successfully imported the recent Hanoi bakery article.

Public HTTP/browser fetching retries **once** for transient connection/timeouts, 408/429 and selected 5xx statuses. Permanent failures such as 403/404, oversized content, or disallowed hosts are not retried. Only successful fetches enter the in-run cache; failed collection never refreshes observation verification. No proxy or paid renderer fallback was added.

## Reproduce the local preview

1. Check out the three journey branches. Apply the full backend migration sequence through `20261110060000_discovery_journey.sql` before running the updated API. Empty-database setup already walks that full sequence. Never bootstrap an existing preview database.
2. On the existing loopback PostgreSQL cluster, create and bootstrap a **new** database:

   ```sh
   createdb -h 127.0.0.1 -p 55442 -U "$USER" lo_setup_check_journey
   .venv/bin/python docs/setup_local_database.py --port 55442 --user "$USER" \
     --database lo_setup_check_journey --backend ../LoAppBackend
   ```

3. Collect websites only; no `.env` provider keys or `--providers` are needed:

   ```sh
   DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_setup_check_journey" \
   LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending \
     --sources vietnamnightlife,ticketbox,hanoigrapevine,danangfantasticity,vnexpress,ticketgo,lifeofdanang \
     --limit 4 --browser --write-db --out pilot-output/journey-live.json
   DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_setup_check_journey" \
     .venv/bin/python -m trending.health --json
   ```

   Exit codes: 0 complete, 2 partial, 1 fatal. Valid rejections alone are not collection failures. Health counts use the same eligibility function as details, search and the public feed. Source failure/yield information remains in receipts and health output. Provider accounting is labelled local accounting, not a current provider balance.
4. Start Encore on 4104 with that same `LO_DATABASE_URL` and `LO_DISABLE_GOOGLE_REQUESTS=1`. Start Expo on 8086 with `EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://localhost:4104`, using the installed supported Node and `--max-workers 2`. See the app/backend journey guides for exact commands and auth limitations.

Preview: http://localhost:8086/tabs/explore while the local services run. The database remains loopback-only. No public hosted preview exists. The previous previews and canonical quota ledger were preserved.

## Fresh run: 8 November 2026

Seven adapters completed with zero collection/persistence failures: 33 extracted candidates, 7 accepted, 26 rejected. The bounded run fetched four detail pages per source. Accepted source evidence was reviewed for venue/city and date/publication support; no publisher image permission was inferred.

| City | Eligible events | Eligible places | Total |
|---|---:|---:|---:|
| HCMC | 3 | 0 | 3 |
| Hanoi | 1 | 1 | 2 |
| Da Nang | 2 | 0 | 2 |

TicketGo supplied no eligible records in this bounded sample. This is not a coverage regression comparison with the earlier nine-item run, which used a larger page budget. No entries were added to fill empty place filters.

The existing curated Vĩnh Lợi venue was copied from the prior isolated preview after checking its name/address against the freshly collected article, then candidates were replayed with their **original verification times**. Seven stable records remained; the Hanoi place confidently matched the venue. This tests existing-place matching, not Google venue acquisition. A teammate's empty database can legitimately have no matched venue until verified place records exist.

The run consumed **0 Bright Data records, 0 SerpAPI searches, 0 Google Places API requests**. No social collection was attempted, no quota ledger was reset, and no provider balance was claimed as verified. All social publication remains disabled.

## Validation matrix

| Path | Status | Evidence / limit |
|---|---|---|
| Full empty-database migration sequence | Passed | New isolated journey preview and separate backend test database |
| Scraper unit + real PostgreSQL regression suite | Passed | 72 tests, no skips with the disposable test DB configured |
| Encore tests | Passed | Full sequential suite; dedicated PostgreSQL journey test included |
| Owner isolation / replay / expiry / cleanup snapshots | Passed, controlled | Encore test auth overrides; not a real Auth0 login |
| Frontend types / lint | Passed | 0 type errors; lint 0 errors, 4 existing warnings |
| URL/directions/clipboard/native-share dispatch | Passed, controlled | App `tests/discovery-actions.cjs`; no calls/messages sent |
| Live mobile city × filter / detail / search / venue / Back | Passed | Unmocked local API; zero page errors |
| Live desktop city × filter / detail / source / directions / copy | Passed | Actual links, including same-page publisher redirects; clipboard contents verified |
| Controlled search outage / retry / stale response / clear | Passed | `tests/browser_journey_faults.py`; separately labelled synthetic failures |
| Mobile + desktop image rendering | Passed | Three cities each; `tests/browser_images.py` |
| Publisher-image failure → illustration → placeholder | Passed, controlled | No permission or provider response treated as live evidence |
| Real authenticated browser save | Blocked | Real login not supplied; backend local callback is 8081, preview is 8086 |
| Physical iPhone / native navigation and auth | Blocked | User has no iPhone development build/device; mobile browser is not native evidence |
| Live Google search/details/photos | Blocked | Free capacity unverified; outgoing requests disabled |

Browser save gates and backend bookmark ownership are both tested, but **the full real-login → save → reload journey remains unverified**. Configure a matching Auth0 callback and use a real test account to complete it. Do not bypass authentication with a fake token. No Xcode or simulator installation is needed for the delivered browser preview.

## Evidence and commands

- [Browser walkthrough video](assets/demo/journey-20261108/discovery-journey.mp4) — actual local UI at half speed, silent; not an iPhone recording. External tabs were opened/verified separately and are not composited into this page recording.
- [Discovery detail](assets/demo/journey-20261108/details.png)
- [Venue actions](assets/demo/journey-20261108/venue.png)
- [Saved-item login gate](assets/demo/journey-20261108/saved-login.png)
- [Desktop preview](assets/demo/journey-20261108/desktop.png)

```sh
TRENDING_TEST_DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_trending_guards_test" \
  .venv/bin/python -m unittest discover -s tests
LO_QA_APP_URL=http://localhost:8086 LO_QA_API_URL=http://localhost:4104 \
  .venv/bin/python tests/browser_journey.py
LO_QA_APP_URL=http://localhost:8086 LO_QA_API_URL=http://localhost:4104 \
  .venv/bin/python tests/browser_journey_faults.py
LO_QA_APP_URL=http://localhost:8086 LO_QA_API_URL=http://localhost:4104 \
  .venv/bin/python tests/browser_images.py
```

Browser tests require the installed Chrome and Playwright dependencies. Raw collection reports remain ignored under `pilot-output`; only reviewed screenshots, a recording, and sanitized test receipts are shared. PostgreSQL integration fixtures are disposable and must never target a preview or the canonical provider ledger.

The laptop's older Node emitted an unsupported-version warning and the long-lived Metro process exhausted its heap during repeated edits. Final preview uses the already installed Node v24.1.0 with two workers and a bounded heap. Missing Encore runtime dependencies were restored at pinned versions after a local cache loss; no application dependency upgrade was made.

Sanitized receipts: [mobile](assets/demo/journey-20261108/mobile-results.json), [desktop](assets/demo/journey-20261108/desktop-results.json), [fault injection](assets/demo/journey-20261108/fault-results.json), [images](assets/demo/journey-20261108/image-results.json), [collection](assets/demo/journey-20261108/collection-summary.json). Both final browser runs had zero page errors and zero failed requests. Each logged the existing missing `/favicon.ico` 404; discovery API responses were successful.

## Remaining work

Finish real authenticated browser and physical-phone validation; review the stacked PRs in dependency order (backend migration/API, scraper, app). Retarget after parent merges rather than merging this batch automatically. Manually recollect successful sources to retain freshness: items lose verification after 72 hours and events disappear when eligible sessions end. Scheduling, Google allowance verification, social pilots, production permissions and deployment remain separate work.
