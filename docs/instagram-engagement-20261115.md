# Instagram engagement discovery — 15 November 2026

## Live result

Retrieved 13 actual Instagram records using four bounded Apify jobs: four reels
each from `ninheating`, `danang_angi`, and `utcunggg`, then one exact Hanoi post
discovered through an external creator index. Index counts were not trusted;
the exact post was retrieved from the provider. No downloads or publication.

Three relevant posts met the explicit popularity heuristic:

| Destination | URL | Plays | Likes | Comments | Published |
|---|---|---:|---:|---:|---|
| Hanoi, Đồng Xuân food alley | https://www.instagram.com/p/DTItn_Hj6IF/ | 59,543 | 2,148 | 10 | 2026-01-05 |
| Da Nang, Hải Yến food stall | https://www.instagram.com/p/CiIHj5fM4Di/ | 4,164,141 | 12,562 | 123 | 2022-09-05 |
| Huế–Da Nang heritage train | https://www.instagram.com/p/C6ESHl0PK2Z/ | 1,361,553 | 15,966 | 465 | 2024-04-22 |

These are accumulated-popularity examples, **not this week's verified trends**.
No HCMC sample met the heuristic. Four relevant recent HCMC samples had 107–280
likes, 6,678–15,673 plays and zero reported comments. Three Hanoi technology/
creator-business posts were irrelevant to outings despite the creator's niche.

Comment samples contain useful booking/address questions and friend invitations,
but also criticism, generic reactions and hotel advertising. Do not infer positive
sentiment from total comment count or treat a sampled comment as venue authority.
The provider's sample spans historical dates and does not establish recent momentum.

## Pipeline changes

`trending/engagement.py` normalizes provider aliases, preserves unknown/hidden
counts, separates plays from views, and adapts Instagram records with up to 20
comment texts/timestamps without commenter profile data. The engine considers
popularity candidates after activity/location triage and before recency when
choosing bounded extraction work. Public feed eligibility/ranking is unchanged.

Initial retrieval heuristic: at least 1,000 likes, 50,000 plays/views, or 100
shares/saves. These are adjustable triage thresholds, not calibrated viral labels.
Negative, boolean and non-finite counts are unavailable. Views and plays are never
summed. Every assessment retains viral/growth uncertainty and denies publication.

## Accounting and validation

Verified FREE plan and included balance before submitting; four runs had individual
$0.25 hard charge limits and durable $0.30 reservations. Actual reported usage was
$0.0351 of included credit (three $0.0108 runs plus one $0.0027 run). No subscription,
recharge, Bright Data, SerpAPI or OpenAI request was made. This reaches the existing
90-output Apify campaign limit; do not reset history or silently increase the cap.

130 tests: 90 passed, 40 database-dependent tests skipped. `git diff --check` passed.
Local sanitized review: `.state/instagram-engagement-20261115/review.json`.
Raw evidence remains in the canonical accounting ledger. Existing user edits remain.

## Remaining work

Find fresh corroborating evidence for popular venues; widen creator/topic coverage
only in a separately bounded campaign within freshly checked free allowance.
Measure comparable repeated counts before claiming growth. Assess comment samples
for outing intent, negative experiences and promotional noise separately. Current
live evidence does not establish a current viral result in every city.
