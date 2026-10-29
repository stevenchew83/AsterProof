# Newsletter campaign schema release

The separately approved Newsletter allowance admits only
`website.0002_newsletter_campaigns`, whose exact bytes are frozen in
`scripts/deployment/newsletter_schema.py`. It also verifies the existing initial
website migration bytes. The pending plan must contain exactly its two
CreateModel operations; unknown or additional migrations are rejected.

The migration creates `website_newslettercampaign` and
`website_newsletterdelivery` with their fixed constraints and indexes. It does
not alter or rewrite the existing subscriber, consent, library, account or
progress tables. MigrationExecutor applies the exact plan without unrelated
post_migrate permission writes, with the existing 2-second lock and 30-second
statement bounds.

## Preservation proof

The isolated PostgreSQL 17.9 rehearsal starts with website.0001 applied, then
seeds pending, confirmed and unsubscribed subscribers plus existing editorial,
account and problem/progress rows. It hashes every existing table and sequence,
verifies a separate subscriber count/digest, and requires all prior records,
schema objects and sequences to remain unchanged. Only the single expected
Django migration-record/counter increment is allowed. The active application's
fixed read-only compatibility smoke must pass against the resulting database.

Freeze the discovered two-table catalogue delta as a fixture, bind its digest
in the allowance, and verify the packaged proof again in the protected release
build. Disclosure, release, artifact, starting/ending catalogue fingerprints and
OIDC audience retain their existing bindings. The production audit role keeps
its existing schema-only privileges; no subscriber rows or credentials are
exported and no additional database privileges are granted.

## Authority and activation

Application artifacts cannot replace the installed root authority. Use the
existing reviewed bootstrap installation procedure for the approved immutable
source revision, preserving target/audit configuration, environment, identities,
deploy key/forced command, application and scheduler units, and proxy. Confirm
there is no unresolved deployment before installation. Do not reinstall or
redispatch an ambiguous outcome.

Compute the expected catalogue state from the production metadata snapshot and
frozen two-table delta. Dispatch the exact current main revision as
`backward-compatible-schema` with this validated disclosure and full checks.
Verify the packaged rehearsal, archive and provenance before the protected
production approval. After activation compare workflow, durable operation,
registry, process paths, health and hashed Newsletter CSS/JS, then perform the
immediate and short stabilization checks. Do not send a real campaign as a
deployment test. No delayed monitoring is scheduled without a user request.

Recovery retains existing subscribers and any new campaign/history records.
An error after entering migrating requires reconciliation; never infer that
database changes rolled back or retry the migration automatically. The existing
recovery gates remain unchanged.
