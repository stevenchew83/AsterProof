# Production target bootstrap

Bootstrap is a separately authorized host-administration procedure. Repository implementation and merge do not authorize production writes. Begin with read-only discovery and stop if any required value is unknown, inconsistent, or places persistent state under a replaceable release root.

The adoption states are:

```text
UNMANAGED -> INVENTORIED -> BOOTSTRAPPED -> BASELINE_RECORDED -> READY
```

## Read-only discovery

Using the approved production access procedure, collect a bounded report for:

- unique AsterProof host marker and repository name/numeric ID;
- actual application origin/SHA/dirty state and service identity;
- release root, external shared root, environment file, media root, and owners/modes;
- application, build, and deploy users/groups;
- stable Python 3.12 authority-runtime path/ABI/platform, its `cryptography` import, and free disk space;
- systemd service command/environment/current working directory and full cgroup;
- proxy ownership of `/static/` and `/media/`, plus TLS health URL;
- technique-catalog scheduler command/path/state;
- TeX/`latexmk` availability required by the application;
- bounded HTTPS access to GitHub OIDC discovery/JWKS endpoints;
- independent database/media/secret recovery owner and most recent restore-drill evidence.

Production discovery commands must be shown and approved individually under the repository production-access policy. Do not print environment contents, private keys, database URLs, tokens, customer data, or broad logs.

Copy `deployment/production-target.example.json` to a proposed `deployment/production-target.json` only after discovery. Replace every example value with confirmed evidence. The repository contract and root-owned server contract must match exactly; do not commit secrets or a host-key line.

At minimum, validate the proposed contract locally:

```bash
python - <<'PY'
from pathlib import Path
from scripts.deployment.target import TargetContract

TargetContract.load(Path("deployment/production-target.json"))
print("target contract syntax: ok")
PY
```

From the reviewed repository source on the target, the audit CLI is:

```bash
python -m scripts.deployment.bootstrap audit \
  --contract /path/to/reviewed/production-target.json \
  --source-root /path/to/exact-reviewed-repository
```

`audit` is read-only and emits secret-free JSON. Before first installation it may exit 2 only for the expected not-yet-installed marker, migration-audit configuration, and authority manifest; every other check must be true.

## Installation review

Before separately authorizing installation, review a literal diff of all proposed host changes:

- marker and root-owned target contract;
- dedicated app/build/deploy accounts and directory ownership;
- immutable release/shared directory boundaries;
- forced-command authorized key with forwarding/shell/SCP/SFTP disabled;
- root-owned gateway and submit helper hashes/modes;
- exact no-argument sudoers entry;
- hardened durable operation systemd unit;
- existing application service updated to use external environment/media and `current`;
- proxy/static/media and scheduler paths updated to stable pointers;
- no candidate release code executed as root.

Validate rendered systemd and sudoers configuration with platform-native syntax checks before installation. Keep the previous service/proxy/scheduler definitions available through the independently approved host rollback procedure. An application release must never replace its own gateway, helper, unit, sudoers entry, contract, or marker.

The audit validates the reviewed repository origin, target runtime/platform, disk threshold, service/proxy/scheduler paths, TeX runtime, OIDC discovery/JWKS reachability, persistent boundaries, and installed authority hashes. Before first installation, only `marker_matches`, `migration_audit_configured`, and `trusted_authority_matches` may be false; every other check must be true.

Before locking the database identity, run the fixed read-only identity command with the reviewed audit role and a placeholder hash, then copy only its returned hash into the final reviewed configuration:

```bash
python -m scripts.deployment.migration_audit identity --config /path/to/proposed/migration-audit.json
```

The identity command validates the expected database role and returns only that role plus a hash of the database/cluster/server identity tuple; it does not expose credentials or schema data.

```bash
python -m scripts.deployment.bootstrap install \
  --contract /path/to/reviewed/production-target.json \
  --source-root /path/to/exact-reviewed-repository \
  --deploy-public-key '<dedicated-ed25519-public-key>' \
  --migration-audit-config /path/to/reviewed/migration-audit.json \
  --expected-authority-sha '<exact-merged-main-sha>' \
  --confirm-marker '<confirmed-target-marker>'
```

