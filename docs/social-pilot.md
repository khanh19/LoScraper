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

### November 24 provider and organizer recheck

Social triage recognizes styled Unicode activity headings. The organizer
schedule parser reads dotted dates such as `29.11.2026`. A dotted date
without a four-digit year stays unresolved even when the caption names a
weekday. The Yoga Lab post was recognized as an activity lead and held for
its missing event year. The staging card uses the organizer website's
reviewed schedule. [Original Instagram post](https://www.instagram.com/p/DgEXUf7hYR5/)

The 1900 anniversary captions contain a 2019 founding date and a November 27,
2026 event date. Explicitly labeled founding dates stay out of event sessions.
Date-only captions containing only ended dates are recaps. A mix of ended and
upcoming dates without that attribution stays unresolved. The three anniversary
posts came from the same publisher. [Organizer post](https://www.instagram.com/p/DgDABDCk5Vj/)

The original Bright Data and SerpAPI ledger remains unavailable. The separate
multimodal ledger was audited from a local PostgreSQL copy with read-only
transactions. Apify's account API reported the Free plan, a $5 monthly credit
limit, and approximately $0.39 of November usage. The Lô campaign had all
132 output units reserved. A read of the available actor-run history found
no matching runs for the two reservations without a run ID. Both reservations
remain unresolved. [Apify actor-run history](https://docs.apify.com/api/v2/actor-runs-get)

The November 24 Bright Data dashboard showed 4,996 shared free credits and a
$5 balance fully accounted for by promotional transactions. Both recharge
switches showed off. The read-only API checks matched the existing account
credentials and confirmed the same allowance and recharge state. The receipt
was used in memory for this check. New jobs still require the complete
canonical reservation ledger.

KaT Jewelry's own homepage links to its TikTok profile and advertises its
November in-person appointment calendar for HCMC. The HCMC public audit uses
this profile as a lead. Each post still needs its own publication timestamp
and the original activity or branch evidence.
[KaT organizer page](https://katjewelry.vn/) ·
[Original profile](https://www.tiktok.com/@katjewelry)

The Vietnam Exposition Center calendar links to `@vec.expo` on Instagram and
`@vec.global` on TikTok. The Firebeat festival site links to `@firebeat.global`
on TikTok. Both accounts and the festival use VEC's publisher identity for
independent-source counting. Their sites supplied account ownership evidence
and no original post links in the sample, so they stay outside the six-site
website scan. The Instagram profile returned fresh, review-only booth announcements
for the same November 27–29 event. The venue listing opens at 09:00, while
the festival's visitor guide and Hanoi's tourism portal say 10:00. The event
remains held while the public schedules disagree.
[VEC event listing](https://vec.global/events/hanoi-firebeat-world-festival-2026) ·
[Festival visitor guide](https://firebeat.global/khach-tham-du) ·
[Hanoi tourism portal](https://hanoigo.hanoi.gov.vn/event/hanoi-firebeat-world-festival-2026) ·
[Sample booth announcement](https://www.instagram.com/p/DgEyy7qAgbL/)

The Hanoi source directory now checks Yoga Lab Hanoi's public profile against
the account linked on its own website. The profile embed tied its **Detox Your
Posture** announcement to November 23 at 10:00 Vietnam time. The caption and
organizer's workshop calendar agree on the November 29 session at 10:00–11:30.
The caption and studio page agree on floor 5, 19–21 ngõ Yên Ninh, Ba Đình.
The original Instagram preview confirmed the account and showed six likes
and zero comments. Its unzoned day differs from the embed's timestamp, so
the exact embed time is used for recency. The post remains an organizer lead
for individual review. [Original Instagram post](https://www.instagram.com/p/DgEXUf7hYR5/) ·
[Workshop calendar](https://www.yogalabhanoi.com/events) ·
[Studio location](https://www.yogalabhanoi.com/locations)

When a website link and its verified public Instagram profile give the same
publication instant for the same post, the saved lead keeps the checked
profile as its evidence. The page discovery report retains the website link.
Conflicting times retain separate review evidence and cannot use that merge
rule. The saved lead still requires review before publishing.

The Saigon Garden Flea listing announces a November 28–29 event, but its
linked Instagram announcement reports a November 11 publication day.
The later event dates do not make it a recent social mention.
[Event listing](https://www.discoversaigon.vn/su-kien/saigon-garden-flea-5a-nguyen-dinh-chieu-november-2026) ·
[Original Instagram post](https://www.instagram.com/p/DfoeZp4nWAq/)

## Public TikTok metadata check

Run `python -m trending.tiktok_public` locally or manually dispatch **Scraper CI**
with `public_tiktok_audit=true`. It verifies up to four creator links per city on
reviewed organizer sites, calls the official profile oEmbed endpoint per distinct
profile, and examines at most two original video pages from that creator. The
job uses public HTTPS metadata and does not receive credentials.
Pass `--browser` to render a public profile whose initial HTML has no video
links. The manual Actions check enables this option. The first hosted check
verified Ticketbox's profile identity, but its initial HTML had no original
video links. The rendered check also found no links, and Da Nang's official
tourism profile returned HTTP 400 at oEmbed. The expanded check also tries the
profiles linked by 1900 Le Théâtre, Visit HCMC, and DANAGO. [Direct HTTP check](https://github.com/khanh19/LoScraper/actions/runs/45112850240) ·
[First browser check](https://github.com/khanh19/LoScraper/actions/runs/45113197703)

If the creator page opens with no original links, the browser audit can also
render TikTok's public creator widget. The oEmbed author, cited profile, and
creator handle must match. The widget runs in a fresh page that allows only
its HTTPS frame and scripts. It blocks media requests and extracts only
same-account video permalinks. Each permalink still needs its own publication
timestamp. The report records the widget result as `creator_embed`.
[TikTok creator widget](https://developers.tiktok.com/docs/en/embed-creator-profiles/)

On 23 November, the local HTTPS diagnostic identified the certificate
presented for TikTok as Virginia Tech's DNS-block certificate. The curl and
browser checks both correctly rejected the hostname mismatch. This diagnosis
applies to the local network. The hosted audit reached creator oEmbed for
several reviewed profiles and still found no original videos. Treat these as
separate results. Keep hostname verification enabled and use a permitted
environment for subsequent TikTok checks. [Virginia Tech application restrictions](https://it.vt.edu/projects/app-restrictions.html) · [Hosted audit](https://github.com/khanh19/LoScraper/actions/runs/45124845084)

The report requires a timestamp with a timezone from structured video metadata
bound to the exact original post. City hints from the organizer still need
venue corroboration. A fresh date produces a lead for review. The command keeps
publication and scheduled collection separate. The GitHub job runs only on
explicit manual dispatch. [TikTok creator embeds](https://developers.tiktok.com/docs/en/embed-creator-profiles/) ·
[TikTok player URLs](https://developers.tiktok.com/docs/en/embed-player/)

The expanded hosted check on 23 November verified five profile links from
organizer sites across all three cities. Four profiles loaded without any
original video links after rendering. The official Da Nang tourism profile
returned HTTP 400 from oEmbed. That check recorded zero fresh posts and zero
metered provider requests. [Hosted audit](https://github.com/khanh19/LoScraper/actions/runs/45113777936)

### TikTok links shared from the phone

The contributor workbook uses 33 distinct `vm.tiktok.com` or `vt.tiktok.com`
links. Publisher discovery now resolves up to three distinct TikTok share links
per city with at most two redirect hops each. It accepts a TikTok video or photo
permalink, deduplicates the post with any full URL already found, and preserves
any dated evidence from the publisher. A redirect only establishes identity.
The post still needs its own fresh date, relevant activity, and venue evidence.
Shop destinations, profiles, and off-platform redirects do not create leads.

Use `python -m trending.social_links --url <public-publisher-page>` for a
free-only transport check. If the local network cannot reach TikTok, dispatch
**Scraper CI** with `public_tiktok_audit=true` and `public_share_publisher_url`
set to a public page. The job reads link metadata, omits post text from the log,
and keeps metered collection and publication disabled.

### Social links in streamed page data

The public-page extractor reads complete JSON records in inline React Flight
chunks without running scripts. It keeps the same original-permalink checks,
freshness filter, deduplication, and per-page result bound. A link found in
page data still needs a publication date from the platform and verified venue
evidence before promotion.

On 23 November, the public ANs Vegetarian Cuisine page yielded seven original
TikTok permalinks from its inline data. The same page and clock yielded zero
links with the previous parser. The page supplied no publication dates, so
all seven links stayed in review. The check started no provider jobs and
wrote no feed records. [Public venue page used for link discovery](https://airial.travel/restaurants/vietnam/da-nang/ans-vegetarian-cuisine-S9TuRweh)

### Check an original TikTok video

```sh
python -m trending.tiktok_public --url https://www.tiktok.com/@danangzip.site/video/7707589251193474312
```

Pass up to six original video permalinks locally. To check a single link from
the hosted runner, dispatch **Scraper CI** with `public_tiktok_video_url`.
The audit reads the original video's public HTML. An unambiguous
`VideoObject` timestamp with a timezone must match the page and video.
When the date is unavailable, the official oEmbed response can confirm
the video ID by matching its product ID and player URL. A legacy response
with a matching creator and permalink also confirms those fields. Both
response formats leave the publication time unresolved.
The report includes transport and evidence status and performs no feed writes,
metered requests, or video downloads. [TikTok embed metadata](https://developers.tiktok.com/docs/en/embed-videos)

### Publisher transport and city-targeted links

Social lead discovery can use the existing website adapters' browser support
for public publisher pages. For example, the Hanoi Grapevine adapter can
retry its TLS handshake failure in a browser while keeping normal certificate
verification. The CLI reports the remaining error when the browser also
fails.

```sh
python -m trending.discover --city hanoi --browser
```

Ticketbox social discovery selects its two detail pages from public on-sale
entries that match the requested city. A mixed homepage put a Sài Gòn event
into the Hanoi detail budget. Listing city labels now route the fetches.
Venue verification still comes from the event and independent location
evidence. Dated post evidence still comes from the original post or a matching
provider record.

On 23 November, an audit opened 14 of 18 official detail pages from the
verified staging feed. Four Hanoi Grapevine pages failed TLS on the local
network. None of the 14 readable pages linked to an original Instagram or
TikTok post. The venue site for Mì Cay Sasin An Hải did link to an original
TikTok video. Its article is dated 15 November, and TikTok's source did not
return a verifiable publication timestamp. The link remains held.
[Venue's original-post reference](https://micayhanquoc.com/tin-nha-hang/sasin-an-hai-tren-tiktok-nicherryy)

Five public Instagram profile embeds returned no original-post links.
The source directory now records the publisher-confirmed Life of Da Nang,
Da Nang Fantasticity, REALITY and 1900 accounts as discovery leads.
New checks made zero metered requests and published zero records. The
Bright Data preflight found no currently verified free allowance. The
legacy quota ledger is still unavailable, and Apify's existing campaign
remains fully reserved.
[Life of Da Nang](https://lifeofdanang.com/weekly) ·
[Da Nang Fantasticity](https://danangfantasticity.com/vi) ·
[REALITY](https://realitydn.com/vn/) ·
[1900 Le Théâtre](https://1900club.vn/vi/ve-chung-toi/)

### Public Instagram post verification

```sh
python -m trending.discover --city hcmc --review-instagram
python -m trending.instagram_public --url https://www.instagram.com/reel/Df_0zs_oXt6/
```

The first command checks up to three Instagram permalinks found on publisher
pages. The second accepts up to six existing permalinks. Each check requests the
public HTML and matches the page's canonical or Open Graph identity to the
post. Recognized descriptions report the publication day, account, likes, and
comments. Profile links, conflicting identity or metadata, and unavailable pages
remain unresolved. The date has day precision and is kept separate from an
exact timestamp or event date. Review considers today and the previous six
Vietnam calendar days. These commands write no feed records and use no credits.

On 23 November Vietnam time, the HCMC publisher scan discovered two original
posts. Saigon Outcast's 18 November reel showed 23 likes and one comment, but
its line-dancing event ended on 22 November. The 16 November post fell outside
the date-only review window. The Hanoi and Da Nang publisher scans found no
original links in their bounded set. [Publisher](https://www.saigonoutcast.com/) · [Line-dancing reel](https://www.instagram.com/reel/Df4uHYdTFDg/) · [16 November post](https://www.instagram.com/p/DfzcxWlk-xE/)

Direct checks of the two existing Da Nang reels independently confirmed their
reported publication days. Tiệm Yến showed 32 likes and zero comments on a
21 November reel, and the restaurant corroborates the branch. Mì Cay Gangwon
showed 137 likes and one comment on a 19 November reel. The promotion end date
remains unknown. The older 8 November Burger Fest reel was rejected by date.
The public checks made no metered requests or imports. Fresh TikTok validation
remains open. [Tiệm Yến reel](https://www.instagram.com/reel/Df_0zs_oXt6/) · [Restaurant branch](https://tiemyen.vn/chao-yen-tuoi-mua-o-dau/) · [Gangwon reel](https://www.instagram.com/reel/Df7X04roCHE/)

#### Discover new posts from reviewed Instagram accounts

Run `python -m trending.discover --city danang --review-instagram`. The same
option works for `hanoi` and `hcmc`. The collector verifies profile ownership
against the reviewed publisher's website first, then checks at most three
public profile embeds per city and reports up to six recent posts per profile.
It decodes the embed's literal JSON data without executing its JavaScript.
Profile username and URL are checked against the requested account, and each
post must have the matching owner ID, an original shortcode, a public status,
and a timestamp within the past seven days. Hidden likes stay unknown.

Exact profile timestamps go into unverified discovery leads. Native post
previews still report a timezone-unspecified date and are kept as separate
evidence. The direct previews of two REALITY posts displayed November 22
while the exact embed timestamps were on November 23 in Vietnam. Neither
publication timestamp is a session date. City hints route review and do not
verify a place. No contact with a metered provider is needed.

Coauthored posts and posts with missing attribution metadata stay in the
profile review output. The audit reuses any checked previews and reads up to
three additional original posts per city. An ambiguous post can become a
review lead when the direct preview verifies the same shortcode and reviewed
profile account and gives a date within one calendar day of the embed's local
date. The lead retains the exact timestamp from the embed. The optional
`attribution_evidence` field records this independent original-page check.
Venue, timing, and publication review still apply. In the Nghề Nghệ sample,
the COMPLEX 01 embed named itself while the original Instagram page credited
`nghenghe.vn`, so the post remained held under COMPLEX 01.
[Original Instagram post](https://www.instagram.com/p/DgDCfuTnxt8/)

The November 23 live run found **29** recent records from six publisher-linked
profiles. Hanoi returned six posts from 1900, HCMC eight from Saigon Outcast
and Saigoneer, and Da Nang 15 from three profiles. One Hanoi listing page failed
transport. The original links included recent recaps and posts with no specific
local destination, both of which stay out of the feed. The REALITY Buildathon
announcement was corroborated by the organizer's public November 26
11:00–13:00 ICT listing. The Bếp Hên caption's address agrees with Michelin's
listing. Both are review candidates. This run published zero cards and used
zero metered requests. [Instagram Buildathon](https://www.instagram.com/p/DgEl9LqI6AH/) · [Organizer listing](https://app.realitydn.com/events/a1c345c5-5552-411a-a8b5-015f872adc4e) · [Bếp Hên post](https://www.instagram.com/p/Df6vOXfmjhg/) · [Michelin listing](https://guide.michelin.com/vn/en/da-nang-region/da-nang_2984390/restaurant/bep-hen)

The same path now covers COMPLEX 01 in Hanoi and Discover:Saigon in HCMC.
Their publisher sites link to the exact Instagram profiles and the pilot
returned six and three recent posts respectively. The COMPLEX 01 post about
Nghề Nghệ corresponds to an ongoing exhibition through November 28. In the
Discover:Saigon market roundup, Dấu Sắc Việt has a separately corroborated
venue and window through November 24. Its other entries require individual
review. These are discovery leads awaiting publication review. [COMPLEX 01](https://complex01.vn/) · [Nghề Nghệ Instagram](https://www.instagram.com/p/DgDCfuTnxt8/) · [Exhibition listing](https://hanoigrapevine.com/vi/2026/11/nghe-nghe-art-salon-mau-xua-sac-nay/) · [Discover:Saigon](https://www.discoversaigon.vn/) · [Market roundup](https://www.instagram.com/p/Df9uPUGoL37/) · [Dấu Sắc Việt venue evidence](https://codongson.vn/co-dong-son-le-hoi-van-hoa-dau-sac-viet-2026/)

On November 24 Vietnam time, direct previews confirmed four previously
ambiguous author attributions. The three Da Nang place leads were New Phương
Đông, Bếp Hên, and PRIME Pilates. The November 18 Saigon Outcast post's event
had already ended. Three Hanoi previews named a different original account,
and the run left two more attribution checks deferred under the read limit.
The Hanoi website scan was partial. All three city checks used zero metered
requests and published zero cards.
[New Phương Đông post](https://www.instagram.com/p/Df_4KPoGvG9/) · [Bếp Hên post](https://www.instagram.com/p/Df6vOXfmjhg/) · [PRIME Pilates post](https://www.instagram.com/p/Df4YX_jmqEb/) · [PRIME venue](https://primepilates.vn/)

### November 24 · Three-city event check

Public profile metadata supplied exact publication times. The original post
previews confirmed each author and reported the engagement counts below.
Local times are Vietnam time. A single snapshot supplies no growth signal.

| City | Original post and publication | Likes / comments | Confirmed outing |
| --- | --- | ---: | --- |
| Hà Nội | [Yoga Lab Hanoi](https://www.instagram.com/p/DgEXUf7hYR5/) · 23 Nov 10:00 | 6 / 0 | [Detox Your Posture](https://www.yogalabhanoi.com/vi/events), 29 Nov 10:00–11:30 at 19–21 ngõ Yên Ninh, Ba Đình. |
| TP.HCM | [Discover:Saigon arts roundup](https://www.instagram.com/p/Df7Dl-OILZM/) · 19 Nov 19:14 | 3 / 0 | [Mạch Thổ](https://quangsan.museum/su-kien/) at Quang San Art Museum, 189B/3 Nguyễn Văn Hưởng, Phường An Khánh, through 29 Nov. The counts belong to the roundup as a whole. |
| Đà Nẵng | [REALITY Đà Nẵng](https://www.instagram.com/p/DgEl9LqI6AH/) · 23 Nov 12:07 | 5 / 0 | [Vibe Coding × AI Buildathon](https://app.realitydn.com/events/a1c345c5-5552-411a-a8b5-015f872adc4e) at [86 Mai Thúc Lân](https://realitydn.com/vn/). Four timed sessions remain on 26 Nov and 3, 10, and 17 Dec, 11:00–13:00. |

The REALITY website adapter uses the organizer's series and checks each
session page for matching identity, venue, status, start, and end. The series
groups the session links under one stable URL. Its title is in Vietnamese in
Discover. The Instagram posts remain review evidence and do not add a second
publisher count for the same organizer. Public TikTok searches included these
and other current events but did not return a verifiable original video. No
metered provider requests or social publication were made in this check.
