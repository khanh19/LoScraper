# TikTok example learning and unseen discovery — 15 November 2026

The eight supplied workbook posts are development examples, not an unbiased evaluation set or a training run. Their age does not diminish their value for extraction regression tests; it does prevent using them as current recent-place mentions.

## Implemented

- `multimodal.py`: versioned destination-array extraction (maximum six), separate child evidence identities and judgments, independent sibling validation, and a deterministic rejection when place-only claims contain event sessions.
- Evidence instructions distinguish broad geotags, branch addresses, nearby businesses, opening hours, creator opinions, irrelevant speech and commercial disclosures.
- `engine.py`: retains per-destination results instead of flattening an itinerary into one item. Public feed contracts are unchanged; routine publication remains disabled.
- `engine_providers.py` and normalization retain views, saves, shares and advertising flags separately, including false/unknown values.
- `intent.py`: adds food-tour, date-night dining, photobooth and social-activity vocabulary. The query catalogue still needs measured query selection improvements rather than assuming each phrase works.
- `tests/test_destination_extraction.py`: multi-stop preservation, empty bundles, place-hours rejection and metric/flag preservation.

## Live evaluation

One automatically searched Apify run used three Vietnamese city/week/month queries, no supplied post URLs. It returned 30 records (10 per city), all distinct from the workbook. Date eligibility is evaluated from API publication timestamps, not the query words. Six records were selected for bounded caption/cover extraction and separate judging; this is not continuous video review. Full local records and review URLs are in `/Users/macbook/Desktop/Lo_fresh_discovery_20261115/`.

The shared accounting ledger and existing campaign caps were preserved. The run used verified Apify included credit with a $0.90 provider charge ceiling and $1 reservation, at most 30 outputs. No Bright Data, SerpAPI, subscription or recharge was triggered. Existing raw API artifacts remain local.

## Findings and limitations

HCMC/Hanoi returned plausible outings and announcements. Da Nang's general weekend query was dominated by weather content: retrieval success is not relevance success. Query category specificity and reviewed organizer leads are the next priority. Festival end-date disagreements and weekday/date inconsistency must remain held pending authoritative corroboration. Different food festivals must not be merged solely because their names are similar.

Automatic sampled-video/end-card acquisition, timed-subtitle relevance filtering and destination-scoped video escalation remain unfinished. Current multi-destination processing preserves permission gates and uses available captions/images; permitted video escalation is retained only for a single destination to avoid cross-stop contamination. The previous manual player-frame audit is not an installed production crawler.

No venue or organizer directory entry was automatically approved. No live feed import, human-calibration approval, deployment, schedule or merge occurred. No claim of improved precision is justified without paired baseline results and independent review.

## Validation

`python -m unittest discover -s tests -q`: 121 discovered, 81 executed successfully, 40 skipped (database-dependent tests unavailable in this invocation). `compileall` and `git diff --check` passed. Existing unrelated user changes were preserved.

Final live results: 30/30 unseen records retrieved; publication within seven days: HCMC 7/10, Hanoi 7/10, Da Nang 5/10. These counts include irrelevant content. Six caption/cover extraction+judge evaluations completed; all six held. Apify reported $0.112 included-credit usage. The review HTML/CSV lists every original URL. Remaining limitations are material: no continuous-video analysis, no verified Da Nang publication and no proof that retrieval relevance improved over a paired baseline.

## Storage recovery and frame sampling follow-up

Removed only regenerable Homebrew, pip and npm caches. uv cache cleanup was cancelled because another process held its lock; no forced deletion. Final filesystem observation: approximately 3.2 GiB available (concurrent activity means not all of the change is attributable to this cleanup). User repos, databases, browser runtimes and audit evidence were preserved.

Saved the user's 15 relevance approvals and recovered all 38 development exclusions from existing ledger results after Desktop artifact reads timed out. These approvals are not factual publication approvals.

The permitted-media path now samples up to 12 decoded frames, explicitly including opening and final frames with extra coverage near the end. ffprobe timestamps are paired to selected frame indexes; duplicate sample indexes in short clips are collapsed. A real FFmpeg-generated clip test verifies final-frame inclusion and timestamps. This does not establish access to new social videos, full video understanding, or permission to publish media.

Validation: 125 tests discovered; 85 passed, 40 skipped. New live retrieval remains blocked by the existing Apify campaign reservation ceiling. No budget reset, publishing, deployment or schedule activation occurred. Desktop audit-file read timeouts persist independently of the recovered free space.
