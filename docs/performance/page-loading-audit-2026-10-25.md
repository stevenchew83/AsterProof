# Page loading audit — 25 October 2026

All 49 distinct destinations in the requested sidebar snapshot were audited and return HTTP 200. Training overview and Continue training share `/dashboard/`; the latter jumps to `#recommended-next`. Home, Train, Our progress, Problems & resources, My work, Tools, and Management are navigation headings/groups rather than separate pages.

## Changes and measured results

- Shared vendor JavaScript: **551,400 → 195,228 bytes (65% smaller)**; gzip **144,782 → 60,080 bytes (58% smaller)**. Replaced the two Lucide theme icons with the already loaded Tabler set and rebuilt the existing bundle. Bootstrap, jQuery, SimpleBar, the theme shell, and script ordering are preserved.
- Training overview: **357 → 18 queries** in the fixture. Batched published-content progress into four grouped queries, reused it for topic cards and recommendations, and reused point totals for level selection.
- Roadmap: **53 → 13 queries**. Progress counts, historical awards, duplicate accepted-submission handling, publication rules, and empty-subtopic recommendation behavior are covered by regression tests.
- Trainer materials / Training curation: **542 → 11 queries**. Trainer problems: **540 → 9 queries**. Eager-loaded topics for subtopic form-choice labels.
- Problem lists and Discover lists: **9 → 7 queries each**, without loading all list items and problem bodies for summary counts.
- My solutions: **8 → 7 queries**, counting blocks without reading proof bodies; detail pages retain full blocks.
- Problem library: **23 → 20 queries** by combining inventory aggregates. Contest progress: **20 → 18 queries** by reusing loaded heatmap data.
- My submissions and training summaries skip unused large body fields.

No audited route increased its query count. Permissions, URLs, completion identities, publication rules, and saved business records were preserved. Audit measurements were collected locally; release status is tracked separately from these measurements.

## Method and limits

The repeatable server audit is [`inspinia/test_page_loading.py`](../../inspinia/test_page_loading.py). It discovers named sidebar links, authenticates a synthetic approved administrator, and requests each distinct destination three times using Django's test client. Server times below are the median of the two warm requests, including SQL-capture overhead; they exclude network transfer and browser rendering. Query counts include middleware/session/transaction work. Timings are observations, not CI thresholds.

The isolated SQLite test fixture contains 240 archive problems and linked statements, 80 archive completions, 531 seeded training subtopics with one material and problem each, 36 completed training subtopics, 12 public lists with 20 items each, and 20 solutions with three blocks each. Ranking, benchmark, and review-queue data are unpopulated: those pages received loading/smoke checks, not representative volume benchmarks. Tests bypass the repository `.env` file.

A temporary loopback-only Django test server served the same synthetic data and rebuilt static assets. All 49 destinations were then opened in the in-app browser. Every document returned HTTP 200, with zero captured JavaScript exceptions or failed network requests; per-navigation event buffers were checked without truncation. Tables and charts initialized on populated analytics pages. Browser DOM-ready and first-contentful-paint observations below use normal local browser settings and a shared asset cache, without mobile/network/CPU throttling. They are one-run observations; no before-browser comparison, production latency, LCP, INP, or CLS claim is made.

## Main navigation

Queries and server times show **before → after**. HTML is the final uncompressed response size. Browser numbers are after-only local observations.

| Page | URL | Queries | Server ms | Browser TTFB / DOM-ready / FCP ms | HTML KiB |
|---|---|---:|---:|---:|---:|
| Training overview / Continue training | `/dashboard/` | 357 → 18 | 115.3 → 45.9 | 55 / 172 / 208 | 26.5 |
| Roadmap | `/training/` | 53 → 13 | 49.4 → 24.9 | 31 / 101 / 128 | 26.3 |
| My submissions | `/submissions/` | 7 → 7 | 9.6 → 9.7 | 9 / 79 / 112 | 36.5 |
| My progress | `/dashboard/my-progress/` | 12 → 12 | 73.5 → 65.2 | 27 / 304 / 300 | 370.1 |
| Technique progress | `/dashboard/techniques/` | 10 → 10 | 10.3 → 7.0 | 7 / 87 / 124 | 31.9 |
| Contest progress | `/dashboard/contests/advanced/` | 20 → 18 | 41.9 → 21.1 | 14 / 238 / 240 | 127.7 |
| Contest MOHS | `/dashboard/contests/mohs-summary/` | 10 → 10 | 14.0 → 10.2 | 8 / 147 / 164 | 53.3 |
| Problem library | `/dashboard/problem-statements/` | 23 → 20 | 82.5 → 45.8 | 39 / 168 / 188 | 217.9 |
| Problem lists | `/problem-lists/` | 9 → 7 | 64.7 → 9.7 | 7 / 86 / 120 | 41.8 |
| Discover lists | `/problem-lists/discover/` | 9 → 7 | 23.2 → 11.2 | 8 / 105 / 124 | 43.7 |
| Benchmark map | `/dashboard/technique-benchmarks/` | 7 → 7 | 16.8 → 5.9 | 6 / 66 / 104 | 46.3 |
| Record completions | `/dashboard/completion-quick-update/` | 17 → 17 | 159.9 → 89.0 | 35 / 312 / 212 | 1059.8 |
| My solutions | `/solutions/` | 8 → 7 | 16.1 → 10.1 | 7 / 79 / 116 | 40.7 |
| My activity | `/dashboard/my-activity/` | 8 → 8 | 145.5 → 101.5 | 291 / 706 / 732 | 288.9 |

