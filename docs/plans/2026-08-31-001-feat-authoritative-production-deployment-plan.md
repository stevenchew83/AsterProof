---
title: Establish Authoritative AsterProof Production Deployment
type: feat
status: planned
date: 2026-08-31
origin: docs/brainstorms/2026-08-31-authoritative-production-deployment-requirements.md
deepened: 2026-08-31
---

# Establish Authoritative AsterProof Production Deployment

## Overview

Make GitHub Actions, protected by the GitHub `production` environment, the sole normal authority for deploying AsterProof. A manually dispatched workflow will build and attest one immutable artifact for the exact current `main` commit, publish its migration disclosure before approval, and send it through a forced-command SSH gateway to a bootstrapped AsterProof target. The server will verify target identity, artifact integrity, migration state, persistent-data boundaries, and health before recording the release.

The design keeps the existing server and Django/Gunicorn/WhiteNoise architecture. It introduces no Docker, Kubernetes, automatic deploy-on-push, or workstation SSH deployment path.

## Requirements Trace

- R1-R5: authoritative GitHub workflow, explicit same-owner approval, exact-current-`main` restriction, dedicated least-privilege credential, and pinned host identity.
- R6-R9: one-time fail-closed target bootstrap, immutable target contract, serialization, and non-secret active SHA evidence.
- R10-R15: CI-built source/static artifact, digest and attestation verification, disclosed migrations, bounded activation/health/rollback, and persistent state outside releases.
- R16-R21: protected `main`, supply-chain hardening, deployment records, runbooks, one merge-and-deploy entry point, and recovery-only break glass.

## Scope Boundaries

- Retain the existing production host, database topology, filesystem media architecture, DNS, TLS, and application authentication behavior.
- Do not deploy from a developer workstation, expose a generic production shell, or grant the deploy account broad `sudo` or arbitrary `systemctl` access.
- Do not claim host-replacement readiness until independent secret, database, and media restore procedures have been verified.
- Do not automatically reverse database migrations. Code/static rollback is a separate, compatibility-gated operation.
- Do not commit real secrets, private keys, environment contents, host fingerprints, or unverified historical production paths.

## Context and Repository Findings

- AsterProof is a Django 5.1/Python 3.12 monolith served by Gunicorn. Production uses PostgreSQL, Redis cache, filesystem media, and WhiteNoise compressed-manifest static files (`config/settings/production.py`, `requirements/production.txt`).
- `scripts/build_and_collectstatic.sh` already provides the correct frontend/static build path (`npm ci`, `npm run build`, secret-free `collectstatic`) and must remain the shared implementation.
- `package-lock.json` is the frontend lock. The existing `uv.lock` is not a production lock because `pyproject.toml` declares only two dependencies while `requirements/production.txt` contains the application runtime set.
- `MEDIA_ROOT` and optional `.env` loading are currently relative to `BASE_DIR`. Versioned releases therefore require an explicit persistent production media path and a systemd-owned external environment file with `DJANGO_READ_DOT_ENV_FILE=False`.
- No Actions workflows, deployment scripts, infrastructure-as-code, health endpoint, release metadata, or repository-owned service/proxy definitions exist. Historical `/srv/asterproof/app` and `asterproof.service` values are discovery hints only.
- Production also needs the existing technique-catalog scheduler and host-level TeX/`latexmk` capability considered during bootstrap; these must not silently retain a stale release path.

## Key Technical Decisions

### 1. Exact current-main release identity

Dispatch `.github/workflows/production-deploy.yml` against `main` with a required `release_sha` input. Treat the input as untrusted data passed through an environment variable, require exactly 40 lowercase hexadecimal characters, and require both `github.ref == refs/heads/main` and `release_sha == github.sha` before build. After environment approval, query the GitHub ref API again and require `refs/heads/main` to still equal `release_sha`; a queued run for a now-stale commit fails before secrets are used to mutate the host.

Normal deploy accepts only this SHA. `.github/workflows/production-rollback.yml` accepts only the immediate previous successful SHA/digest in the server release registry, and only while its artifact remains intact and compatible with the current database. Both workflows use the same fixed `asterproof-production` concurrency group with `cancel-in-progress: false` and `queue: max`; document/test the platform's bounded queue capacity. Each run repeats its eligibility checks because queue order and dispatch time are not authority signals. The server lock remains the correctness boundary if GitHub queue behavior or availability changes.

### 2. Protected approval and workflow trust boundary

Only the secret-bearing deploy/rollback job references `environment: production`. The environment is restricted to `main`, requires the repository owner as reviewer, allows that owner to approve their own dispatch, and disables administrator bypass. Build, tests, migration disclosure, artifact creation, and attestation run without production secrets. Same-owner approval is an explicit audit checkpoint, not separation of duty; compensate with phishing-resistant MFA/passkeys, protected recovery methods, security-alert monitoring, minimal GitHub App/PAT grants, and immediate environment-secret/SSH rotation after suspected account compromise.

Set top-level `permissions: {}` and grant only per-job permissions. Build uses `contents: read`; attestation adds `id-token: write` and `attestations: write`; environment-protected deploy/rollback uses `contents: read` for the post-approval `main` check and `id-token: write` for per-run server authorization. Pin every action to a reviewed full commit SHA with its release tag in a comment. Enable repository SHA-pinning policy if available.

### 3. One immutable artifact and dependency lock

