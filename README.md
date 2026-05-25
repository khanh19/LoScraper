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

Requires `DATABASE_URL` or `SUPABASE_DB_URL` (Postgres connection string with write access).

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

Set one of these repository secrets:

- `DATABASE_URL`, or
- `SUPABASE_DB_URL`

Use the Supabase **direct** Postgres connection string (not the anon key).
