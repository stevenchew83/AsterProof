# Combinatorics concept implementation

The app packages all **358 finalized concepts across 13 areas** in
`inspinia/pages/data/combinatorics_concepts_v1.json`. Runtime code has no
dependency on the review files under `artifacts/`. The packaged source hash
identifies the finalized catalog used to build it.

## Catalog and links

The authenticated Benchmark Map has a Combinatorics concept catalog and an
original role-profile view. All 358 identities appear even when no assessment
exists. Search, sorting, pagination, target selection, and deep links retain
the selected subject. The original-profile view keeps excluded, composite,
and underspecified benchmark records accessible.

Runtime IDs use `comb-`, for example `comb-hall-theorem` and
`comb-permutation-cycle-decomposition`. The original finalized ID is retained
as `catalog_id`. This preserves existing Algebra, Number Theory, and Geometry
IDs and avoids collisions between shared tools. The six merged IDs redirect
to their surviving Combinatorics identities. The four retired ambiguous IDs
do not redirect to an arbitrarily selected meaning.

## Ratings

The catalog references 386 original assessments. All 507 captured source
profiles remain unchanged: 470 primarily Combinatorics profiles and 37 shared
profiles. The other 121 profiles remain outside the combined identity view;
they are available through their original profile views. No benchmark,
benchmark-alias, rating, or import-history database record is created,
deleted, or rewritten by this implementation.

The 145 concepts without a direct assessment appear unrated. A combined
reference is selected only when the captured vectors agree. All original
profiles remain visible. Differing live vectors or a missing selected
reference suppress the combined score and automatic priority; another role
is not silently substituted, and ratings are never averaged. Existing
reference decisions for the other subjects remain intact.

Benchmark lookup groups exact keys by role, avoiding one nested SQL branch
per profile when all subject catalogs are loaded together.

## Problem membership and context

Exact aliases retain their role and Combinatorics subject boundary, including
secondary subject associations. The packaged catalog contains 1,249 such
associations and 52 additional source-context rules. No fuzzy or punctuation-
stripping lookup is used. The legacy method caption `EXTREMAL METHOD` resolves
to the existing extremal-principle identity rather than another gap.

Context rules require the same original tag's stored technique, canonical
family, role value, and subject. A neighboring tag on the same problem cannot
supply the missing context. In particular:

- Graph and permutation cycle decompositions stay separate. A problem with
  both source occurrences can legitimately belong to both concept unions.
- Set-family hitting sets, distinct representatives, and geometric
  transversals are distinguished per source occurrence.
- `ORDERED BELL NUMBERS` supplies the context for Fubini numbers; it does not
  turn integer compositions into ordered set partitions.
- Unnamed orientation, fixed-point, and other excluded theorem labels remain
  outside automatic identity membership.

Gap counts use unions of statement IDs, so multiple matching roles on one
statement count once. Practice filters apply the same rules with correlated
original-tag queries. Subtopic previews use the actual source family for
context-dependent members. Context reads are batched and previews remain
streamed.

Statement tags take precedence over linked-problem tags. Linked tags are used
only when no statement tags exist. When a source tag has no subject, the
statement's topic takes precedence over the linked problem's topic. An
explicit statement completion likewise takes precedence over a linked
problem completion.

Problem UUIDs, statement UUIDs, linked-problem IDs, stored tags, and completion
records are untouched. Existing import preview/write classification remains
unchanged; its recognized role facts resolve through this registry. A
coarsened or unqualified legacy caption remains in its original role when no
reviewed exact or source-context mapping identifies a concept.

Progress cache versions incorporate all four packaged subject catalogs, so
installing this catalog invalidates the old cached projections.

## Verification

Regression tests are in `inspinia/pages/test_combinatorics_concepts.py`.
They cover all catalog/profile counts, exact aliases and exclusions, cross-
subject ownership, contextual membership, statement unions, practice URLs,
completion and tag fallback precedence, retired links, import parity,
authentication, and read-only request behavior.

The local suite uses SQLite with dotenv loading disabled:

```sh
DJANGO_READ_DOT_ENV_FILE=false .venv/bin/pytest \
  inspinia/pages/test_combinatorics_concepts.py \
  inspinia/pages/test_technique_concepts.py \
  inspinia/pages/test_number_theory_concepts.py \
  inspinia/pages/test_geometry_concepts.py \
  inspinia/pages/tests.py -q
```

The combined archive and subject regression suite passed **1,142 tests**.
The isolated release snapshot also passed the full suite: **1,898 tests**.
Django system checks, migration drift checks, changed-module lint, the
application lint baseline, and packaged-data reproducibility checks also passed.

PostgreSQL contextual queries are also compiled locally without opening a
database connection. Live PostgreSQL execution and production deployment are
outside this local implementation. No migration or production write is needed
to activate the source-controlled concept projection.
