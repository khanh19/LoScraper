# Teammate setup: Lô discovery and search

> **Reliability update:** see [migration order, operator health, and current validation](reliability.md). The 55-test / 8-item website snapshot supersedes the earlier test and feed counts below; provider pilot history is unchanged.

Start here for the three-repository local preview. This guide uses a new local database, API **4101**, and web app **8083**. It does not deploy, enable schedules, or make paid provider requests. No Xcode, simulator, Docker, or hosted database upgrade is needed for this path.

See [tool status](tool-status.md) for what is implemented, actually tested, and still blocked; [pipeline details](trending.md) explains validation and ranking. The last validation was **7 November 2026 in New York / 8 November in Vietnam**. Provider allowances and feed counts below are historical evidence, not today's entitlement.

## 1. Access and prerequisites

Ask the maintainer for GitHub access to all three repositories and local-development access to Encore app `loappbackend-a9f2`. Use `stephen-develop` in each repo; the implementation includes the full `origin/develop` frontend/backend history. Do not merge to the default branch as part of onboarding.

Install or reuse Git, Python 3.11/3.12, Node 22, Yarn Classic 1.22, PostgreSQL 16, the [Encore CLI](https://encore.dev/docs/quick-start), and desktop Chrome. Use Chrome for the committed browser suites. Python runs collection; PostgreSQL stores the local feed; Encore runs the API; Expo serves the browser UI. Dependencies and Go build caches need disk space; sequential Go tests and two Metro workers reduce peak resource use. There is no measured universal disk/RAM total for this setup.

On macOS with Homebrew, if PostgreSQL is missing:

```sh
brew install postgresql@16
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
```

The guide starts its own loopback cluster; do not start a second Homebrew service for it. Linux users can use their package manager's PostgreSQL binaries and omit the Homebrew PATH line.

Check your tools with `python3 --version`, `node --version`, `yarn --version`, `psql --version`, and `encore version`. If Yarn Classic is missing but Node/npm are installed, run `npm install --global yarn@1.22.22`. Install missing Python/Node from your usual development toolchain before continuing.

## 2. Clone sibling repositories

```sh
mkdir -p "$HOME/Hack"
cd "$HOME/Hack"
git clone --branch stephen-develop https://github.com/khanh19/LoScraper.git
git clone --branch stephen-develop https://github.com/khanh19/LoAppBackend.git
git clone --branch stephen-develop https://github.com/khanh19/LoApp.git
```

For existing clones, inspect `git status` first; preserve local edits and `.env` files. Fetch/check out the branch only when safe. On Stephen's Mac the parent is `/Users/macbook/Hack`, alongside ArchiMind. The sibling layout is used by the setup helper and integration tests.

## 3. Install dependencies

```sh
cd "$HOME/Hack/LoScraper"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ../LoApp
yarn install --frozen-lockfile
cd ../LoAppBackend
encore auth login
```

Encore handles the Go build. Follow any missing-secret/access error through the app owner and [Encore's secrets configuration](https://encore.dev/docs/go/primitives/secrets). A backend `.env` file is not automatically an Encore secret store. Never copy real keys into this guide or the frontend.

## 4. Create an isolated PostgreSQL preview

Use a **new dedicated cluster** on port 55440, separate from Stephen's existing preview on 55439. Run these in one terminal. If the directory, database, or port is already in use, stop and inspect it; never reset an existing preview to follow this guide.

```sh
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
export LO_PGDATA="$HOME/.local/share/lo-teammate-postgres"
export LO_PGSOCKET="$HOME/.local/share/lo-teammate-pg-socket"
mkdir -p "$LO_PGSOCKET"
initdb -D "$LO_PGDATA" -U "$(whoami)" --encoding=UTF8 --locale=C \
  --auth-local=trust --auth-host=trust
pg_ctl -D "$LO_PGDATA" -l "$LO_PGDATA/server.log" \
  -o "-h 127.0.0.1 -p 55440 -k $LO_PGSOCKET" start
createdb -h 127.0.0.1 -p 55440 -U "$(whoami)" \
  --template=template0 --encoding=UTF8 lo_teammate_preview
cd "$HOME/Hack/LoScraper"
.venv/bin/python docs/setup_local_database.py --user "$(whoami)"
```

Trust authentication is restricted to this personal loopback development cluster; do not expose it to a network. The helper refuses a nonempty database. It applies the auth baseline, the two historical unnumbered profile/follow migrations, then numbered migrations in order. It seeds the three cities, categories, and vibes, omits demo venues from the old onboarding seed, and clears remote city cover images. The historical `adding_column_for_users.sql` adds then removes obsolete columns and is intentionally skipped. This helper is **not** a production migration tool or an incremental migration ledger. If it fails midway, keep the log and investigate; do not rerun against the partially populated database blindly.

## 5. Collect websites without provider credentials

First inspect a bounded read-only report. Chrome is reused rather than downloading another browser:

```sh
cd "$HOME/Hack/LoScraper"
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending \
  --browser --pilot --limit 20 --out pilot-output/website-review.json
```

`--limit 20` means up to 20 candidate pages **per adapter**, not 20 total and not a provider-credit budget. The six adapters run by default. For a smaller run add `--city hanoi --sources hanoigrapevine,vnexpress --limit 5`. Without `--browser`, browser-dependent Ticketbox/Vietnamese VnExpress collection is skipped; other website collectors continue. `--supplemental` optionally follows discovery links from Life of Da Nang, Saigoneer, and Visit HCMC.

Review accepted items against original URLs: supported city, identifiable destination, real sessions/dates, cancellation status, and recent evidence. Images remain placeholders until publisher reuse permission is established. Then run the same collection into the new local preview:

```sh
DATABASE_URL="postgresql://$(whoami)@127.0.0.1:55440/lo_teammate_preview" \
LO_BROWSER_CHANNEL=chrome .venv/bin/python -m trending \
  --browser --pilot --write-db --limit 20 --out pilot-output/website-import.json
```

This re-fetches and validates pages; it does not import the earlier JSON report. Inspect the final import report too. Repeat imports preserve stable IDs and valid records from other sources/cities. Do not add `--providers` for this onboarding path. Fresh data availability varies: an empty feed is valid and should not be filled with old fixtures or invented entries.

## 6. Start the API and UI

Terminal A:

```sh
cd "$HOME/Hack/LoAppBackend"
LO_DATABASE_URL="postgresql://$(whoami)@127.0.0.1:55440/lo_teammate_preview" \
LO_DISABLE_GOOGLE_REQUESTS=1 encore run --port 4101
```

`LO_DATABASE_URL` covers all services using the shared database connector, including venue resolution. The older `LO_DISCOVERY_DATABASE_URL` only isolates discovery and is insufficient for end-to-end testing. The shared override is accepted only in Encore's local environment with loopback PostgreSQL hosts. The Google guard blocks requests before HTTP, including photos, in Places and Lists. Keep it set until the owning Google Cloud project and its non-billable capacity are verified.

Terminal B:

```sh
cd "$HOME/Hack/LoApp"
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://localhost:4101 \
  yarn expo start --web --port 8083 --max-workers 2
```

Open **http://localhost:8083/tabs/explore**. `EXPO_NO_DOTENV=1` avoids accidentally selecting staging from an existing local frontend `.env`; the explicit URL selects the isolated API. Discover is public and can be opened directly without logging in. Full Auth0 login is separate: current local callback configuration uses port 8081. Align the backend callback and Auth0 allowlist before testing login on a different port. This preview does not bypass protected endpoints.

Terminal C:

```sh
curl --fail 'http://localhost:4101/cities'
curl --fail 'http://localhost:4101/discover/trending?city_slug=hanoi&kind=all&limit=10'
```

Switch HCMC/Hanoi/Da Nang and **Tất cả / Sự kiện / Địa điểm** in the UI. Compare titles, dates, cities, sources, and counts with the API. Cards always open their original source; a venue screen is available only when an existing place matches confidently. A new empty venue database will usually have no `place_id` matches. Do not insert fake Google data to make that test pass.

## 7. Understand refresh and expected limitations

Collection writes observations, occurrences, and ingestion receipts to PostgreSQL. The API validates eligibility and ranks on each read. Expo's trending query caches by city/filter (the request limit is fixed at 10), with a 60-second stale time and 60-second refetch interval while active; city/filter changes and the retry/refresh controls also request data. UI polling does **not** scrape websites.

Events must overlap the next seven days in Vietnam time; places need dated mentions from the previous seven days. Unverified observations expire after 72 hours. Rerun website collection to refresh evidence; changing an old article's scrape time does not make it new. The planned daily 06:00 Vietnam GitHub job is currently **disabled**, so local data will age out without manual collection.

Live Google search is expected to be unavailable with the guard enabled. Cached local venues can still open. Existing Call/Website/Hour/Menu action-row placeholders are not complete product functionality. Native-device, authenticated, and production behavior are separate validation work.

## 8. Run checks and interpret the results

```sh
cd "$HOME/Hack/LoScraper"
.venv/bin/python -m unittest discover -s tests -v
```

This skips PostgreSQL tests unless configured. Create a **separate disposable test database**, never use `lo_teammate_preview` or a shared DB:

```sh
createdb -h 127.0.0.1 -p 55440 -U "$(whoami)" \
  --template=template0 --encoding=UTF8 lo_trending_guards_test
TRENDING_TEST_DATABASE_URL="postgresql://$(whoami)@127.0.0.1:55440/lo_trending_guards_test" \
  .venv/bin/python -m unittest discover -s tests -v
cd ../LoAppBackend
encore test -p 1 ./...
cd ../LoApp
yarn typecheck
yarn lint
```

The integration suite drops discovery tables and truncates its test data. It permits only the dedicated loopback names in `tests/test_postgres.py`; never rename your preview to bypass that guard. Sibling `LoAppBackend` is required (or set `LO_BACKEND_ROOT`). The last full result was 37 scraper tests including 10 real PostgreSQL tests, backend tests passed, frontend typecheck passed, lint 0 errors/4 existing warnings.

With API/UI running and fresh feed data, from LoScraper:

```sh
LO_QA_API_URL=http://localhost:4101 LO_QA_APP_URL=http://localhost:8083 \
  LO_QA_OUT=/tmp/lo-teammate-qa/live .venv/bin/python tests/browser_live.py
LO_QA_API_URL=http://localhost:4101 LO_QA_APP_URL=http://localhost:8083 \
  LO_QA_OUT=/tmp/lo-teammate-qa/faults .venv/bin/python tests/browser_faults.py
LO_QA_API_URL=http://localhost:4101 LO_QA_APP_URL=http://localhost:8083 \
  LO_QA_OUT=/tmp/lo-teammate-qa/smoke .venv/bin/python tests/browser_smoke.py
```

These scripts reuse installed Chrome. The full browser scenarios currently expect a **fresh matched Hanoi place** (the original pilot used a source-verified Vĩnh Lợi venue). A fresh clone does not include that private local seed or old screenshots. Without an evidence-backed matching venue, record that navigation scenario as blocked; the basic API/city/filter checks can still be performed manually. `browser_live.py` has an unmocked discovery section and a separately controlled search section. `browser_faults.py` injects failures; `browser_smoke.py` mocks unrelated services. None proves live Google or social quality.

## 9. Optional providers: credentials and gates

Website collection requires **none** of the optional provider keys. To prepare optional collection, copy `.env.example` to `.env` only if no `.env` exists, obtain keys privately from the owner, and keep the file ignored. Do not copy keys from chat or put them in `EXPO_PUBLIC_*` values.

| Configuration | Where it belongs | Purpose/status |
|---|---|---|
| `DATABASE_URL` | LoScraper shell or ignored `.env` | Same isolated DB as the backend; persistent quotas live here too. |
| `LO_DATABASE_URL` | Backend launch environment | Shared local database override; not an Encore cloud secret. |
| `LO_DISABLE_GOOGLE_REQUESTS=1` | Backend launch environment | Required for this free-only local preview. |
| `EXPO_PUBLIC_API_URL` | Frontend launch environment | Public backend URL only. |
| `SERPAPI_API_KEY` | LoScraper ignored `.env`; optional Actions secret | Included free discovery; cap 200/month or smaller verified allowance. |
| `BRIGHTDATA_API_KEY` | LoScraper ignored `.env`; optional Actions secret | Existing User-permission scraping key. |
| `BRIGHTDATA_BILLING_API_KEY` | LoScraper ignored `.env`; optional Actions secret | Separate Finance user, same account; billing GETs only in our code. |
| `BRIGHTDATA_FREE_VERIFICATION_JSON` | Same scraper/Actions configuration | Dashboard receipt, current UTC month, at most 24 hours old. |
| Encore runtime secrets | Encore app's Local environment | `Auth0ClientSecret`, `ExternalDBPassword`, `GooglePlacesAPIKey`; app-owner access/configuration. Their presence does not authorize live Google requests. |
| Apify token | Not required by the implemented pipeline | Alternative only; no Actor integration or fallback. |

The scraper reads `.env` **only** when passed `--env-file .env`. Shell values take precedence; with multiple files, the first file's value wins. `BRIGHT_DATA_API_KEY` is a supported legacy alias; prefer `BRIGHTDATA_API_KEY`. Encore and local files do not automatically populate GitHub Actions secrets. `Domain`/`ClientID` for Auth0 are currently in `auth/auth-config.cue`, not read from same-named Encore secrets.

Read-only Bright Data preflight:

```sh
cd "$HOME/Hack/LoScraper"
.venv/bin/python -m trending.preflight --env-file .env
```

It checks Bright Data, **not SerpAPI or Google**, and never starts scraping. A valid key is insufficient. Verify matching accounts, no deposited funds, auto-recharge off, remaining free credits, and any balance entirely promotional; record those facts using the receipt schema in `.env.example`. Never refresh its timestamp without inspecting the dashboard. Finance permission is broader than read-only even though our code uses GETs. Billing alerts are notifications, not a hard cap.

Each collection request requires a durable reservation. Bright Data's cap is 4,500 credits/month; SerpAPI's is 200 searches/month or less if remaining included capacity is lower. Unknown, stale, paid, or exhausted allowance blocks providers while websites continue. The previous pilot's **3 Bright Data reservations / 6 SerpAPI searches** were that run's budget, not a global CLI per-run limit. `--limit` does not impose those provider limits. Do not launch a generic `--providers` run as a teammate smoke test. Arrange a separately bounded pilot and review failed social inputs first; Facebook, Instagram, and TikTok publication remain disabled. `--pilot` can inspect disabled sources and allow local publication, so it is not a production-quality approval.

## 10. Handoff, future rollout, and troubleshooting

Record source counts/rejection reasons, UTC/ICT run time, actual provider usage, checks passed/failed/blocked, and local screenshot paths. Share sanitized summaries, not credentials or raw provider payloads. GitHub Actions is implemented on the feature branch; manual dispatch is blocked until the workflow exists on the default branch. Leave `TRENDING_SCHEDULE_ENABLED` unset/false and `providers=false`. Production migration, deployment, default-branch merge, and schedule activation are separate rollout steps, not teammate onboarding tasks.

| Symptom | Check |
|---|---|
| Blank or stale UI | Use port 8083, confirm API URL 4101, restart Expo after changing environment, inspect browser console and `/cities`. |
| Feed is empty | Check import report, city/filter, original publication/session dates, 72-hour verification expiry, and that both processes use the same database. |
| Missing relation | Run the setup helper only against a new empty DB; an older discovery-only database lacks other service tables. |
| Browser source skipped | Add `--browser`; ensure Chrome is installed and `LO_BROWSER_CHANNEL=chrome`. |
| Bright Data preflight blocked | Check Finance permission/account match and re-inspect an expired receipt; do not remove the free-only gate. |
| Google search unavailable | Expected until project ownership and free allowance are verified; keep the local guard. |
| Images are placeholders | Expected: publisher image permissions have not been approved. |
| Browser test lacks Hanoi match | Fresh setup has no venue seed; inspect evidence and establish a real local match, or report the path blocked. |
| Auth callback mismatch | Public Explore uses 8083; existing Auth0 callback uses 8081. Configure real login separately. |
| Disk pressure during Go tests | Use `encore test -p 1 ./...`; avoid installing Xcode for the browser preview. |

Stop Expo/Encore with Ctrl-C. To stop only this guide's PostgreSQL cluster, run `pg_ctl -D "$HOME/.local/share/lo-teammate-postgres" stop`. Restart later with the same `pg_ctl ... start` command from step 4; **do not** rerun `initdb`, `createdb`, or the bootstrap helper. Preserve the database and rerun website collection for fresh evidence.
