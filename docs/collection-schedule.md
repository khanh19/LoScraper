# Trending collection schedule

User-confirmed cadence, starting **1 December 2026**, timezone **Asia/Ho_Chi_Minh**:

| Day | 06:00 Vietnam time |
| --- | --- |
| Tuesday, Friday | Recheck stored website entries, then full discovery across all enabled website adapters and all three cities |
| Other days | Recheck stored website entries only |

First full runs: December 1 and 4. First maintenance run: December 2.
GitHub uses `0 23 * * 1,4` UTC for full runs and `0 23 * * 0,2,3,5,6` UTC for
rechecks. Both map to 06:00 the next day in Vietnam. Scheduled jobs derive
the due slot from GitHub's original workflow run creation time and the
triggering cron. Job delays and reruns of that run keep the recorded slot.
Slots before December 1 skip collection. Missing run metadata stops a scheduled
job before collection. Manual dispatch remains available before then. Scheduled
starts can be delayed by GitHub. [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) · [Workflow run metadata](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)

## What a recheck does

`python -m trending --browser --write-db --refresh-existing`

Uses enabled website observations for places mentioned within seven days and
events with remaining sessions within 30 days. Re-fetches their existing pages,
re-parses and validates, and upserts only known URL/entry-key pairs. It does not
visit listing pages or discover/import sibling entries from roundups. Ordinary
adapter enrichment may follow venue corroboration links. No provider jobs run.

A successful parse/write renews verification, never original publication time.
Failures or disappeared entries retain old observations and verification time;
missing evidence is not cancellation. Confirmed cancellations use the existing
cancellation path. Whole-event conflicts and seven-day verification expiry still apply.
The existing receipts/health command report failures and interrupted work.
Identical evidence reached through both a catalogue and a legacy link counts
once per recheck. Distinct evidence for the same observation is still evaluated.

