# Rollback and operation recovery

Rollback changes code and static files only. It never reverses database migrations or restores data.

## Protected rollback

Use **Production rollback** only for the server-recorded immediate previous successful release when its artifact remains intact and `rollback_eligible` has not been revoked. The workflow uses current trusted `main` workflow/gateway code; it never executes scripts from the old release.

Obtain the exact current `main` workflow SHA:

```bash
workflow_sha="$(gh api repos/stevenchew83/AsterProof/git/ref/heads/main --jq '.object.sha')"
gh workflow run production-rollback.yml \
  --repo stevenchew83/AsterProof \
  --ref main \
  -f workflow_sha="$workflow_sha" \
  -f confirmation=ROLLBACK_IMMEDIATE_PREVIOUS
```

Inspect the disclosure before approving `production`: current production SHA/digest, requested immediate-previous operation, unchanged-database rule, target marker, and eligibility evidence. After approval, current `main` is revalidated and the server chooses the immediate previous eligible release. A client-supplied old SHA is never accepted as a rollback target.

Rollback succeeds only when the restored SHA/digest agree across `current`, registry, restarted process cgroup, public health, and representative static bytes, while the database fingerprint remains unchanged. Otherwise the canonical result is `recovery_required`.

## Interrupted or ambiguous operation

SSH loss and runner cancellation do not cancel the durable systemd operation. Never create a new run merely to “try again.”

1. Record the original GitHub run ID and last workflow status response.
2. Reconcile the server operation through the protected `status` command for that same numeric run ID.
3. Compare the operation record, request record, lock, incoming artifact, release manifest, `current`/`previous` links, service cgroup, `/healthz/`, and database fingerprint.
4. If the operation is still in `receiving`, `verified`, `prepared`, `migrating`, or `activating`, wait for its bounded supervisor outcome; do not replay migration or activation.
5. If evidence is missing, malformed, contradictory, or the operation remains unclosed after its service timeout, block both workflows and obtain action-specific recovery authorization.

Terminal states are `active`, `rolled_back`, `failed`, and `recovery_required`. Only a fully reconciled terminal state permits a later workflow run.

## Eligibility rules

- `none`: post-activation automatic code/static rollback may be allowed.
- `backward-compatible-schema`: reserved for a future protocol that binds reviewed start and end fingerprints; the current routine workflow rejects it.
- `data-or-non-compatible`: automatic rollback is disabled; use independently verified data recovery and a separately reviewed maintenance procedure.

`previous` means the immediately prior active release, not inherently known-good. Mark a latent-defect release manual-only/revoke its eligibility before replacing it. Protect `current`, `previous`, every in-progress release, and the latest additional successful release from pruning.

## Manual recovery boundary

Do not manually repoint symlinks, edit release contents, restart production, mutate the database, or mark a record successful as part of routine rollback. Those are break-glass mutations governed by [disaster recovery](disaster-recovery.md). After any authorized manual recovery, reconcile exact SHA/digest/schema evidence into the server registry and a protected GitHub adoption run before normal deployments resume.
