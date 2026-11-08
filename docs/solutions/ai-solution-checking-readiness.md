# Offline solution-checking readiness evidence

Date: 2026-11-01. Scope: architecture contract v1 and the completed offline
foundation release. This records historical evidence; it is not a claim about
the latest production revision or authority for another deployment, provider
execution or student activation.

## Source-bound CI evidence

[CI 41288461538](https://github.com/stevenchew83/AsterProof/actions/runs/41288461538)
passed on `17ff1ae47a733e9b5f0d5b3312e27de1a807b0bb`. Both Docker isolation
modes, mandatory PostgreSQL races, additive schema preservation, assets, lint,
Django and application checks passed. The application suite had 2720 passes and
10 SQLite skips; the isolated PostgreSQL evaluation suite had 299 passes and no
skips. Source-lock checks added 74 PostgreSQL passes.

[CI 41290288254](https://github.com/stevenchew83/AsterProof/actions/runs/41290288254)
passed after integrating main `0f3ad3a46734a51b757bbfb2d3fdc3276a25cfaf`, on
`8742d4f496c4f3ba62bf684a8afae152a1835ea0`:

- Credential-free `--network=none`: 286 passed, 6 PostgreSQL-only skips.
- Internal-only PostgreSQL 17.9 evaluation suite: 299 passed, no skips. Required
  concurrency targets include the first-document-save race.
- Application/core checks: 2789 passed, 12 SQLite skips. These counts include
  newer main changes; skips are reported, not interpreted as executed tests.
- Existing PostgreSQL source locks/review regressions: 74 passed.
- Synthetic systemd maintenance contracts: 2 passed.
- PostgreSQL schema preservation, actionlint, dependency lock, static build and
  manifest, Ruff, Django checks and migration consistency passed.

Artifacts for that integrated source:

| Artifact | ID | Archive SHA-256 |
|---|---|---|
| `offline-evaluation-41290288254` | 13077056690 | `fbe213574ebbc33745299b4a18c611568d98b419cb041826beda0d5b8758100d` |
| `website-schema-rehearsal-41290288254` | 13076936909 | `216b246c7933fffe3be58d584aadf7e7d78efc00476dc497bf3848428f63c9f0` |

The first artifact contains the immutable dependency image identity, installed
package list and isolation logs. The second includes the synthetic PostgreSQL
delta: exactly 19 tables, 131 columns, 62 constraints, 65 indexes and no extension.
Its normalized schema fingerprint is
`e34c2715374cba7a9aab59c473d3308c4dcd656896509c76165972cf568842d0`.
Actions artifacts expire after seven days; the reviewed frozen schema delta is
retained in the repository. Artifact archive digests are distinct from normalized
schema fingerprints and from an individual evidence file's digest.

[Release-contract CI 41290974336](https://github.com/stevenchew83/AsterProof/actions/runs/41290974336)
passed on PR head `77d203ac8b77df1f5df0964a87d09978340c6b5d`, testing merge
`e01c8df93c4a275538da3aacf9790399166869c6`. The tested tree and head tree were
identical (`c4b2df60ec7efde2f99ef4d02db7bf94a2b71974`). The separate release
rehearsal passed active-code compatibility against main
`0f3ad3a46734a51b757bbfb2d3fdc3276a25cfaf`; source/schema/sequence/trigger
preservation, empty evidence tables and disabled/unfunded AI were explicit true.

- Isolation archive ID 13077352313, SHA-256: `de2bba45251236953356723f704d86be14fa5decaf89727abf9fa86fd2a2ab17`.
- Schema archive ID 13076588754, SHA-256: `340dfc894602be6e99fb9f4a8af4fb7bceed3485e9ada250f1838cf382534107`.
- Individual schema evidence file SHA-256: `e6153ce07337e8adbbe1a1cbc808e2e56571f516e727fa24ce1588530f29c023`.

The application totals above do not count the full deployment-script suite. An
existing overlapping directory/file pytest target selected only the explicit
JavaScript file under `scripts/`. The selector was corrected before the final
released checks so the whole directory, including all deployment regressions,
is collected. Local deployment regressions were independently executed. No omitted
test is represented as a pass.

Main subsequently advanced to `2fae98fcdb74d3eb6e4141598c02f00c5f59d9e7`
(learning-activity tracking). Both exact allowances are retained separately.
The subsequent merged release completed those checks, including the full script
suite and active-code rehearsal. The required check remains `verify`. The earlier
artifacts above remain historical engineering evidence, not model executions.

## Completed production release

[PR 391](https://github.com/stevenchew83/AsterProof/pull/391) merged as
`8b09bf548aa96c857b2b74a24ac06633d929c585`. Its first deployment
[41293526704](https://github.com/stevenchew83/AsterProof/actions/runs/41293526704)
failed before activation: an old navigation smoke expected an unassigned
administrator to have workspace access. The server correctly denied that access.

The separately authorized test/CI correction in
[PR 393](https://github.com/stevenchew83/AsterProof/pull/393) merged as
`c0c7ff57829a32a33bb4a4351ff151c70055ff94`. It tests rendered visible navigation,
explicitly checks unassigned-administrator denial and includes navigation smoke
coverage in shared CI. Authorization was not weakened.

[Deployment 41295842073](https://github.com/stevenchew83/AsterProof/actions/runs/41295842073)
successfully activated that exact release on 2026-11-01 at 10:17 UTC. Its full
quality suite reported **3796 passed, 16 environment-specific skips**. Skips are
not represented as passes. Final merged-release PostgreSQL 17.9 evidence verified
active-code compatibility against `2fae98fcdb74d3eb6e4141598c02f00c5f59d9e7`,
preserved existing rows/schema/sequences/triggers and empty new evidence tables.

- Merged schema evidence file SHA-256: `450a7b69f58054f5ec25df7433e2f8d118ef9d039d9d20224422a61178ab5160`.
- Compatibility smoke SHA-256: `6237ce7efca875836854ef3017611fce28535d062f8007c768dbdad1933e3bea`.
- Deployed archive SHA-256: `7f65c74c02b9632c2fe77bdda7f5e52bcdf3c71b76bc518c38daa0d30b3ea4a4`.

The reviewed migration allowance was installed under separate human approval,
without changing the six preserved production configuration/transport files or
restarting the application during installation. Deployment applied exactly
`solutions.0010_offline_evaluation_contract` and its 19 new tables. Immediate
health, release/archive, schema, cgroup, static-asset and short stabilization
checks passed. There was no automatic retry, rollback or delayed monitoring.

Read-only postflight found both AI flags false, execution mode `offline`, document
writes enabled, no funded/enabled policy, no activation authorizations and no
evaluation cases, snapshots or runs. The provider boundary remained hard-disabled.
This deployment authorization is completed; it supplies no future activation or
deployment grant. Later unrelated releases have their own evidence.

## Earlier local evidence

The initial local verification had 879 passes, 10 PostgreSQL-only skips, 14 direct
JavaScript contracts, successful desktop 1440px/mobile 390px synthetic workspace
checks, and SQLite preservation of existing rows, triggers, constraints, sequences
and foreign keys. No page errors, external requests or horizontal overflow were
observed in those synthetic previews. This is historical local evidence rather
than a substitute for the source-bound CI runs above.

- Local JUnit SHA-256: `bfeb65f2fafcc74f4bcc1fc404f04deb1c4d5fc9750cec332675c7f47a069566`.
- Local SQLite schema artifact SHA-256: `c40b9f1413a5253e24215415d2a00daaf075ff8d11e9de5638f0331a26673c94`.

## Readiness decisions and limits

| Gate | Conclusion |
|---|---|
| E — Engineering | Passed for the exact released offline foundation above; subsequent source changes require their own verification |
| D — Dataset | Provisional: genuine source/rights evidence, coach judgments, sampling and frozen holdouts remain outstanding |
| M — Model | Untested; fixture/import scores cannot qualify |
| P — Pedagogy | Untested; no independent-learning study performed |
| A — Activation | None issued |

No qualified coach judgment, lawful reuse permission or representative learner
corpus was fabricated. Human data-quality checks remain mandatory. The newer
statement/community systems retain their own scope and approvals.

The [release record](../deployment/offline-evaluation-release.md) distinguishes
the completed allowance installation and deployment from future operations.
Production schema changed only through the reviewed additive migration. No
provider credential, AI worker, funded policy, coach appointment, dataset or
student activation was created by that release.

## Operating result

Both AI-review flags default to false. Solution-provider execution remains
hard-blocked before SDK construction or credential use, and normal execution mode
is fixed to `offline`. Policies remain disabled and unfunded; no activation
authorization or live dispatcher is issued. The deployment plan check additionally
rejects enabled AI flags or a funded/enabled solution policy.

Paid model API calls: zero. Student AI review: disabled. Real-model performance
and educational effectiveness: untested. Editor saving, autocomplete, managed
image handling, preview, sharing and completion remain regression-covered.

See [the architecture contract](ai-solution-checking-architecture.md) and
[the isolation procedure](offline-evaluation-isolation.md) for requirements and
future approval boundaries.

The next offline milestone is [benchmark staffing, intake and protocol
preregistration](ai-solution-checking-benchmark-intake.md). That work cannot
retroactively inherit the released foundation's engineering evidence.

## Unreleased milestone preparation — 2026-11-01

Local implementation adds authenticated offline protocol preregistration using
existing immutable audit records. It creates no schema migration, appointment,
benchmark case, provider request or activation. The intake runbook and intentionally
incomplete templates prepare real staffing/source collection without inventing
qualifications, mathematical judgments or reuse permission.

Verification of the local changes:

- Broader solution/problemset/core/user/navigation/script regressions: 1877 passed,
  15 environment-specific skips. Four additional protocol edge-case checks added
  after that run were included in the final PostgreSQL check below.
- Final protocol and row-lock race suites on a disposable local PostgreSQL 15
  cluster: 51 passed, no skips. TCP was disabled; the private Unix socket and
  temporary cluster were removed after the run. This does not claim container
  isolation or deployment-version equivalence.
- Ruff, Django system checks, migration consistency and whitespace checks passed.
  The frozen migration 0010 SHA-256 is unchanged.
- CI selects the new protocol module and requires the new concurrency test to pass
  without skipping in the existing pinned PostgreSQL 17.9 isolation job. Those
  container checks have not been rerun for these local changes; Docker is absent
  from this workstation. Historical green CI is not reused as new evidence.

This preparation does not authorize deployment or activation. Genuine appointments,
source rights, independent mathematical annotation, population/sampling decisions
and an actual human-reviewed experimental protocol remain pending. D is provisional;
M/P are untested. Both AI flags and the provider block are preserved. Paid API
calls and production changes for this preparation: zero. The accompanying PR records
fresh source-bound CI evidence when available; the local counts above remain historical.
