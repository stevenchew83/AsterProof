# Area and concept dashboard timeouts — 26 October 2026

## Incident evidence

The signed-in `/dashboard/topic-tags/` and `/dashboard/techniques/` pages returned nginx 504 errors. The analytics browser navigation began at 11:57:59 UTC (19:57:59 Asia/Kuala_Lumpur). Its recorded connection took 55 ms, including a 28 ms TLS handshake; time to first byte was 120,074 ms, and the response status was 504. Browser console capture contained no error entries. No historical request ID or initiator trace was available for that navigation.

A bounded read through `asterproof-prod` exited 0. Nginx recorded upstream timeouts while reading response headers at 11:59:59 and 12:00:01 UTC for the two routes. Gunicorn recorded a worker timeout at 12:00:00 and replaced that worker. At 12:02:20 UTC, the service and public application health were healthy under release `2535b6da2532d7aefbc317feb0c66f6fa723f081`. The host reported 414 MiB RAM, 120 MiB available and 300 MiB swap in use. The worker log's generic “Perhaps out of memory?” message does not establish a kernel OOM event.

The existing signed-in problem library rendered successfully and reported 13,722 statements, including 10,710 linked entries. The affected dashboards instead loaded all statement objects, all own and linked tags, and full role/label payloads before pagination. They repeatedly resolved identical source metadata and constructed a URL for every problem. Progress also sent all library IDs back in a completion query. This request path imposes avoidable CPU and memory pressure; the production trace establishes that the delay occurred before response headers rather than during browser rendering.

## Fix

- Stream narrow statement and archive projections in batches of 256. Load source tags only for the current batch, and skip linked archive tags when a statement has its own tags, including suppressed tags.
- Reuse source-tag resolutions within the request through an LRU capped at 2,048 signatures. Keys retain every source field and fallback subject, including contextual alias requirements. There is no cross-request cache or delayed completion/mapping update.
- Retain compact concept identities for aggregation instead of a full role/label dictionary for each occurrence. Keep full-scope UUID deduplication, totals, filters, global sorting, search, pagination and exports.
- Resolve problem links only for visible review and drill-down rows. Select distinct filter choices in SQL.
- Query completions through the indexed selected-user scope, then match current library identities in memory. Preserve statement completion precedence over legacy problem completion.

The fix changes no dependencies, schema, service settings, timeout settings or access rules.

## Local verification

On the same synthetic 5,000-statement / 50,000-tag dataset:

| Measurement | Before | After |
|---|---:|---:|
| Profiled loader time | 5.49 s | 1.62 s |
| Peak Python allocations under tracemalloc | 73.06 MiB | 12.82 MiB |

The allocation comparison warmed URL configuration before both runs. Tracing imposes overhead, so those traced run times are not used for the timing comparison. These figures exclude the application's baseline RSS, database memory and operating-system caches. A separate synthetic 13,722-statement / 137,220-tag run completed the revised loader in 4.46 seconds under cProfile. Neither local run is a production latency claim or a copy of production data.

The four focused concept/loading test modules passed 72 tests. Existing statement and progress routes/navigation passed 260 selected tests. New regressions check batch size, resolution reuse across batches, full totals and tail-page access, compact completion SQL, suppressed own-tag precedence, subject isolation, and source edits. Focused Ruff, Django test-settings system check and whitespace validation passed.

Production acceptance must use the signed-in browser to open both affected routes after the fix is deployed, record document status and response timing, and correlate fresh application/proxy errors and health with the exact release. Local test success and unauthenticated redirects do not establish that acceptance. At the time of this record, this fix has not been committed, merged or deployed.
