# Seven-day verification and phone preview coverage

Successful source verification now lasts 168 elapsed hours. At exactly 168 hours the record is withheld. This does not extend event sessions or the seven-day publication window for place mentions. Failed retrieval never renews verification. Daily checks and the agreed twice-weekly full-update schedule are unchanged.

## Migration and local setup

Apply every discovery migration in filename order, including `20261115060000_discovery_creator_places.sql`, then `20261115080000_discovery_weekly_verification.sql`. The phone preview was missing the creator migration; both were applied locally. Restart the backend after updating Go code, reload Expo Go after updating the client. Production databases and provider accounting were untouched.

## Coverage run — 15 November 2026

Direct website collection only, at most 30 detail pages per source, using installed Chrome where needed. The expanded eight-source run completed partially. A separate Life of Da Nang monthly-calendar run retrieved 30 detail pages; after review and stricter extraction, nine candidates passed. Sources were fetched live; no provider credits or fabricated data were used.

| City | Weekly cards | Planning cards | Total |
|---|---:|---:|---:|
| HCMC | 2 | 2 | 4 |
| Hanoi | 2 | 2 | 4 |
| Da Nang | 10 | 0 | 10 |

These are API-visible counts, not a claim of 20 distinct reviewed outings or balanced coverage. All currently eligible cards are events; recently mentioned places remain empty. Categories include nightlife, music, culture, cafés hosting activities, workshops, and sports. Restaurant/bar/market/experience coverage remains incomplete.

The new month-based Vietnamese calendar seed follows Vietnam time. Event category and text come from that event's structured name/description, excluding related cards. City-only addresses are held. Conflicting province metadata is rejected even when the publisher appends a supported city.

Review withheld incomplete city-only snapshots in the local database (facts version 0 with a review reason; original evidence preserved). Also withheld the Yên Tử/Quảng Ninh item mislabeled HCMC. Two Chillpark/Dạ Quang listings disagree on their end time: both snapshots remain withheld and their canonical URLs have collection review holds in `sources.json`. Resolve against organizer evidence before removing those holds. No cancellation was inferred.

## Remaining gaps

- Hanoi Grapevine: TLS protocol failure from this machine, also no successful browser retrieval.
- Ticketbox: rendered listing returned no usable detail links.
- Saigoneer: partial HTTP 429; retrieved place stories lacked qualifying recent evidence.
- Fantasticity/VnExpress: insufficient usable location/schedule/freshness evidence in this bounded sample.
- Coverage target remains approximately 7 HCMC / 7 Hanoi / 6 Da Nang; do not weaken validation to fill quotas.

## Validation

Scraper unit and real local PostgreSQL tests pass, including exact seven-day expiry, current-month discovery, primary-text isolation, city-only holds, and province conflicts. Encore discovery tests pass. Frontend typecheck, lint (39 existing warnings, zero errors), and 183 Maestro flow definitions pass. All three cities and all weekly kind filters were checked through real HTTP responses; planning was checked per city. iPhone visual confirmation remains with the user. No deployment, merge, or schedule activation.
