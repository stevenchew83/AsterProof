# Production host replacement

Host replacement rebuilds the application deployment boundary around independently restored persistent state. It does not create, validate, or replace the database/media/secret backup authority.

## Go/No-Go inputs

Before writing to a replacement host, require:

- an independently authorized owner and tested restore procedure for the exact production database, media, and environment secret set;
- resource/tenant identifiers, backup/recovery-point identity, timestamps, checksums where applicable, and a successful restore-drill record;
- the replacement host's independently verified identity, supported Python 3.12 runtime, disk capacity, systemd/proxy/TeX/scheduler capability, and outbound GitHub OIDC discovery/JWKS access;
- a reviewed target contract containing confirmed values, never copied historical guesses;
- an approved DNS/TLS/cutover and rollback window.

If independent recovery evidence does not exist, stop. Open a separate backup-authority scope; do not enable `data-or-non-compatible` releases or claim host-replacement readiness.

## Replacement sequence

1. Keep the old host serving traffic and disable release dispatch during the replacement window.
2. Restore secrets, database connectivity, and media through their independent recovery authorities. The deploy account, application user, and candidate release code must not receive backup-provider credentials.
3. Run the bootstrap discovery/audit phase against the replacement host. Validate host marker uniqueness, paths, users/groups, origin, service, proxy/static behavior, scheduler, TeX, disk, and persistent-state separation.
4. Review the discovery report and target contract. Separately authorize bootstrap installation; do not let an application artifact update the gateway, helper, systemd unit, sudoers entry, contract, or marker.
5. Configure a new dedicated deploy key and independently pinned host key, then update the GitHub `production` environment using [credential rotation](credential-rotation.md).
6. Record the restored runtime as a baseline only if its clean SHA, source identity, artifact/content digest, schema fingerprint, health, service, and host marker are proven. Otherwise record a legacy, non-rollback-eligible baseline and perform a reviewed no-migration adoption release.
7. Run a non-mutating protected preflight, then complete the safe-target deploy/induced-failure/rollback drill using the same gateway, operation worker, and probes.
8. During a separately authorized staffed window, deploy the exact current `main` SHA, verify immediate/stabilization evidence, and cut traffic over through the approved DNS/TLS procedure.
9. Complete +1h/+4h/+24h monitoring and preserve the old host according to the recovery plan until replacement evidence is accepted.

The replacement is complete only when GitHub, `/healthz/`, service cgroup, static bytes, registry SHA/digest, database fingerprint, scheduler, and restored media checks agree. Destroy or repurpose the old host only through a separate provider-authorized procedure.