## Tools and Management

| Page | URL | Queries | Server ms | Browser TTFB / DOM-ready / FCP ms | HTML KiB |
|---|---|---:|---:|---:|---:|
| LaTeX preview | `/tools/latex-preview/` | 6 → 6 | 19.6 → 5.1 | 10 / 118 / 144 | 43.3 |
| Handle parser | `/tools/handle-summary-parser/` | 6 → 6 | 43.0 → 4.6 | 4 / 55 / 88 | 26.6 |
| Problem analytics | `/dashboard/problem-analytics/` | 10 → 10 | 53.1 → 19.4 | 33 / 436 / 436 | 223.6 |
| Contest analytics | `/dashboard/contests/` | 10 → 10 | 11.7 → 10.1 | 12 / 172 / 184 | 63.5 |
| Topic tag analytics | `/dashboard/topic-tags/` | 8 → 8 | 5.4 → 5.5 | 11 / 68 / 96 | 29.3 |
| Statement analytics | `/dashboard/problem-statements/analytics/` | 11 → 11 | 38.2 → 41.9 | 28 / 150 / 168 | 228.7 |
| View analytics | `/dashboard/page-views/` | 19 → 19 | 13.9 → 10.6 | 15 / 75 / 108 | 33.5 |
| Completion records | `/dashboard/completion-records/` | 11 → 11 | 43.0 → 41.1 | 30 / 125 / 140 | 173.8 |
| Progress analytics | `/dashboard/completion-progress/` | 14 → 14 | 127.6 → 64.3 | 27 / 280 / 276 | 370.7 |
| Solution records | `/dashboard/user-solutions/` | 8 → 8 | 10.8 → 11.7 | 15 / 216 / 232 | 54.0 |
| Trainer dashboard | `/trainer/` | 11 → 11 | 7.2 → 7.8 | 14 / 216 / 260 | 23.1 |
| Training content | `/trainer/topics/` | 10 → 10 | 172.6 → 170.7 | 123 / 828 / 540 | 918.1 |
| Materials / Training curation | `/trainer/materials/` | 542 → 11 | 265.1 → 176.7 | 223 / 851 / 492 | 617.5 |
| Trainer problems | `/trainer/problems/` | 540 → 9 | 208.6 → 152.6 | 83 / 272 / 308 | 369.7 |
| Trainer submissions | `/trainer/submissions/` | 8 → 8 | 17.3 → 13.3 | 13 / 104 / 136 | 38.4 |
| Ranking table | `/rankings/` | 13 → 13 | 8.1 → 8.0 | 10 / 99 / 112 | 26.9 |
| Ranking dashboard | `/rankings/dashboard/` | 15 → 15 | 8.5 → 7.7 | 19 / 86 / 160 | 24.8 |
| Students | `/rankings/students/` | 9 → 9 | 5.6 → 5.5 | 6 / 70 / 100 | 23.9 |
| Assessments | `/rankings/assessments/` | 8 → 8 | 6.5 → 5.2 | 5 / 62 / 88 | 23.8 |
| Formulas | `/rankings/formulas/` | 7 → 7 | 5.2 → 4.7 | 5 / 58 / 88 | 21.5 |
| Ranking imports | `/rankings/imports/` | 8 → 8 | 9.5 → 7.4 | 8 / 61 / 88 | 28.8 |
| Problem data | `/import-problems/` | 6 → 6 | 9.4 → 5.4 | 5 / 64 / 96 | 37.0 |
| Contest names | `/tools/contest-rename/` | 9 → 9 | 8.9 → 8.4 | 7 / 99 / 112 | 41.5 |
| Contest details | `/tools/contest-details/` | 10 → 10 | 8.8 → 8.8 | 8 / 75 / 112 | 47.7 |
| Statement links | `/tools/problem-statements/linker/` | 13 → 13 | 14.8 → 14.4 | 17 / 123 / 144 | 134.8 |
| Statement editor | `/tools/problem-statements/editor/` | 10 → 10 | 15.6 → 16.1 | 10 / 111 / 128 | 108.3 |
| Statement metadata | `/tools/problem-statements/metadata/` | 7 → 7 | 6.4 → 5.9 | 6 / 62 / 88 | 28.3 |
| Statement duplicates | `/tools/problem-statements/duplicates/` | 8 → 8 | 55.1 → 22.4 | 34 / 135 / 156 | 103.7 |
| Delete statement | `/tools/problem-statements/delete-by-uuid/` | 7 → 7 | 5.8 → 6.1 | 6 / 81 / 100 | 35.3 |
| Benchmark import | `/dashboard/utilities/technique-benchmarks/import/` | 7 → 7 | 6.1 → 6.0 | 7 / 67 / 92 | 24.7 |
| Contest audit | `/tools/contest-existence-audit/` | 6 → 6 | 5.8 → 5.9 | 9 / 63 / 92 | 27.0 |
| User roles | `/users/manage-roles/` | 8 → 8 | 6.1 → 5.7 | 8 / 94 / 108 | 28.9 |
| Level settings | `/admin/levels/` | 7 → 7 | 5.7 → 5.6 | 8 / 60 / 80 | 22.4 |
| Session monitor | `/users/monitor/sessions/` | 14 → 14 | 6.5 → 6.4 | 13 / 74 / 108 | 27.7 |
| Event log | `/users/monitor/events/` | 12 → 12 | 7.4 → 6.9 | 7 / 65 / 96 | 28.1 |

