# Image provenance and fallback policy

The collector no longer treats a source-wide boolean as reuse permission.
`trending/image_permissions.json` is the reviewed permission registry. It is
currently empty: **no publisher images are approved**.

A permission record requires a stable `id`, `source_slug`, `scope` (`asset` or
`publisher`), `creator`, `license_name`, HTTPS `license_url`, HTTPS `evidence_url`,
`reviewed_at`, and either exact `image_url` or publisher-controlled `asset_host`.
Record attribution requirements alongside the evidence. Use `revoked: true` to
withdraw a grant. Do not grant an entire shared CDN merely because it hosts a
publisher's files; prefer exact-asset grants. An accessible URL is not permission.

The adapter must independently establish the image belongs to this observation.
Roundup entries never inherit the article-wide Open Graph image. Import synchronizes
permission records; removals/revocations immediately hide existing linked images
without deleting source evidence. The API joins the selected website observation's
permission, not a supporting social post. Optional `image_credit` fields are
additive; older clients keep their existing fields.

LoApp bundles six optimized standard Unsplash JPEGs, each below 200 KB, reused
across the eight existing categories. The asset-specific source page, creator,
license, review date, bytes and hash are recorded in
`LoApp/assets/images/trending/credits.json`. These are free Unsplash assets, not
Unsplash+; see the [license](https://unsplash.com/license). No runtime image search,
paid image API, publisher image download/rehosting or video download is involved.

Display order: permitted publisher image → bundled category photo → neutral
placeholder after image failure. Category photos show **Ảnh minh họa**, category
accessibility text and a separate photographer/Unsplash credit. They do not claim
to depict the destination. Event-source links remain separate from image credits.

Tests cover scope, association, revocation, future review dates, exact host matching,
API revocation and actual mobile/desktop fallback rendering. Image-network failure
is explicitly injected in a separate browser pass; it is not live publisher evidence.
