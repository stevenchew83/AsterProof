# Geometry concept implementation

The app loads the reviewed Geometry catalog from
`inspinia/pages/data/geometry_concepts_v1.json`: **334 identities in 10 areas**, with
**1,823 distinct exact role/caption mappings**. Runtime IDs use `geo-` to preserve
existing Algebra and Number Theory identities. Parent links retain the reviewed
distinctions, including general, orthogonal, parallel, central, and stereographic
projections. Geodesics remain independent of the spherical-geometry branch.

## Application behavior

The authenticated Benchmark Map provides a Geometry concept catalog and the
original Geometry role-profile view. Concepts without a dedicated assessment
appear as unrated. Search includes exact aliases; pagination, target selection,
area filters, and concept deep links retain their scope.
Existing role/key deep links open the original assessment, including its stored
rating, even when an area now has a consolidated concept catalog.

Combined learning gaps count a union of statements across accepted roles and
captions. Exact practice filters use the same union and Geometry subject scope,
including secondary subject associations. Completion keeps the existing
statement-before-linked-problem precedence. Existing role-specific tabs and
benchmark import/export keys remain available.

Statement metadata imports preserve the atomic Radical axis, Arc-midpoint geometry,
and Trapezoids captions instead of collapsing them into legacy families. Re-imports
update both statement and archive tags, respecting the selected merge or replace
behavior, so authoritative statement coverage reflects the imported metadata.

Aliases match a complete caption, case-insensitively, within its role and subject.
Canonical captions and the explicit approved terms also work as legacy technique
tags. Source captions become aliases only through an explicit exact-equivalence
allowlist; no substring, fuzzy, or general punctuation normalization runs at
request time. Historical benchmark alias routes do not determine mathematical
identity. For example, Mass points resolves independently of Ceva, and contact
triangles remain independent of the incenter/incircle family.

The 3,653 resolved references from the second review are not all exact synonyms.
Compound, conditional, alternative, and qualified-family references keep their
original meanings. **All 308 held pairs are excluded from automatic aliasing.**
Four context-only candidate identities are visible in the catalog without aliases
or assessments. Bare overloaded names, unexpanded acronyms, and cross-topic
collisions remain unmapped. Brocard points/angle and the Brocard-Brokard
pole-polar theorem use separate identities.

## Assessment preservation

This implementation performs no benchmark or benchmark-alias database writes.
It does not replace source tags, change ratings, merge assessment rows, or change
problem UUIDs and completion records. No data migration is required.

All **431 captured Geometry profiles** remain accessible. Of those, **337** are
associated with accepted identities; **94** broad, compound, or ambiguous profiles
remain accessible through the original-profile view. An additional **27**
profiles from other areas are retained as shared references, giving **364**
distinct profile associations. Shared references use the same original database
rows. Existing Algebra and Number Theory ownership takes precedence in the
unfiltered map.

The **79 concepts with differing captured rating vectors have no combined
assessment or automatic priority**. The **191 concepts without a dedicated
profile remain unrated**. The remaining 64 use an existing source profile only
when their retained vectors agree. A missing selected reference or differing live
vectors disables the combined rating. Numeric source IDs record provenance;
runtime lookup uses the existing role/key contract and does not assume identical
database primary keys in every environment.

The shared progress-cache fingerprint includes the packaged Geometry catalog,
so concept and alias changes invalidate cached projections.

## Reproduction and verification

The offline compiler, its reviewed phrase allowlist, source-alias decisions, and
counts remain in the local review workspace under
`artifacts/geometry-concept-catalog-2026-10-26/implementation/`. Run it from the
repository root:

```sh
python artifacts/geometry-concept-catalog-2026-10-26/implementation/build_runtime.py
```

That local audit reads the frozen review and taxonomy metadata, checks unique alias ownership
and held-pair exclusion, and produces the packaged catalog and captured profile
fixture. It has no database access. The app itself has no dependency on the
`artifacts/` directory.

Regression coverage in `inspinia/pages/test_geometry_concepts.py` checks exact
aliases and exclusions, role/subject isolation, parent links, assessment
preservation, rating conflicts and drift, missing references, gap/practice union
parity, secondary associations, authenticated navigation, and import parity.

```sh
DJANGO_READ_DOT_ENV_FILE=false uv run --no-sync pytest \
  inspinia/pages/test_geometry_concepts.py \
  inspinia/pages/test_technique_concepts.py \
  inspinia/pages/test_number_theory_concepts.py \
  inspinia/pages/test_algebra_vocabulary.py -q
```

The packaged data records source-catalog and exact-term hashes. Production activation
uses the protected release workflow with no benchmark or alias data migration.
