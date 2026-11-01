# Synthetic mathematical assessment prototype release

The release preserves the existing offline evaluation workspace and adds four
empty tables for versioned mathematical references, human approval decisions,
synthetic reports, and hint reveals. The synthetic prototype stays disabled in
production. Both AI review flags stay disabled, execution mode stays offline,
and no provider, funded policy, permissions, or publication is activated.

## Exact migration contract

The frozen bundle consists only of:

| Migration | SHA-256 |
| --- | --- |
| `solutions.0011_problem_evaluation_packages` | `84d90530396e51ca2cbd1c2bfb65ebb6c50de0e5af2db912d0d3091592c7dad3` |
| `solutions.0012_synthetic_review_prototype` | `0b17355ca04f2cc39a2535d52573c0130ea44256d725f813e6bc4cff53952cf4` |

Migration `solutions.0010_offline_evaluation_contract` and every earlier solution
migration remain byte-for-byte unchanged. Package models live in
`problem_evaluation_models.py`; main's `evaluation_models.py` retains its existing
evidence models. These are separate workflows with separate records and access
checks. A synthetic report does not approve a database package or a dataset.

`assessment_prototype_schema.py` freezes both migration files, previous migration
hashes, the exact two-item pending plan, four-table catalog delta, compatibility
smoke, and packaged preservation evidence. It admits no backfill, unrelated
migration, enabled AI/prototype flag, or funded review policy. The worker retains
the existing lock and statement timeouts and recovery-required handling.

The normalized catalog delta fingerprint is
`2189a047bfbf7bc636149708e5590f7a974dbc32d58e4b993e87c15d8b177adc`.
The fixture is `scripts/deployment/tests/fixtures/assessment-prototype-schema-delta.json`.
Initial discovery used isolated PostgreSQL 15.19 and grants no release proof.
PR and release builds independently require the pinned PostgreSQL 17.9 image,
exact delta agreement, unchanged existing schema/rows/triggers/sequences, two
unused new sequences, empty new tables, and active-code read compatibility.
Only a passing source-bound PostgreSQL 17.9 run establishes that evidence.

## Production boundary

The application deployment request does not install the trusted worker allowance.
Before dispatch, use the separately authorized existing bootstrap installer from
the exact reviewed merged revision. Review its literal host changes, preserve
all existing allowances, target, accounts, gateway, sudoers, credentials, service,
environment/media paths, and protection rules. The supported installer updates
the root-owned authority modules and manifest/pointer and reloads systemd; it
does not authorize an application restart, provider activation, or ad hoc SQL.
Follow [production bootstrap](production-bootstrap.md) and obtain the separate
action-specific authority-installation authorization before executing it.

Read the actual production catalog and registry before preparing a disclosure.
`expected_catalog_audit` derives the expected fingerprints from that metadata and
the frozen delta. Do not invent production fingerprints from synthetic fixtures.
Dispatch `Production deploy` only for exact current main, with full CI,
`backward-compatible-schema`, and the source-bound disclosure and proof. Keep the
protected environment approval and normal immediate/stabilization checks.

Other pending migrations require their own established release path. This allowance cannot consume them, and their
installation is not implied by preparation of this four-table release. Do not
dispatch an incomplete disclosure or widen a plan to bypass a deployment gate.

Repository preparation grants no new production authority. No model accuracy,
human dataset approval, learning benefit, privacy eligibility, or student
publication is established by merging or deploying this code.
