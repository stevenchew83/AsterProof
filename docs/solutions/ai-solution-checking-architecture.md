# AI solution checking: offline architecture contract v1

Status: offline implementation; student AI review and all real-provider execution disabled.

This contract implements the two mathematical-quality gap reviews and the accepted
A–D plan. Engineering correctness, mathematical dataset quality, actual model
performance and independent learning outcomes are separate claims. None grants
activation authority to itself.

## Operating boundaries

- Typed LaTeX and explicitly managed diagrams only. Handwriting requires new evidence.
- Django and the existing database worker remain authoritative. No external eval service.
- Custodians retain case-level final-test evidence. Developers receive one aggregate
  report per snapshot, across all developer accounts. A tuned candidate needs new
  final-test evidence. Prior preparation, assignments and related-family exposure
  preclude blinded developer access.
- Database/host administrators are trusted operators. The app does not claim to hide
  labels from them. App administrator status alone grants no benchmark access.
- Existing technical fixtures remain technical fixtures. No coach approvals, genuine
  learner cases, legal permissions, pricing verification or activation are fabricated.
- No OCR, formal prover, second AI auditor, vector database, fine-tuning or authorship detector.

## Records and trust boundaries

`ReviewInputBundle` captures exact statement/source, shared problem UUID, revision,
conditions, conventions, language, rubric, modality, limitations and completeness.
Managed image records contain original and normalized RGB PNG bytes and digests.
They are database-backed, private and served only through audited authorized routes.
Arbitrary URLs are never fetched. Missing official diagrams prevent positive review.
Serialization is canonical; source text is not rewritten for hashing.

`ReviewerProfile` freezes the prompt, model, rubric, schema, preprocessing, reasoning,
output limit, timeout, retry and pricing configuration. Student review dispatch uses
that profile and the exact frozen normalized assets. New profiles do not inherit
approval. Provider execution is hard-disabled before SDK import or credential use;
only explicit injected fixtures can exercise execution in tests.

`EvaluationProblemFamily` groups translations, alternative proofs and mutations.
Cases are immutable versions with provenance and retention deadlines. Technical,
challenge and representative-learner corpora remain separate. Initial challenge
collection target is 40 families across ALG/GEO/NT/COM, not a certification sample.
Default allocation is 60/20/20 by family and domain, with explicit frozen membership.
Known families cannot change partitions across frozen snapshots. Duplicate statements
and unresolved duplicate warnings prevent freezing. Public/pretraining familiarity
remains a curator uncertainty; internal splitting cannot prove absence of contamination.

`CoachJudgment` stores independent rubric dimensions and defect graphs: validity,
completeness, justification, significance, root dependencies, method recognition,
task compliance, context and uncertainty. Omission findings may have no quote.
Ambiguous quotations remain unanchored; offsets count Python Unicode code points.
A preparer cannot independently approve their case. Two distinct appointed reviewers
submit blind judgments; differing judgments require a distinct third adjudicator.
A single judgment remains provisional. Original judgments are never overwritten.
Verified alternatives receive separate false-accusation reporting. Agreement is
conservative: differing written judgments go to adjudication rather than being
silently declared mathematically equivalent by software.

Frozen snapshots bind family partitions, exact inputs, labels, reviewer identities,
provenance and approved mathematical relationships. Withdrawals, corrections, family
leakage and exposure invalidate eligibility without quietly creating a fresh test.

Offline protocol preregistrations use immutable, authenticated audit records rather
than an additional table. They bind a snapshot partition, exact case inputs and
family counts, reviewer profile, rubric, explicit quality/sample thresholds,
population/language/level and analysis declarations, named recipients and repetition
limit before any matching report import. Existing imports cannot be retroactively
preregistered. Identical registration is idempotent; changed rules cannot reset the
limit. Failed and ambiguous imported runs consume slots. Named recipients must also
retain current scoped assignments; developers still receive only one aggregate.
The application authenticates its own registration/import chronology, not the
original generation time of an external report. All origins remain unverified for
model readiness, financial authority remains zero and provider execution stays off.

