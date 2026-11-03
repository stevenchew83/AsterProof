# Ranking student profile release

The profile opens on Achievements, with separate scores, selections, complete
records and sources. Year groups stay visible; evidence and import details use
native disclosures. The yearly discipline chart and award/placing evidence chart
count all matching achievement records before pagination and provide GET filter
links, accessible counts and responsive layouts.

## Data boundary

`rankings.0006_student_achievement_profiles` has SHA-256
`e5cf53b69329c6c21f3caa9523c3c495a71638f338b4f825b563d172c0d19898`.
It adds only `rankings_resultprofile` and `rankings_resultclaim`, plus correction
kind choices. It does not backfill classifications, verify imported claims,
rewrite results/provenance, recompute rankings or change access permissions.
Award, score and placing evidence remain independent. Existing records begin
with conservative display classifications and unreviewed evidence.

The release is deliberately classified `data-or-non-compatible`: the previous
correction reader does not understand new profile/claim correction kinds. Ordinary
code rollback is disabled; schema reversal or correction reversal is not a release
recovery procedure.

## Review and verification

The ranking suite covers role boundaries, immutable correction receipts, stale
reviews, source-link safety, family reports, exact score binding, no-op imports,
whole-year pagination and chart filters. A migration regression test preserves
every prior table's rows, columns, constraints, triggers and existing sequence
values, including same-name students, zero scores, provenance and old audit items.
The two new tables must remain empty after migration.

Pre-merge local verification passed: 235 ranking/migration checks on an isolated
PostgreSQL 17.9 cluster, 10 JavaScript checks, ranking lint, Django migration-drift
checks and the asset build. The PostgreSQL run included all four concurrency/index
checks skipped by SQLite. Hosted CI remains a separate required merge gate.

The charts also have keyboard and phone checks at 390 px and 320 px using synthetic
local data. These checks do not modify production student records.

## Production gate

Read-only preflight on 3 November 2026 confirmed application revision
`64dc552c6321404d88807405b5893666449eea1f` and installed authority revision
`22e851efcad158b04f2dbdd4e4d0ab5314ed0123`. The public health result matched the
active release. Installed ranking schema support stops at migration 0005.

Application merge is not authority installation. The exact 0006 migration needs
a separately authorized, frozen deployment-helper allowance, PostgreSQL 17.9
preservation/recovery evidence and a protected data-class deployment. Do not
dispatch this release with `migration_class=none` or bypass the installed gate.
Follow [production bootstrap](production-bootstrap.md) and
[production release](production-release.md); preserve the current target,
credentials, accounts, network controls and existing release protections.

After the bounded allowance is installed and audited, resolve the exact current
main SHA, freeze its disclosure and dispatch Production deploy once with normal
CI enabled. Verify the attested archive, protected environment, durable operation,
migration record, process/health/static identities, authenticated profile filters
and immediate stabilization. A deploy request alone does not authorize unrelated
student corrections, metadata backfill or public publication.
