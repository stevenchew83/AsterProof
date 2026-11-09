# Community problems

> **Superseded submission guide.** This page records the original workflow.
> Use the [Community Proof Library guide](community-proof-library.md) for current
> visibility, moderation, and publication rules. The similarity-index command
> below still applies. Its original schema setup and AI activation steps describe
> the earlier release.

At this guide's original checkpoint, the adopted
[Community Proof Library requirements](plans/2026-11-01-community-proof-library-requirements.md)
called for moderated Private/Unlisted/Public publication, separate private
attempts and public proofs, preferred-explanation voting, and independent human
verification. Phase 1 had been implemented locally with AI disabled and its
production deployment was still ahead.

Signed-in, approved users can browse `/community/problems/` and post at
`/community/problems/new/`. These posts never create or modify
`ContestProblemStatement` or `ProblemSolveRecord` rows, including on approval.

The default **Admin reviewed** tab contains approved posts. **All problems**
contains every status, including pending, changes requested, and declined.
Both tabs paginate on the server, 20 posts at a time. The all tab applies no
status filter. Posts, attribution, metadata, and human review notes are visible
to signed-in users. Solution outlines are private to the author and admins;
AI reports are admin-only. Nothing is added to the public website.

## Posting and moderation

Required details are title, complete statement, subject, proposed MOHS (0-60),
topic tags, core ideas, difficulty rationale, authorship/source type, attribution,
and confirmation that the statement can be shared. Source URL, pitfalls, and a
private solution outline are optional. Contest name/year/code are optional for
original problems; supplying any requires all three.

Users must check the library before submission. A signed, 15-minute check is
bound to the user, complete content, post version, and library signature. Changed
details invalidate the check; possible matches require explicit acknowledgement.
The server repeats the bounded search when submitting and refuses an unavailable
index. Repeated identical new submissions from the same author reuse the existing
post. New posts are limited to ten per author per day.

Admins make a separate human decision: approve, request changes, or decline.
The latter two require notes. Decisions retain the exact submitted version and
content snapshot. Authors can edit pending or changes-requested posts; resubmission
creates a new version, returns it to pending, and requires another similarity check.
Approved and declined posts cannot be edited by their authors. Stale admin forms
cannot approve a changed version. AI never changes a moderation status.

Untrusted statements are escaped and rendered as text/math. Asymptote remains
source; this workflow never executes or sends diagram code to a rendering service.

## Library similarity index

Apply migrations `0042_community_problems` and `0043_statement_similarity_source`, then build the derived index:

```bash
python manage.py refresh_statement_similarity_index
```

Run it again after library imports or other canonical source changes. It is a
separate off-request command, with a ten-minute build deadline and transactional
publication. A failed build retains the previous index. A stale or missing index
is shown as unavailable, never as zero matches. The command is idempotent when
the library signature and algorithm version are current. Production scheduling
or initial execution is a deployment operation, not performed by this local change.

Indexed word and token-pair postings select candidates without loading the entire
statement corpus into a web request. Direct digest lookup also retrieves matching
wording and renamed-variable structure. The matcher handles short statements and
common LaTeX spacing/delimiter/fraction/inequality-command variations. It preserves
numbers and mathematical operators; related wording does not establish equivalence.
At most 200 candidates are compared, with eight displayed. Archive text is limited
to its first 12,000 characters and previews to 1,000. Candidate truncation and
limitations are disclosed in the UI. Source revision triggers detect direct and
bulk writes even when `updated_at` is omitted. The revision is scoped to statement
text and active status; publishing a solution, linking an existing statement, or
changing unrelated catalogue tags does not invalidate it. Candidate labels and
links are read from the current statement rows.

This augments submission checking; it does not change the existing nightly admin
duplicate report or its thresholds. Future improvements should be measured against
a labelled evaluation set containing exact copies, renamed variables, changed
constants/assumptions, translations, equivalent formulations, and unrelated problems
using the same technique. Semantic retrieval could improve recall for rewording and
translations, followed by explicit mathematical comparison. It should remain
advisory and should be evaluated before adding paid embedding generation.

## Admin ChatGPT review

The implementation reuses the already-declared OpenAI SDK dependency and the
Responses API with strict JSON output and `store=False`. It has its own opt-in
setting and policy; it never consumes the solution coach's budget.

1. Configure `OPENAI_API_KEY` through the existing secret mechanism.
2. Create the **Statement review policy** in Django Admin. Set an explicit model,
   verified input/output prices, per-request/daily/monthly budgets, a pricing
   verification timestamp (valid for 30 days), and up to 20 requests per UTC day.
   Prices are microdollars per million tokens; budgets are microdollars.
3. Enable that policy and `PROBLEM_STATEMENT_AI_REVIEW_ENABLED=True` only when
   the worker and spending policy are ready.
4. An admin opens a pending post, acknowledges which content will go to OpenAI,
   and selects **Request ChatGPT review**.
5. A configured worker invokes the bounded one-job command:

```bash
python manage.py process_statement_reviews
```

Each request freezes the statement, all details, private outline, and up to eight
library candidate previews. The rubric covers assumptions/domains, boundary and
equality cases, plausibility, notation, subject/tags, difficulty rationale,
attribution, and similarity. It explicitly disclaims originality and formal proof.
The report contains issues, metadata suggestions, a similarity assessment, and
limitations. An admin must still make the decision.

Requests reserve a conservative input/output allowance before queueing. Policy
locking serializes budget reservations and one worker dispatch at a time. Each
post version has one durable request; double-clicks return that request. Requests
older than 15 minutes, changed versions, or requests from a former admin expire
before dispatch. Output is capped at 4,000 tokens and SDK retries are disabled.
Connection timeouts, interrupted workers, and ambiguous outcomes are retained and
never automatically retried. Uncertain usage retains its reservation; measured
usage updates accounting. Usage above its reservation disables further dispatch.
Provider errors are stored as safe codes, without credentials or raw error bodies.

The setting and budgets default to off/zero. Tests use a synthetic provider; no
paid API request, production configuration change, worker installation, or
deployment is part of implementation verification.

API reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
