# Ranking analysis release

The application adds `/rankings/analysis/` and the reviewed correction workflow.
Moderators/admins can inspect and propose; only admins can apply/reject. Existing
Results/History table tools share clipboard behavior. No production corrections,
student merges, result transfers, or source imports are part of deployment.

## Frozen migration boundary

`rankings.0005_ranking_analysis_review` creates eleven supporting tables. Its
exact migration hash, prior ranking migration hashes, allowed operation shape,
PostgreSQL 17.9 catalog delta and compatibility smoke are frozen in
`scripts/deployment/ranking_analysis_schema.py`. The complete pending migration
plan must contain only this migration. Existing ranking rows, source notes,
student/result links, catalogue and solution records, triggers and sequence
values must remain intact. New supporting tables must be empty.

`ranking_analysis_schema_rehearsal` uses an empty, exact loopback Actions database.
It seeds synthetic preserved records, including separate same-name students and
a zero score; applies the frozen migration; verifies all prior records/schema;
and runs the previous application's ranking and existing reader smoke against
the resulting database. Catalog metadata can be retained on a mismatch for
review, but a mismatched delta cannot produce a passing preservation receipt.
CI also runs the full ranking suite and its concurrent application/import checks
against a separate disposable PostgreSQL test database.

## Release procedure

1. Merge only after CI and the PostgreSQL preservation proof pass. Record the
   exact main SHA and currently active release. Keep normal GitHub protections.
2. Prepare the exact helper diff and artifact hashes. Installing the newly
   bounded root helper requires separate action-specific authorization under
   `production-bootstrap.md`; an application deployment request does not grant
   unrestricted host authority. Preserve the installed contract, accounts,
   credentials, network, audit role, media, keys and existing release records.
3. After that authorization, use the established bootstrap installer from the
   exact reviewed clean source. Validate helper hashes and existing service
   configuration. Do not mutate application data or restart the app during
   helper installation.
4. Obtain a fresh bounded catalog-only audit through the approved channel.
   Derive the expected ending fingerprints from the reviewed eleven-table
   delta. Freeze the disclosure to the exact active/target SHAs and metadata.
5. Dispatch `production-deploy.yml` once with `backward-compatible-schema`,
   `skip_ci=false`, no legacy adoption and that disclosure. Verify the attested
   artifact, packaged rehearsal receipt and protected production gate before
   activation. Reconcile the original run ID if its outcome becomes ambiguous.
6. Complete the normal health, static hash, service, login/role boundary and
   short stabilization checks. Verify migration 0005 is recorded and existing
   student/result counts and distinct identity links remain intact, using a
   bounded approved read. Do not apply any actual correction as a smoke test.

Code recovery must retain the supporting tables and durable correction receipts.
It must respect the existing document, image and Training reader compatibility
floors. No automatic schema reversal, data correction reversal or audit deletion
is part of this release. Delayed monitoring remains opt-in.