The shared `ReviewExecutionAttempt` survives deletion of a learner-facing review.
Fixture/import receipts bind run/case/dataset/input/profile/software/output identities.
Receipt origins are deterministic fixture, manual import or unverified external
execution. Caller-supplied model IDs or perfect JSON cannot become verified provider
origin. No offline code issues verified provider execution or passing M/P decisions.

Critical audit events commit atomically with approvals, protected delivery and spending.
Failures fail closed. Low-volume trust decisions use one database row mutex plus scoped
assignment and lifecycle checks. Execution accounting locks policy before attempt.
The general best-effort user-monitoring logger is not the authoritative event store.

## Scoring and assistance

Each run selects exactly one frozen partition. Failed/missing/incomplete attempts
remain visible in eligible denominators. Findings require human judgments of support,
localization, severity, context, hint validity, spoilers and matched root defects.
A correct verdict for the wrong reason fails diagnosis. All-abstaining reviewers fail
coverage. Null denominators stay null. Reports include case and family counts,
domain slices, failure/abstention categories, root recall, finding precision,
false-clear/accusation risks and family-level uncertainty limitations.

The minimum agreement floor is 90%; usable coverage, finding precision, defect recall
and minimum family count must be explicitly configured. Unknown all-field spoiler
checks cannot pass the candidate gate. Scores always report model_readiness=false.
These operational thresholds are not population error-rate guarantees.

Coach-approved metamorphic records bind both variants and expected rubric relations.
Equivalent semantics require consistent mathematical judgments, not identical prose.
Injected instructions in comments, text and images remain untrusted input. Fixture
checks establish evaluation behavior, not real-model resistance or correctness.

Student reports use per-finding POST reveal actions. A durable, idempotent release
precedes returned content; GET/query parameters cannot unlock hints. Only released
hints appear in status responses. A release is not proof of reading or understanding.
Legacy exposure remains historical_unknown. Stale hint responses cannot replace a
newer revision in the client. Edits never automatically resolve mathematical issues.
Repair records distinguish requested reassessment from independent coach judgment.

Restricted assessment windows deny enqueue, dispatch and historical report/hint
reads for the problem. Ordinary shutdown preserves otherwise-permitted historical
feedback. Restrictions, quarantine and withdrawal can separately withhold delivery.
Already dispatched work cannot be recalled; usage must still reconcile.

## Privacy, retention and finance

Feedback acknowledgement and benchmark reuse are different purposes. Learner reuse
requires current consent bound to learner, saved revision and actual source digest,
plus independent eligibility approval and a bounded retention policy. Managed
supporting-image bytes are included in the consent scope. It never copies
proofs automatically. Owner withdrawal invalidates/purges dependent private copies;
original learner writing is retained under its own ownership. Account/record deletion
also purges private execution copies. Explicit erasure is the documented exception
to immutable content: retain minimal event/financial facts and historical digests,
mark affected evidence ineligible and record the purge. Do not claim byte-identical
replay of erased evidence. Backup/WAL retention requires the separately approved
operating policy; a digest is not assumed anonymous.

No real learner submissions are imported by installation. Unknown legal/age/provider
eligibility blocks future processing. Under-13/applicable-consent-age personal data
requires verified provider retention eligibility and legal permissions; store=false
is not Zero Data Retention. No provider account configuration is changed here.

Append-only USD-micro spending events record reservations, settlements, releases,
adjustments and credits independently of student content. Deletion never restores
spent budget. All outstanding holds count across accounting windows. Unknown outcomes
retain their holds and never retry automatically. Never-dispatched expiry/revocation
releases the hold once. Cached usage details are preserved; unapproved cached-price
settlement keeps a reservation pending reconciliation instead of inventing an invoice.
One worker and existing limits remain in force. No cheaper-model silent fallback.

## Workspace and operation

The assigned workspace is `/solutions/evaluation/`. Use existing Inspinia/Bootstrap
navigation, bounded forms and pagination. Every endpoint uses the same capability
services, including original source, images, blind annotation, adjudication, snapshot
freezing, imports and finding assessment. No activation button is included.

