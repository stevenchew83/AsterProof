# Problem evaluation packages: local Phase 1

Phase 1 adds reference infrastructure and a provider-free evaluation harness. It
does not enable AI review, call a model, change completion records, publish
feedback, grant roles or permissions, or provide evidence for a production release.
The existing coaching harness and runtime review path remain unchanged.

The [local Phase 2 admin prototype](synthetic-review-prototype.md) now exercises
three disclosure modes and rubric arithmetic on bundled synthetic packages only.
It does not activate real package use, provider execution, or student publication.

## Frozen packages and human decisions

`ProblemEvaluationPackage` belongs to `pages.ProblemSolveRecord`, preserving the
shared problem UUID. Each `(problem, version)` is unique. Its SHA-256 digest binds
the problem UUID, version, and canonical JSON content. To correct a statement,
reference, diagram manifest, or rubric, create a new package version.

The content contract includes the exact statement, explicit assumptions, domain,
level, reference solutions with methods and provenance, known pitfalls, image
identifiers/hashes/descriptions, and an optional rubric. A rubric has an integer
maximum, criterion IDs/points/dependencies, conditional caps, and mutually exclusive
criterion groups. Unknown references and cyclic dependencies are rejected. These
rules are stored and structurally validated; awarding credit and executing the
rules belong to Phase 2. Image manifests do not contain image bytes; a future
provider request must supply matching image contents separately.

All packages start pending. There is no writable `approval_status` in package
content. `EvaluationPackageApproval` records a human reviewer, timestamp, exact
package digest, decision (`approved`, `rejected`, or `revoked`), and reasons. The
latest inserted decision supplies the current status; all earlier decisions
remain. A new package version never inherits approval. Approval requires at least
one reference solution. Approving a package does not approve evaluation labels,
a model, spending, student-data processing, or a release.

Django admin provides add/view access for both record types. It requires an active
application admin role, the existing staff/admin-site access, and the relevant
Django model permissions. No permissions are automatically granted. The creator
and reviewer come from the authenticated request. Submitting a decision requires
explicit human-review confirmation. Existing records cannot be edited or deleted;
revocation is a new decision. No real approvals or synthetic package records are
seeded into an application database by this change.

Both records reject updates/deletes, conflict updates, and bulk insertion through
their standard ORM managers, and use protected foreign keys. This is application
immutability, not tamper-proof storage against privileged SQL or Django's low-level
save APIs. Integrity checks detect content/digest mismatches. Reviewer and creator
accounts are protected from normal deletion while referenced. A future retention
or erasure procedure must deliberately address that history.

Migration `solutions.0010_problem_evaluation_packages` creates only two new tables
and their constraints; it has no data backfill or provider configuration. The
consolidated local validation below covers SQLite and PostgreSQL. Production
schema/release compatibility remains outside this local work.

## Consolidated local review and validation

On 1 November 2026, the Phase 1–3 feature and existing review/revision/completion
regressions passed: 259 tests on an isolated PostgreSQL 15.19 cluster, and 255
tests on SQLite with four expected PostgreSQL concurrency skips. No provider was
called. A separate PostgreSQL run passed all 75 existing solutions app tests.
These checks establish application behavior, not mathematical accuracy.

The review added regressions and fixed concurrent duplicate report/hint requests,
incorrect author/reviewer attribution in read-only admin views, changed feedback
contexts hidden by invalid model output, and complete-reference leakage through
report limitations or criterion justifications. The disclosure guard remains
lexical and does not establish the absence of paraphrased spoilers.

Migrations `0010` and `0011` were applied, reversed to `0009`, and reapplied in a
separate throwaway PostgreSQL database. Existing synthetic rows were preserved,
all four new tables stayed empty, and the database uniqueness, check, and foreign
key constraints were verified. This is not the pinned PostgreSQL 17.9 production
release rehearsal or deployment authorization.

The cluster used a private Unix socket with no TCP listener. Temporary settings
imported `config.settings.test`, explicitly overrode `DATABASES` to that cluster,
disabled both paid review flags, and cleared `OPENAI_API_KEY`. The repository's
normal test settings use SQLite. Use `--create-db` for a fresh migration-backed
run: `--reuse-db` can retain a database whose seed rows were flushed by earlier
transaction tests.

The consolidated test selection is:

```sh
python -m pytest --create-db \
  inspinia/solutions/test_model_comparison.py \
  inspinia/solutions/test_evaluation_harness.py \
  inspinia/solutions/test_evaluation_packages.py \
  inspinia/solutions/test_assessment_contracts.py \
  inspinia/solutions/test_review_prototype.py \
  inspinia/solutions/test_coach_evaluation.py \
  inspinia/solutions/test_reviews.py \
  inspinia/solutions/test_document_revisions.py \
  inspinia/solutions/test_solution_completion.py
```

For PostgreSQL, add `--ds=<isolated_local_postgres_test_settings>` and verify the
database target before running. Never point this command at an application or
production database.

## Run the offline example

From the repository root, using Python 3.12 or newer:

```sh
python -m inspinia.solutions.evaluation_harness \
  --dataset inspinia/solutions/testdata/problem_evaluation_synthetic.json \
  --reports inspinia/solutions/testdata/assessment_reports_synthetic.json \
  --split held_out
```

This command uses only the standard library. It does not initialize Django, load
application settings or credentials, read a database, import OpenAI, or make a
network request. It emits JSON on stdout and does not modify its input files.
An invalid dataset or report exits nonzero; valid synthetic metrics exit zero,
including when a candidate performs poorly. Exit zero is not a quality gate.

The corpus has eight synthetic problems across ALG/GEO/NT/COM and 24 submissions.
Development and held-out splits contain different problems, with three submissions
per problem. Examples include alternative proofs, invalid arguments, unfinished
work, and unavailable proof material. All labels and references remain unapproved.
Candidate reports are hand-authored fixtures containing deliberate mistakes, not
outputs measured from Astra, Sol, or any other model.

Packages have content digests; reports bind to a case-input digest that includes
the exact submission and package digest. Target labels are excluded from that
input digest. Dataset/report digests in the result bind the full measurement,
including labels and split definitions. Every selected case needs an explicit
report, including failed/refused/incomplete outcomes. Duplicate or unknown reports,
changed inputs, invalid scores, ambiguous JSON, and oversized files are rejected.
One problem identity cannot appear in both splits, even across package versions.
Dataset authors must preserve the identity of mathematically equivalent problems.

Metrics include category agreement (failed outcomes stay in the denominator),
critical-error detection, critical false acceptances, false criticism of valid
proofs, acceptance of invalid/incomplete work, alternative-method slices, exact
quotation grounding, required escalation recall, and score MAE alongside score
coverage. Undefined rates are `null`. Scores with no target label are counted
separately and excluded from MAE; scores issued despite a target requiring human
review are also counted. Quotation grounding checks source occurrence only, not
whether the mathematical explanation is correct. All metrics are synthetic
exercise results, not estimates of mathematical reliability or learning benefit.

The harness accepts only `synthetic_unapproved` datasets. It always emits
`human_validated: false` and `release_gate_passed: false`, including for perfect
fixture results. Human-approved evaluation labels, adjudication/inter-rater
agreement, calibrated release thresholds, disclosure/hint-leakage evaluation, and
provider cost/latency measurements remain future work. Never promote fixture
labels to human approval or put identifiable student submissions in this corpus.
The [Phase 3 preparation](model-comparison-preparation.md) now supplies separate
human annotation/adjudication contracts and offline comparison; the shipped
examples still contain no human approvals or measured model results.