Keep `requirements/production.txt` as the reviewed dependency input, add every imported runtime dependency currently present only in `pyproject.toml` (including `bleach` and `markdown`) to `requirements/base.txt`, and generate `requirements/production.lock` using Python 3.12 and `uv pip compile requirements/production.txt --generate-hashes`. CI verifies regeneration produces no diff and checks overlapping `pyproject.toml` declarations remain aligned. The requirements tree is the production authority.

After bootstrap confirms the target Python ABI and Linux platform, CI downloads a complete hash-verified, binary-only wheelhouse for that target and packages it in the attested artifact. Each candidate receives a fresh `.venv` installed offline with `python -m pip --no-index --find-links wheelhouse --require-hashes`; production does not contact package indexes or run source-distribution build hooks. The active release's environment is never mutated before activation.

Build source from the exact checked-out commit, run the full deployment verification suite, call `scripts/build_and_collectstatic.sh`, and create one tar artifact containing only deployable source, `staticfiles/`, the wheelhouse, the committed production lock, and `release-metadata.json`. Exclude `.git`, `.env`, `.venv`, `node_modules`, caches, and media by construction. The in-archive metadata contains a format version, immutable GitHub repository owner/name and repository ID, exact commit, canonical GitHub run ID, build timestamp, target platform/ABI, wheelhouse inventory, and content-entry manifest; it cannot contain the enclosing archive's digest or size. Emit archive SHA-256 and size as an external signed envelope/workflow output, use them for attestation and `receive`, and store them in the server registry after verification. GitHub deployment ID is a separate audit field; run ID is the sole server idempotency key.

Upload without recompressing the release file where supported, generate a GitHub artifact attestation, and verify not just that it is valid but that repository ID/name, workflow path, trusted `main` ref, commit SHA, event, issuer, builder identity, and subject digest exactly match the approved production build policy. Only the build job's fixed digest may cross into the environment-protected job. Explicitly verify SHA-256 both after download and on the server; GitHub artifact download's own mismatch warning is not the fail-closed check.

### 4. Bootstrapped target contract and forced-command gateway

The one-time bootstrap begins with a read-only discovery report and writes nothing unless every required fact is supplied and validated: unique AsterProof marker, repository origin, release/shared roots, service identity, environment file, media path, app user/group, Python 3.12, disk threshold, proxy/static behavior, scheduler path, and TeX runtime. Commit only non-secret confirmed values to `deployment/production-target.json`; put the matching root-owned contract and marker on the server. Any mismatch or persistent state inside the replaceable checkout stops bootstrap and opens a separate infrastructure-migration decision.

Use a dedicated unprivileged SSH account/key with `restrict,command=...` (or equivalent `ForceCommand` plus `DisableForwarding`). A root-owned gateway parses a tiny allowlist from `SSH_ORIGINAL_COMMAND`, never evaluates shell text, and permits only `preflight`, `receive`, `submit`, and `status` against fixed AsterProof paths; `submit` has fixed operation types `deploy`, `rollback`, and `migration-audit`. Define a versioned grammar and length bound for every field—SHA, digest, size, run ID, deployment ID, migration class, recovery-point ID, and protocol version—and reject NUL/newline, non-ASCII/normalization ambiguity, separators, leading hyphens, duplicates, unknown fields, and replay across commands. No client value becomes a path, environment name, service name, or unchecked subprocess option; use fixed arguments and `--` boundaries.

Stream the artifact through `receive`; do not enable SCP/SFTP or a generic shell. SSH authenticates transport but does not authorize deployment. Every `receive`/`submit` request also carries a short-lived GitHub OIDC token through framed stdin, never the command line. Its custom audience contains a digest of the canonical operation envelope. The root-owned submit helper validates issuer/JWKS signature, audience-envelope binding, not-before/expiry/JTI, repository ID, `production` environment subject/claim, trusted `workflow_ref`, `refs/heads/main`, run ID, workflow SHA, operation, release SHA, artifact digest, and target marker; it records those claims and rejects replay. Possession of the static SSH key alone cannot authorize a mutation. Bootstrap preflights bounded HTTPS access to GitHub's OIDC discovery/JWKS endpoints and fails closed when keys cannot be validated.

Use one exact narrow sudoers entry allowing the deploy user to invoke `/usr/local/libexec/asterproof-deploy-submit` with no client-controlled arguments. The helper revalidates the fixed request/OIDC claims, atomically writes a root-owned request record, and starts `asterproof-deploy-operation@<numeric-run-id>.service`; status is read from an allowlisted record. This is the minimum durable bridge to prototype before adding any daemon/protocol layer. Candidate-controlled code never runs as root: the deploy user owns bounded receipt only; a secret-free build user extracts and installs binary wheels; a dedicated audit role runs trusted read-only inventory; the constrained application user runs authorized migrations with its existing environment/database rights; the privileged supervisor performs only fixed ownership, atomic-symlink, journal, and exact-service operations. It may not import candidate Python, execute dependency hooks, run migration code, or disclose the external environment file.

Harden the submit and operation units with the smallest service user/capability set, `NoNewPrivileges`, protected system/home/kernel interfaces, private temporary storage, fixed `ReadOnlyPaths`/`ReadWritePaths`, restricted address families/network, compatible syscall filtering, and CPU/memory/file/time limits. Keep the tiny root-only symlink/ownership/exact-service helper separate from archive parsing and candidate execution. Gateway/helper/unit upgrades are bootstrap operations requiring separate authorization; an application artifact never replaces its own deployment authority.

