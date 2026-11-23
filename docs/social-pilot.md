# Bounded social pilot — coverage-20261108

## Email snapshot verification — 8 November 2026

Read-only progress and snapshot GET requests confirmed that
`sd_mw88d4ve1wyhgxljq2` is ready (both HTTP 200), using the Instagram Reels
dataset `gd_lyclm20il4r5helnj`. It contains one record for
`https://www.instagram.com/reel/DfezjTRTU4a/`, published
`2026-11-08T13:01:20.000Z`. This matches the reel already documented below;
no trigger, retry submission, discovery search, or new reservation was issued.

Its caption mentions Saigon Burger Fest on 14–15 November but provides no
session hours or independently verified street address. Successful retrieval
does not authorize publication or resolve the separate 22:00/23:00 conflict.
The canonical local ledger on port 55439 was unavailable during this check,
so its accounting was not modified and new provider submissions remain blocked.

The provider email distinguishes profile discovery from direct reel retrieval:
All Reels reads the Reels tab, while Discovery by URL reads a profile's Posts
tab. Those discovery modes are not interchangeable with our bounded one-post
requests. Date filters can omit results; an empty response is a coverage gap,
not evidence that no event exists. Validate returned publication timestamps
separately from event sessions, and compare public pages without login.

Local regression check after the schedule-range guard: 83 tests discovered,
51 passed and 32 PostgreSQL-dependent tests skipped because no test database
was configured. This is not a completed database or UI acceptance pass.

Routine social collection stays disabled. This exploratory CLI uses the existing
provider ledger and an isolated feed database. Never copy an empty quota table
into a new preview and treat that as a fresh allowance.

## Before running

1. Apply `20261109080000_discovery_pilots.sql` to the **existing canonical quota
   database**, preserving all earlier jobs and reservations. The isolated feed
   database receives the full discovery migration sequence.
2. Set `QUOTA_DATABASE_URL` to that existing ledger, and `DATABASE_URL` to the
   separate loopback `lo_setup_check_*` feed database. Neither value is printed.
3. Keep scraping and Finance credentials separate in ignored configuration.
   Re-inspect the same account's shared free-credit pool, promotional-only balance,
   transaction history (no deposits), and both auto-recharge controls. Update the
   existing `BRIGHTDATA_FREE_VERIFICATION_JSON` receipt only after those checks.
   `python -m trending.preflight --env-file .env` verifies billing, matching
   credential account IDs, live shared credits and both auto-recharge switches.
   It performs read-only account calls.
4. Provide a local JSON manifest with `queries` (at most six strings) and `posts`
   (at most nine objects containing `url` and the collected `primary` candidate
   payload). The primary must already be imported and fresh in the isolated feed.
   Only Facebook post/video, Instagram post/reel and TikTok video URLs qualify.
   Search results are **not** automatically submitted: inspect association first.
5. Run `.venv/bin/python -m trending.pilot --env-file .env --manifest /path/to/manifest.json`.
   Re-run the same command to poll known jobs. Do not delete ambiguous reservations.

The fixed pilot ID has atomic caps: nine Bright Data single-record attempts,
maximum three per platform, six SerpAPI searches. Provider/monthly locks also
preserve 4,500-credit and 200-search monthly caps and any smaller verified remainder.
Failed requests retain reservations. Unknown submissions cannot be retriggered;
known snapshots resume polling. Pilot reservations survive routine cleanup, so
recreating a preview or waiting 90 days cannot reset the pilot budget.
The fixed-pilot commands check the existing ledger before contacting providers.
They require at least the six SerpAPI reservations, one Facebook reservation,
and two Instagram reservations established by the pilot receipts. An empty
ledger or one missing this recorded history blocks collection. Restore the
complete canonical ledger, including unresolved jobs, before further calls.

No free allowance evidence means no submission. SerpAPI account reads must confirm
an active zero-price free plan before search. Bright Data's receipt covers the
shared pool, including other products, not just this app.

## Endpoint audit

