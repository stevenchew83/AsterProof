# Catalogue and progress idle-load investigation

The first page request after idle can spend most of its application time outside
SQL execution. On 28 October, catalogue/progress requests took 1.40/0.77 seconds
to first byte with 138/81 ms of measured SQL. Immediate repeated requests were
43/155 ms; later catalogue requests still varied up to 462 ms.

A bounded process-counter sample correlated another set of page requests with
151 major faults and 251 swapped-in pages. The single web worker started that
sample with about 98 MiB swapped out on a host with about 412 MiB RAM. This is
evidence of paging, not proof that every millisecond outside SQL is paging.
Database connection setup, Redis, result processing and rendering are not
separately attributed by the existing aggregate SQL execution timer.

The shared startup dependency was spreadsheet processing. A user-session signal
imports `technique_progress`, which imported pandas and the Excel helper. Tag
parsing also imported pandas solely to detect a floating-point NaN. URL setup
loaded further spreadsheet libraries through import/export modules and rankings,
even when the requested page only needed the catalogue tables.

Spreadsheet engine imports now run inside the operations that use them. The
ordinary tag parser uses `math.isnan` under the same `isinstance(value, float)`
guard. Workbook readers, dataframe handling, cell sanitization and Excel writers
retain their existing implementations. No routing, permissions, middleware,
schema, cache lifetime, concept IDs, completion records or progress calculations
change. The frequent catalogue process benefits from the same lighter startup.

One fresh local interpreter measured Django setup at 120 MiB before and 67 MiB
after, and URL setup at 148 MiB before and 108 MiB after. These are workstation
maximum-RSS samples, not production RSS guarantees. A fresh-interpreter
regression test rejects pandas, NumPy or openpyxl imports during app setup, both
route resolutions, template compilation and maintenance command loading.
Existing import/export, catalogue and progress tests verify deferred execution.

Release acceptance includes real browser checks, matching request/server timing,
the same selected learner's progress totals, service identity, and a bounded
counter sample after idle spanning a routine catalogue refresh. Do not reset
production caches or force memory reclamation to manufacture a cold request.
