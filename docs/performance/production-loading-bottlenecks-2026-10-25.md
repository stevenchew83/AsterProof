# Production loading bottlenecks — 25 October 2026

The production audit found a 120-second 504 on Statement duplicates, 31–45-second TTFB on Topic tag analytics, 35.6-second TTFB on Statement links, and 14–18-second DOM readiness on Benchmark map. The small local navigation fixture did not represent the production corpus sizes.

## Changes

- Statement duplicates reads a completed, versioned report from the existing cache. A GET never starts a full-corpus scan, including on a cache miss. Missing results are explicitly unavailable, rather than zero matches. Results show generation time and a stale warning when source metadata changes or the report is over an hour old.
- The existing `recompute_technique_progress_catalog` command independently checks duplicate-report freshness after normal catalog maintenance, including when `--queued-only` or `--if-stale` skips catalog work. The existing production timer calls this command every five minutes. No unit, timer, credential, infrastructure, dependency or database schema changes are required.
- Duplicate computation streams narrow source fields into a temporary SQLite index with a 4 MiB page cache and disk-backed intermediate storage. It preserves case/whitespace normalization, Asymptote stripping, original shingle bucket exclusions and the SequenceMatcher threshold. Candidate overlap is counted per left statement and only the best 250 similar pairs are retained, as before. Exact groups and all deduplicated problem-label members remain reachable through pages of 25.
- An OS file lock prevents concurrent report builds on this single-host deployment. Cache writes are read back because production Redis ignores backend exceptions. A new manifest is published only after source-signature and generation-completeness checks. A partial build leaves the old manifest intact; generation inventories allow the next timer run to repair evicted chunks. Chunk lifetimes are renewed at completion.
- The private per-user scratch directory recovers only its known SQLite files after an interrupted run. SHA-256 shingle keys reduce disk usage; the main index is capped at 512 MiB. Refresh requires at least 1 GiB initially free, checks reserved disk headroom during SQL/Python work, and stops within a budget below the existing 30-minute service timeout. Capacity or time-budget failure keeps the last completed report.
- Topic analytics uses grouped SQL and narrow distinct projections instead of loading every tag and full record object. Exact filters run before aggregation; filter options retain their text-search scope. All matching data contributes to totals and leaders. The directory has 25 rows per page, global sort controls, and a scatter chart capped at 200 most-used matching techniques.
- Statement links selects the existing latest-100-row window first, loads minimal candidates for its exact contest/year groups and UUID suggestions, and checks all claimants for those candidate UUIDs. Duplicate code counts remain global within the visible groups, including hidden statements. UUID availability and linking writes retain their existing rules.
- Benchmark map computes lightweight full-scope summaries and selected-target scores, then fetches details and aliases only for the visible 25 rows. Global sorting precedes pagination. The matrix includes up to 200 chartable rows; the heatmap includes up to 40 families and 12 areas, with a visible scope note. Server search still finds records beyond the first page.

## Verification

Regression coverage includes cold/stale/evicted-cache reads, publication failure, source changes during build, process lock ownership, scheduled refresh after skipped catalog work, equivalence with the old duplicate algorithm at shingle bucket boundaries, large exact-group members, hidden linker claimants and duplicate codes, global selected-target sorting, chartability before capping, topic aliases and JSON domain membership, full-scope counts, and bounded payloads.

A synthetic local comparison used 1,000 archive problems/statements, 2,000 technique tags and 600 benchmarks:

| Page | Previous HTML bytes | Revised HTML bytes |
|---|---:|---:|
| Statement duplicates | 406,657 | 49,364 |
| Topic tag analytics | 1,356,366 | 97,798 |
| Statement links | 128,617 | 128,617 |
| Benchmark map | 3,709,643 | 254,284 |

These are fixture observations, not production latency improvement claims. The duplicate comparison uses an already completed snapshot; its full refresh runs outside the web request. Production acceptance requires observing the first full-corpus scheduled build complete within the existing catalog service's 30-minute limit, reading a completed report, and remeasuring all four pages. The cache can be unavailable or stale; neither condition may cause a synchronous fallback scan.

The release is migration-free. Automated GitHub quality checks may be skipped only for the explicitly requested release-scoped exception; artifact integrity, migration disclosure, the protected environment, activation and postflight remain enabled.
