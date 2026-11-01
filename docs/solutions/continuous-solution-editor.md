# Continuous solution editor and AI coach

The full workspace, embedded problem editor, public Solution Writer, and homepage
Writer use one continuous LaTeX source field. CodeMirror provides local completion,
paired braces and environments, snippets, undo, and search. A textarea remains
available when JavaScript cannot load. Preview and completion make no AI requests.

## Content and compatibility

`ProblemSolution.current_revision` selects an immutable `SolutionRevision`; null
continues to read the original ordered blocks. The first explicit document save
creates a revision without changing or deleting those blocks. Conversion preserves
claim statements separately from their proofs and escapes literal plain text.
Titles, key ideas, and PDF display options are recorded with each saved revision.

An editor context binds the account, problem, original solution identity and edit
version. Saves use a transaction and optimistic version check. Stale tabs retain
the submitted document and cannot overwrite newer work. Saving, publishing, and AI
review never mark a problem solved. Device recovery is optional and scoped.

Public snapshot version 1 retains its existing blocks. New explicit sharing of a
canonical document creates version 2. Private saves and AI feedback do not update
public copies. Collections retain the existing revocation/generation rules.

Public Writer handoffs and device recovery write version 2 while recognizing
version 1. An imported original problem statement becomes private provenance;
it is not prepended to the proof or substituted for the linked canonical problem.
Public PDF exports current form text; workspace PDF exports the saved revision.
Public compilation keeps its existing restricted command/file/time/resource gates.

## AI coach

Review is an explicit owner action. Unsaved writing is saved first, then a
revision-bound request enters a database queue. The worker calls the OpenAI
Responses API with structured output, no tools, `store=false`, and automatic SDK
retries disabled. Only owned managed raster images can be sent. Asymptote source
is supplied as text with an explicit limitation; no diagram compilation is added.

The report gives an assessment, strengths, passage-specific findings, limitations,
and two progressively disclosed hints. It provides neither marks nor automatic
acceptance. Passage locations are resolved from exact quotes by the application.
Old feedback opens its exact reviewed source instead of attaching to edited text.
Existing feedback remains readable by its owner when new requests are disabled.

Processing is disabled by default. Activation requires the application kill switch,
an enabled funded policy, verified model pricing, a healthy bounded worker, and
membership in `solution-ai-pilot`. The initial policy limits are 3 requests per
user per UTC day, 20 globally, and one worker. The model is initially restricted to
`gpt-6-astra`. Unknown pricing/model configurations fail closed. Pricing verification expires after
30 days; future timestamps and limits above the initial hard caps are rejected.

All monetary budgets start at zero. Reservations account for the documented long
input price tier. An image request reserves the full model context as a deliberately
conservative upper bound (currently $22.20 at the configured baseline prices);
this is a reservation, not a predicted charge. Known usage reconciles the balance.
Ambiguous outcomes retain their reservation and are never automatically dispatched
again. Expired queued work is not sent. These controls do not authorize spending.

The private policy is configured through Django admin by an administrator who also
has the applicable Django model permission. API keys remain in server environment
configuration. Do not put keys or real learner data in source, fixtures, logs, or
browser configuration. The user acknowledgement explains third-party processing;
`store=false` is not a promise that all provider retention is eliminated.

## Validation and activation prerequisites

Ordinary tests use a fake provider and no paid requests. The 80 synthetic cases in
`inspinia.solutions.testdata` are seed material requiring coach review, not validated
benchmark labels. The offline evaluation command rejects unapproved labels and
scores externally supplied reports. Pilot activation requires coach-approved labels,
held-out evaluation meeting the recorded thresholds, and an explicitly bounded API
execution budget. No paid benchmark or production activation is part of local work.

`SOLUTION_DOCUMENT_WRITES_ENABLED` defaults off outside local/test settings. The
reader-compatible schema/release floor must be established before enabling writes.
Follow the document-schema deployment runbook; do not install deployment authority,
change production configuration, or start a production worker as a side effect of
running local checks. Do not roll back to a block-only writer after the schema floor.

## Offline evaluation architecture v2

The offline workspace and stricter evidence contract are described in
[AI solution checking architecture](ai-solution-checking-architecture.md).
Provider execution is hard-disabled in this release, independently of the student
flag and funded policy. The old scorer stays compatible but explicitly reports
non-authoritative model readiness. New hints require authenticated per-finding
release actions; status query parameters cannot reveal them. No production worker,
model experiment or activation is part of this implementation.
