# Provider exhaustion and deterministic fallback

The baseline feed uses Python website adapters, structured metadata, date parsing,
validation, exact deduplication and PostgreSQL eligibility. It does not need an AI
key. Scheduled website updates and existing-page checks remain independent of
OpenAI, Apify, Bright Data, YouTube and SerpAPI credit.

## Failure behavior

| Situation | Behavior |
| --- | --- |
| Budget/quota exhausted, missing key, stale free-allowance receipt | Stop that provider for the current engine run; keep other explicitly selected providers within their own existing gates |
| HTTP 401/402/403/429 or 5xx; transport unavailable | Stop repeated calls to that provider during the run; no automatic paid retry or account switch |
| One request returns HTTP 400 | Hold that request; unrelated requests remain possible |
| Malformed provider response | Sanitized failure, isolated to that provider |
| Canonical accounting missing/unreachable at startup | Block all metered collection, continue bounded website lead discovery across the requested cities; never create a replacement ledger |
| OpenAI unavailable during extraction | Preserve original evidence and deterministic text-only review output; no automatic approval |
| Previously completed OpenAI response with identical inputs | Read from the existing cache even if the key is absent; no new request/reservation |
| Unknown submission | Keep the existing reservation and job identity; no resubmission or allowance reset |

Circuit flags last for one invocation. A later manual run rechecks credentials and
allowances; durable accounting remains authoritative across all runs. A circuit
already open suppresses that provider's remaining calls, including cache paths.
No new provider, subscription, paid fallback or spending ceiling is enabled.
Other selected services offer their existing capabilities, not guaranteed access
to the same failed post or a substitute model judgment.

## Deterministic review output

`deterministic_text_v1` matches a complete reviewed venue name and address in one
available text source, preserving its source ID, quotation and existing verification
time. It uses the existing conservative Vietnamese session parser. Each match stays
separate. No fuzzy location matching, guessed price, image interpretation, or date
invention. Session candidates are suggestions for review, not confirmed schedules.
Unknown ownership, conflicts, cancellation, recency and media-only facts remain held.
All fallback results have `published=false` and `validation_status=needs_review`.
They cannot enter the feed through the reviewed-publication command as accepted AI
claims. Re-running fallback never renews source verification.

## Operation

Use the existing website CLI when metered services are unavailable:

```sh
python -m trending --browser --supplemental --write-db
python -m trending --browser --write-db --refresh-existing
```

These require the intended migrated DATABASE_URL. Use no `--write-db` for a read-only
website audit. The multimodal engine automatically gathers bounded website leads on
live runs; it does not import those leads as events. Existing CLI provider selection,
free receipts and campaign ceilings still apply. Inspect `provider_circuits`, per-city
errors and each result's `fallback` in the engine report. Degraded execution returns
exit code 2 rather than claiming complete success. Missing feed storage means no
publication; the app's expiry rules remain intact rather than showing stale content.

## Validation — 2026-11-15

149 unit/PostgreSQL tests passed, including simulated exhaustion, unavailable keys,
provider isolation, malformed responses, cached responses without keys, lost accounting
with zero provider calls, deterministic repeatability and unchanged source timestamps.
Controlled API responses are tests, not new live provider validation. No paid requests,
new credentials, production writes, deployment, schedule activation or quota reset.