Appointments are explicit, audited operations via `evaluation_appoint`; installation
creates no grants. The workspace scope UUID is `00000000-0000-0000-0000-000000000001`.
`evaluation_readiness` prints a non-authoritative inventory and never authorizes calls.
Owner reuse-consent create/withdraw POST routes require CSRF and the current saved
revision; they never copy a proof automatically. `evaluation_retention` defaults
to a bounded scoped preview; explicit `--apply` performs audited erasure for the
appointed curator. No schedule is installed. Historical D decisions are rechecked
against current eligibility in the readiness inventory.

An actual deployment, production appointment, configuration change or data erasure
requires its applicable operational authorization. The foundation's separately
authorized deployment is recorded in the readiness evidence; it grants no further
operation or AI activation. Protocol preparation dispatches no provider work.

## Acceptance trace and phased evidence

| Package | Implemented mechanism | Verification / remaining boundary |
|---|---|---|
| A1 | Scoped authority, critical audit, offline provider guard | Contract, security and execution tests; no authority auto-created |
| A2 | Bundles/assets/profiles/attempts/ledger | Integrity, deletion, idempotency and financial tests |
| B1 | Families, source-bound reuse, blind judgments/adjudication | Contract, assistance, security and workspace tests; genuine coach data pending |
| B2 | Frozen partitions, exposure, lifecycle propagation | Governance/security tests; legitimate representative sampling pending |
| C1 | Finding/root scoring, coverage, metamorphic checks | Deterministic scorer tests; actual mathematical model quality untested |
| C2 | Coach workspace, hint reveals, restrictions, repair events | HTTP/CSRF/owner tests, client tests, desktop/narrow synthetic preview |
| D1 | Isolated harness, PostgreSQL races, additive schema rehearsal | Local SQLite smoke and credential-free CI Docker/PG acceptance; see readiness evidence |
| D2 | Readiness inventory, this contract and evidence map | Readiness record binds isolated acceptance artifacts; human dataset evidence remains separate |

T01/T03/T04: provider guard, imported origin and security suites.
T02: isolation runner, credential-free Docker no-network and internal PostgreSQL modes.
T05–T08: scorer coverage, failure, diagnosis and protected-alternative fixtures.
T09–T10: frozen bundle/asset and missing-official-diagram tests.
T11–T13: approved relationship/injection fixtures; actual model behavior remains untested.
T14: source-changed/unassessed and authenticated repair tests.
T15–T18: per-finding release, CSRF, restriction and queue lifecycle tests.
T19–T21: owner/assignment/blinding/adjudication tests.
T22–T25: family partition, aggregate disclosure and withdrawal tests.
T26–T29: deletion-safe ledger, unknown outcomes, race and fail-closed audit tests.
T30: exact additive schema preservation smoke and legacy regression suites.
T31: immutable configuration and dependency checks.
T32: continuous editor, preview, upload and saving regressions with AI disabled.

See `offline-evaluation-isolation.md` for the reproducible isolation procedure. CI
prepares dependencies before isolation, resolves an immutable local image ID, then
requires external-network denial and non-skipped PostgreSQL race tests. The new
migration allowance is separate from the completed document-editor deployment guard.

Protocol acceptance adds immutable pre-output rules, recipient restrictions,
repetition preservation, legacy diagnostic compatibility, fail-closed audit and
PostgreSQL freeze/import races in `test_evaluation_protocols.py` and
`test_evaluation_concurrency.py`. See the [benchmark intake
runbook](ai-solution-checking-benchmark-intake.md) for the human-evidence milestones.

## Approval gates

- E: verified engineering, security, compatibility and process isolation evidence.
- D: legitimate source rights, independent mathematics, adjudication, sampling and split evidence.
- M: verified, separately authorized real-model executions under a preregistered protocol.
- P: authorized supervised educational evidence, including later independent performance.
- A: a responsible human's bounded activity/cohort/configuration/budget/time authorization.

A first controlled pilot generates P evidence; completed P is not a prerequisite
for that first study. Wider activation needs the relevant educational evidence.
A paid benchmark experiment can be authorized independently while student AI stays off.
No score or readiness record activates anything. Current M/P are untested; A is absent.
Deployment does not activate AI; delayed monitoring is not scheduled by this change.
