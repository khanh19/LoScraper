# Scraper CI

Required check: **Offline scraper tests**.

Python 3.12 installs pinned requirements, checks dependency consistency, and runs `python scripts/ci_tests.py`. This explicitly excludes the two PostgreSQL modules; all other skipped tests fail CI. No website/provider calls are intentionally made by the test suite.

Real database tests run in **LoAppBackend / Encore and PostgreSQL contracts**, using this public repository at an immutable commit and the backend PR's private migration files. The backend workflow must advance its scraper `ref` for each scraper change requiring contract validation. A green scraper unit job alone is not proof of database compatibility. This arrangement avoids putting private backend checkout credentials into a public PR workflow.

Local full validation:

```sh
LO_BACKEND_ROOT=../LoAppBackend \
TRENDING_TEST_DATABASE_URL=postgresql://localhost:55443/lo_trending_test \
.venv/bin/python scripts/ci_tests.py --postgres
```

Use only the disposable loopback test database: these tests truncate tables. Never point them at preview or accounting databases. The full runner fails if PostgreSQL tests skip.

Both collection workflows are manual-only. Their shared concurrency group prevents overlapping website ingestion jobs; CI does not import real data or access collection secrets.

All PR targets (including stacked PRs), pushes to `main`, `develop`, and `stephen-*`, and manual dispatch run CI. Jobs have read-only repository permissions, time limits, and cancel superseded runs. They use no provider credentials or live scraping. No deployment, signed iOS build, merge, or schedule activation is configured.

After the parent PRs merge, an administrator should make the job names below required in branch protection/rulesets on the integration branches. Workflow files alone do not enforce merge protection. Keep production deployment as a separate, explicitly approved environment gate.
