---
date: 2026-08-31
topic: authoritative-production-deployment
---

# Authoritative Production Deployment

## Problem Frame

AsterProof releases currently stop after merge because source ownership and runtime ownership are disconnected. GitHub has no production environment or deployment workflow, the production server is outside the authenticated AWS account, and the local `asterproof-prod` alias has no working deployment credential. Checkout paths, service names, and deployed revisions therefore have to be rediscovered from historical notes during every release.

The durable outcome is a single, auditable deployment authority: GitHub Actions deploys an exact merged revision to the existing AsterProof server after explicit production approval. Local developer or Codex sessions may diagnose production through approved read-only access, but they do not become alternative deployment channels.

## Requirements

**Authority and access**

- **R1.** GitHub Actions and a protected GitHub `production` environment must be the sole normal mechanism for deploying AsterProof production.
- **R2.** Production deployment must require explicit environment approval and must accept an exact Git commit SHA rather than an implicit moving branch tip. As the current single operator, the repository owner may both dispatch and approve a run; approval remains a separate explicit action recorded by GitHub.
- **R3.** Normal production deployment must accept only the current `main` SHA. Older revisions may be activated only through the dedicated rollback workflow and must match a recorded previous release.
- **R4.** The production server must use a dedicated least-privilege deployment account and credential. The credential must not be shared with another project or stored in the repository.
- **R5.** GitHub production secrets must contain only the connection material required by the workflow, including a pinned SSH host identity. Secrets must be rotatable without changing application code.

**Target identity and fail-closed behavior**

- **R6.** A one-time server bootstrap must establish an AsterProof-specific host marker, authoritative checkout/release location, expected repository origin, service identity, persistent environment location, and persistent media location. If preflight cannot prove the required connection, privilege, disk, or persistent-state boundaries, bootstrap must stop and require a separately approved infrastructure-migration scope.
- **R7.** Every deployment must verify the host marker, repository origin, service identity, and expected filesystem boundaries before making any change. A mismatch must stop the deployment without attempting repair or discovery.
- **R8.** Deployments must be serialized so two releases cannot modify the runtime concurrently.
- **R9.** The deployed application must expose or record enough non-secret metadata to prove the active commit SHA after release.

**Release execution and recovery**

- **R10.** Build and test work that does not require production secrets, including frontend compilation and static-file collection, must run in GitHub Actions. CI must reuse `scripts/build_and_collectstatic.sh` unless planning documents a concrete incompatibility. Production must not require Node.js merely to receive a release.
- **R11.** CI must produce one immutable release artifact for the requested SHA containing the deployable source and collected static tree. GitHub and the server must record its cryptographic digest; production must verify the digest and safely extract the artifact into a new bounded release directory before activation. The active-SHA signal must come from this verified artifact.
- **R12.** Before production approval, a non-secret job must compare the requested and active revisions and publish the exact Django migration plan and rollback classification. The production step must install dependencies from the selected authoritative lock, apply only the disclosed migrations, activate the exact release, restart only the AsterProof service, and run bounded service and HTTP health checks.
- **R13.** Every failure before activation—including transfer, digest validation, safe extraction, dependency installation, configuration validation, and migration execution—must stop before switching the active code/static release, preserve secret-safe diagnostic evidence, and leave the current release untouched. A migration failure must block activation and require explicit recovery rather than implying automatic database rollback.
- **R14.** If activation or post-deploy health checks fail, the mechanism must preserve secret-safe logs and restore the last known-good code and static release when database compatibility permits. Releases without migrations may use automatic code/static rollback. Backward-compatible schema migrations may permit code rollback only when the pre-approval classification demonstrates compatibility. Data, destructive, or otherwise non-backward-compatible migrations require a verified database recovery point and disable automatic rollback. Code rollback must never be represented as reversing data changes.
- **R15.** Persistent secrets, database data, and user-uploaded media must live outside replaceable release directories and must survive deploy and rollback operations.

**Governance and auditability**

