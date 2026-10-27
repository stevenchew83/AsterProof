# Areas & concepts dashboard audit — 27 October 2026

## Outcome

The compact layout is implemented locally. Performance was audited; the backend changes below are proposals, not implemented or deployed by this task.

The main observed delay is waiting for the HTML response. Reducing layout spacing will not resolve that delay.

## Live browser evidence

Target: `https://18.142.249.181/dashboard/topic-tags/`, authenticated, default filters. One fresh reload started at **15:29:14 MYT / 07:29:14 UTC**, timezone `Asia/Kuala_Lumpur` (UTC+08:00). The action was an ordinary reload of the existing signed-in page. The browser automation observation timed out while the page was loading; the completed navigation subsequently returned HTTP 200 and provided the measurements below.

| Measurement | Observed value |
| --- | ---: |
| Request to first response byte | 35,133 ms |
| Connection establishment, including TLS | 38 ms |
| TLS handshake (included above) | 21 ms |
| HTML download after first byte | 4 ms |
| First contentful paint, from navigation start | 35,856 ms |
| DOM content loaded | 35,908 ms |
| Load event | 35,992 ms |
| HTML compressed body | 23,014 bytes |
| HTML decoded body | 131,499 bytes |
| DOM elements | 2,070 |

The slowest recorded asset duration was approximately 284 ms; the listed assets had zero transferred bytes, consistent with a warm browser cache. No warning/error console entries were returned. This is a single warm-cache observation, not a cold-load Lighthouse score, percentile, or production benchmark series. The aggregate browser timing does not separate application CPU, database work, or proxy/worker queueing.

The returned page showed 25,804 problems. Initial connection and response download times are small relative to the 35.1-second first-byte wait, making server-side work/queueing the primary investigation target.

## Deployed revision and diagnostic limits

