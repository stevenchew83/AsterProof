# Production release

GitHub Actions is the sole normal authority for changing AsterProof production. A local request to “merge and deploy” means: merge an approved pull request, obtain the resulting exact `main` SHA, and manually dispatch **Production deploy** for that SHA. It never means deploying over workstation SSH.

## Preconditions

Before dispatch, require all of the following:

- the pull request is merged and its **CI / verify** check succeeded, unless the owner explicitly authorized a release-scoped CI exception under [GitHub governance](github-administration.md);
- the requested SHA is the current `main` SHA and is 40 lowercase hexadecimal characters;
- [GitHub governance](github-administration.md) has been read back successfully;
- the target is `READY` under [production bootstrap](production-bootstrap.md);
- the live cache-busted public `/healthz/` response agrees with the server registry;
- every new migration is classified in `deployment/migration-classifications.yml`;
- the named release operator is available for the immediate and stabilization checks;
- rollback/recovery ownership is staffed for the release window.

Obtain the candidate without relying on a local branch:

```bash
gh api repos/stevenchew83/AsterProof/git/ref/heads/main --jq '.object.sha'
gh pr view <merged-pr-number> --repo stevenchew83/AsterProof \
  --json state,mergeCommit,statusCheckRollup
```

Unknown, blank, stale, or conflicting evidence is No-Go. Do not substitute historical paths, service names, host keys, or SHAs.

## Verification scope

**CI / verify** runs on pull requests, without a duplicate run on pushes to `main`.
Documentation-only changes get whitespace validation while still completing the
required check. Runtime changes get lint, Django/migration checks, settings and
user-access tests, and tests for the affected apps and their known consumers.
Shared authentication, routing, templates, dependencies, and unknown paths broaden
coverage. Asset builds, lock-resolution checks, and workflow lint run when their
inputs change. Selection is defined in `scripts/ci_checks.py`.

The manually dispatched **Production deploy** workflow still runs the complete
test suite against the exact release SHA, validates the production lock, builds
the offline runtime and static files, and attests one immutable release archive.
Subsequent disclosure and deployment stages consume that same verified artifact.
All existing tests remain available; no production packaging runs for ordinary
PRs. Shared changes may also require the complete suite during PR verification.
Deploy and rollback remain manual and retain their production environment gate.

An owner-authorized CI exception may set the manual dispatch input `skip_ci=true`.
This skips installation and execution of the automated quality suite and records
the exception in the workflow summary. Production lock validation, reproducible
packaging, static checks, artifact attestation, migration disclosure, the protected
environment, preflight, activation, and postflight remain mandatory. Record the
owner's request, exact release SHA, and available local verification in the release
record. The default remains `skip_ci=false`.

Packaging verifies downloads against `requirements/production.lock`. The pinned
`django-allauth` release is source-only, so Actions builds its wheel; all other
runtime packages must have binary wheels. A generated `wheelhouse/install.lock`
requires exactly the reviewed package versions and hashes every resulting wheel.
Both the clean Actions runtime and the server install those wheels offline with
hash checking and source builds disabled. The original source lock, generated
wheel lock, and wheel bytes are all included in the attested release.

## Dispatch and approval

For a release with no migrations:

```bash
release_sha="<exact-current-main-sha>"
gh workflow run production-deploy.yml \
  --repo stevenchew83/AsterProof \
  --ref main \
  -f release_sha="$release_sha" \
  -f migration_class=none
```

The routine workflow accepts `none` and one narrowly bounded schema exception: `pages.0036_concept_assignment_reviews` at the exact hash in `scripts/deployment/concept_schema.py`. No other schema or data migration is enabled. The exception requires the frozen schema disclosure JSON input, exact starting/ending state/schema/migration fingerprints, a PostgreSQL 17.9 release-build rehearsal against the pinned image, unchanged prior schema/source fixture, and a passing active-revision compatibility smoke. The rehearsal proof is included in the attested archive; the operation's OIDC audience binds the disclosure to its exact artifact/release. The trusted worker checks the complete pending plan and exact migration bytes, repeats the starting audit, executes only the four-model migration with bounded locks/statements, then checks the expected ending audit before activation. A failure after entering `migrating` remains `recovery_required`; never blindly retry or infer a database rollback.

Install the separately approved frozen authority update through the bootstrap procedure before submitting this schema deployment. Application releases cannot update their own authority. Keep the assignment projection disabled while installing schema and materializing the reviewed seed. The new catalog-only audit command `catalog-snapshot` returns public schema/migration metadata and the server version, never application rows or credentials; store its production evidence outside source control. Compute the expected ending fingerprint using only the approved rehearsed four-table delta and the verified starting catalog. All existing integrity, environment, registry and postflight checks remain required when `skip_ci=true`.

For the one first release after `adopt-legacy`, dispatch the same exact SHA with `initial_adoption=true` and `initial_legacy_sha=<SHA from the adoption record>`. The disclosure diffs that legacy commit against the target and still requires an empty migration plan; the worker additionally runs non-mutating `migrate --check`. After approval, the server proves that no managed release exists and that the one-use adoption record, live clean legacy checkout, process path, and complete database-state fingerprint still agree. Never use these inputs after a managed `current` release exists.

Open the workflow run and inspect the build attestation, archive SHA-256, active-release evidence, and complete migration disclosure. Approve the `production` environment only when they match the release record. Approval is a separate audit checkpoint; in the single-owner model it is not separation of duty.

After approval, the job rechecks current `main`, validates the pinned target and OIDC-bound request, transfers the one immutable artifact through the forced-command gateway, and polls the durable server operation. Do not retry blindly after runner cancellation or an SSH interruption. Inspect the original run and server operation state first; GitHub run ID is the server idempotency key.

The root worker moves each received archive out of deploy-user control before handing it to the isolated build account, deletes that stabilized archive after preparation, promotes only frozen root-owned release trees, and retains at most five release directories while always preserving `current`, `previous`, and non-terminal operation targets. A cleanup failure is recorded as `retention_cleanup_failed`; capacity monitoring remains a release gate.

## Success evidence

A release is successful only when all of these agree:

- workflow requested SHA and archive SHA-256;
- verified GitHub attestation subject and source identity;
- server `current` release and release registry;
- the restarted service's complete systemd cgroup;
- cache-busted public `/healthz/` SHA, digest, schema fingerprint, and timestamp;
- representative hashed CSS and JS bytes;
- immediate and stabilization checks.

Record the workflow URL, approver, run ID, SHA, artifact digest, migration class, target marker, old/new process evidence, health/static result, and outcome. The workflow artifact retention is currently 30 days; the server registry is the longer-lived rollback authority.

Then assign the named +1 hour, +4 hour, and +24 hour follow-ups in [production monitoring](production-monitoring.md). They are operational follow-ups and do not hold the workflow open.

## Failure handling

- Before activation: current code/static must remain unchanged. Record `failed`; investigate the normalized error code.
- During or after migration: do not imply the database was rolled back. A failed or ambiguous result is `recovery_required`.
- After activation: automatic code/static rollback is allowed only when the recorded compatibility gate permits it and the unchanged database fingerprint is proven.
- On `unknown`, an unclosed non-terminal state, identity drift, or disagreement between evidence sources: stop both deploy and rollback and follow [rollback and recovery](rollback-and-recovery.md).
