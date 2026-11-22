# Phone-preview readiness — 21 November 2026

## Latest Expo feed

The Expo API returned 73 distinct cards across six city/section requests at the phone client's limit of 20 per section.

| City | Weekly served / target | Planning served / target |
|---|---:|---:|
| Hanoi | 14 / 14 | 8 / 7 |
| HCMC | 20 / 18 | 14 / 7 |
| Da Nang | 12 / 12 | 5 / 5 |

Collection used Ticketbox’s public search and per-event showings, and the Vietnamese Life of Da Nang event directory. Ticketbox session times now come from individual showings. Publisher addresses embedded in a Da Nang listing’s venue field can qualify when they contain an unambiguous numbered street. For the Pullman tree lighting, a manual review additionally matched the resort’s venue, street address and 18:30–20:30 session on December 4. The Firebeat listings are held because two publishers disagree about the schedule. Two booking windows with unresolved opening or performance times are also held.

All six counts are for website-backed events. The local card and original-link inventory is in `pilot-output/targets-20261121/live-sources.md`. All 174 scraper tests passed with PostgreSQL integration enabled. Counts change as sessions end.

## Earlier baseline


Before the additional collection, counts below used the shared
eligibility evaluator against isolated `lo_setup_check_coverage_20261121`.

| City | Weekly actual / target | Planning actual / target | Total |
|---|---:|---:|---:|
| Hanoi | 9 / 14 | 4 / 7 | 13 / 21 |
| HCMC | 6 / 18 | 1 / 7 | 7 / 25 |
| Da Nang | 10 / 12 | 0 / 5 | 10 / 17 |

Each section has its own shortfall. Surplus weekly items do not fill planning
requirements. Existing valid items survive partial imports. All eligible items
in this preview are website-backed events; social and recent-place coverage are
still incomplete. No stored social examples count toward the targets.

## Fresh collection

- Life of Da Nang: 20 detail pages, 4 accepted, 15 rejected; valid imports retained.
- Hanoi Grapevine: TLS handshake failure; no verification timestamps renewed.
- Hanoi Go local pilot: 30 detail pages, 4 accepted, 26 rejected.
- Saigoneer local pilot: 30 pages, 46 entries, none accepted; no recent evidence.
- TicketGo follow-up: 29 previously unvisited leads prioritized within a 30-page
  run; 2 accepted and 28 rejected. Unresolved individual sessions remain held.
- These acceptance totals include updates and duplicate evidence. They are not
  counts of new unique cards. The final eligibility totals above are authoritative.

Run receipts: `ef13a91d-9111-4750-8ad0-5561f212b7f1`,
`dddb2c70-d96e-4db1-b3cb-238f9bbf107d`,
`62c06a53-57f6-4e26-8ac7-ca6e94661734`.

## Checks and limits

- 172 scraper tests passed including PostgreSQL integration tests.
- Real feed/detail API equality checks passed before the backend stopped.
- Frontend typecheck and Maestro flow lint passed; UI lint: zero errors, 41 warnings.
- Eight event-specific nightlife posters returned HTTP 200 with image content.
  Local-only source preview mapping was updated; no image reuse permission claimed.
- The rebuilt Encore API and Metro served the preview on the Mac’s LAN address. Metro bundled the iOS entry successfully.
- Responsive Chrome passed 38 checks against real API responses, including guest entry, city and category filters, API-to-card and detail consistency, source-link copy, return navigation and the private Home login requirement. Physical iPhone validation is pending.
- No new metered-provider requests, deployment, merge or schedule activation.

The app's phone launcher now prints actual counts, section targets and source
coverage, checks stale/malformed feed data, disables bundled social samples, and
uses one Metro worker with a reusable cache. Test instructions are in LoApp's
`docs/expo-go-iphone.md`. API reachability alone is not proof that Expo can render.

Next: scan the local Expo QR on the physical iPhone. Expand eligible planning and recent-place
coverage and separately validate fresh social collection within intact quotas.
