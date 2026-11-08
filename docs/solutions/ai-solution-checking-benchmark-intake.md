# Next offline milestones: people, mathematical evidence and preregistration

Status: engineering preparation, not Dataset Gate D approval. AI review and real
provider execution remain disabled. No paid calls, production appointments,
benchmark imports, activation or deployment are authorized by this document.

The foundation release is closed out in [readiness evidence](ai-solution-checking-readiness.md).
This runbook prepares genuine human work without substituting technical fixtures
for qualified judgment. The legacy 80 cases remain software fixtures and do not
count toward the new challenge-set collection target.

## 1. Appoint actual people and define their scope

Use the [appointment worksheet](examples/coach-appointments.template.csv) privately.
Record real account identifiers, domain expertise, the appointing authority,
scope, conflicts, expiry/review date and the evidence supporting the appointment.
Do not put personal details or private approval documents in the public repository.

| Responsibility | Required separation and evidence |
|---|---|
| Curator/preparer | Verifies input, source rights and family relationships; may make a provisional judgment |
| Reviewer A and Reviewer B | Distinct qualified coaches; neither prepares the case; independent initial submissions |
| Adjudicator | A third qualified judge, distinct from both initial reviewers and case preparer |
| Finding evaluators | Assigned coaches check each allegation, root match, hint and spoiler; disagreements retain both originals |
| Custodian | Protects final labels, protocol and case-level results; no conflicting prompt-developer history |
| Prompt developer | Can receive one authorized aggregate; cannot inspect hidden labels, original reports or protocol case detail |
| Later activity authority | Approves a specific future experiment/pilot; no automatic grant follows appointment |

An account role is not proof of mathematical qualification. Existing trainer
eligibility is necessary but does not grant case access. The preparer cannot
count toward independent approval. A custodian may also curate when independent
review and developer-separation rules remain satisfied; do not require unnecessary
extra staff merely to populate a diagram.

The existing `evaluation_appoint` management command writes audited scoped grants.
Prepare an exact actor/account/role/scope/expertise list first. Executing it against
production expands authority and needs action-specific authorization. This runbook
does not execute it or grant any role. A new local/demo account never stands in
for a real appointed coach.

Completion evidence: authentic appointments, checked conflicts, scoped denial tests,
and acknowledged responsibilities. Missing identities or expertise remain pending.

## 2. Establish legitimate mathematical source material

Use the [source worksheet](examples/benchmark-sources.template.csv) as an intake
queue, not an approval ledger. For every proposed family, obtain:

- Source identity/version, exact statement and all official diagrams, restrictions,
  conventions and relevant translations.
- Who can grant reuse, the permission/license evidence, permitted purposes,
  retention deadline, withdrawal contact/process and any export restrictions.
- Corpus, domain, level, language, modality, construction method and public
  familiarity/possible contamination.
- Known related problems, translations, alternative proofs and mutations, including
  previously exposed relatives. Resolve duplicate warnings explicitly.
- Whether the original statement is defective, ambiguous or missing context; do
  not force a student-error label onto a defective problem.

Possession of a book, public availability, a link or an author's name does not
establish benchmark-reuse permission. Start with genuinely coach-original material
with documented permission when available. Do not copy real learner proofs into
the challenge set by default. Learner reuse additionally needs separate, current,
source-bound consent, eligibility review and a retention/withdrawal policy.
Age or provider-eligibility uncertainty blocks future personal-data processing.

Keep private submissions and rights documents in the approved private system.
Repository worksheets contain empty columns only. Curator-uploaded managed assets
use the application; arbitrary URLs are not fetched. A coach must decide whether
the mathematical input is sufficient.

Completion evidence: an actual rights/eligibility review per source, not a filled
free-text “approved” field supplied by an agent.

## 3. Construct and independently judge the challenge set

Collection target: **40 independent problem families**, initially about 10 each
in ALG, GEO, NT and COM. This is an organizational milestone, not proof of a low
population error rate. Prefer depth and authentic mistakes over a large collection
of trivial synthetic errors.

For each family, select relevant variants: valid conventional proof, verified
alternative/advanced proof, concise valid proof, authentic or controlled root
error, omitted case and partial/missing-context proof. Not every family needs the
same variants. Preserve mutation intent privately from initial judges. Include
boundary/equality cases and theorem hypotheses, especially nonzero/gcd conditions,
existence of geometric intersections, bijection/invariant claims and descent.

Use `/solutions/evaluation/` to create the family and immutable case. Reviewers
record the multidimensional rubric and justified root-defect graph independently.
Unfamiliar methods may be valid; source anchors are optional for omissions. Two
independent judgments or supported adjudication are required before freezing.
Keep original judgments and disputes. Unresolved or single-review cases remain
provisional; do not lower the requirement to meet a collection count.

