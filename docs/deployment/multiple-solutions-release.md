# Multiple library solutions maintenance release

The `multiple-solutions-maintenance-v1` allowance targets only
`solutions.0017_multiple_problem_solutions` on PostgreSQL 17.9. Its starting
application revision is `bf74e8f4f1159656c88501ab0ab41bd990ffdbc3`, with
`solutions.0016_admin_review_takedown` and `users.0010_public_registration` already recorded.

The verified delta appends one nullable UUID with no database default on
`public.solutions_problemsolution`. It replaces the existing uniqueness
constraint and its backing index with two partial unique indexes. One reserves
the original slot for existing solutions. The other makes repeated creation
requests return the same additional draft. The migration writes no application
rows. Existing IDs, revisions, share tokens, completion records and triggers
retain their original values.

## Review and preflight

1. Run the exact PostgreSQL 17.9 rehearsal on an empty isolated database. It
   validates the frozen catalog delta, the active reader in a read-only
   transaction, every old record and sequence, privileges, and concurrent draft
   creation. Local evidence is labelled `local-rehearsal`. The protected
   workflow repeats the proof against the exact merged release and packages
   deployment evidence.
2. Read the live active release and obtain the catalog and community trigger
   fingerprints through the installed audit helper. Verify the exact starting
   migration and schema. Apply the frozen delta to that audit to compute the
   expected ending fingerprints.
3. Review the trusted file diff and the bootstrap audit. Install from the exact
   clean merged revision. The installation retains the existing target, SSH
   restrictions, audit identity and managed service configuration. Validate the
   installed authority and its matching private recovery runtime before
   approving production activation.
4. In the protected release run, inspect the exact target SHA, archive
   attestation, packaged proof and schema disclosure. The supported
   `skip_ci=true` option omits the quality suite while keeping the PostgreSQL
   rehearsal and protected approval.

## Preservation and recovery

The trusted worker checks the catalog and exact pending plan before draining
traffic. It requires an encrypted RPO0 backup and a verified isolated restore
before applying 0017. Afterward it compares every original record and sequence
and the large-object digest against the recovery manifest. Only the appended
UUID field and the one migration-recorder increment are projected out. It
requires the new field to remain null on every existing solution before the
candidate can serve traffic.

Record the durable operation, backup receipt, release SHA, archive digest,
expected and observed schema and migration fingerprints, process-bound health,
and immediate stabilization. This release disables ordinary code rollback.
After additional drafts exist, the original uniqueness constraint cannot be
restored without reconciling those rows. A failure after drain enters
`recovery_required`. Reconcile the original operation and recovery receipt
before any separately authorized restore or retry. Follow the existing
[recovery procedure](catalogue-backup-and-maintenance.md) and
[trusted bootstrap procedure](production-bootstrap.md).
