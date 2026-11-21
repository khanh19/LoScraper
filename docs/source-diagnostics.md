# Local source diagnostics

This view renders up to five real stored samples per source, separately from Trending. It proves retrieval/rendering only, not event validity or publication readiness. It is available only in a development web build on localhost. No raw media, signed image URLs, credentials, provider requests, or publication writes are exposed.

Start the read-only helper from LoScraper (keep it running):

```sh
LO_DIAGNOSTICS_ENGINE_DATABASE_URL=postgresql://macbook@127.0.0.1:55443/lo_engine_accounting \
.venv/bin/python -m trending.diagnostics \
  --report pilot-output/source-coverage-20261108.json \
  --report pilot-output/source-coverage-rendered-20261108.json
```

Open `http://localhost:8084/discovery/sources`, or use **Kiểm tra nguồn · Local diagnostics** above Discover. The Expo development server must be running. The helper binds only 127.0.0.1:4110, rejects non-loopback Host/Origin, uses a read-only database connection, and serves an explicit field allowlist. Reports are local ignored files; use your own report paths when reproducing.

To collect new website samples, use the existing manual collector with `--pilot --browser --limit 5 --write-db --out <local-report.json>` and the isolated preview DATABASE_URL. Never point a pilot at shared production storage. Add that report to the helper's `--report` arguments and restart it. Refreshing diagnostics only rereads stored results. Rejected report entries now retain bounded identifying fields and rejection codes; historical reports without those fields cannot reconstruct rejected samples.

## Verified on 2026-11-08

| Source | Samples rendered | Interpretation |
|---|---:|---|
| Instagram | 1 | Retrieved; publication not approved |
| TikTok | 4 | Retrieved; unresolved/expired evidence remains withheld |
| YouTube | 2 | Retrieved; not verified upcoming events |
| Ticketbox, Hanoi Grapevine, Danang Fantasticity, VnExpress, TicketGo, Life of Da Nang, Saigoneer | 5 each | Mix of collector-accepted and withheld candidates |
| Facebook | 0 | Historical accounting ledger unavailable; no new request |
| Vietnam Nightlife | 0 | Listing fetch failed / no detail links |
| Visit HCMC | 0 | Supplemental discovery, no dedicated collected sample |
| Threads | 0 | Dedicated retrieval unvalidated |

Two website passes used 10 detail pages/source without rendering, then five/source with rendering. Browser rendering recovered Ticketbox (three accepted) and VnExpress (one accepted). Both runs were partial because some sources failed. Accepted imports are not the same as current API eligibility. Existing records were preserved. No metered provider calls were made during this validation; social samples came from the existing accounting store.

Actual API/UI counts after collection:

| City | Weekly events | Weekly places | Planning events |
|---|---:|---:|---:|
| Hanoi | 1 | 1 | 3 |
| HCMC | 0 | 0 | 4 |
| Da Nang | 1 | 0 | 0 |

Unmocked Chrome checks passed all 12 city/filter/planning cases, with zero page errors or failed requests. Diagnostics rendered 42 source actions, passed desktop/mobile width and refresh checks, and rejected a foreign Origin. All 117 scraper/PostgreSQL tests passed. TypeScript passed; lint had zero errors and four existing warnings. Evidence is local under `pilot-output/source-diagnostics/` (screenshots, receipt, feed checks).

The stored YouTube examples are unrelated news/history and were rejected; they demonstrate transport only, not useful local discovery. The requested minimum for **every** source remains unmet. Zero-sample sources remain visible rather than filled with invented examples. Human calibration and reviewed ownership/location gates still apply before social publication. Wikipedia remains outside weekly ingestion by design.
