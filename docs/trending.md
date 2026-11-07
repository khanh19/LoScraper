# Verified local discovery

The `trending` package collects visitable events and places for HCMC, Hanoi and Da Nang. It is separate from the legacy nightlife importer. It never calls `replace_external_events`, deletes another city's feed, translates through a paid service, or downloads videos/posters.

## Run locally

```sh
cd /Users/macbook/Hack/LoScraper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Reuse Chrome on a Mac; a simulator and Xcode are unnecessary.
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending --browser --pilot --limit 20
# A smaller source/city inspection:
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending --browser --pilot --city hanoi --sources hanoigrapevine,vnexpress --limit 10
```

On a machine without Chrome, install Chromium with `.venv/bin/python -m playwright install chromium` and leave `LO_BROWSER_CHANNEL` unset. HTTP-only collection is available without `--browser`; Ticketbox and Vietnamese VnExpress will report `browser_disabled` and other sources continue.

The default is a read-only run. To import, apply the backend migration `20261108060000_discovery_trending.sql` to the existing Postgres database, supply `DATABASE_URL` through the environment or an ignored `.env`, and add `--write-db`. `--pilot --write-db` is restricted to loopback databases. Failed/invalid candidates do not replace valid observations. Each accepted page has its own transaction.

`--out pilot-output/review.json` writes an optional local audit report. That directory is ignored and GitHub Actions does not upload it. `--env-file` may be repeated and only reads an allowlist of collector configuration. It does not execute shell syntax or print credentials:

```sh
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending --browser --pilot \
  --env-file ../LoApp/.env --env-file ../LoAppBackend/.env
```

An API key alone never enables a provider. Add `--providers` explicitly and provide a persistent quota database. Credentials should ultimately live in the scraper's ignored `.env` or GitHub Actions secrets, never in a mobile bundle. `BRIGHT_DATA_API_KEY` is accepted as a local alias for `BRIGHTDATA_API_KEY`.

## Sources and publication

Six adapters have passed the bounded local pilot and are enabled in `trending/sources.json`. Ticketbox resolves its individual **Lịch diễn** sessions; TicketGo uses structured events. Hanoi Grapevine reads editorial schedule/address blocks and rejects multi-venue roundups. Fantasticity follows official campaign links to individual activities. Nightlife corroborates destinations against its venue pages. VnExpress uses original article publication dates and explicit destination/address evidence in the opening article paragraphs; it does not use sidebar/footer locations.

`--supplemental` discovers primary-source links from Life of Da Nang Weekly, Saigoneer and Visit HCMC. These are not assumed to publish daily. Wikipedia is not ingested. Unknown formats, unsupported cities, missing destinations, cancellations and unresolved schedules are rejected with reason codes. Source failures appear in run receipts. `no_detail_links` flags a likely layout change instead of reporting a silent success.

Every candidate retains canonical source and location-evidence URLs, original text, publication and verification dates, event occurrences, image provenance, and Vietnamese display fields. Structured VND prices are captured when supplied. Official names remain unchanged. Image URLs are collected, but all publishers currently have `image_permission: false`; cards therefore use neutral placeholders. Enable image reuse only after recording the publisher's permission/licence and attribution requirements.

Stable fingerprints use kind, city, normalized venue/address and event title. A known source URL preserves its ID through edits. Exact matching deduplicates supporting sources without combining similarly named branches. Existing Lô places require exact city, name and address agreement. Less certain matches remain source-linked items.

The backend applies a rolling seven-day window in Vietnam time, including ongoing events. Places require a genuinely recent dated mention. Re-scraping an old article does not refresh its publication date. Observations expire after 72 hours without verification; a confirmed cancellation remains effective until that source confirms reinstatement. Fresh contradictory event schedules are held out. Independent owner/content counts come first, then hourly engagement growth normalized within platform/city, then evidence freshness and event start. Events and places alternate; sparse categories are not padded. External evidence is never a Lô rating.

## Provider gates and actual account checks

No scrape/search credits were consumed during the account checks on 2026-11-08 ICT.