- **R16.** GitHub `main` must require pull-request-based changes before the production workflow is enabled.
- **R17.** The workflow must use minimal job-level GitHub token permissions, pin third-party actions to reviewed full commit SHAs, keep production secrets out of pull-request and build/test jobs, and separate untrusted build/test execution from the production secret-bearing deployment job.
- **R18.** Each deployment must leave an auditable GitHub record containing actor, approval, requested SHA, artifact digest, outcome, timestamps, and health-check result, plus a server-side current/previous release record. Shell tracing around credentials is prohibited; logs must redact sensitive values and have bounded retention and least-privilege access.
- **R19.** Repository documentation must define the one-time bootstrap, normal deployment, rollback, credential rotation, host replacement, and disaster-recovery procedures with exact validation commands and expected evidence.
- **R20.** A local `merge and deploy` request must resolve to the same GitHub production workflow; it must not perform an independent SSH deployment from the operator's workstation.
- **R21.** Emergency break-glass access may be used only through an independently authorized server/provider recovery channel when the GitHub deployment mechanism cannot restore service. It is not a normal deployment path; every action must be recorded and reconciled into the GitHub deployment history afterward.

## Success Criteria

- A merged revision can be deployed from GitHub after one explicit production approval, without local production credentials.
- The workflow refuses an unmerged SHA, an unknown host, the wrong repository, the wrong service, or a concurrent deployment.
- GitHub and the server agree on the exact active SHA and immutable artifact digest after a successful release.
- A failed non-migration release can restore the previous code/static release and demonstrate service recovery.
- Deployment credentials can be rotated and the application runtime can be rebuilt on a replacement server using repository documentation and independently restored secrets, database, and media rather than historical chat context.
- Future Codex sessions can determine deployment authority from the repository and GitHub configuration alone.

## Scope Boundaries

- Keep the existing production server; do not migrate hosting providers or AWS accounts in this work.
- Do not introduce Docker, Kubernetes, or a second application platform.
- Do not change application features, authentication behavior, DNS, TLS, database topology, or media-storage architecture except where an explicit deployment health/version signal is required.
- Do not automatically deploy every push to `main`; production remains an explicitly approved action.
- Do not store production private keys, environment files, database credentials, or provider credentials in Git.

## Key Decisions

- **GitHub Actions is authoritative:** source review, production approval, deployment audit, and exact revision identity remain in one system.
- **Existing server stays in place:** this removes the recurring release ambiguity without coupling the work to an infrastructure migration.
- **CI produces the release artifact:** production previously lacked Node.js, so CI builds and tests one SHA-bound source/static artifact that production verifies rather than reconstructs.
- **Deployment fails closed:** target mismatches are configuration failures, not invitations to probe or mutate another host.
- **Rollback distinguishes code from data:** automatic code recovery is permitted only when it does not misrepresent migration reversibility.
- **Single-operator approval is explicit:** the repository owner may approve their own dispatch, but GitHub still records a separate production approval event.
- **Current main is the normal release:** older code is activated only through the bounded rollback workflow against recorded release metadata.
- **Bootstrap failures stop scope expansion:** an incompatible existing host triggers a separately reviewed infrastructure decision rather than an improvised deployment exception.
- **Break-glass access is recovery-only:** emergency server/provider actions must be reconciled back into the authoritative GitHub record.
- **Runtime recovery is distinct from data recovery:** this initiative documents how to rebuild the application around externally restored persistent state; it does not create a new database/media backup program.

## Dependencies / Assumptions

- One-time console or otherwise authorized access to the existing AsterProof server is required to install the dedicated deploy credential and bootstrap the authoritative target markers.
- A repository administrator must create the GitHub `production` environment, add its protected secrets, configure required reviewers, and enable branch protection.
- The current production database, environment file, and media directory can remain persistent outside versioned releases.
- An authoritative owner and independently validated restore procedure must already exist for production secrets, database data, and uploaded media before host-replacement readiness can be claimed.

## Outstanding Questions

### Deferred to Planning

- **[R6, R15][Needs research]** Confirm the current server's real checkout, service unit, environment-file location, media location, Python runtime, and available disk space during the one-time bootstrap; historical `/srv/asterproof/app` and `asterproof.service` values must not be assumed.
- **[R12, R14][Technical]** Select the smallest release-directory and symlink activation design that works with the confirmed service unit and safely preserves the previous release.
- **[R9, R12][Technical]** Choose the least-exposed health/version verification mechanism that proves both application health and active SHA.
- **[R4, R12][Technical]** Define the deploy account's forced-command or narrowly scoped non-interactive service-control boundary, prohibited shell/forwarding capabilities, permitted paths, and revocation procedure.
- **[R12][Technical]** Select one authoritative production dependency lock consumed by both CI and production, including its regeneration and review process.
- **[R13, R14, R18][Technical]** Define bounded release and log retention that protects active and previous known-good releases, checks disk space before transfer, and never traverses persistent state.

## Next Steps

→ Run structured implementation planning, including the repository workflow/scripts, GitHub administration steps, one-time server bootstrap, verification matrix, and rollback drill.