[Facebook post endpoints](https://docs.brightdata.com/products/scrapers/facebook/send-first-request),
[Instagram endpoints](https://docs.brightdata.com/products/scrapers/instagram/send-first-request),
[TikTok endpoints](https://docs.brightdata.com/products/scrapers/tiktok/send-first-request)
and the [async workflow](https://docs.brightdata.com/products/scrapers/scrapers-library/async-requests)
were checked. Direct post collection now sends one URL in the bare input array,
with the limit in query parameters. No profile discovery or comment expansion is
requested. The new Facebook trigger returned a snapshot and one record, unlike
the earlier HTTP 400 attempts. This does **not** establish that Instagram's prior
400 is resolved; no new Instagram job was submitted.

## Actual run, 8 November 2026

The dashboard showed 4,999/5,000 free credits, $7 entirely from two promotional
bonuses, no deposited funds, and both recharge controls off. Fresh billing reads
confirmed the two credentials belong to the same account. The six SerpAPI searches
were reserved in the existing ledger after included allowance checks.

| Platform/path | Result | Actual new usage |
|---|---|---:|
| SerpAPI discovery | Passed retrieval; poor relevant-post coverage | 6 searches |
| Facebook transport | Passed trigger, resumed polling, one record | 1 single-record attempt |
| Facebook evidence | Failed: post did not corroborate the specific event; not imported | 0 published observations |
| Instagram | Blocked: no suitable destination-specific post in this bounded discovery sample | 0 attempts |
| TikTok | Blocked: no suitable video URL in this bounded discovery sample | 0 attempts |

No extra searches or retries were used to fill the nine-record allowance. The nine
records are a ceiling, not a collection target. No subscription, deposit, recharge,
Apify fallback, proxy service, remote browser or video download was initiated.

The canonical ledger retains earlier usage (six SerpAPI reservations and three
Bright Data reservations) separately from this pilot. New reservations total six
searches and one Bright Data unit; polling did not create additional reservations.
Provider billing totals can lag and are not inferred from local job counts.

Regression tests cover concurrent platform-cap reservations, durable replay,
exhausted allowance, zero credentials, ambiguous submission and resumed snapshot
polling. The live result remains a failed quality pilot; social publication is not
ready to enable. First improve organizer/venue URL discovery, then authorize a
new bounded pilot rather than silently resetting this ID's caps.

## Instagram continuation — 8 November 2026

The existing account preflight passed again using the still-valid dashboard
receipt from 05:18 UTC and fresh billing/account reads. This was not a new dashboard
inspection or a claim about the precise live free-credit balance. The canonical
ledger on port 55439 was reused; the existing six-search pilot ceiling was not reset.

Free organizer-page discovery is now available:

```sh
.venv/bin/python -m trending.social_links
# Or inspect up to six explicit public organizer pages:
.venv/bin/python -m trending.social_links --url https://www.saigonoutcast.com/
```

It reads original social links from nested JSON embeds and visible anchors, keeps
entry-specific descriptions/publication dates, filters dated posts outside seven
days, and deduplicates links. It defaults to the reviewed Saigon Outcast organizer
site. It does not call Bright Data/SerpAPI, publish records, or claim that website
embeds are independent social corroboration. Unknown-date links require provider
validation. The live organizer page yielded eight recent Instagram links.

A bounded live Posts request successfully retrieved
[the organizer's event post](https://www.instagram.com/p/Dfa848qFPwL/), published
7 November 2026, for Saigon Burger Festival on 14–15 November at 182 Nguyễn Văn
Hưởng, HCMC. The async job was polled by its existing ID, not resubmitted. This
establishes successful Instagram post retrieval; it does not identify the earlier
HTTP 400's exact cause.

**Publication remains held:** the organizer's post says 12:00–23:00, while
[Vio's ticket sessions](https://vioapp.io/en-vn/event/saigon-burger-festival-2026)
show 12:00–22:00. No primary or social observation was imported for this event.
Do not silently select an end time or use date-only evidence to conceal the conflict.
One snapshot of engagement also does not establish that the event is trending.

The endpoint audit found Reels incorrectly shared the Posts dataset. The collector
now routes `/reel/` to `gd_lyclm20il4r5helnj`, keeping `/p/` on
`gd_lk5ns7kz21pck8jpis`, as documented in the
[Instagram endpoint reference](https://docs.brightdata.com/products/scrapers/instagram/send-first-request).

## November 22 staging check

The bounded Instagram run returned two recent public posts. Both remain lead
evidence pending venue verification. A later read of the same run reconciled its
included usage to $0.0062. Apify's campaign ledger retains all 132 reserved units.

The TikTok submission returned HTTP 400. The actor's run list had no new run,
and its live metadata advertised a $0.50 minimum value for `maxTotalChargeUsd`.
The attempted $0.10 cap was below that minimum. The minimum is a ceiling the
caller must be willing to reserve, with actual usage charged separately. Confirm
the current `pricingInfos[].minimalMaxTotalChargeUsd` with the actor details API
before a new authorized test. The outstanding reservation remains intact, and
this diagnosis did not submit another run. [Actor API](https://apify.com/clockworks/tiktok-scraper/api)
A second single-record reservation tests the organizer's
[recent reel](https://www.instagram.com/reel/DfezjTRTU4a/).

TikTok remains blocked at discovery: public hashtag/search requests failed TLS
checks and installed-Chrome navigation failed. No certificate checks were disabled,
no guessed post IDs were submitted, and no proxy or alternative provider was used.
The organizer website only links to a TikTok hashtag; the reviewed searches yielded
no relevant original video URL. Automatic discovery therefore still needs broader
verified organizer sources exposing original TikTok video links or a separately
bounded, documented discovery endpoint. User-supplied URLs are not the intended
product workflow.

Tests: 74 collected, 46 passed and 28 PostgreSQL-dependent tests skipped in this
pass. The new controlled regressions cover nested embeds, stale/future dates,
deduplication, profile exclusion, and distinct Posts/Reels trigger routing.
Routine social publication remains disabled.

Final result: Posts **and Reels retrieval passed**, one returned record each. The
reel was published 8 November but lacks explicit city/address evidence. Neither
record was published to the feed. Additional usage: **2 Bright Data single-record
attempts, 0 SerpAPI searches, 0 TikTok submissions**. Including the previous Facebook
attempt, this fixed pilot now holds 3 of 9 Bright Data attempts (Instagram 2 of 3).
No reservations were reset. The follow-up PostgreSQL run passed all **74 tests**.
[Sanitized live receipt](evidence/social-20261108/results.json).

## November 23 public-source validation

Discovery now reads original post links in Instagram embeds and matching
TikTok video blockquotes. Alias links share one post identity and keep the
dated publisher evidence. The website adapters supply detail links so calendar
downloads and navigation links use none of the two detail fetches per publisher.

The baseline attempted 20 pages and had five fetch failures. The updated run
used the same source directory and opened all 22 selected pages successfully.
Hanoi and Da Nang returned no original social links. HCMC returned two from
Saigon Outcast, both confirmed against their live Instagram pages. The dance
session advertised for November 22 had ended. The burger awards post was a
recap. Neither became a feed item. [Organizer site](https://www.saigonoutcast.com/) ·
[Dance reel](https://www.instagram.com/reel/Df4uHYdTFDg/) · [Awards post](https://www.instagram.com/p/DfzcxWlk-xE/)

The two recent Da Nang reels from the previous pilot were also checked against
their original pages. The covers confirmed the named venues. The engagement
counts are a single public observation.

| Original reel | Published | Venue evidence | Likes / comments |
| --- | --- | --- | ---: |
| [Tiệm Yến](https://www.instagram.com/reel/Df_0zs_oXt6/) | November 21 | The cover names the Da Nang branch. The [restaurant](https://tiemyen.vn/chao-yen-tuoi-mua-o-dau/) confirms 347 Nguyễn Văn Linh. | 32 / 0 |
| [Mì Cay Gangwon](https://www.instagram.com/reel/Df7X04roCHE/) | November 19 | The storefront in the cover shows 489 Hoàng Diệu. The promotion end date is unknown. | 137 / 1 |

These remain review samples. No image reuse or public social publication was
approved. TikTok returned no fresh original lead and its official public player
failed TLS hostname verification on this machine. There were zero metered
provider requests and the campaign reservation total stayed at 132.

## Bounded TikTok profile discovery

Use the manual dry run to find a reviewed publisher's public profile automatically.
The publisher's current site must link to the exact profile. Ticketbox is a lead
for Hanoi and HCMC, and the Da Nang tourism site links to its own profile. The city
of the publisher is only a search hint.

```sh
python -m trending.social_collect --city danang --tiktok-profile
```

An explicit `--providers --env-file .env` switches this command to collection.
It requires the existing canonical `QUOTA_DATABASE_URL` ledger with recorded
history for the fixed pilot. Each profile shares the pilot's existing limits and
can reserve one record. Profiles used for multiple cities reuse the same job.
The request limits `num_of_posts` and the provider's response cap to one. The
provider documents one free credit per delivered Web Scraper API record.
[Profile input schema](https://docs.brightdata.com/scrapers/gd_m7n5v2gq296pex2f5m.json) ·
[Async request limit](https://docs.brightdata.com/api-reference/rest-api/scraper/asynchronous-requests) ·
[Free credit units](https://docs.brightdata.com/general/account/billing-and-pricing/free-tier)

The command returns a matching fresh post for review, with its original URL and
available engagement counts. It leaves publication to the existing review process.
Re-running the command polls a known snapshot or checks cached publication time.

Bright Data's Finance API now exposes [shared credits](https://docs.brightdata.com/api-reference/account-management-api/Get_free_tier_credits)
and [both auto-recharge settings](https://docs.brightdata.com/api-reference/account-management-api/Get_auto_recharge_settings).
The free-only check uses the smaller of the dashboard receipt and live allowance,
with one credit left unreserved because the API rounds fractional usage. A fresh
dashboard transaction check still reconciles the source of a positive wallet
balance. At the November 23 Vietnam-time check both switches were off and the
provider returned 4,996 credits left. The wallet had $5 and the prior receipt
recorded $7 promotional. The collector did not spend credits.

A public check of REALITY's Vietnamese site verified its Đà Nẵng venue and the
outbound link to the organizer's Instagram profile. The page supplied a profile
link only. A fresh post still needs its own timestamp and activity evidence.
[Organizer site](https://realitydn.com/vn/) · [Organizer profile](https://www.instagram.com/reality.dn/)

## November 23 public social recheck

The retained review export contained 68 Instagram and 47 TikTok links.
None of its dated posts fell within the rolling seven-day window at the check.
Two separate Đà Nẵng review leads returned HTTP 200 and the requested original
permalink from Meta's token-free Instagram oEmbed endpoint. The embed supplied
no publication timestamp. The native Tiệm Yến reel showed a November 21 date
and the venue name again. The restaurant's site confirms the branch at
347 Nguyễn Văn Linh. The Mì Cay Gangwon reel showed November 19 in an initial
read, consistent with the earlier review. Its repeat read timed out waiting for
the post details, and the promotion end date remains unknown.
[Instagram oEmbed](https://developers.facebook.com/docs/graph-api/reference/instagram-oembed) ·
[Tiệm Yến reel](https://www.instagram.com/reel/Df_0zs_oXt6/) ·
[Restaurant branch](https://tiemyen.vn/chao-yen-tuoi-mua-o-dau/) ·
[Mì Cay Gangwon reel](https://www.instagram.com/reel/Df7X04roCHE/)

Official TikTok creator-profile oEmbed requests for Ticketbox and Da Nang's
tourism profile both failed TLS before returning a post list. Fresh automatic
TikTok discovery remains unverified. The canonical quota database was
unreachable. The check made no metered requests and wrote no feed records.
[TikTok creator-profile oEmbed](https://developers.tiktok.com/docs/en/embed-creator-profiles/)

A read-only audit of the separate multimodal ledger on 23 November confirmed
the exact provider dates for the two Instagram reels. The saved November 22
snapshot recorded 4,495 plays for Tiệm Yến and 21,395 for Mì Cay Gangwon. Tiệm
Yến's own article confirmed the Da Nang branch on November 21. Gangwon's
promotion end date still needs evidence. The Instagram samples are for review.
The 30 cached TikTok results have no publication later than November 15, and
the November 22 reservation contains no records. Apify has 132 of 132 reserved
units, including two unresolved requests. The old Bright Data/SerpAPI ledger
was absent from this cluster. No new provider request or feed import was made.