The approved `asterproof-prod` SSH alias was used for this bounded, read-only check. It completed with exit status 0:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 asterproof-prod '
date -u
readlink -f /srv/asterproof-managed/current
systemctl show asterproof.service --property=ActiveState,SubState
journalctl -u asterproof.service --since "2026-10-27 07:28:30 UTC" --until "2026-10-27 07:30:30 UTC" --no-pager -n 200 | grep "request_timing path=/dashboard/topic-tags/" | sed -E "s/user_id=[^ ]+/user_id=[redacted]/g" | tail -10
'
```

At 07:30:56 UTC, the release path resolved to `53237044b854996a104644ba84edfc6298caa881`; the service was active/running. No matching request-timing lines were returned for the window. No per-request trace ID was available in the captured evidence. Proxy access logs, SQL durations, CPU, memory, database pools and worker queues were not measured, so their individual contribution remains unverified. Service activity alone does not rule out saturation. No settings, services, production records or infrastructure were changed.

The deployed analytics implementation differs from the current local working copy. The production code findings below come from the exact deployed commit in the local Git object database, rather than treating the older local implementation as production evidence.

## Source findings

1. **Library-wide computation precedes pagination.** The deployed [`library_coverage_rows`](https://github.com/stevenchew83/AsterProof/blob/53237044b854996a104644ba84edfc6298caa881/inspinia/pages/concept_analytics.py#L60) walks the full matching library in batches of 256. [`build_concept_analytics_context`](https://github.com/stevenchew83/AsterProof/blob/53237044b854996a104644ba84edfc6298caa881/inspinia/pages/concept_analytics.py#L209) builds coverage memberships, aggregates and review lists before paginating the concept results. Search, sorting and pagination therefore repeat the expensive library pass. Subject/area selection is applied to memberships after the library read; only contest/year narrow the initial source query. A low visible row count does not bound backend work.

2. **The enabled assignment-projection path does substantial work per batch.** [`statement_coverage_payloads`](https://github.com/stevenchew83/AsterProof/blob/53237044b854996a104644ba84edfc6298caa881/inspinia/pages/statement_concept_coverage.py#L154) checks projection state and, when enabled, reloads sources and builds projection payloads. [`read_assignment_sources`](https://github.com/stevenchew83/AsterProof/blob/53237044b854996a104644ba84edfc6298caa881/inspinia/pages/concept_assignment_source_export.py#L82) reads statements, archive records and source tags, includes full statement text, and hashes source content. [`projection_payloads`](https://github.com/stevenchew83/AsterProof/blob/53237044b854996a104644ba84edfc6298caa881/inspinia/pages/concept_assignment_service.py#L265) reads assignment records and validates evidence through `project_source`/`trace_source`. This is a source-backed likely contributor, not a measured breakdown of the 35 seconds. Projection-state checks can also recur across batches. Existing batching and tag-resolver caching are already present and should be retained.

3. **The browser payload is a secondary concern in this sample.** The HTML body arrived in 4 ms and assets were cached. Do not prioritize a new CSS framework, chart rewrite, smaller icons, or arbitrary database indexes ahead of the request's library-wide processing.

## Proposed performance fixes, in order

1. **Measure the exact deployed request phases on a representative local/staging corpus.** Record source SQL count/time, source export/hash time, evidence projection time, aggregation time, template time and peak memory. Include both projection modes, a cold cache, search, next page, subject/area scope and concept drill-down. Use existing request-timing support where available. This establishes whether CPU, SQL or queueing dominates before selecting a smaller optimization or index.

2. **Remove avoidable repeated work while preserving assignment semantics.** Resolve the projection mode once per request. Reuse source identities/metadata already read for each batch, use narrow assignment projections where practical, and avoid constructing display/evidence detail for invisible rows. Push scope predicates into database reads only when they preserve cross-subject concepts, statement precedence, source freshness and reviewed evidence. Do not substitute raw tag counts for accepted concept assignments or skip evidence freshness checks.

3. **Serve a versioned coverage snapshot/read model for the durable fix.** Compute deduplicated UUID-to-concept/area memberships, mapping status, contest/year/difficulty dimensions and scope aggregates outside the web GET. Bind publication to the source revision, assignment revision and concept-registry version; invalidate for edits, deletions, activation changes, source links, statement text, reviewed assignments and published evidence. Generate/reuse it through the established maintenance path if suitable. Search/sort/page should operate on this published data and fetch only visible problem detail. A missing snapshot should show an explicit unavailable state; a stale snapshot needs a visible freshness policy, especially for reviewed/rejected mappings. Neither should silently start a full-library rebuild in a web request. Cache unavailability must not create a rebuild stampede.

4. **Verify against the production-sized corpus before release.** Proposed acceptance targets: warm TTFB under 1 second for the default view, search, sort and next page; cold/missing cache returns promptly without a synchronous full scan; stable memory and bounded source reads; identical full-scope counts, median MOHS, UUID deduplication, gaps and mapping permissions. These are targets, not achieved results. Re-measure authenticated production navigation after any separately requested deployment.

## Local compactness changes and verification

- Reduced title spacing, control height, stat-card padding, table padding and pagination spacing using existing theme tokens.
- Replaced the large circular coverage graphic with a compact labelled percentage/progress bar.
- Made area rows denser and show four initially; every remaining area stays available through the existing disclosure.
- Preserved filters, sorting, search, pagination, detail links, mapping review and access boundaries.

Before/after previews used the real templates and the same **200 synthetic problems**, with a disposable local SQLite database. No production database was copied. At a 1440 × 900 viewport:

| Layout measurement | Before | After |
| --- | ---: | ---: |
| Concept explorer top, document px | 1,309.75 | 774.30 |
| First area row height, px | 93.31 | 45.70 |
| First concept row height, px | 72.30 | 52.89 |

The explorer begins 535 px / 41% earlier in this fixture. At a freshly loaded 390 × 844 mobile viewport, the document width was 375 px, with no page-level horizontal overflow. The concept table retained its own horizontal scrolling container (318 px viewport, 650 px table). More filters, subject-dependent area options, and expanding all 45 areas were checked in the browser. Browser emulation sizing was restored afterward.

`DJANGO_READ_DOT_ENV_FILE=false UV_CACHE_DIR=/tmp/asterproof-uv-cache uv run pytest inspinia/pages/test_concept_analytics.py -q`: **11 passed**. Whitespace checks passed. No Python, shared asset source, dependency or schema changes were made by this task.

## Audit tools

The internal browser tools supplied Chrome DevTools Protocol navigation/resource timing, HTTP status, console inspection, responsive checks and screenshots using the existing authenticated session. Repository tests cover query/payload bounds and analytics correctness. Optional `RequestTimingMiddleware` already exists; this audit did not enable production logging.

PageSpeed Insights is useful for publicly accessible pages, but its remote runner does not inherit this signed-in browser's session. For this dashboard, use **Lighthouse in the authenticated Chrome DevTools session**, retaining authentication state. Google's [authenticated-page guidance](https://github.com/GoogleChrome/lighthouse/blob/main/docs/authenticated-pages.md) and [Lighthouse overview](https://developer.chrome.com/docs/lighthouse/overview/) describe that workflow. This task used direct browser timing rather than claiming a Lighthouse score. The existing HTTPS IP endpoint's compatibility with PageSpeed's remote certificate validation was not tested.
