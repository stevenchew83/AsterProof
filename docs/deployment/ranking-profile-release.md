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

Application merge is not authority installation. The separately authorized
helper extension admits only `ranking-profile-maintenance-v1`, the exact 0006
migration bytes and the frozen PostgreSQL 17.9 catalog delta
`1e39e6ff9903566f6307ed52cb45d8a2b1e464d6131bec19f441918ea29409ba`.
It requires the fixed RPO0 encrypted backup, isolated restore verification and
complete old-record/sequence/large-object preservation against that backup.
No catalogue refresh or application data backfill runs. The new empty tables
and migration recorder retain a reader floor in deploy and rollback paths.

The existing private PostgreSQL runtime can be rebound to the exact new authority
revision only with the explicit `postgres_runtime rebind-identical` administrator
command, the previous source revision and the new attested archive digest. It
verifies the installed tree and requires identical image, file membership, bytes,
sizes and permissions. Only its source-provenance manifest changes; runtime
software, accounts, credentials and network controls remain unchanged. The
ordinary installer still rejects a mismatching existing runtime.

The separately reviewed recovery-capacity extension bounds the source database
at 2 GiB. The storage gate still requires the configured 2 GiB free reserve plus
twice the actual database size, after candidate preparation. Preserve all retained
releases and recovery artifacts when provisioning capacity. The source version,
locale, encoding, provider, extensions, isolated restore, encryption and timeout
checks are unchanged. Capacity and cost authorization remain separate from an
application deploy request.

Follow [production bootstrap](production-bootstrap.md) and
[production release](production-release.md). Review the literal helper diff from
the installed authority, install from the exact clean merged revision, audit it,
and retain the unchanged target contract and protected environment. Do not
select `migration_class=none` or bypass the installed gate.

Resolve the exact current main SHA, freeze its disclosure and dispatch Production
deploy once with normal CI enabled. Verify the attested archive, protected
environment, durable operation, migration record, process/health/static identities,
authenticated profile filters and immediate stabilization. A deploy request does
not authorize unrelated student corrections, metadata backfill or publication.