### 5. Release layout, persistent state, and activation

Use the bootstrap-confirmed equivalents of:

```text
<release_root>/
  releases/<sha>/       verified source, staticfiles, metadata, per-release .venv
  incoming/             bounded partial receives
  registry/             immutable release records plus current/previous pointers
  current -> releases/<sha>
  previous -> releases/<prior-sha>
<shared_root>/
  media/                 persistent user uploads
  environment            persistent runtime configuration, unreadable by deploy user
```

The exact paths are data in the confirmed target contract, not assumptions embedded in scripts. Production settings accept an explicit persistent media root. Systemd loads the external environment file, sets `DJANGO_READ_DOT_ENV_FILE=False`, and resolves code/Gunicorn through `current`. If nginx aliases `/static/`, bootstrap changes it only through a separately reviewed host configuration step to target `current/staticfiles`; otherwise WhiteNoise remains authoritative. `/media/` always targets shared media directly. Scheduler commands must likewise resolve through `current`.

Receive into a newly created, SHA-named boundary; reject duplicates with a different digest, unsafe archive members, unexpected owners/modes, oversize input/member count/expanded bytes, and insufficient free space. Reject all symlink, hardlink, sparse, device, FIFO, socket, absolute, duplicate, and traversal members. Use only the builder's documented reproducible tar format, allowlist required PAX keys if PAX is necessary, and reject unknown GNU/PAX extensions. Verify digest before descriptor-relative/no-follow extraction by the unprivileged build user into a new unpublished directory, then make it non-writable before privileged atomic publication. Build the per-release virtualenv and run configuration checks before migrations. Activation updates `previous`, atomically replaces `current`, restarts only the confirmed service, and then runs bounded service, loopback HTTP, public health/version, and representative static-asset checks.

### 6. Health and release evidence

Add a minimal unauthenticated, `Cache-Control: no-store` `GET /healthz/` endpoint that loads and validates root-written per-release `runtime-release-state.json` once at process startup from `BASE_DIR.resolve()`, never through a later lookup of the mutable `current` symlink. Its fixed schema contains only status, process commit SHA, artifact digest, canonical migration fingerprint, record timestamp, and schema version. Switching `current` without restarting must leave old workers reporting the old process state. Missing/malformed state fails non-200 and the endpoint never probes or exposes database, Redis, configuration, host paths, versions, migration names, or secrets.

This HTTPS endpoint is the authoritative non-secret preapproval release-state signal. The disclosure job cache-busts the request, validates hostname/TLS, schema, timestamp freshness, SHA/digest formats, and continuity with the last successful GitHub deployment record, then archives the exact response. After approval, live gateway/database preflight reconciles every field against the server registry and current process before mutation; absence, staleness, or disagreement stops. The gateway `status` independently returns a fixed allowlisted JSON schema with marker ID, release SHA/digest, operation state, service state, and bounded probe codes—never raw paths, commands, stdout, or stderr.

The workflow records requested SHA, artifact SHA-256, GitHub artifact digest/attestation result, migration class and plan, approval actor, target marker, server-confirmed active SHA, static checks, health result, timestamps, and outcome in the job summary. Server registry records current and previous SHA/digest and activation outcome. Logs disable shell tracing around credentials, redact connection material, and use explicit retention.

Health acceptance proves the running process, not merely the candidate files: after a bounded restart, `systemctl` must show a new stable main PID/start timestamp, and the verifier enumerates every process in the confirmed systemd cgroup. Every Gunicorn master/worker executable, working directory, and start time must belong to `releases/<target-sha>` with no residual process; fresh-connection health probes plus deterministic cgroup audit prove worker uniformity. `/healthz/`, the current symlink, registry, and artifact digest must agree. Repeat after a short stabilization interval. Probe one cache-busted hashed CSS and JS URL with fixed Host/SNI, connection/read timeout, status, content-type, and downloaded SHA-256 expectations from the artifact. Without adding a production login credential to GitHub, the gateway also runs bounded trusted database readiness; an authenticated browser smoke remains an operator verification when an existing authorized session is available.

### 7. Migration disclosure and rollback policy

Create a fail-closed registry in `deployment/migration-classifications.yml`. Use one canonical enum across registry, workflow input, disclosure, protocol, and records: `none`, `backward-compatible-schema`, or `data-or-non-compatible`; the release class is the strictest class among its migrations. Every migration introduced after the registered active SHA must have a reviewed entry declaring its class, whether a recovery point is required, whether code rollback remains permitted, and rationale. File inspection alone does not infer safety because the repository includes `RunPython`, no-op reverse functions, PostgreSQL-specific work, and destructive field removal.

Before approval, obtain the active SHA/digest and normalized starting migration/schema fingerprints from the no-store HTTPS release-state response, reconstruct that state in a temporary PostgreSQL CI database, and publish the ordered active-to-target Django migration plan plus registry classifications. At production preflight, trusted audit code uses the dedicated catalog-only role to require the actual starting fingerprints and declared data preconditions to match the disclosure exactly; candidate `migrate --plan` does not run with production credentials. Drift, an unknown migration, a failed precondition, or a classification mismatch stops before `migrate`. A `backward-compatible-schema` classification must explicitly prove that the old code remains safe while the forward migration runs as well as after a code rollback.