Each source checks at most 200 distinct pages, oldest verification first. Exceeding
that bound produces `refresh_page_limit` and a deferred-page count, not a false
complete result. Missing known entries produce `existing_entry_not_recovered`.
The default recheck visits the other publishers before Ticketbox, which had the
largest set of pending pages in staging. Explicit `--sources` order still works.
Verified observations are saved as each page finishes. A slow or interrupted page
leaves previously committed work and the unfetched observations intact.
Full discovery retains the bounded 20 detail pages per source plus existing checks;
“full” means all enabled sources/cities, not unlimited scraping or a minimum feed size.
The workflow allows 45 minutes for a recheck alone and 90 minutes for a full
run, including setup and its recheck. A slow serial staging run spent more than
40 minutes on discovery alone, and two later rechecks hit the previous 25-minute
cutoff. Page limits and per-request retries stay the same. Inspect interrupted
receipts if either timeout is reached.
Collector connections enforce a one-minute idle-in-transaction timeout so an
abandoned pooled session cannot retain the import lock. Run staging imports
serially when validating outside GitHub Actions.
Page fetches write at most one heartbeat every 30 seconds. The collector still
records each candidate outcome and the final run status as they happen.
A handled interruption ends the active source receipt as partial if it already
accepted candidates, or failed otherwise. An abrupt process kill still relies on
the health report's stale-heartbeat detection.
The collector writes all verified sessions for an event in one database statement
inside that candidate's transaction. This keeps repeated shows from paying a
separate database round trip for every session.
An explicit activity in the title takes priority over words in the venue or
article body when assigning a category. For example, the Hanoi lacquer and
woodcraft exhibitions belong under culture even though the venue name contains
“Thể thao”. [Lacquer exhibition](https://hanoigrapevine.com/vi/2026/11/trien-lam-con-duong-son-mai-viet-nhat/) ·
[Woodcraft exhibition](https://hanoigrapevine.com/vi/2026/11/trien-lam-luu-dau-thu-moc/)
Compact date ranges such as `13–28/11/2026` retain both endpoints. A range
without an explicit recurrence rule remains date-only.

Life of Da Nang collection reads the Vietnamese calendars through the end of the
30-day horizon. It shares the same detail-page cap across calendar and weekly
listings, giving both weekly and planning leads a chance before the cap. The
individual event pages still determine eligibility. Nhà hát Hồ Gươm's performance
pages provide another planning source. The collector stores the exact announced
show days when the venue omits the end time.

On November 23, the Hồ Gươm Opera catalogue returned 200 while three linked
performance pages returned 404. The catalogue showed two complete slots for
St. Petersburg Night and Don Quixote, but only one timed slot for the gala's
two announced dates. The failed detail fetches left those observations at their
previous verification times. [Publisher catalogue](https://hoguomopera.vn/chuong-trinh-bieu-dien?page=1) ·
[Staging recheck](https://github.com/khanh19/LoScraper/actions/runs/45219666848)

For reviewed programs, the collector can now recover a missing detail page
through the publisher's catalogue. It matches every visible local-time slot to
the program ID and its own booking page, checks the theatre address, and updates
the existing observation and card IDs. The app opens the reachable programme
catalogue. An incomplete or inconsistent slot set never renews verification.
The gala needs its announced and booked dates to agree before this fallback
can verify the whole event.
[St. Petersburg booking](https://hoguomopera.vn/dat-ve/127) ·
[Don Quixote booking](https://hoguomopera.vn/dat-ve/131)

November 24's rehearsal found that several individual Opera programme pages
returned 404. Discovery now records 404 and 410 per page and continues within
the existing limit. Three consecutive other fetch failures still stop that
source. A response body interrupted in transit gets one retry, and only a
complete successful response is cached. The rehearsal observed an interrupted
TicketGo body. [Hosted rehearsal](https://github.com/khanh19/LoScraper/actions/runs/45250748714)

The Opera's reviewed catalogue fallback now includes **Lang Lang Piano Recital
in Hanoi**. Its individual programme link returns 404. Both visible slots agree
with their corresponding booking records at 40 Hàng Bài. The sessions are
December 18 and 20, 20:00–23:00 Vietnam time. Each run still checks both records.
[December 18 booking](https://hoguomopera.vn/dat-ve/137) ·
[December 20 booking](https://hoguomopera.vn/dat-ve/138)

New discovery uses the Opera catalogue's visible and structured timetables
to skip archived programmes before spending its detail-page allowance. A row
qualifies for skipping only when its session set agrees between both views,
every slot has ended, and ticket sales are unavailable for each slot. Rechecks
of stored observations and explicitly supplied leads still fetch their URLs.
If every linked programme is a confirmed archive entry, the source completes
with zero new candidates. Missing programme links still surface as a failure.
On November 24, a read-only comparison against the live catalogue kept the
same three eligible programmes and reduced missing detail pages from seven to
one. The ballet gala remained the one failure in that rehearsal. The catalogue
describes two nights but lists a timetable and booking for only December 8.
When the collector confirms that discrepancy, it withholds the event until
both dates agree. The hold preserves the prior verification time and IDs.
A hold from the catalogue applies to the old programme URL only when the
event identity matches. If both dates later have agreeing bookings, the
collector can clear the hold and show the existing card again.
[Publisher catalogue](https://hoguomopera.vn/chuong-trinh-bieu-dien?page=1) ·
[December 8 booking](https://hoguomopera.vn/dat-ve/128)

Two Hanoi sources seed reviewed public announcements directly. Varan Vietnam's
exhibition block gives the admission dates and daily hours for Một bát thương.
The collector creates one session for each published day. The Hoàn Kiếm
heritage announcement gives a date range for Dược trà at 40 Lãn Ông. Its card
uses date precision because the section omits hours. The other activities in
the press release require separate review, including reconciliation of dates
that differ from the Creative Design Festival listings.
[Varan Vietnam](https://varanvietnam.com/project/varan-vietnam-tai-trien-lam-mot-bat-thuong/) ·
[Hoàn Kiếm announcement](https://phocohanoi.hoankiem.vn/tin-tuc/ngay-di-san)

The Nhà hát Tuổi trẻ calendar renders times in the browser's timezone. The
collector renders in Vietnam time and accepts the two reviewed November 29
performances only when the booking table matches their published starts and
the theatre's contact page confirms the Hanoi address. Run this source with
`--browser`. [Theatre booking calendar](https://datve.nhahattuoitre.vn/) ·
[Ministry announcement](https://bvhttdl.gov.vn/nha-hat-tuoi-tre-to-chuc-tuan-bieu-dien-nghe-thuat-huong-ung-ngay-van-hoa-viet-nam-2411-20260228171220914.htm)

The Yoga Lab Hanoi adapter pairs the reviewed November 29 class with its
own timetable block, then verifies the Hanoi address on the booking page
linked from that timetable. The reviewed date resolves the workshop page's
omitted year for this class. Other workshop slots require separate evidence.
[Workshop calendar](https://www.yogalabhanoi.com/events) ·
[Booking and directions](https://www.yogalabhanoi.com/book-a-class)

Two Da Nang events are held pending schedule confirmation. The Ariyana Christmas
Market publications disagree on the start day and opening hour. Pullman's official
pages give different hours for the same tree lighting. [City market notice](https://1022.vn/en/su-kien/da-nang-christmas-market-2026/) · [Market organizer](https://danangchristmasmarket.com/) · [Pullman program](https://www.pullman-danang.com/news/festive-season-2026/) · [Pullman event overview](https://www.pullman-danang.com/discovery/event/danang-christmas-market/)

The Furama tree lighting is corroborated by the exact venue link, the resort's
street address, and the city's matching schedule. Its December 3 session is
17:30–19:00 Vietnam time. The separately booked dinner is outside that session.
The collector checks these pages again before renewing evidence.
[Life of Da Nang](https://lifeofdanang.com/vi/danang/city-christmas-tree-lighting-at-furama-resort-2026-12-03) · [Resort address](https://team.furamavietnam.com/khach-san.html) · [City tourism calendar](https://danangfantasticity.com/en/discovery/christmas-2026-new-year-2027)

The Da Nang Jazz Festival uses a reviewed organizer link and Furama's street
address. The collector compares the organizer's two explicit 17:00–23:00
sessions with the listing's date coverage and stated hours before storing
them separately. The bounded November 24 staging import also accepted
REALITY's December 9 book club, whose organizer lists 19:30–21:00 at
86 Mai Thúc Lân. Both events resolved in the expected API section and detail
response. The stored snapshot meets all six coverage targets at November 28
06:00 Vietnam time, including Da Nang at 12 weekly and 5 planning. This
forecast uses the stored evidence and excludes any later collection.
[Jazz organizer](https://danangjazz.com/) · [Jazz listing](https://lifeofdanang.com/vi/danang/city-da-nang-jazz-festival-2026-at-the-furama-2026-11-27) · [REALITY session](https://app.realitydn.com/events/bb88d620-dd4c-4e9e-8466-1e39f3a1ae70)

When both sources give complete and different schedules for an existing event,
the collector records a hold on the reviewed observation. The shared evaluator
withholds the event and its pending reminder until a later successful check
clears the hold. The hold preserves the last successful verification time.
Incomplete schedules and failed fetches leave the existing observation alone.
Apply backend migration `20261122110000_discovery_confirmed_schedule_holds.sql`
before running the updated collector.

The notification companion branch records whether the publisher explicitly
cancelled the event. Postponements and title-only warnings can hide the card
without triggering a cancellation alert. Ticketbox confirmation comes from its
official event endpoint with the matching event ID. A replay older than existing
evidence cannot overwrite the current status. [Notification collector PR](https://github.com/khanh19/LoScraper/pull/13)

## Activation checklist — not yet active

The November 23 check found that `main` still contains only the legacy scraper
workflow. The reviewed schedule and its staging rehearsals are in the
open PR stack. The repository has the staging database secrets. The scheduled
database secret and enable switch are still absent.

1. Review PR #6 and its follow-ups. Before the workflow reaches `main`, dispatch
   **Scraper CI** on the reviewed staging branch. The `staging_collection` input
   calls that branch's workflow with the two staging secrets.
2. Apply all discovery migrations to the intended feed database and verify the app
   backend reads that same database. The coverage summary needs backend migration
   `20261123100000_discovery_coverage_snapshot.sql` and `EXECUTE` on
   `public.discovery_coverage_snapshot()` for that environment's collector role.
   The function returns counts and does not require table access to publisher
   approvals, verified venue records or provider accounting. Keep the target
   separate from the local accounting database.
3. Run manual `mode=full`, `pilot=true`; inspect source coverage.
4. Set `TRENDING_STAGING_DATABASE_URL` for manual writes to the isolated staging
   feed with `sslmode=verify-full`. For Supabase, set
   `TRENDING_STAGING_DATABASE_ROOT_CA` to the project's published root certificate.
   Select `check-staging` under `staging_collection` to verify TLS, check the
   collector connection and website collection grants, and read the feed counts.
   This runs without starting a collection. Select `full`, then `refresh` for the
   staging writes. Check stable IDs, timestamps and health without erasing data.
5. Store the verified scheduled feed target as **TRENDING_DATABASE_URL** in Actions
   secrets with `sslmode=verify-full`. Use **TRENDING_DATABASE_ROOT_CA** when the
   target uses its own CA. Once the workflow is on `main`, dispatch it with
   `mode=check-scheduled` while the enable variable is still off. Compare the
   read-only coverage summary against the intended deployment. Every scheduled
   run repeats this check before starting collection. The check rejects replicas
   and read-only connections. It plans the collector's website statements with
   PostgreSQL EXPLAIN in a read-only transaction. It covers source registration,
   image permissions, recheck selection, place matching, item and observation
   writes, session replacement, and receipt and item cleanup. The manual full
   and refresh runs still verify actual writes and row access, including policies
   that can only be evaluated for real rows.
6. Set repository variable **TRENDING_SCHEDULE_ENABLED=true** after those checks.
   Keep both database secrets separate from the legacy workflow target.

To pause, set the variable false or disable the workflow. No raw payload uploads.
After a collection command exits, its Actions summary shows the weekly and
planning results for each city and the counts of eligible cards with Instagram
or TikTok evidence. It uses the collection database and a single read-only feed
snapshot. Targets are goals for coverage. A shortfall stays visible and does not
loosen eligibility or change the collection exit status. A missing coverage
report fails an otherwise successful run. The same check can be used with the
database connection already configured in the operator terminal.

```sh
python -m trending.coverage
```

Provider/social automation is still gated: this cadence covers website adapters.
Website-only runs can use a scoped database role without access to provider jobs.
It does not make TikTok/Instagram posts verified, renew social evidence, or run
OpenAI/Apify/Bright Data/SerpAPI automatically. Those need a separate validated
refresh path and allowance checks before inclusion in unattended collection.

## Verification

The isolated staging database's shared eligibility evaluator returned these
website-backed counts on 23 November 2026 Vietnam time. They describe a
point-in-time feed with expiring evidence.

| City | Weekly / target | Planning / target |
| --- | ---: | ---: |
| Hanoi | 16 / 14 | 8 / 7 |
| Ho Chi Minh City | 19 / 18 | 12 / 7 |
| Da Nang | 14 / 12 | 5 / 5 |

An earlier daily staging recheck processed 71 existing observations from six
publishers in 10 minutes and 23 seconds. It completed with zero fetch or write
failures, preserved the item IDs, and made no metered requests.

On 23 November, a separate full run imported 25 candidates before database
connection errors prevented its final database receipt. The Mac slept during
that run, so the 42-minute result is a poor baseline for a hosted runner.
A subsequent manual recheck ended at a 25-minute cutoff after 9 accepted and
3 rejected candidates and 4 fetch or extraction failures. Vietnam Nightlife
finished partially and Ticketbox was still processing. The parent receipt
recorded a failed run and the feed evaluator still returned 73 cards. These runs
used website collection only. The later hosted rehearsals below completed the
manual recheck and full-run gates.

The next all-source staging recheck with batched session writes accepted 51
candidates before the 25-minute cutoff. It rejected three candidates and recorded
three publisher failures, plus the interruption. The active TicketGo receipt
ended as partial, with its five finished imports preserved. The feed still met
all six targets in the table above. A separate publisher replay saved both
corrected Da Nang categories with stable IDs. Two staging attempts hit a TLS
protocol error on Hanoi Grapevine. The same pages loaded in Chrome with TLS
verification enabled. The collector now uses the browser for this source only
after an HTTP client TLS failure when `--browser` is set. The targeted staging
recheck then accepted both Hanoi corrections with their original IDs.

The page-by-page staging recheck finished in 5 minutes 39 seconds. Five
publishers refreshed 65 observations with zero database errors. Ticketbox also
returned three rejected entries. Hanoi Grapevine failed before it could verify
eight stored entries, so the run ended as partial. The browser reported
`ERR_SSL_PROTOCOL_ERROR`. New browser receipts retain the code without the raw
navigation URL or exception text.

The following full staged collection completed in 9 minutes 39 seconds. Five
publishers accepted 25 candidates that matched existing item IDs. The run
rejected 90 candidates and recorded two Hanoi Grapevine listing failures. That
publisher was the only failed source. No database errors or metered requests
were recorded in either run. The staged feed still had 73 eligible items and
met all six city targets. Both runs ended as partial.

The first GitHub Actions recheck completed in 4m37s with 73 accepted
observations, three rejections and zero failures. The full rehearsal then
completed its recheck and accepted 35 candidates in the discovery phase,
with 101 rejections and zero failures. Both used the dedicated QA database
and website collection. [Recheck](https://github.com/khanh19/LoScraper/actions/runs/45101943631) ·
[Full rehearsal](https://github.com/khanh19/LoScraper/actions/runs/45102243085)

Review of the three new Da Nang cards held two pickleball listings. Picklehead's
visible agenda lists starts omitted from its structured data. Spin City's
Sunday session is at PICO Pickleball while its Tuesday and Thursday sessions
are at PapiPoint. The collector compares the visible and structured starts for
the selected day, and keeps Spin City held until one card can show the correct
venue for every session. The holds preserve item IDs and verification times.
The original Ticketbox source confirmed the children's theatre listing. All
six staging coverage targets still passed after both holds. [Picklehead](https://lifeofdanang.com/vi/danang/picklehead-pickleball) ·
[Spin City](https://lifeofdanang.com/vi/danang/spin-city-pickleball-social) ·
[Theatre listing](https://ticketbox.vn/kich-thieu-nhi-vi-nu-cuoi-tre-tho-26824)

Life of Da Nang's structured data for the Cơ Tu exhibition listed only the
morning opening hours. Its visible schedule and the city's tourism notice both
list 07:30–11:00 and 13:30–16:30 Vietnam time. The adapter now keeps both
windows on each dated, scheduled day supplied by the publisher. It holds the
event if a structured window contradicts either range. [Publisher schedule](https://lifeofdanang.com/vi/danang/weekly-co-tu-plants-exhibition) ·
[City tourism notice](https://danangfantasticity.com/en/trien-lam-va-toa-dam-chuyen-de-thuc-vat-trong-doi-song-van-hoa-co-tu)

The next hosted full run accepted 33 candidates, rejected 104 during validation,
and recorded zero collection or write failures. The public API still withheld
both held listings and served the children's theatre detail. The same isolated
environment served the verified DẾ GARDEN workshop from a signed-in reminder on
a physical iPhone. [Corrected full rehearsal](https://github.com/khanh19/LoScraper/actions/runs/45104600109) ·
[Device rehearsal](https://github.com/khanh19/LoApp/blob/db299b3/docs/design/notifications/README.md#hosted-release-rehearsal)

A venue review found two Hưng Yên shows that Ticketbox placed under Hanoi or
Ho Chi Minh City and an online merchandise listing. At that point 68 eligible
cards remained. Later website imports brought the feed to the counts above.
Apply backend migration
`20261122120000_discovery_correct_ticketbox_locations.sql` to withdraw the older
fact snapshots without deleting records or creating cancellation alerts.
[VinPalace venue](https://vinpearl-theatre.vinwonders.com/) ·
[YeaH1 venue announcement](https://www.yeah1group.com/concert-anh-trai-vuot-ngan-chong-gai-2026-completely-sold-out-in-88-minutes-of-ticket-sales?locale=en) ·
[Ticketbox online listing](https://ticketbox.vn/combo-khongxinhe-kosmik-2026-26880)

Ticketbox discovery uses the public on-sale listings when they supply event
links. The collector still checks each detail page and its individual sessions.
The live on-sale check fetched six detail pages, accepted five and rejected one
with no fetch failures. The pre-sale section returned three event links that
were still HTTP 404. The daily recheck continues to use stored event URLs.

The manual Furama run imported one eligible event without a failed fetch or
provider usage. Controlled tests cover matching dates and times, competing
sessions, missing address evidence, and venue ambiguity. Scheduling remains disabled.

### Reviewed HCMC listings on Vio

The website collector reads four reviewed Vio event URLs. Each page must
match the reviewed event title, organizer and branch. The adapter uses
individual timestamped sessions and compares their days, start and end
times against the visible booking timetable and event description. When a
booking row groups multiple sessions on one day, the description must
corroborate all of that day's times. Conflicting schedules hold the event.

On November 24, three live pages passed. Kloud Art Thảo Điền listed one
November 27 session, Kloud Art The Estella listed two November 29 sessions,
and Saigon Wine Fair listed December 19 and 20 sessions at Saigon Outcast.
Vinhomes Central Park's workshop description gives 19:00–21:00 while its
booking row gives 20:00–22:00 on November 28. The collector rejected it.
Run the same website-only check with `python -m trending --sources vio --city hcmc --limit 4`.
[Vio wine fair](https://vioapp.io/vi-vn/event/saigon-wine-fair-2026) ·
[Kloud Art branches](https://kloudart.com/) ·
[Vinhomes booking page](https://vioapp.io/vi-vn/event/kloud-art-vinhomes-central-park-workshop-gom-giang-sinh)