## Remaining loading costs

The largest responses are Record completions (~1.03 MiB), Training content (~918 KiB), and Materials (~617 KiB). They contain substantial table/form markup. Charts and table initialization remain visible in browser DOM-ready time, particularly on Training content and Materials. A later behavior-level change could load table rows or detailed controls on demand and paginate large management collections. The present changes retain the existing visible rows and controls.

My progress and My activity still compute full-history chart summaries. Activity tables already use server pagination; this does not bound the preceding chart computation. Larger-history profiling should guide any further aggregation work. The isolated fixture also cannot establish production database latency, connection contention, compression/cache headers, CDN behavior, or third-party MathJax performance.

## Verification

- Pages, problemsets, and solutions suites: 1,127 tests passed.
- Training and shared-progress suites: 50 tests passed.
- Users and configuration suites: 119 tests passed, including the updated vendor-bundle expectation.
- Total: 1,297 automated tests passed across these suites and the navigation audit.
- Navigation audit: all 49 distinct routes passed, before and after.
- Browser: 49 documents returned 200; no captured runtime exceptions or failed network requests.
- `npm run build` passed; generated vendor bundle matches configured sources.
- Django test-settings system check passed.
- Focused performance-change Ruff checks passed. The application lint baseline check passed before concurrent shared-progress edits appeared; its final workspace run reports three new findings in those unrelated files (`shared_progress.py`, `shared_progress_comparison.py`, and `shared_progress_views.py`). Those concurrent changes were preserved.
- Focused Ruff checks and `git diff --check` passed.

Reproduce server measurements from the repository root:

```bash
DJANGO_READ_DOT_ENV_FILE=false \
UV_CACHE_DIR=/tmp/asterproof-uv-cache \
PAGE_LOAD_AUDIT_OUTPUT=/tmp/asterproof-page-loading.json \
uv run --no-sync pytest inspinia/test_page_loading.py -q --disable-warnings
```

The test database is isolated from the configured local/production database. The audit records normal GET/session/page-view side effects only inside that disposable test database. It does not create a public audit endpoint or require production settings changes.

## Release snapshot validation

The scoped release snapshot excludes the concurrent shared-progress comparison work. On current main `a0c8156f77b08a8e62aa3b297918ba1f57ccd796`, the 1,297 affected-area tests, application lint baseline, configuration/scripts Ruff checks, focused application Ruff checks, Django system check, and whitespace checks all pass. No migrations are included.