The production migration audit is an explicit read-only gateway operation with a transaction/query timeout. Trusted, bootstrap-installed audit code—not candidate Django code—connects using a dedicated database role permitted to read only approved catalog metadata and `django_migrations`, with transaction-level read-only enforcement, no application environment file, bounded resources, and denied outbound network. It records a contract-approved database identity hash/role, canonical `(app, name)` rows, row count/fingerprint, and a normalized PostgreSQL schema fingerprint over approved app-owned tables, columns, types, nullability/defaults, constraints, indexes, and extensions. The candidate's `migrate --plan` runs only in CI; production compares starting migration/schema fingerprints to the disclosure and later verifies the exact expected ending fingerprints. Any identity, role, row, ordering, count, fingerprint, schema, timeout, or disclosure difference is No-Go. Reviewed data migrations also declare bounded precondition queries executed by trusted audit code. Return redacted evidence without exposing connection details.

Deployment input repeats the canonical class and automation cross-checks it against the registry-derived value. `data-or-non-compatible` is rejected by the routine live-traffic workflow. It may proceed only through a separately authorized maintenance/drain variant that stops request-serving workers before migration, verifies a non-secret immutable recovery-point identifier, applies the forward migration, activates/restarts the target, and defines failed-migration/data-recovery handling. The verifier may consume only an already-existing independent backup authority discovered during bootstrap; if none and no conforming restore-drill evidence exist, this class remains disabled and this project does not build a backup program.

The target contract must supply the external authority's machine-checkable policy: production database/resource identity, backup ID/creation/completion, maximum backup age/RPO, maximum restore-drill age, full restore scope, integrity checks, measured recovery duration/RTO, evidence URI/digest, independent approving authority, and expiry. Missing, expired, partial, identity-mismatched, or unapproved evidence is No-Go. Free-text assurance or fresh backup metadata alone is insufficient.

Migration failure blocks activation and requires explicit recovery. Post-activation failure automatically restores code/static only for `none`, or for a registry-approved compatible schema change. Data/non-compatible releases never auto-rollback and never describe a code switch as data recovery.

### 8. Bounded retention and recovery

Protect `current`, `previous`, every release named by an in-progress operation, and the latest additional successful release. `previous` means the immediately prior active release, not inherently known-good. Automatic rollback requires its `rollback_eligible` record to remain unrevoked at dispatch and activation; a known latent defect is marked manual-only in the protected deployment request before attempting its replacement. Prune only validated children of the fixed releases directory after a successful deployment and minimum-free-space check; never traverse symlinks or shared state. Delete incomplete incoming files after seven days and retain workflow logs/artifacts for the repository-approved bounded period documented during bootstrap. If these defaults cannot meet measured artifact size and host capacity, bootstrap must set stricter safe values before enabling deployment.

Break-glass access remains a separately authorized provider/server recovery procedure. After any use, record what changed, rebuild or import a matching release record, and reconcile the active SHA/digest into a GitHub deployment run before normal deployment resumes.

### 9. Durable operations and cancellation

Assign one GitHub run ID to every request and persist it in the server journal before receipt, migration, activation, or rollback; record the distinct GitHub deployment ID only for audit correlation. Repeated run IDs are idempotent. The forced-command gateway uses the exact sudo submit helper to start a systemd operation unit whose lifecycle is independent of SSH; it then polls status. Loss of SSH or runner cancellation therefore cannot invite blind replay: the bounded server-owned operation completes or records one canonical state, and the next workflow calls `status` to reconcile before doing anything else. Canonical non-terminal states are `receiving`, `verified`, `prepared`, `migrating`, and `activating`; terminal states are `active`, `rolled_back`, `failed`, and `recovery_required`. Any ambiguous/unclosed state blocks both deploy and rollback until the documented recovery procedure resolves it.

Bootstrap adoption follows `UNMANAGED -> INVENTORIED -> BOOTSTRAPPED -> BASELINE_RECORDED -> READY`. The running production may become rollback-eligible only when a clean known commit, matching repository origin/service/host marker, artifact or reproducible content digest, normalized migration fingerprint, and successful health evidence are all proven. A dirty, detached-with-unknown-origin, or otherwise unverifiable runtime is recorded as a legacy non-rollback-eligible baseline and requires an explicit adoption/remediation release before normal deployment is enabled.

Bootstrap also records hashes, versions, owners, and modes for the forced-command gateway, submit helper, systemd/sudoers drop-ins, target contract, proxy/static and scheduler configuration, plus release contents covered by the artifact manifest. Every preflight remeasures these values and stops on out-of-band drift. This detects normal-channel violations but cannot make GitHub cryptographically authoritative over an independently privileged root/provider administrator; such access is explicitly break-glass and must be reconciled.

## End-to-End State Model

```text
dispatch current main
  -> validate exact SHA and repository controls
  -> test/build/lock/static/artifact/digest/attest
  -> discover active release and disclose migration plan
  -> wait for explicit production approval
  -> revalidate current main and target preflight
  -> reconcile prior operation and receive/verify candidate under one run ID
  -> verify actual database/schema starting fingerprints and data preconditions
  -> install/check/migrate candidate
  -> atomically activate and restart AsterProof
  -> service + HTTP + SHA + static verification
  -> record success and apply safe retention

Any pre-activation failure -> current release remains active; candidate is failed/quarantined.
Eligible post-activation failure -> restore previous code/static, verify health, record rollback.
Ineligible post-activation failure -> preserve evidence, block automation, require recovery procedure.
```

## Implementation Units

- [ ] **Unit 1: Reproducible production dependencies and CI baseline**