Separately collect a representative learner corpus only after authorization and
sampling design. Never infer intended-use prevalence from a balanced challenge set.

Completion evidence: approved, rights-cleared families, actual preserved judgments,
adjudication where needed and documented coverage gaps. No cases are generated or
called coach-verified by this engineering task.

## 4. Freeze partitions and protect final evidence

Default family-level split is 60/20/20. For 40 families evenly distributed across
domains, 6 development, 2 validation and 2 final-test families per domain is an
initial allocation proposal. Coaches must verify the allocation and record any
deviation before freezing. Related variants always stay together.

Freeze exact case revisions and the declared split through the workspace. Validate
rights, retention, independent approval, duplicates and relationships. Keep case
and family counts distinct. Track exposure and withdrawal; do not silently reshuffle
exposed cases into a supposedly fresh final test. Database/host administrators are
trusted operators, not claimed to be blinded by application permissions.

Completion evidence: reproducible snapshot digest, input/label/provenance bindings,
approved partition decisions and current lifecycle eligibility. Gate D remains a
human dataset decision, separate from successful schema installation.

## 5. Preregister an offline evaluation protocol

From the frozen snapshot, choose **Preregister protocol**. Select the immutable
reviewer profile and complete the [protocol template](examples/evaluation-protocol.template.json).
Its null/empty fields intentionally fail validation. The software supplies no
permissive readiness defaults. A qualified responsible person must choose and
justify the thresholds, scope, sample minimums and analysis plan.

| Field | Required decision |
|---|---|
| `partition` | One nonempty frozen partition |
| `thresholds` | Agreement at least 0.9; explicit usable coverage, finding precision, root-defect recall and independent-family minimum |
| `min_cases` | Explicit eligible-case minimum; distinct from independent-family minimum |
| `max_runs` | Total permitted imports, including failed, cancelled and ambiguous outcomes; no selective retries |
| `sampling_plan` | Selection method, exclusions, target population and limitations; do not count variants as independent families |
| `analysis_plan` | Denominators, domain/language/level slices, missing outcomes, family-level uncertainty, repeatability and stop conditions |
| `population`, `languages`, `levels` | Intended evaluation scope; coaches verify semantic coverage |
| `custodian_ids` | Explicit currently assigned custodians, including the registering actor |
| `aggregate_recipient_ids` | Explicit currently assigned developers; may be empty for offline preparation |

The record captures exact input/profile/snapshot/rubric digests, case IDs, family
IDs and domain coverage. It fixes typed LaTeX/managed diagrams, preservation of all
attempts, no automatic retry, named case-level custodians and one developer aggregate.
Financial cap is zero and execution authority is none.

Registration is immutable and idempotent for identical content. A different rule
set cannot replace it or reset its repetition allowance. Reports already imported
for the candidate/partition block retrospective preregistration. Aggregate final-test
disclosure blocks a new candidate registration on that evidence. Material tuning
needs fresh final evidence, not another label for the same exposed dataset.

Select the registration when importing reports. The server rejects different
profiles, scoring overrides, omitted registration, forged registration references
and excess runs. A malformed import that rolls back consumes no slot; a persisted
failed attempt does. Current authorization and snapshot eligibility are rechecked.
Revocation or withdrawal fails closed.

These remain diagnostic imports. The application authenticates registration and
import order inside its trust boundary; it cannot establish when an external file
was generated, whether its creator inspected labels or whether the claimed model
actually ran. Even a perfect preregistered import cannot pass Model Gate M.

Completion evidence: a genuine scoped preregistration and explicit human review of
its population, thresholds and statistical limitations. The software feature can
be tested now without claiming that a real experimental protocol is approved.

## 6. Stop before paid experiments and activation

The trusted real-provider dispatcher and verified receipts are a later engineering
milestone. They require execution authorization, privacy/age/retention checks,
frozen pricing and budget, failure reconciliation and execution-bound provenance.
The current hard provider block is retained. No credentials or worker are installed.

A later paid benchmark requires E plus relevant D, a separately approved protocol,
candidate and spending authorization. Student AI remains off during that experiment.
An initial supervised pilot needs relevant M evidence and separately approved cohort,
ages, assistance rules, support and stop conditions; it generates P evidence.
Wider activation needs the relevant learning evidence and a new operating decision.

No fixtures, imports, appointments, protocol freeze or successful deployment can
authorize itself. Until genuine evidence and human authority exist: D provisional,
M/P untested, AI disabled, paid calls zero, activation authority none.