The command is mutating, requires root, installs and hashes the fixed worker helpers, reloads systemd, and needs separate action-specific authorization. Do not substitute ad hoc file-copy, account creation, sudoers, systemd, or authorized-key commands. The PostgreSQL service file and catalog-only role must already exist and match the reviewed migration-audit identity; bootstrap never creates database authority or reads application credentials.

The configured Python executable is part of the root-owned authority boundary: it must be stable, outside the replaceable release root, and already contain the hash-reviewed `cryptography` runtime required for OIDC verification. Bootstrap renders every authority entrypoint against this exact audited interpreter and fails closed if its ABI, platform, libc, or import check fails.

## Transition from a running legacy checkout

Bootstrap audits the **unit configuration on disk** with `systemctl cat`; legacy adoption separately checks the **running service cgroup's process working directories**. These are different states. The configured `current` path does not mean the existing process has already moved.

For an initial adoption, the separately reviewed host procedure must:

1. Verify the clean legacy checkout and running processes, shared environment/media readiness, audit database identity, and recovery procedure before staging service changes.
2. Prepare and syntax-check the exact app, proxy, and scheduler configuration diff. Confirm the actual scheduler mechanism first; an absent unit may mean cron is used or scheduling was never configured. Do not create a dummy unit to satisfy the audit.
3. Stage the managed unit configuration without restarting the app or starting a scheduler that references the not-yet-created `current` link. Preserve the previous configuration for recovery. Installing authority runs `daemon-reload`; it does not restart the app. This transition needs a staffed window because an unexpected restart or reboot cannot use the missing `current` path.
4. Install authority from a separate clean checkout at the approved authority SHA. Keep the running legacy checkout unchanged. Use that legacy checkout as `--source-root` for `adopt-legacy`; the installer source and adoption source need not be the same revision or directory.
5. Record adoption only while the running process still matches the verified legacy source, no managed links/releases exist, and the database fingerprint is verified. Complete the separately authorized first activation before leaving the transition window, or restore the prior configuration through the reviewed recovery procedure.

Do not bypass the managed configuration audit or the legacy process check to complete this transition. Missing credentials, scheduler configuration, host identity, or recovery evidence remain blockers.

## Baseline adoption

The running production release is rollback-eligible only if all of these are proven: clean known commit, exact repository origin/ID, service and host marker, artifact or reproducible content digest, normalized schema/migration fingerprint, process-bound health evidence, persistent boundaries, and successful immediate/stabilization checks.

A dirty, detached-with-unknown-origin, manually edited, or otherwise unverifiable runtime is recorded as a legacy non-rollback-eligible baseline. Perform a reviewed no-migration adoption release before enabling routine deploy. Never invent a digest or mark an unknown release known-good.

When the legacy process is proven to run from the clean repository passed as `--source-root`, the installed authority and migration audit pass, and no managed `current` release exists, separately authorize the one-use adoption record:

```bash
python -m scripts.deployment.bootstrap adopt-legacy \
  --contract /etc/asterproof/deployment-target.json \
  --source-root '<confirmed-running-clean-checkout>' \
  --confirm-marker '<confirmed-target-marker>' \
  --confirm-no-rollback LEGACY_NON_ROLLBACK
```

This writes only a root-owned one-use adoption record. It does not call the application, change a symlink, restart a service, or claim the legacy checkout is rollback-eligible. The next approved `none` migration-class deployment may consume it. If that first activation fails, the operation becomes `recovery_required`; automatic rollback is unavailable until one managed release has activated successfully.

## Enablement gates

After installation and baseline adoption:

1. read back every installed file's hash, owner, and mode and every stable service/proxy/scheduler path;
2. configure and read back [GitHub administration](github-administration.md);
3. install/rotate the dedicated deployment key and pinned host identity;
4. run the protected non-mutating preflight;
5. on a safe target, deploy the same mechanism, induce a post-activation health failure, and prove eligible rollback;
6. record a first-production Go/No-Go sheet with no blank/unknown fields;
7. separately authorize a first production activation whose migration plan is exactly empty;
8. verify and monitor it under [production release](production-release.md).

If independent restore evidence is absent, keep data/non-compatible deployment disabled and open a separate backup-authority scope. If any target/drift/preflight check fails, stop; bootstrap does not auto-repair or rediscover production.