**Goal:** Establish one dependency/static/test baseline consumed by CI and every release.

**Requirements:** R10, R11, R17

**Files:**
- Create: `requirements/production.lock`
- Create: `scripts/deployment/check_production_lock.py`
- Create: `.github/workflows/ci.yml`
- Modify: `scripts/build_and_collectstatic.sh`
- Modify: `README.md`
- Test: `scripts/deployment/tests/test_production_lock.py`

**Approach:**
- Generate a fully transitive Python 3.12 lock with hashes from `requirements/production.txt`; document normal regeneration and explicit upgrade commands.
- Add `bleach` and `markdown` to the requirements authority, keep overlapping project declarations aligned, and make the static build invoke Python from the explicitly supplied release/CI environment rather than relying on the incomplete project `uv.lock`; preserve `npm ci`, existing frontend build, staticfiles settings, and `collectstatic` semantics.
- Build a target-platform binary wheelhouse and prove an offline clean-environment install/startup imports every runtime package.
- Add CI for lint, Django checks, targeted/full pytest, lock-drift validation, and static build. Pin Python and Node versions and all actions.

**Test scenarios:** stale/missing hash lock fails; regenerated lock is stable; requirements/project overlap drifts; clean offline environment includes Django/Gunicorn/psycopg/bleach/markdown; missing or wrong-platform wheel fails; static manifest contains representative assets; production secrets are not required.

**Verification:** `uv pip compile ... --generate-hashes` is clean, binary wheels match every hash/target tag, offline `pip install --no-index --require-hashes` succeeds in a fresh venv, and `./scripts/build_and_collectstatic.sh` succeeds there.

- [ ] **Unit 2: Release metadata, health signal, and persistent media setting**

**Goal:** Decouple persistent state from releases and expose minimal SHA evidence.

**Requirements:** R9, R15

**Files:**
- Create: `config/health.py`
- Create: `config/tests/test_health.py`
- Modify: `config/urls.py`
- Modify: `config/settings/base.py`
- Modify: `config/settings/production.py`
- Modify: `config/tests/test_base_settings.py`
- Modify: `config/tests/test_production_settings.py`
- Modify: `.env.sample`

**Approach:**
- Add environment-overridable `DJANGO_MEDIA_ROOT`, preserving the existing local/test default.
- Add a fixed `/healthz/` response sourced only from validated `BASE_DIR.resolve()/runtime-release-state.json` loaded at process startup; production cannot override that path outside the release root.
- Require production documentation/systemd to disable release-local `.env` loading and provide external media/environment paths.

**Test scenarios:** valid metadata returns status/SHA; missing, unreadable, symlink-escaped, oversized, malformed, wrong-version, or wrong-shape metadata fails without detail; response contains no path/config data; media override works without changing local/test behavior.

**Verification:** focused config tests plus `uv run python manage.py check` under test and secret-free static settings.

- [ ] **Unit 3: Artifact builder and verifier**

**Goal:** Create one allowlisted, SHA-bound, safely extractable release artifact.

**Requirements:** R10, R11, R13, R17

**Files:**
- Create: `scripts/deployment/build_release.py`
- Create: `scripts/deployment/build_wheelhouse.py`
- Create: `scripts/deployment/release_manifest.py`
- Create: `scripts/deployment/archive_safety.py`
- Test: `scripts/deployment/tests/test_build_release.py`
- Test: `scripts/deployment/tests/test_archive_safety.py`

**Approach:**
- Build from the checked-out exact SHA after tests/static collection; stage deployable tracked source plus `staticfiles`, target-platform binary wheelhouse, lock, and deterministic metadata containing canonical repository identity.
- Compute and emit release SHA-256/size separately from the archive, reject dirty/mismatched source, and never copy ignored runtime directories. Verify an exact attestation policy for repository/workflow/ref/SHA/event/issuer/builder/subject.
- Implement shared fail-closed archive member/path/link/size/mode validation for server receipt.

**Test scenarios:** exact-SHA happy path; wrong repository ID/name or attestation provenance; `.env`, media, `.git`, `.venv`, `node_modules`, caches, and sockets absent; digest mismatch rejected; traversal, absolute path, every link type, sparse/device/FIFO/socket, duplicate member, unknown PAX/GNU extension, excessive member/expanded size, and malformed metadata rejected.

**Verification:** build twice from the same staged inputs with deterministic member contents/order, inspect allowlist, verify digest, and safely extract into a temporary fixed boundary.

- [ ] **Unit 4: Migration disclosure and production-plan gate**

**Goal:** Make migration risk explicit before approval and require production state to match it.

**Requirements:** R12-R14

**Files:**
- Create: `deployment/migration-classifications.yml`
- Create: `scripts/deployment/migration_plan.py`
- Create: `scripts/deployment/schema_fingerprint.py`
- Create: `scripts/deployment/tests/test_migration_plan.py`
- Modify: documentation process for every new `inspinia/**/migrations/*.py`

**Approach:**
- Seed classifications for all migrations between the bootstrap baseline and first target release; thereafter require an entry for every new migration.
- Produce canonical JSON containing active/target SHA, ordered operations, declared class, rollback eligibility, and recovery requirement using a temporary PostgreSQL database reconstructed at the active revision.
- For a compatible-schema rollback claim, check out both active and target revisions, build the active schema, apply target migrations, then run a defined active-revision Django smoke/contract suite against the migrated schema; include this evidence in the disclosure.
- Add server-side comparison through a fixed `submit` operation type `migration-audit` with its own allowlisted input/output schema and idempotency rule. Trusted audit code and its catalog-only database role compare actual migration/schema starting fingerprints with the disclosure; candidate `migrate --plan` never runs with production credentials. Accept no extra, missing, reordered, unknown, or failed data-precondition result.

