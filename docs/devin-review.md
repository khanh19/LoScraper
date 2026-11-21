# Devin review setup

Repository guidance lives in the root REVIEW.md, which Devin Review reads automatically.
This file prepares review context; it does not enable the GitHub integration by itself.

## Activation
1. Connect GitHub to Devin and install/authorize its GitHub App for khanh19/LoScraper.
2. Publish REVIEW.md on the branch being reviewed.
3. Open https://app.devin.ai/settings/review and add a single-repository rule for this repo.
4. Start with ready-for-review PRs, Normal effort and a per-PR spend limit chosen by
   the account owner. Confirm account billing before enabling repeated automatic reviews.
5. Enable bug/security findings and the review status check. Leave auto-fix and
   autoapproval off. Keep existing CI requirements; do not require a new check before
   confirming it actually runs on the repository.
6. For a one-off review, open the PR in https://app.devin.ai/review or post
   `/devin review` on that PR after the integration is connected.

## Acceptance
Verify a review names the current head SHA, uses REVIEW.md, and posts findings/status.
Check that a later push is covered by the configured cadence and that stale results
are not mistaken for review of the new commit. A completed review is not proof of
zero defects, passing tests, or native-device validation.

## Credentials and costs
The local DEVIN_API_KEY was authenticated read-only on 2026-11-21.
The native GitHub review integration does not require putting this key in Expo or CI.
Do not source the entire frontend .env into CI or copy it into Devin's environment.
Manual reviews may bypass automatic-review spending limits; confirm cost before use.
No automatic rules, paid sessions, auto-fixes or approvals were enabled by these files.

References:
- https://docs.devin.ai/work-with-devin/devin-review
- https://docs.devin.ai/api-reference/overview
