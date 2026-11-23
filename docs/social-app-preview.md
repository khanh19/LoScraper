# Reviewed social examples in the local app

The current preview contains 15 user-selected TikTok examples and nine Instagram
examples. This is relevance review, not factual approval or weekly publication.
No production database or public feed was changed.

## Run

From LoScraper, export known records from the existing local accounting ledger:

```sh
PYTHONPATH=. .venv/bin/python -m trending.social_preview \
  --database-url postgresql://macbook@127.0.0.1:55443/lo_engine_accounting \
  --selection .state/social-app-preview/selection.json \
  --output .state/social-app-preview/report.json
.venv/bin/python -m trending.diagnostics \
  --report .state/social-app-preview/report.json
```

From LoApp:

```sh
PATH=/opt/homebrew/opt/node@24/bin:$PATH npx expo start --web --port 8082
```

Open http://localhost:8082/discovery/sources. The Discover screen also links to
this local-only view. The service binds loopback, never triggers provider jobs,
and exposes no signed media URLs. It is deliberately unavailable on a phone.

## Data and imagery

`social_preview.py` matches selected canonical post URLs against completed API
records and exports original captions, publication dates, snapshot counts and
literal address excerpts. Unknown locations/schedules stay unknown. It retains
up to six original post image references in an ignored private manifest for
subsequent association/permission review; it does not download or republish them.
Cards use licensed category illustrations with visible attribution, or a neutral
placeholder when category/image availability is unknown. Captions are not a
completed multimodal extraction or an independent venue verification.

## Validation — 2026-11-15

- 137 scraper tests passed, including PostgreSQL integration on the disposable
  `lo_trending_guards_test` database. Existing preview/accounting databases preserved.
- Frontend `npm run validate` passed: type checking, lint (39 existing warnings,
  zero errors), and 183 Maestro flow definitions. This is not a native test.
- Real local diagnostic API/browser: 24 retrieved samples; Instagram/Hanoi gives
  3 samples; expansion/collapse works; 414px and 1440px have no horizontal overflow;
  no browser console errors. These are held diagnostics, not published feed results.
- Encore discovery tests blocked during Go dependency download by disk exhaustion.
- No provider jobs or paid inference were submitted in this implementation pass.

## Creator places and migration order

Apply backend `20261115060000_discovery_creator_places.sql` after the existing
migration sequence, then use the updated importer. Account `authority_type`
defaults to `organizer`, preserving existing rows. Explicitly reviewed `creator`
accounts can establish **places only**, with matching registry role, publication
permission, independent venue/address/city evidence, recent publication and fresh
verification. Creator posts cannot establish events or authoritative cancellations.
Revoked accounts/venues remain withheld. Stable IDs and public query parameters
are unchanged; `authority_type` may now be `creator`.

Cards truncate titles to 80 characters and two lines. Original captions and
snapshot counts remain behind the evidence toggle. No count is labelled viral.
Unknown image categories use a neutral placeholder; available licensed category
illustrations remain visibly labelled. Private media candidates never reach clients.

## Remaining publication blockers

The 24 records are relevance samples, not approved extracted claims. This pass
has not created human claim-review receipts or enabled routine social publication.
The existing `publish_reviewed` command still requires claim-hash approval,
accepted evidence, a reviewed account and independently verified venue. Apply it
only to qualifying evidence in an isolated `lo_setup_check_*` database.

No new venue-image permission was established. Search matches alone do not resolve
branch identity or reuse rights. Keep licensed illustrations until both checks pass.
Native-device testing, verified social feed publication, and a successful Encore
run remain outstanding. No deployment, merging or schedule activation.