**Test scenarios:** no-op plan; known expand/compatible schema plan proves old-code compatibility during migration; `RunPython`/no-op reverse/remove-field requires explicit non-compatible classification; missing registry entry; active SHA unavailable; wrong database/role; timeout; DB drift; row-order/fingerprint/count mismatch; disclosed/actual mismatch; unverifiable recovery point or stale restore drill.

**Verification:** exercise representative existing migration shapes in temporary PostgreSQL and prove the same canonical plan is produced preapproval and accepted server-side.

- [ ] **Unit 5: Server target contract, bootstrap, and restricted gateway**

**Goal:** Convert the existing host from historical knowledge into a validated, least-privilege deployment target.

**Requirements:** R4-R8, R15, R19, R21

**Files:**
- Create: `deployment/production-target.example.json`
- Create after live discovery: `deployment/production-target.json`
- Create: `scripts/deployment/bootstrap.py`
- Create: `scripts/deployment/server_gate.py`
- Create: `scripts/deployment/server_activate.py`
- Create: `deployment/systemd/asterproof-deploy-operation@.service`
- Create: `deployment/sudoers/asterproof-deploy-submit`
- Create: `scripts/deployment/tests/test_bootstrap.py`
- Create: `scripts/deployment/tests/test_server_gate.py`
- Create: `docs/deployment/production-bootstrap.md`

**Approach:**
- Split bootstrap into read-only discovery/report and explicitly invoked installation; do not write a target contract from guessed defaults.
- Validate ownership/modes, marker/origin/service/path/media/environment/static/scheduler/runtime/disk boundaries before installing the key/gateway.
- Parse only fixed allowlisted commands/tokens, stream bounded artifacts to `incoming`, and submit fixed framed operation records through the one exact sudo helper to the durable systemd unit. Require per-run GitHub OIDC authorization and enforce the deploy/build/audit/application/privileged execution matrix so root never imports or executes candidate code.
- Installation requires a separately authorized operational session; repository implementation and tests do not themselves mutate production.

**Test scenarios:** correct fixture; wrong host marker/origin/service/repository ID; shared state under releases; writable/drifted gateway/helper/unit/sudoers; invalid OIDC issuer/audience/environment/workflow/ref/repository/expiry/binding; replay; sudo with any argument; partial/duplicate frame; unit-start failure; unknown command; option injection; malformed/oversized/newline/NUL/Unicode/separator/leading-hyphen/duplicate protocol fields; forwarding/shell attempts; root candidate-code execution attempt; insufficient disk; stale scheduler/static path; repeated bootstrap idempotence; partial-install recovery.

**Verification:** unit tests use temporary roots/fake service probes; `bootstrap.py audit` produces no changes; shell wrappers, if any, pass `bash -n`; a reviewed bootstrap transcript proves the real target before enablement.

- [ ] **Unit 6: Receive, activation, rollback, registry, and retention state machine**

**Goal:** Safely activate or restore immutable releases while protecting persistent state.

**Requirements:** R7-R9, R11-R15, R18

**Files:**
- Create: `scripts/deployment/release_state.py`
- Create: `scripts/deployment/operation_worker.py`
- Create: `scripts/deployment/tests/test_release_state.py`
- Modify: `scripts/deployment/server_gate.py`
- Modify: `scripts/deployment/server_activate.py`
- Create: `docs/deployment/rollback-and-recovery.md`

**Approach:**
- Persist operation/release records keyed by canonical GitHub run ID, retain deployment ID separately for audit, and run critical phases under the durable supervisor rather than the SSH process.
- Use fsync/atomic rename for completed receive/records and atomic symlink replacement for `current`/`previous`; serialize locally with a fixed lock in addition to Actions concurrency.
- Capture a pre-deploy baseline for service/PID, loopback and public HTTP, static hashes, active SHA/digest, DB fingerprint, disk, scheduler status, and recent application error evidence; degraded/unknown baseline is No-Go.
- Restart only the target-contract service and enumerate its full systemd cgroup before bounded loopback/public `/healthz/`, SHA/digest, trusted database readiness, and representative static checks immediately and after stabilization.
- Apply automatic rollback only when disclosed policy permits; otherwise stop with `recovery_required`.

**Test scenarios:** proven and unverifiable first-adoption baselines; degraded baseline; normal activation with process path/PID evidence; duplicate idempotent request; disconnect/retry cannot replay migration; same SHA/different digest; deploy/rollback lock contention; failures at receive/extract/venv/check/migrate/symlink/restart/health/record; compatible and ineligible rollback; interrupted activation reconciliation; current/previous retention protection; symlink/path attack; bounded log redaction. Rollback success requires previous SHA/digest across symlink, registry, process, health and static bytes while the DB fingerprint remains unchanged; otherwise record `recovery_required`.

**Verification:** integration test runs the state machine against temporary releases and fake systemctl/HTTP/DB adapters, asserts old current remains untouched before activation, and completes a deploy/health-failure/rollback drill.

- [ ] **Unit 7: Authoritative deploy and rollback workflows**

**Goal:** Make every normal production change originate from one protected GitHub path.