* **SerpAPI:** authenticated, Active free plan, 250 included searches remaining at inspection. Our maximum remains 200/month. Each search checks the account again and reserves a unit in Postgres before requesting results. Paid, unknown or exhausted plans are disabled. In-flight/uncertain reservations stay charged conservatively. [Account API](https://serpapi.com/account-api)
* **Bright Data:** key authenticated through the free zones endpoint; the billing balance endpoint returned **403**. No scraping request was submitted. Billing-read access and free-tier eligibility remain unverified. Its documentation states that free-credit balance and auto-recharge status are unavailable through the billing API. [Balance API](https://docs.brightdata.com/api-reference/account-management-api/Get_total_balance_through_API), [free tier](https://docs.brightdata.com/general/account/billing-and-pricing/free-tier)
* **Apify:** authenticated; account reports plan `FREE` and $5 monthly usage credits. No Actor was run. It remains an alternative for a separately bounded quality pilot, not an automatic fallback. Authentication alone is not a quality benchmark or proof of remaining credit. [Private account API](https://docs.apify.com/api/v2/users-me-get)

Bright Data additionally requires `BRIGHTDATA_FREE_VERIFICATION_JSON`: a control-panel receipt no older than 24 hours with `verified_at`, `unfunded: true`, `no_payment_method: true`, `auto_recharge: false`, and integer `free_credits_remaining`. The live balance response must explicitly report zero balance, credit, prepayment and pending costs. Missing fields fail closed. Do not invent this receipt from a zero balance. Reservations are deducted from verified remaining credits and capped at 4,500/month. No subscription, deposit, top-up, proxy fallback or account changes are performed by the collector.

Social collection accepts bounded public Facebook posts/videos, TikTok videos and Instagram posts/reels associated with a named independently located destination. Creator location cannot establish venue location. Only dates, text, source/owner references and engagement metrics are retained. YouTube can surface through direct search but is not a metrics provider. Provider IDs persist across runs; submitted jobs resume polling, while ambiguous submissions are held instead of retried. The social adapter remains unvalidated against live output because the billing gate is unresolved. Facebook/TikTok/Instagram publication therefore stays disabled in `sources.json` even when provider credentials exist. Review a free-only pilot before enabling each social source. Social posts must explicitly corroborate the same city as the independently located venue.

## Validation and rollout

```sh
.venv/bin/python -m unittest discover -s tests -v
# Optional real Postgres tests: destructive ONLY to discovery tables in this dedicated local database.
TRENDING_TEST_DATABASE_URL=postgresql://macbook@127.0.0.1:55439/lo_trending_test \
  .venv/bin/python -m unittest discover -s tests -v
# After importing a fresh pilot and starting Expo :8082 and Encore :4100:
.venv/bin/python tests/browser_smoke.py
```

Integration tests read the actual migration/query from sibling `../LoAppBackend` (override `LO_BACKEND_ROOT`). The backend is private; public CI does not automatically check it out. Tests cover Vietnamese schedules, session separation, city evidence, stable upserts, conflicting dates, cancellations, partial imports, expiry, syndicated mentions, missing images, free quotas and resumed provider jobs. The browser check uses the real discovery API; unrelated app APIs and explicit error/image cases are isolated test responses. Screenshots stay in `/tmp/lo-trending-qa`.

Local reviewed pilot: **11 published samples: HCMC 5 events; Hanoi 3 events + 1 place; Da Nang 2 events**. All published samples were re-fetched after parser corrections. Source-linked examples include [33.23.45](https://hanoigrapevine.com/vi/2026/11/trien-lam-33-23-45/), [Vĩnh Lợi](https://vnexpress.net/tiem-banh-mi-77-nam-cua-dan-sanh-an-ha-noi-5141032.html), [DACC reading room](https://danangfantasticity.com/vi/ket-noi-nghe-thuat-sang-tao-da-nang-2026/phong-doc-mo-diem-tuong-quan-tai-dacc-2026), and [QVTH XV](https://ticketbox.vn/liveconcert-qvth-xv-26686). Counts are a pilot snapshot, not guaranteed daily supply. HCMC/Da Nang places can legitimately be empty.

Roll out in this order:

1. Review/merge the three `stephen-develop` branches. App/backend include `origin/develop` through merge commits, preserving branch history.
2. Apply the new migration to the existing database and deploy the backend before the frontend requests its endpoint. No production migration has been applied by this change.
3. Make `.github/workflows/trending.yml` available on the repository's default branch. It uses standard public-repository Ubuntu runners. Leave `TRENDING_SCHEDULE_ENABLED` unset/false.
4. Run **Collect verified local discovery** manually with `pilot=true`, `providers=false`. Review counts, rejected reasons and failures. Then run with `pilot=false` against the migrated database. The `DATABASE_URL` repository secret already exists; confirm it targets the intended database. Local/Encore secrets do not transfer to Actions.
5. After those manual runs pass, set repository variable `TRENDING_SCHEDULE_ENABLED=true` for 23:00 UTC / 06:00 Vietnam daily. Scheduled provider use remains off. Optional manual provider runs require their separate Actions secrets and verified free allowance.

The previous nightlife workflow was observed as `disabled_inactivity` and has not been re-enabled. The new workflow cannot be manually dispatched until it exists on the default branch. No scheduled production collection or live social pilot is claimed by the local tests.

Monitor `discovery_ingestion_runs` for per-source/city failures and rejection reasons, observation `verified_at` for freshness, and `discovery_provider_jobs` grouped by provider/billing month for reserved usage. Receipts retain 30 days, completed jobs 90 days, and long-unverified items 90 days. Uncertain provider jobs are retained for manual reconciliation; do not delete their reservations to force retries.

## Verification record

The local suite passed all 28 tests, including eight real-Postgres tests. `encore test ./...` passed; frontend type checking passed and full lint reported zero errors/five existing warnings. The browser checks passed again after pricing support, with clean console checks and phone/desktop screenshots. The 11 samples exist only in the disposable local database.

`SERPAPI_API_KEY` and `BRIGHTDATA_API_KEY` have been configured as LoScraper GitHub Actions secrets using the existing local credentials. No Apify key or invented free-tier receipt was copied. The attempted manual dispatch returned HTTP 404 because `trending.yml` is not yet on the default branch. This is a rollout dependency, not a successful Actions pilot.
