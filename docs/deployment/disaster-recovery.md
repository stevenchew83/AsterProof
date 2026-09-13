# Disaster recovery and break glass

Break glass is recovery-only. It is used only when the protected GitHub mechanism cannot restore service and an independently authorized provider/server recovery channel has approved the action. It is not permission for workstation deployment, an interactive production coding session, or an undocumented database change.

## Declare and contain

1. Name the incident owner, recovery operator, start time, affected service, observed public health evidence, and last trustworthy GitHub run/server record.
2. Pause routine deploy and rollback dispatch. Preserve workflow, registry, journal, proxy, service, database, and monitoring evidence without exposing secrets or personal data.
3. Classify the failure: GitHub authority, transport/host identity, release filesystem, service/runtime, database, media, environment/secrets, proxy/TLS, or provider host.
4. Prefer the least invasive documented recovery: reconcile a durable operation, run the protected rollback workflow, rotate credentials, or replace the host.

Never automatically reverse Django migrations, restore a database over a live application, clear data, edit the active release, repoint `current`, restart services, or change provider configuration without action-specific authorization and a reviewed recovery procedure.

## Independent data recovery

Database, media, and secret recovery must use the pre-existing independent recovery authority. Before a restore, verify the exact account/project/tenant, database/resource identifier, backup/recovery-point ID, creation time, retention, encryption ownership, destination, and last restore-drill evidence. Credentials must be unavailable to the deploy key, candidate code, and application user.

Stop if any identity is blank or ambiguous. Record pre-restore evidence, authorize the exact mutation, perform the provider-owned restore, and validate database fingerprint/readiness and media sample integrity before application activation. Code rollback must never be described as data recovery.

## Reconciliation after break glass

Normal deployment remains blocked until all manual changes are reconciled:

- identify the exact running source SHA and repository origin, or declare it unverifiable;
- compute/import the matching artifact or reproducible content digest;
- record the active schema/migration fingerprint and persistent resource identities;
- verify target marker, gateway/helper/unit/contract hashes, service cgroup, public health, and static bytes;
- record every actor, command/action, timestamp, reason, output summary, and credential change;
- create or repair the server release record without inventing rollback eligibility;
- run a protected GitHub reconciliation/adoption release so GitHub and server SHA/digest evidence agree;
- rotate credentials exposed or used during recovery and re-read GitHub governance.

An unverifiable or manually edited runtime is a legacy non-rollback-eligible baseline. It requires an adoption/remediation release before returning to `READY`.

## Incident exit criteria

Service recovery alone is insufficient. Close the recovery state only when the active SHA/digest/schema evidence is consistent, persistent data ownership is confirmed, all ambiguous operations are terminal, normal authority controls pass, credentials are rotated as required, and named +1h/+4h/+24h follow-ups are assigned.