**Requirements:** R1-R3, R5, R8, R16-R20

**Files:**
- Create: `.github/workflows/production-deploy.yml`
- Create: `.github/workflows/production-rollback.yml`
- Create: `scripts/deployment/validate_dispatch.py`
- Create: `scripts/deployment/tests/test_workflow_contract.py`
- Create: `docs/deployment/production-release.md`

**Approach:**
- Deploy workflow stages: exact-SHA validation; CI/static/lock; artifact/digest/attestation; active-release lookup and migration disclosure; environment approval; post-approval `main` revalidation; SSH preflight/receive/plan verification/activate/status; job summary.
- Rollback workflow stages: exact immediate-previous successful SHA/digest lookup; artifact and database compatibility verification; environment approval; post-approval target verification; bounded rollback/status; audit summary. It always executes the current trusted gateway/workflow code, never scripts from the old release.
- Share `asterproof-production` concurrency without cancellation. Keep SSH key, host/user, pinned known-host line, and expected marker only in `production` environment secrets/variables.
- Use strict known-host verification, no dynamic `ssh-keyscan`, no expression interpolation into shell code, per-run environment-bound GitHub OIDC authorization, and secret-safe logging. Server-side subprocess output is normalized into allowlisted codes/bounded sanitized excerpts before GitHub sees it; raw Django/systemd/package/database/HTTP errors and internal paths are not forwarded.

**Test scenarios:** malformed/unmerged/stale SHA; main changes while awaiting approval; environment missing; host-key mismatch; marker mismatch; artifact/attestation/digest mismatch; SSH timeout; unknown rollback target; concurrent queued runs; summary includes required evidence and excludes secrets.

**Verification:** static workflow contract tests plus `actionlint`; run a non-secret artifact build; then use a deliberately non-mutating production preflight run before enabling activation.

- [ ] **Unit 8: GitHub governance, adoption, and operational runbooks**

**Goal:** Enable the mechanism without leaving an alternate or ambiguous authority path.

**Requirements:** R1-R5, R16-R21

**Files:**
- Create: `docs/deployment/github-administration.md`
- Create: `docs/deployment/credential-rotation.md`
- Create: `docs/deployment/host-replacement.md`
- Create: `docs/deployment/disaster-recovery.md`
- Create: `docs/deployment/production-monitoring.md`
- Modify: `README.md`

**Approach:**
- Before workflow enablement, verify repository visibility/plan entitlements; this repository is currently public, but the runbook must block if visibility changes and required reviewers/attestations are unavailable.
- Create an active `main` ruleset requiring PRs, existing CI checks, no force-push/deletion, and no direct-push bypass. Zero PR approvals is intentional for the single-owner model; production approval remains separate.
- Configure `production` reviewer/branch/no-bypass policy, environment secrets/variables, artifact/log retention, and full-SHA action policy.
- Register the currently running release as the baseline only after server SHA/digest/source identity is proven; otherwise stop and perform a reviewed initial artifact adoption.
- Document `merge and deploy` as dispatching the authoritative workflow, credential/host-key rotation, recovery-only break glass, reconciliation, and host replacement around independently restored persistent state.
- Consume an already-existing independently administered recovery-point source, if bootstrap proves one, using credentials unavailable to the deploy key, candidate code, and application user; validate strict database/resource/backup identities and retain separate restore-drill evidence. Otherwise keep data/non-compatible deployment disabled and open a separate backup-authority scope.
- Keep workflow-blocking verification to immediate and one short stabilization check. Assign +1-hour/+4-hour/+24-hour observations of errors, latency, SHA drift, static failures, disk, DB connectivity/fingerprint, and scheduler paths as a named-owner, non-blocking operational follow-up using existing monitoring/manual evidence; do not create a monitoring platform or hold the workflow open for 24 hours.

**Test scenarios:** administrator checklist detects missing rules/environment/reviewer/secret/variable/action policy; rotation overlaps old/new key safely and revokes old key; baseline mismatch blocks first deploy; break-glass reconciliation prevents normal deploy until recorded.

**Verification:** export/read back GitHub ruleset/environment configuration, execute a dry-run preflight, deploy one no-migration release with approval, prove GitHub/server SHA+digest agreement, force a post-activation health failure in a safe test target, and complete the rollback drill. Production mutation remains a separately approved operational step.

## System-Wide Impact

### Interaction graph

1. A PR changes application, dependency, migration registry, or deployment code and passes CI.
2. Merge makes one immutable SHA the current `main` candidate.
3. Manual dispatch builds and attests that SHA; migration disclosure compares it with recorded active SHA.
4. Environment approval releases connection secrets; current-main and server target are revalidated.
5. Forced-command gateway receives and prepares a new release without modifying active code/static.
6. Matching migrations run, then the atomic `current` switch moves Gunicorn/WhiteNoise/static to the candidate.
7. Health/version/static evidence becomes the GitHub and server release record; eligible failure invokes bounded code/static rollback.

### Error propagation and recovery

- GitHub/ref/artifact/attestation failures stop before production access.
- Target/disk/path/registry/DB-plan failures stop before activation and leave current untouched.
- Migration failures may have persistent DB effects even though activation is blocked; the workflow records `recovery_required` and never claims rollback.
- Service/HTTP/static failures after activation enter the compatibility gate; eligible code/static rollback must itself pass health and be recorded, otherwise the system remains blocked for recovery.
- An interrupted run is reconciled from the local lock, symlinks, manifest, and append-only operation record; a new run cannot guess or overwrite ambiguous state.

