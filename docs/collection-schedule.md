# Trending collection schedule

User-confirmed cadence, starting **1 December 2026**, timezone **Asia/Ho_Chi_Minh**:

| Day | 06:00 Vietnam time |
| --- | --- |
| Tuesday, Friday | Recheck stored website entries, then full discovery across all enabled website adapters and all three cities |
| Other days | Recheck stored website entries only |

First full runs: December 1 and 4. First maintenance run: December 2.
The GitHub trigger is `0 23 * * *` UTC (the preceding calendar date). Vietnam
has no daylight-saving shift. Runs before the start date skip collection;
manual dispatch remains available before then. GitHub schedules are best effort,
not an exact-time guarantee. Overlapping collections queue rather than cancel.

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

Each source checks at most 200 distinct pages, oldest verification first. Exceeding
that bound produces `refresh_page_limit` and a deferred-page count, not a false
complete result. Missing known entries produce `existing_entry_not_recovered`.
Full discovery retains the bounded 20 detail pages per source plus existing checks;
“full” means all enabled sources/cities, not unlimited scraping or a minimum feed size.
The workflow has a 25-minute timeout; inspect interrupted receipts if it is reached.

Life of Da Nang collection reads the Vietnamese calendars through the end of the
30-day horizon. It shares the same detail-page cap across calendar and weekly
listings, giving both weekly and planning leads a chance before the cap. The
individual event pages still determine eligibility. Nhà hát Hồ Gươm's performance
pages provide another planning source. The collector stores the exact announced
show days when the venue omits the end time.

Two Da Nang events are held pending schedule confirmation. The Ariyana Christmas
Market publications disagree on the start day and opening hour. Pullman's official
pages give different hours for the same tree lighting. [City market notice](https://1022.vn/en/su-kien/da-nang-christmas-market-2026/) · [Market organizer](https://danangchristmasmarket.com/) · [Pullman program](https://www.pullman-danang.com/news/festive-season-2026/) · [Pullman event overview](https://www.pullman-danang.com/discovery/event/danang-christmas-market/)

The Furama tree lighting is corroborated by the exact venue link, the resort's
street address, and the city's matching schedule. Its December 3 session is
17:30–19:00 Vietnam time. The separately booked dinner is outside that session.
The collector checks these pages again before renewing evidence.
[Life of Da Nang](https://lifeofdanang.com/vi/danang/city-christmas-tree-lighting-at-furama-resort-2026-12-03) · [Resort address](https://team.furamavietnam.com/khach-san.html) · [City tourism calendar](https://danangfantasticity.com/en/discovery/christmas-2026-new-year-2027)

## Activation checklist — not yet active

1. Review PR #6 with its parent stack. Confirm the reviewed workflow reaches the
   default branch (`main`) before using manual Actions dispatch.
2. Apply all discovery migrations to the intended feed database and verify the app
   backend reads that same database. Never point this job at the local accounting ledger.
3. Run manual `mode=full`, `pilot=true`; inspect source coverage.
4. Set `TRENDING_STAGING_DATABASE_URL` for manual writes to the isolated staging feed. For Supabase, use `sslmode=verify-full` and set `TRENDING_STAGING_DATABASE_ROOT_CA` to the project's published database root certificate. Run `pilot=false`, then `mode=refresh`
   with `pilot=false`. Check stable IDs, timestamps and health without erasing data.
5. Store the verified scheduled feed target as **TRENDING_DATABASE_URL** in Actions
   secrets. Use **TRENDING_DATABASE_ROOT_CA** when the scheduled target uses its own CA. Scheduled writes use these dedicated settings.
6. Set repository variable **TRENDING_SCHEDULE_ENABLED=true** after those checks.
   Keep both database secrets separate from the legacy workflow target.

To pause, set the variable false or disable the workflow. No raw payload uploads.
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
| Ho Chi Minh City | 19 / 18 | 10 / 7 |
| Da Nang | 13 / 12 | 5 / 5 |

The manual Furama run imported one eligible event without a failed fetch or
provider usage. Controlled tests cover matching dates and times, competing
sessions, missing address evidence, and venue ambiguity. Hosted app validation
requires the staging deployment to include the release branch. Scheduling remains
disabled.
