# LoScraper

Scrapes recurring nightlife events from [vietnamnightlife.com](https://vietnamnightlife.com) for Lo! content seeding.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
./run.sh                    # both cities -> events.json
./run.sh hcmc               # HCMC only
./run.sh hcmc --write-db    # scrape and import to Postgres
```

Or directly:

```bash
python lo_scrape_club_trending_events.py --city hanoi --write-db
```

### Database import

Requires `DATABASE_URL` (same Postgres connection string as lo-app-backend).

Apply the schema migration in `lo-app-backend`:

```bash
cd ../lo-app-backend
supabase db push
```

The scraper calls `public.replace_external_events('vietnamnightlife', events)` which deletes prior rows for that source and inserts the latest snapshot.

## GitHub Actions

Workflow: `.github/workflows/scrape-events.yml`

- **Schedule:** Monday and Friday at 05:00 ICT
- **Manual:** Actions → Scrape nightlife events → Run workflow

Set this repository secret:

- `DATABASE_URL` — same Postgres connection string used in lo-app-backend

For GitHub Actions, you can keep the same `db.<project>.supabase.co` URL. If that host is IPv6-only, the scraper automatically rewrites it to the Supabase Session pooler (`aws-0-ap-southeast-1.pooler.supabase.com` by default). Override the pooler host with `SUPABASE_POOLER_HOST` if your project uses a different region.
