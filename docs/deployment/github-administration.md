# GitHub production administration

These controls make GitHub Actions the normal deployment authority. Configure them before adding production credentials or enabling activation. Re-read them before the first production release and after repository visibility, ownership, billing plan, or Actions policy changes.

## Required repository controls

The repository is expected to be `stevenchew83/AsterProof`, numeric repository ID `1165803960`, public visibility, with `main` as the default branch. Verify rather than assume:

```bash
gh repo view stevenchew83/AsterProof \
  --json id,nameWithOwner,visibility,defaultBranchRef
gh api repos/stevenchew83/AsterProof/rulesets
gh api repos/stevenchew83/AsterProof/environments/production
gh api repos/stevenchew83/AsterProof/actions/permissions
gh api repos/stevenchew83/AsterProof/actions/permissions/selected-actions
gh variable list --repo stevenchew83/AsterProof
gh variable list --repo stevenchew83/AsterProof --env production
```

Stop if visibility is no longer public and the current GitHub plan does not provide required reviewers, environment branch restrictions, or artifact attestations. Do not weaken the design to fit missing entitlements.

Create one active `main` ruleset with:

- pull requests required for all changes;
- required status check **CI / verify**;
- zero PR approvals intentionally allowed for the single-owner repository;
- branch deletion and force pushes blocked;
- direct pushes and bypass actors disabled, including administrators where supported.

Create the `production` environment with:

- deployment branches restricted to `main` only;
- the repository owner as required reviewer;
- self-review allowed for the current single-owner model;
- administrator bypass disabled;
- the `PRODUCTION_TARGET_MARKER` variable;
- the five environment secrets below, available only to the environment-bearing job.

Create `PRODUCTION_HEALTH_URL` as a repository-level variable. It is deliberately public release evidence and is needed by the preapproval disclosure/inspection jobs, which must not reference the protected environment or receive its secrets.

| Name | Purpose |
|---|---|
| `PRODUCTION_SSH_HOST` | Confirmed target hostname, not an unreviewed historical IP |
| `PRODUCTION_SSH_PORT` | Confirmed SSH port |
| `PRODUCTION_SSH_USER` | Dedicated forced-command deploy account |
| `PRODUCTION_SSH_PRIVATE_KEY` | Dedicated private key used only by this environment |
| `PRODUCTION_SSH_KNOWN_HOSTS` | Exactly one independently verified pinned host-key line |

Require third-party actions to be pinned to full commit SHAs, disallow unapproved actions, and keep default workflow-token permission read-only. The workflow files also set `permissions: {}` and opt in per job; repository policy is defense in depth.

Set a bounded Actions log/artifact retention consistent with the 30-day workflow artifacts. Restrict administration and secret access to the repository owner, require phishing-resistant MFA/passkeys, protect account recovery, and monitor repository/security alerts. Same-owner dispatch and approval is explicitly auditable but is not separation of duty.

## Read-back checklist

Save the JSON returned by the read-only commands above with the bootstrap/release record. Verify literally:

- repository name and numeric ID match the target contract;
- active ruleset targets only `refs/heads/main` and has no bypass actor;
- required status check name exactly matches the live CI job;
- environment branch policy admits only `main`;
- required reviewer is present, self-review remains intentionally permitted, and admin bypass is off;
- repository variable `PRODUCTION_HEALTH_URL`, environment variable `PRODUCTION_TARGET_MARKER`, and all required environment secret names exist (never print secret values);
- workflow actions use full 40-character SHAs;
- deploy and rollback use the shared `asterproof-production` concurrency group, do not cancel in-progress work, and retain at most the platform's bounded queue capacity.

Run repository contract tests before enablement:

```bash
uv run pytest scripts/deployment/tests/test_workflow_contract.py
uv run ruff check scripts/deployment
```

CI downloads checksum-pinned actionlint 1.7.7 and validates every workflow. The single ignore covers GitHub's newer bounded `concurrency.queue` key, which this actionlint schema does not yet recognize; no other syntax finding is ignored. A clean static check is not production authorization; complete bootstrap and a non-mutating preflight first.

## Change control

Changes to workflow paths, repository identity, target marker, gateway/helper/unit, OIDC policy, secret names, or protection rules are authority changes. Review them by pull request, rotate affected credentials, update the root-owned target contract through a separately authorized bootstrap session, and read all controls back before resuming deployment.
