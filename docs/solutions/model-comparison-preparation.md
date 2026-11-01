# Human-reviewed datasets and model comparison: local Phase 3 preparation

This is a standard-library-only offline workflow. It creates experiment plans and
compares supplied result files. It does not execute models, load credentials or
Django settings, contact a provider, change a database, or deploy anything. It
does not enable the existing review worker or change the synthetic admin prototype.

## Run the synthetic example

From the repository root, inspect review coverage:

```sh
python -m inspinia.solutions.model_comparison coverage \
  --corpus inspinia/solutions/testdata/comparison_corpus_synthetic.json \
  --reviews inspinia/solutions/testdata/comparison_reviews_pending.json
```

The expected result is 24 synthetic cases, zero independent human annotation
pairs, and zero approved packages. Candidate labels are explicitly unreviewed.
No named reviewers, approvals, or adjudications are shipped as real evidence.

Compare the authored fixture runs:

```sh
python -m inspinia.solutions.model_comparison compare \
  --corpus inspinia/solutions/testdata/comparison_corpus_synthetic.json \
  --reviews inspinia/solutions/testdata/comparison_reviews_pending.json \
  --plan inspinia/solutions/testdata/comparison_plan_synthetic.json \
  --astra inspinia/solutions/testdata/comparison_astra_fixture.json \
  --sol inspinia/solutions/testdata/comparison_sol_fixture.json
```

The fixtures exercise 12 held-out cases twice per model slot. The Sol-designated
fixture deliberately contains a failed pipeline, an invented quotation, and a
false criticism of a valid alternative proof. These choices test the comparator;
they are not observations about Sol or Astra. Usage, latency, returned models, and
provider request IDs are absent. No cost or timing observations are invented.

Outputs always have `release_gate_passed: false` and `recommended_model: null`.
Even perfect synthetic results cannot select a production default or approve a
release. Invalid artifacts exit nonzero; a valid comparison with poor results
exits zero. CLI success is not a mathematical acceptance gate.

## Versioned corpus and separate review evidence

`reviewed_datasets.py` supports version 2 corpora. Each has an identity, version,
source kind (`synthetic` or `deidentified_human`), frozen packages, cases, and digest.
Cases contain only identity, split, submission, package reference, and input digest.
The input digest binds the exact submission and package, excluding target labels.
Problem identities must stay in a single split across all package versions. The
validator also catches identical statements under different identities crossing
splits after whitespace normalization. Semantically equivalent rewordings still
require curator care.

Review evidence is a separate sidecar bound to the whole corpus digest, including
its split definitions. Two provenance values have deliberately different rules:

- `synthetic_unreviewed`: candidate labels may support smoke-test metrics. The
  reviewer registry and all human decision lists must be empty.
- `human_review_records`: candidate labels must be absent. Gold labels require
  current package approval and at least two independent current annotations per
  selected case. Missing evidence fails closed; candidates are never a fallback.

The review sidecar has these fields:

| Field | Meaning |
| --- | --- |
| `reviewers` | Pseudonymous reviewer IDs and assessor/adjudicator roles |
| `package_reviews` | Approval, rejection, or revocation of an exact package digest |
| `annotations` | Case-input-bound labels, reviewer, aware timestamp, reasons, and decision |
| `adjudications` | Independent resolution bound to the exact annotation IDs considered |
| `candidate_labels` | Unreviewed synthetic targets, forbidden in a human benchmark |
| `digest` | SHA-256 of canonical content excluding the digest field itself |

Labels use the existing assessment category, critical-error flag,
alternative-method flag, score or null, and required-human-review flag. A score
must fit the package rubric. Unassessable/unresolved targets have no score.

Annotations and adjudications use `decision: labelled` or `withdrawn`. A withdrawal
has null labels. Corrections append a new record with `supersedes` pointing to the
previous record for that case/reviewer; adjudications and package reviews similarly
form explicit chains. Forks, backwards timestamps, duplicate IDs, unknown reviewers,
stale input/digest bindings, and invalid labels are rejected. Every record includes
its own digest, rationale, and timezone-aware `reviewed_at`.

An adjudicator must have the adjudicator role and must not be one of the original
assessors. The resolution identifies distinct earlier annotations from independent
reviewers for the same case. If an annotation changes or is withdrawn, the old
resolution cannot silently remain authoritative. A withdrawn resolution requires
a fresh decision. Current package rejection/revocation also prevents benchmark use.

Inter-rater category agreement, full-label agreement, and score MAE are calculated
from independent annotations before adjudication. Pair counts and score coverage
are explicit. More than two assessors create multiple pairs per case; these
descriptive statistics are not independent statistical samples or significance tests.
Pairwise calculation is bounded to ten current assessors per selected case.

Start an empty review sidecar without inventing human decisions:

