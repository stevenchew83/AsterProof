# Learning activity schema release

Signed-in learning pages report visible-tab time and counts for a fixed button-action vocabulary. Administrators view measured visits separately from historical page opens. See [measurement scope and limitations](../learning-activity.md).

## Exact additive change

The only pending migration is `pages.0044_learning_page_activity`, SHA-256 `a55e4fe4f34729e7db3f1c4bf67a1deaadeb39f799958b900e2c5d840e9559e2`. It creates `pages_learningpagevisit` (UUID identity, account, canonical path/route, timestamps, cumulative time/sequence/click total) and `pages_learningpageaction` (visit, fixed action key, count). It adds the user/date index, unique visit/action constraint, non-negative checks, and cascading references. There is no backfill, existing-record update, role change, or new extension.

The classification is `backward-compatible-schema`. Code recovery retains both tables and their measurements. Account deletion cascades through the new rows. Historical durations and clicks cannot be reconstructed.

The frozen allowance is `scripts/deployment/learning_activity_schema.py`; prior page migration/seed bytes are also hash-bound. Its catalogue delta is `scripts/deployment/tests/fixtures/learning-activity-schema-delta.json`, fingerprint `6b02d16be4c90708375c5d176bedda8f868d0068f7287947aac37bc8e1621d68`. The literal pending-plan guard accepts exactly two CreateModel operations, one AddIndex, and one AddConstraint in this migration, with no additional pending plan.

## Preservation proof

CI and the protected build run `scripts.deployment.learning_activity_schema_rehearsal` in the pinned empty PostgreSQL 17.9 database. The rehearsal compares all prior migration sources with the active revision, seeds synthetic accounts, statements, progress, private/shared solutions, newsletter records and a historical page view, then compares all existing rows, sequences, schema objects, and trigger/function definitions. Both new tables and their identity sequence remain unused. Only the exact new migration-recorder row and its counter increment are allowed. A fixed active-revision compatibility smoke must pass and preserve the same state.

After merging, dispatch CI on the exact merged `main` with `baseline_sha` equal to the verified active production revision. Preserve the original Actions evidence bytes and their digest. Construct the disclosure from the catalog-only production snapshot plus the frozen delta; bind its starting/expected fingerprints, active/target revisions, exact migration, smoke digest and rehearsal digest. A local rehearsal is supporting evidence, not the exact merged Actions proof.

## Authority installation and deployment

Application deployment authorization does not install new deployment authority. Install this exact reviewed allowance only through a separately authorized [bootstrap installation](production-bootstrap.md) from the clean immutable merged revision. Preserve the current target and audit identity, marker, deployment public key and forced-command restrictions, entrypoint helpers, service definitions, users/roles, persistent environment/media, GitHub protections, active release, PID and schema fingerprints. Review the literal old/new installed authority diff. The installer reloads systemd; it does not restart the application or apply the migration. No IAM, credential, firewall, database-role or system-package changes are included.

After verifying the installed hashes and preserved controls, run the normal protected Production deploy workflow with the exact disclosure, `backward-compatible-schema`, complete CI, and environment review. The worker rechecks starting state, candidate bytes, evidence and the full pending plan, applies the migration with the existing two-second lock and thirty-second statement timeouts, then verifies ending state before activation. Never run a workstation SSH migration, dispatch it as `none`, or broaden the guard. Any failure after entering migration remains `recovery_required`; reconcile the existing operation ID before another dispatch.

Acceptance includes the expected migration/schema fingerprint, healthy process-bound release evidence, immutable tracker/static assets, no tracker on public/account/admin screens, and normal immediate and short stabilization checks. Use synthetic fixtures for collection tests; production read-only verification does not create measurements or modify learning records.
