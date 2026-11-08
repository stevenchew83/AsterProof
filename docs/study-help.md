# Archive AI Study Help

Study Help offers private AI hints and proofs on active text-only archive statements. Each account can save up to two successful hints per problem across statement revisions. A new hint costs one credit from the same 50-credit account allowance as an author-requested AI review. The second hint uses the first as context and asks for a distinct next step. A repeated answer uses no user credit. Proofs have a separate allowance of 50 per account and two per statement. Opening a saved response is free.

## Student and administrator workflows

The archive statement page and draft editor show the shared balance, pending generation, and saved hints. The second hint requires a revealed first hint. The archive offers full or alternative proofs with confirmation and a separate reveal. Saved output uses escaped text and restricted MathJax.

The administrator sidebar groups AI settings, hint and review histories, the review queue, user AI usage, and hint analytics under AI tools. Saving hint instructions in AI settings creates a new immutable prompt draft. The fixture preview shows the composed instructions without a provider request. Publish or restore a version after its qualification is recorded for the configured model and output settings. Hint analytics counts events by date in Kuala Lumpur. Clicks, confirmations, accepted jobs, completed jobs, failures, and first reveals are distinct. Browser clicks are best effort.

Response text is stored once in a private generation record. It does not appear in analytics, source HTML, or the status endpoint. Account deletion removes private generation records, response text, and identifiable interaction events. Provider receipts retain bounded request and response identifiers, usage, spending, and reconciliation references independently of accounts.

## Local verification

Use Django test settings and injected provider fixtures. The PostgreSQL concurrency tests require an isolated test database with no production data or credentials. The migration is additive. It creates Study Help tables and indexes without backfilling archive or user records.

## Before provider use

The DJANGO_STUDY_HELP_ENABLED and DJANGO_STUDY_HELP_EVALUATION_ENABLED flags default to false. Use a separately authorized Study Help OpenAI key provided by the existing service environment mechanism. Confirm the provider agreement, audience and consent requirements, data controls, approved archive source rights, and exact model pricing before enabling any paid operation. The provider receives archive math and generated follow-up context. AsterProof retains learner identity and analytics locally.

Configure the model and prices using the `study_help_control configure` subcommand. Prices are integer USD micros per million tokens. Caps are integer USD micros per request, UTC day, and UTC month. The command pauses student generation. Mutating control operations take an active AsterProof administrator ID and an approved operation reference. Use `study_help_control readiness` for a read-only inventory. Add `--prompt` with a saved prompt UUID to obtain the candidate profile digest. Use the `receipt` subcommand to inspect a single provider receipt.

In an approved evaluation environment, save the candidate prompt in the admin workspace and prepare a private manifest with:

- `prompt` and `profile_digest` for the saved prompt and configured model, including the app's fixed output settings.
- `expires` as an ISO timestamp with offset and `budget_micros` as the approved spending ceiling.
- `pricing` with the exact `input_price` and `output_price`.
- `fixtures` containing 24 current archive statements. Each row has `statement_uuid`, the SHA-256 `revision` of the exact UTF-8 statement text, `domain` (six each for `algebra`, `geometry`, `number_theory`, and `combinatorics`), and a Boolean `alternative` (true for eight).

With student generation paused, run `evaluate_study_help` only under the separately approved evaluation flag, manifest SHA-256, operator ID, budget, expiry, and operation reference. Direct its JSON Lines output to approved private evidence storage. Each dispatch reserves from both the evaluation budget and site caps. An unresolved receipt stops the sample. Inspect and reconcile that receipt before proposing further work. Replaying the same operation reference cannot issue the same sample action twice.

Have two distinct approved trainers or administrators review the fixed sample. Import the signed-off evidence using `study_help_control qualify`. The evidence JSON includes the exact `profile_digest`, the same `fixtures`, and two `reviews` entries. Each entry has `reviewer_id` and a `ratings` object keyed by statement UUID, then action (`hint`, `stronger_hint`, `solution`, and `alternative` where assigned). Allowed ratings are `usable`, `unusable`, `abstained`, `spoiler`, and `material_error`. A missing sample result counts as an abstention. The importer requires joint usable ratings for at least 22 of 24 per primary action and seven of eight alternatives. Either coach reporting a spoiler or material error blocks qualification. Keep the underlying review packet under the approved evidence reference.

## Private BMO 2023 P1 draft pilot

The pilot binds the exact reviewed BMO 2023 P1 statement revision and saved prompt profile on `gpt-6.1-sol`. Access requires an active, approved, enrolled administrator. The draft editor uses the regular Study Help queue, saved hints, and shared AI Review credits. Pilot mode suppresses the archive panel and denies proof actions on the server. The saved prompt remains a draft in AI settings, where publication still requires the full Study Help qualification.

Production makes the pilot available for authorization while the general Study Help and evaluation flags are off. It stays paused until an approved operator runs `study_help_control arm_draft_pilot` with their administrator ID and approval reference. The command binds one admin and the existing AI Review key version, enrolls the admin, and sets conservative request and total caps of US$0.07 and US$0.14. Each hint slot permits one request. The authorization expires after 30 minutes and cannot be replayed.

Use `process_study_help` as a one-shot worker to refresh readiness and handle each explicit click. Verify both hints, the shared credit debits, free reopening, and the two-hint cap on the draft page. Run `study_help_control pause` when verification ends. The AI Review key is decrypted only inside the authorized app account.

## Release and operations

1. Freeze the release SHA and exact additive migration bytes. Follow the [protected production release procedure](deployment/production-release.md), including the release-specific schema allowance, pinned PostgreSQL rehearsal, old application smoke, and separate trusted authority installation. Deploy with both flags off.
2. Under the approved worker operation, render the Study Help systemd templates with the existing current release path, app user, service name, and environment file. Start the dedicated timer, then verify readiness sees a recent worker heartbeat. The worker processes at most one provider call per run and recovers expired leases without replaying dispatched requests.
3. Publish the qualified prompt. Enroll the approved initial accounts and enable the funded policy for the cohort with the approved operation reference. Switch to all eligible accounts only after the audience and consent gates and cohort checks pass. Verify the process and release, worker heartbeat, quota update, explicit reveal, and generation pause during authorized immediate postflight.
4. To pause new generation, use `study_help_control pause`. Permitted saved responses remain available while the feature is enabled. To settle an uncertain provider outcome, use `study_help_control reconcile` with the existing receipt, actual USD micros, and evidence reference. An uncertain receipt holds financial capacity across windows. Reconciliation releases that hold and permits a new explicit request. Recovery keeps the additive tables and their data.
