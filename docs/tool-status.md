# Tools and implementation status

> **Reliability update:** see [migration order, operator health, and current validation](reliability.md). The 55-test / 8-item website snapshot supersedes the earlier test and feed counts below; provider pilot history is unchanged.

Evidence snapshot: **2026-11-07 America/New_York / 2026-11-08 Asia/Ho_Chi_Minh**. This is the last recorded validation, not a new live run. Current balances, source layouts, and feed eligibility must be rechecked. Start with the [teammate setup guide](teammate-setup.md).

## Collection and providers

| Tool/source | Implemented behavior | Last result / next step |
|---|---|---|
| Python HTTP + Beautiful Soup | Direct page collection, source adapters, normalized candidates | Passed bounded six-source pilot. No extraction-service subscription. |
| Playwright + Chrome/Chromium | Browser rendering for dynamic websites; browser QA | Passed using installed Chrome locally. CI installs Chromium. No Xcode. |
| Vietnam Nightlife | Events and recurring schedules with destination corroboration | Enabled; bounded website pilot passed. |
| Ticketbox | Individual sessions, dates, venues, ticket information | Enabled; bounded website pilot passed; browser rendering required. |
| Hanoi Grapevine | Vietnamese exhibitions/workshops/performance schedule blocks | Enabled; bounded website pilot passed; multi-venue ambiguity rejected. |
| Danang Fantasticity | Official local events and linked individual activities | Enabled; bounded website pilot passed. |
| VnExpress | Vietnamese food destinations; English factual discovery | Enabled; bounded website pilot passed; original publication time retained. |
| TicketGo | Structured event dates and venues | Enabled; two unresolved seasonal listings withheld; parser corrected/rechecked. |
| Life of Da Nang / Saigoneer / Visit HCMC | Optional `--supplemental` primary-link discovery | Implemented as discovery only, not independently published adapters or guaranteed daily sources. |
| SerpAPI | Free-plan account check, URL discovery, durable reservations | Six live searches passed; 244 included searches remained then. Cap 200/month or less if verified remaining allowance is smaller. Recheck before future use. |
| Bright Data billing | Separate Finance key, account identity checks, dashboard receipt, monetary checks | Billing access passed. Original scraping key remains User. Receipt expires within 24h; no permanent clearance. |
| Bright Data Facebook | Bounded public-post collection and event-specific corroboration | Pilot failed publication criteria: one returned campaign post rejected, another trigger HTTP 400. Disabled. |
| Bright Data Instagram | Public post/reel collection | Trigger HTTP 400; no validated sample. Disabled. |
| Bright Data TikTok | Public video metadata collection, no video downloads | Implemented but not live-piloted. Disabled. |
| Apify | Researched/authenticated alternative | Free plan observed, no Actor run or integration; no automatic fallback. |
| YouTube | Links may surface during search discovery | No dedicated collection/metrics adapter. |
| Wikipedia / Google Translation | Outside this version | No weekly Wikipedia ingestion or paid translation dependency. |

All six publisher image permissions are currently false: metadata can retain image provenance, but UI cards use neutral placeholders. “Enabled” means the adapter is configured to run and validate candidates; it does not mean every page is accepted or that scheduling is active.

Bright Data pilot: **3 one-record reservations**, including **2 failed triggers**, **1 returned record**, **0 published social records**; no retries. Pre-pilot dashboard showed 5,000 free credits and $7 entirely promotional, no deposits, auto-recharge off. Post-pilot monetary reads were unchanged, but the exact final free-credit total was not rechecked because Safari control disconnected. The collector conservatively retains all reservations. Alert emails alone are not spending protection; free-only gates and an unfunded account remain required.

## Storage, API, UI, and operations

| Component | Implemented / verified | Remaining limitation |
|---|---|---|
| PostgreSQL discovery tables | Stable upserts, observations, occurrences, receipts, quotas/job IDs; replay/partial-failure tests | No production migration performed. |
| Validation/ranking | Three cities, seven-day eligibility, 72h verification expiry, cancellation/conflict checks, independent evidence ordering | Sparse or empty feeds are valid; no fabricated padding. |
| Encore `/discover/trending` | Public city/kind/limit API; all nine city/filter combinations passed | Production deployment not performed. |
| Shared local DB override | `LO_DATABASE_URL` isolates shared-connector services, not only discovery; loopback validation | Local-only; must be explicitly set. |
| Local Google request guard | Blocks Places/Lists HTTP, including photos | Live Google free capacity/project ownership unknown; zero live requests in pilot. |
| Expo trending cards | Vietnamese filters, source/date/venue labels, empty/retry/image fallback, 60s active refetch | Image permissions pending; native-device QA not performed. |
| Matched venue navigation | Unmocked navigation to a source-verified local venue passed | Fresh teammate database contains no demo venues; requires a genuine match. |
| Search race/error handling | Rapid-query/clear/filter/empty/retry tests passed with controlled responses | Live Google autocomplete/details remain blocked; mocks are not provider evidence. |
| Venue presentation | Removed fabricated fallback ratings/reviews/photos/hours | Existing Call/Website/Hour/Menu action-row controls remain placeholders. |
| Public preview/auth | Public Explore works without login; unauthenticated bookmark reads skipped | Authenticated/private flows not validated; no fake auth bypass. |
| GitHub Actions | Ubuntu workflow, manual inputs, 06:00 Vietnam schedule with opt-in guard | Feature branch only; default-branch manual run blocked. Scheduling disabled. Local/Encore secrets do not propagate automatically. |
| Teammate DB bootstrap | New empty loopback database, ordered migrations, three cities, no demo venues | Setup helper is for disposable local databases, not incremental/production migration. |

## Documentation handoff checks

The teammate bootstrap was executed against a new temporary loopback PostgreSQL 16 cluster: all migrations applied, three cities present, zero demo places. A second run correctly refused the populated database. All 37 scraper tests, including ten real PostgreSQL tests, were rerun successfully in a separate disposable database. No external provider collection, balance recheck, deployment, or schedule activation was part of this documentation update.

## Validation evidence and next steps

The last local import had **13 eligible items**: HCMC 5 events; Hanoi 3 events + 1 place; Da Nang 4 events. Those counts age out and are not shipped seed data. The full evidence table is in [the pipeline report](trending.md#end-to-end-validation--2026-11-08-ict).

Checks passed: 37 scraper tests including 10 real PostgreSQL tests, `encore test -p 1 ./...`, frontend typecheck, lint with 0 errors/4 existing warnings, unmocked discovery browser pass, and separately controlled fault/search suites. An existing favicon 404 remained. Screenshots/reports lived in ignored `pilot-output/e2e-20261108/` on the original validation machine; they are not included in a clone.

1. Teammate follows the website-only local guide and records new results without provider keys.
2. Identify the Google Cloud project owning the Encore Google key and verify applicable non-billable capacity before any live search/details/photo test.
3. Refresh Bright Data dashboard verification, diagnose Facebook/Instagram inputs, and run a separately bounded social quality pilot. Enable only a source with valid destination/event evidence.
4. Review image reuse permissions before enabling publisher images.
5. Separately review production migrations/deployments and default-branch workflow availability; validate manual jobs before any schedule activation. No additional spending is authorized.