```sh
python -m inspinia.solutions.model_comparison review-template \
  --corpus inspinia/solutions/testdata/comparison_corpus_synthetic.json
```

This emits empty lists, not approved labels. A record's digest can be calculated
with `reviewed_datasets.artifact_digest(record)` after the human has actually
recorded the decision; then update the enclosing sidecar digest. Record IDs,
timestamps, and reasons must represent real reviewer actions in an actual benchmark.

These are operator-supplied offline records, not authenticated Django approval
exports or cryptographic signatures. Hashes bind content; they do not establish
who reviewed it or whether two IDs represent different people. The output therefore
reports `reviewer_identity_authenticated: false`. Use trusted annotation provenance
and preserve the original evidence. No file or computed metric grants application
permissions, approves a database package, authorizes student-data processing or
spending, or substitutes for the existing production gates. No real student data
is included or processed by the shipped examples. Keep identifiable data out of
the repository and model inputs.

## Matched experiment plans

Create a plan on stdout, optionally redirecting it to a new local artifact:

```sh
python -m inspinia.solutions.model_comparison plan \
  --corpus inspinia/solutions/testdata/comparison_corpus_synthetic.json \
  --reviews inspinia/solutions/testdata/comparison_reviews_pending.json \
  --mode provisional --split held_out --purpose smoke_test --repetitions 2
```

Modes are `coach`, `provisional`, and `examiner`. `human_benchmark` requires the
independent review evidence described above. Image manifests are rejected until
the runner can transport and verify image bytes; this phase supports text only.

The plan freezes `gpt-6-astra` and `gpt-6.1-sol`, high reasoning for both, common
mathematical inputs, prompt/schema versions and content, split, corpus/review
digests, mode, and one to five matched repetitions. Both models use the same
two-stage assessment/feedback contract from Phase 2. Feedback inputs are derived
from each model's assessment using the existing mode disclosure policy. Target
labels and reviewer identities never enter model request data. Comparison rebuilds
the plan against current contracts and rejects changed instructions, schemas,
inputs, model settings, review decisions, or splits. New artifacts are required
after such changes. JSON input artifacts and generated plans are bounded to 1 MB.

There is intentionally no `run`, API-key, provider-dispatch, or activation command.
A future separately authorized executor must preserve these inputs and export
its results for offline comparison; this preparation does not authorize execution.

## Imported result contract and metrics

Each model artifact declares its plan digest, requested model, reasoning setting,
execution kind, records, and digest. Each record contains case ID, trial number,
case-input digest, complete assessment-request digest, feedback-request digest,
completion status, assessment and mode output, returned model IDs, provider request
IDs, aggregate usage, pipeline latency, and error code or null. An imported
completed pipeline needs provenance for both stages. Returned model IDs must
belong to the requested family, and provider request IDs cannot be reused across
stages or repetitions. These checks establish consistency, not authenticity of
provider-supplied evidence.

Every planned case/trial needs one record, including failures, refusals, and
incomplete responses. Extra, missing, duplicate, mismatched-model, or stale-context
records are rejected. Invalid model output is counted as a failed pipeline with
an explicit validation reason, not silently omitted. Backend evidence validation
and rubric arithmetic are reused from Phase 2; an imported numerical grade cannot
bypass criterion evidence or scoring rules. Synthetic and provider artifacts
cannot be mixed, and fixture runs cannot establish a human benchmark.

Per-model metrics retain all planned cases in category/detection denominators and
report false criticism, false acceptance, alternative-method slices, escalation,
invalid output, score error, scoring coverage, and repeatability. Raw claim
grounding includes rejected outputs; the separate accepted-report finding metric
is explicitly scoped. Neither metric proves mathematical correctness or detects
every paraphrased spoiler. The comparator lists disagreements for human inspection.
Paired scoring MAE additionally uses only the common case/trials both models scored,
so unequal abstention cannot silently change that comparison's denominator.

Imported usage must include total input, cached input, and total output; reasoning
tokens, when known, are a subset of output and are not charged twice. Usage and
latency coverage accompany aggregates. Missing observations remain unknown. Cost
is optional: `--pricing` on the plan command accepts an explicit USD snapshot with
source, timezone-aware verification time, and decimal-string input/cached-input/
output rates per million tokens for both slots. There are no bundled current-price
claims or automatic price lookups. Estimated cost covers only known usage and
always has `invoiced_cost_observed: false`. Supply rates appropriate for the run's
context and processing tier; cache-write fees, tools, other service fees, and
unreported requests are not inferred by this simple token estimator.

The local regression tests simulate human annotations and provider metadata only
in memory. Those test objects are not shipped as approved evidence or measured
model runs. Human annotation collection, identity authentication, actual paid
comparison, image support, acceptance thresholds, privacy eligibility, supervised
pilot activation, and deployment remain separate future work.
