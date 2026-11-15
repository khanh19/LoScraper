# Coverage follow-up: review and local setup

This branch follows the reliability work; it does not deploy or activate a schedule.
The existing seven-day window, 72-hour verification expiry, whole-event schedule
holds, and website-only display authority remain in force.

## Changes

- `trending/entries.py`: section-scoped roundup extraction, stable entry keys and
  review locators. A malformed section does not discard valid siblings. A weekday
  mentioned in surrounding commentary cannot change the enclosing day's session.
- `trending/adapters.py`: bounded listing pagination, Da Nang food/experience
  discovery and reserved capacity for campaign activity links; dedicated Life of
  Da Nang and Saigoneer adapters; broader VnExpress destination extraction.
- `trending/store.py`: source + canonical URL + entry key identity, preserving
  existing empty-key observations. Missing entries are not cancellations. Reused
  place entries retain their original evidence date rather than becoming fresh
  because a rotating roundup was updated.
- `trending/health.py`: fetched listing/detail pages, extracted entries, acceptance
  yield, and per-city/kind counters in source diagnostics. Failure reasons remain
  sanitized. Empty results do not mean collection failed.
- [Image permissions and category photos](imagery.md).
- [Bounded social pilot and results](social-pilot.md).

## Teammate setup, in order

1. Check out the follow-up branches in **all three repositories**. They initially
   target `stephen-develop`, not the normal integration branch. Review parent
   reliability PRs first; retarget only after reconciling their eventual merge.
2. Follow [teammate-setup.md](teammate-setup.md) for Python, existing Chrome,
   PostgreSQL, Encore and Expo. Do not replace another developer's `.env`.
3. Create a new empty local database. The bootstrap applies the entire migration
   sequence, including `20261109060000_discovery_entries.sql`,
   `20261109070000_discovery_images.sql`, then
   `20261109080000_discovery_pilots.sql`. Existing previews are not reset.

   ```sh
   createdb -h 127.0.0.1 -p 55442 -U "$USER" lo_setup_check_coverage
   .venv/bin/python docs/setup_local_database.py --port 55442 --user "$USER" \
     --database lo_setup_check_coverage
   ```

4. Set `DATABASE_URL` to that loopback database in the scraper process. Collect
   without `--providers`; no provider key is needed:

   ```sh
   DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_setup_check_coverage" \
     .venv/bin/python -m trending --browser --write-db --limit 12
   DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_setup_check_coverage" \
     .venv/bin/python -m trending.health --city danang --json
   ```

   Use `--pilot --sources saigoneer` for a disabled adapter's isolated evaluation.
   Exit codes remain 0 complete, 2 partial, 1 fatal. Validation rejections alone
   are a complete run. Never relax freshness just to populate a city.
5. Start Encore with `LO_DATABASE_URL` pointing to the same database and
   `LO_DISABLE_GOOGLE_REQUESTS=1`, on port 4103. Start Expo using
   `EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://localhost:4103 yarn expo start
   --web --port 8085 --max-workers 2`. Preview: http://localhost:8085/tabs/explore.
6. Run the checks below. Do not enable a schedule or social provider through this
   setup. Provider accounting must use its existing canonical ledger, not this
   fresh feed database; see the separate pilot guide.

## Evidence, 8 November 2026

Baseline and updated adapters were evaluated against shared cached source pages,
with one frozen clock and the same 12-detail-page budget per source. Supplemental
new adapters add source inputs; this is not a controlled experiment on ranking.
All nine accepted candidates were checked against their source content for venue,
city and schedule/publication evidence. No publisher image is approved.

| City | Baseline | Updated | Places in updated feed |
|---|---:|---:|---:|
| HCMC | 4 | 4 | 0 |
| Hanoi | 3 | 3 | 1 |
| Da Nang | 1 | 2 | 0 |

Life of Da Nang adds the Dragon Bridge schedule. The weekly roundup parser works,
but this captured edition's eligible-looking Friday entry was actually expired.
The audit caught and fixed that date-context error; its temporary local preview
record was removed before final validation. A multi-venue campaign is withheld
rather than presented as one identifiable destination. Saigoneer remains disabled:
no fresh eligible destination survived the bounded sample. No new recent place
was found; this is a coverage limitation, not a reason to refresh old content.

Passed: 69 scraper unit/PostgreSQL tests; Encore `test -p 1 ./...`; frontend TypeScript;
lint (0 errors, 4 existing warnings); replay with stable IDs; actual API and all
three cities × three filters; matched local venue navigation; mobile/desktop
image loading and attribution. The unmocked browser pass had no page exceptions
or failed requests; the existing favicon 404 remains. Search fault injections are
separate controlled checks, not live Google evidence. Google requests remain off.

```sh
TRENDING_TEST_DATABASE_URL="postgresql://$USER@127.0.0.1:55442/lo_trending_guards_test" \
  .venv/bin/python -m unittest discover -s tests
LO_QA_API_URL=http://localhost:4103 LO_QA_APP_URL=http://localhost:8085 \
  .venv/bin/python tests/browser_live.py
LO_QA_APP_URL=http://localhost:8085 .venv/bin/python tests/browser_images.py
```

A subsequent fresh CLI run was **partial**: Life of Da Nang completed (one
accepted, 16 rejected), while VnExpress encountered a browser listing error.
The earlier valid VnExpress observation remained stored without a refreshed
verification timestamp. This demonstrates failure isolation, not a successful
fresh VnExpress run.

The PostgreSQL tests reset **only** the named disposable test database. Local raw
pages, candidates and provider responses are not committed. Sanitized counts and
selected screenshots are in `docs/evidence/coverage-20261108/`.

Next: validate a fresh Saigoneer sample and additional independently dated Da Nang
place mentions; obtain actual publisher reuse permission; expand social quality
only under a separately authorized budget. Native iOS execution is still untested.
