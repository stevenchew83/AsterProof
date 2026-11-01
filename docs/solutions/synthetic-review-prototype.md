# Three-mode admin review prototype: local Phase 2

This prototype exercises the assessment and disclosure workflow with bundled
synthetic submissions only. No provider is imported or called, and no model,
token usage, provider request ID, or calibration result is fabricated. Existing
student solutions, completion status, public shares, paid review policy, and
workers are not involved.

[Local Phase 3 preparation](model-comparison-preparation.md) adds separate human
review records and matched offline Astra/Sol comparison. It does not relax this
prototype's synthetic-only boundary or activate a provider.

## Open the workspace locally

With migrations applied to a verified local/test database, open
`/solutions/admin/review-prototype/` while signed in as an active application
administrator with `solutions.view_syntheticreview`. Creating reports also
requires `solutions.add_syntheticreview`; revealing hints requires
`solutions.add_synthetichintreveal`. Superusers retain their existing authority.
This change does not grant permissions to any account.

`SYNTHETIC_REVIEW_PROTOTYPE_ENABLED` defaults to false in base/production settings
and is true in local/test settings. The workspace, detail pages, hint actions, and
creation services enforce this flag and current database-backed role/permissions.
Debug mode does not bypass authorization.

Select a bundled submission, preview its problem and source, choose a mode, and
create a private report. Inputs are immutable synthetic packets identified by
their content digest, not live `SolutionRevision` objects. Arbitrary proof text,
real submission IDs, user-selected providers, and custom prompts are not accepted.
The recent history shows at most 25 private reports to authorized administrators.
There is no student or public report endpoint and no publication control in this
phase. All feedback stays private even in Examiner mode.

## Shared mathematical assessment and disclosure

Each synthetic case has one common assessment reused across all modes. Claims
contain exact source quotations with character offsets, a supported/invalid/
unjustified/unresolved verdict, a concise justification, and claim dependencies.
Findings refer to those claims. Validation rejects fabricated quotations, invalid
locations, duplicate/unknown IDs, circular dependencies, unsupported prerequisites
for supported claims, and contradictory overall assessments. Unresolved material
requires human review.

`assessment_prompts.py` owns the shared assessment instructions and distinct
feedback instructions. The corresponding strict JSON Schemas are code-managed
in `assessment_contracts.py`, with a small matching local validator. Requests are
data objects only; constructing one never dispatches it. Prompt versions, schema
versions, instruction hashes, schema hashes, and stage-input hashes are frozen
with each report. Target labels, account identities, and permission data are not
included in those mathematical requests.

- **Coach:** diagnosis, next action, and private progressive hints. Its schema
  has no score, criterion decisions, corrected proof, or reference solution.
  The coaching request omits reference proofs, the rubric, and detailed internal
  mathematical justifications. Exact reference-proof reproduction, including
  whitespace variants in hints and report limitations, is rejected as an
  additional lexical guard. Provisional criterion justifications share this guard.
- **Provisional:** coaching plus evidence-backed rubric criterion decisions.
  The response schema has no model-computed total. The backend alone calculates
  permitted credit and labels it synthetic and uncalibrated. Complete references
  are absent from the presented report.
- **Examiner:** detailed corrections covering all findings, followed immediately
  by the exact reference selected from the frozen package. Unknown reference IDs
  are rejected. The synthetic reference remains explicitly unapproved; no score
  is requested or displayed.

The Phase 1 package approval records are not bypassed for real work: this local
prototype uses only bundled `synthetic_unapproved` package snapshots and cannot
turn them into approved database packages. It makes no claim of mathematical
verification. Structural grounding and a supported verdict are not proof that
the mathematical criticism is correct. The lexical guard cannot detect all
paraphrased spoilers. New provider output and student publication require the
later accuracy, disclosure, privacy, and approval work.

## Rubric arithmetic

The scorer revalidates the rubric and requires exactly one decision per criterion.
Each decision cites distinct existing claim IDs. A criterion marked met may cite
only supported claims. Missing or invented criterion/evidence IDs are rejected.
The scorer then:

1. Withholds a numerical total when the assessment requires human review, the
   rubric does not fairly fit the approach, any criterion is unresolved or not
   applicable, or mutually exclusive routes are simultaneously claimed.
2. Awards met criteria only when all their prerequisites receive credit, resolving
   chains independently of list order. A met child cannot bypass an uncredited
   prerequisite.
3. Applies conditional caps whenever any named prerequisite is uncredited, then
   applies the rubric maximum. Raw credit, the awarded breakdown, evidence,
   justifications, and active caps remain inspectable.

This enforces arithmetic and structural credit rules, not the semantic judgment
that a cited proof passage actually earns a particular criterion. The 3/7 parity
example is illustrative synthetic partial credit, not a calibrated Olympiad mark.

## Private storage and hints

`SyntheticReview` stores the requesting administrator, idempotency key, case and
mode, frozen input packet, common assessment, validated mode output, presented
report, private hints, prompt manifest, timestamp, and content digest. A repeated
request key returns the same report, including concurrent retries; reuse for
different input/mode is rejected. Report creation locks the requesting admin row,
and hint creation locks the report before uniqueness/progression validation.
Old reports retain their own source, reference package, and output snapshots.

`SyntheticHintReveal` records report, administrator, finding, hint level, and time.
Hints require a CSRF-protected POST, must be revealed in order, and are idempotent
per administrator/finding/level. A report's initial HTML excludes all unrevealed
hints. Reveals by one administrator do not reveal hints for another. GET never
records a reveal. Private report responses use no-store and noindex headers.

Both tables reuse Phase 1's append-only application guards and protected foreign
keys. Privileged SQL or low-level Django save APIs remain outside that immutability
boundary. This does not implement a human final-mark table, student publication,
or learning analytics. Migration `0012_synthetic_review_prototype` is additive and
creates only these two tables and their constraints, without backfilling users,
solutions, approvals, or operating policy.

## Validation

Focused local suites:

```sh
python -m pytest inspinia/solutions/test_assessment_contracts.py \
  inspinia/solutions/test_review_prototype.py
```

The fixture file `testdata/prototype_assessments_synthetic.json` supplies authored
assessment and feedback candidates for all 24 Phase 1 cases. All 72 case/mode
bundles are validated locally. The separate Phase 1 candidate report fixture keeps
its deliberate failures and remains an evaluation-harness exercise. Passing these
tests establishes local workflow behavior, not model performance, formal proof
correctness, privacy eligibility for real students, or deployment readiness.