### State lifecycle risks

- Filesystem media and external environment must never be placed under a prunable release root.
- Per-release virtualenvs prevent dependency preparation from changing the active process environment.
- Migration state is shared and irreversible by code switching; classification and recovery evidence are therefore release inputs, not after-the-fact notes.
- Server release records outlive GitHub's shorter deployment-status retention and are necessary for rollback eligibility.

### API and compatibility

- New public interface: `GET /healthz/` with a deliberately minimal fixed JSON schema and no authentication dependency.
- New operator interfaces: workflow inputs and the forced-command protocol. Version both contracts and reject unknown versions.
- Application pages and login behavior remain unchanged. Static URLs continue to use the active release's manifest through WhiteNoise or one confirmed proxy alias.

## Verification Matrix

| Layer | Required evidence |
|---|---|
| Repository | Ruff, Django checks, full pytest, lock drift, secret scan of staged artifact, actionlint |
| Artifact | Exact SHA, allowlist, SHA-256, size, GitHub attestation verification, server digest verification |
| Target | Marker/origin/service/path/owner/mode/Python/disk/static/media/environment/scheduler/TeX preflight |
| Database | Published ordered plan, complete classification, actual applied-state match, recovery reference when required |
| Activation | Atomic current/previous pointers, only AsterProof restart, bounded timeout, stable new PID/path, service and HTTP success |
| Public runtime | `/healthz/` exact SHA plus cache-busted representative JS/CSS 200, correct content types, artifact-matching bytes, and active static origin |
| Audit | Actor, separate approval, SHA/digests, migration decision, timestamps, target, health, outcome in both records |
| Recovery | Safe-target preactivation failure, compatible postactivation auto-rollback with unchanged DB fingerprint, ineligible rollback stop, rotation drill |
| Monitoring | Blocking immediate/stabilization checks plus assigned non-blocking +1h/+4h/+24h follow-up against baseline |

## Rollout Sequence and Gates

1. Merge CI, lock, artifact, health, deployment scripts, tests, and runbooks while deployment workflows remain unable to activate production.
2. Configure and read back `main` ruleset and `production` environment. Block if plan entitlements do not satisfy explicit review and attestation requirements.
3. Run bootstrap discovery through separately authorized production access; resolve target/persistence discrepancies without writing.
4. Review and separately authorize bootstrap installation of marker, paths, gateway, key, stable service/static/scheduler pointers, and baseline record.
5. Add environment secrets/variables and run the deploy workflow through build, disclosure, approval, and non-mutating server preflight only.
6. On a safe target with the same artifact, gateway, state machine, service adapter, and probes, complete deploy, induced health failure, automatic rollback, and previous-SHA verification before any production activation.
7. Record a literal first-production Go/No-Go release record with expected and observed values for rules/environment, approval, target marker, service, persistent paths, free space, current and previous eligibility, current health, current SHA/digest, DB identity/fingerprint/plan, artifact digest/attestation, and migration classification/recovery evidence. Blank or unknown is No-Go.
8. Separately authorize the first production activation. Its canonical migration plan must be exactly empty; otherwise it requires the full classified-migration path, machine-verified recovery evidence when applicable, and separate action-specific authorization. Activate in a staffed window with a rollback/recovery operator available.
9. Complete blocking immediate/stabilization verification, then assign and record non-blocking +1-hour/+4-hour/+24-hour operational follow-up.
10. Enable routine use only after credential rotation, rollback, host replacement, and break-glass reconciliation instructions are independently executable.

## Acceptance Criteria

- A local `merge and deploy` operation can merge through a PR and dispatch the protected workflow but has no independent production credential path.
- Deploy rejects malformed, non-main, or stale-after-approval SHA values and never deploys a moving branch tip.
- Production secrets are available only after a distinct recorded environment approval; the same owner may dispatch and approve under the configured policy.
- The target rejects wrong marker/origin/service/path, unknown commands, unsafe archives, digest mismatches, concurrent operations, DB-plan drift, and unclassified migrations before activation.
- Successful release leaves GitHub and server records agreeing on exact SHA/digest, and `/healthz/` proves the active SHA without exposing infrastructure or secret data.
- User uploads, environment secrets, database state, current release, and previous rollback-eligible release survive deploy and rollback operations.
- An eligible non-migration health failure restores and verifies prior code/static; a data/non-compatible release stops for recovery without claiming database rollback.
- A new authorized operator can determine and exercise deployment authority from repository/GitHub documentation, not historical chat context.

## Sources

- Approved requirements: `docs/brainstorms/2026-08-31-authoritative-production-deployment-requirements.md`
- [GitHub workflow dispatch semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)
- [GitHub deployment environments and protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [GitHub workflow token permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)
- [GitHub secure use and immutable action pins](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)
- [GitHub artifact digest validation](https://docs.github.com/en/actions/tutorials/store-and-share-data#validating-artifacts)
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [GitHub OpenID Connect claims and token permissions](https://docs.github.com/en/actions/reference/security/oidc)
- [GitHub repository rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [OpenSSH authorized-key restrictions](https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT)
- [OpenSSH ForceCommand and DisableForwarding](https://man.openbsd.org/sshd_config#ForceCommand)
- [systemd execution sandboxing](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [uv requirements locking and synchronization](https://docs.astral.sh/uv/pip/compile/)
