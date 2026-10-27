# Bulk concept review: export once, review locally, check live before applying

This workflow exports a consistent, focused JSON snapshot. It does not copy or restore the production database. The new routes and commands are read-only; assignment application continues through the existing signed preview → apply → receipt service after authorization.

## Data and boundaries

A snapshot contains exact problem/statement sources and structured tags, including inactive owners and suppressed tags; all current and retired assignment before-images in the selected scope; published solution evidence; and the exact registry and review-engine fingerprints. Assignment audit actor IDs remain numeric references. User accounts, emails, passwords, sessions, completions, private drafts, media and unrelated tables are not exported. Source content and mathematical review metadata remain private.

The admin snapshot route is `/tools/concept-assignments/snapshot/`. Select a subject in the existing review queue and click **Export review snapshot**. Subject, year, contest and problem search define the source scope. State/concept/reason filters do not limit the snapshot: all assignment rows for matching sources are included. Inactive matching sources are included deliberately, so exclusion checks have the full source evidence.

The export uses one PostgreSQL repeatable-read/read-only transaction, 15-second per-statement and one-second lock timeouts, and batches of 250 source identities. It fails instead of silently truncating. Limits are 20,000 problems and 64 MiB uncompressed; narrow source filters when a scope is larger. The download is gzip-compressed JSON with `private, no-store`. SQLite is supported for isolated local rehearsal using transaction and connection read-only enforcement.

A management command provides the same export on an explicitly authorized server/local target:

```sh
python manage.py export_concept_review_snapshot \
  --subject Algebra --output /private/review/algebra-snapshot.json.gz
```

An explicit bounded UUID selection uses repeated `--problem-uuid` instead of `--subject`. Explicit UUIDs cannot be combined with source filters. Paths are examples, not permission to run a production command. Use the existing approved operational channel; never retrieve production credentials or run arbitrary SSH commands to obtain a snapshot.

## Review locally, without a database import

Use the application revision that produced the snapshot. Registry or engine changes are explicit conflicts. The offline review command performs no database queries and needs neither a local production clone nor production credentials. Do not edit the snapshot to change expected values; regenerate it if evidence changed.

Supply a JSON decision array using the existing review format. Confirm/add/replace decisions need supported roles, an exact statement or published-solution excerpt and a rationale. Agent-assisted decisions also need the full reviewed statement hash. This tooling does not automatically approve mathematical suggestions. Protected keys are an optional explicit JSON array of `problem_uuid|concept_id` pairs; include held and flagged associations required to remain unchanged.

```sh
DJANGO_READ_DOT_ENV_FILE=False DJANGO_SETTINGS_MODULE=config.settings.test \
python manage.py review_concept_snapshot \
  --snapshot /private/review/algebra-snapshot.json.gz \
  --decisions /private/review/decisions.json \
  --protected-keys /private/review/protected-keys.json \
  --output-directory /private/review/new-local-dry-run
```

The new output directory contains:

- `review-packet.json`: immutable explicit decisions, full-scope baseline hashes, protected pairs and deterministic per-batch operation IDs.
- `dry-run.json`: exact proposed before/after rows, coverage deltas, conflicts and a checksum.
- `row-changes.csv`: spreadsheet-safe values with proposed roles and rationale.
- `decisions-001.json`, etc.: emitted only when the entire review is conflict-free. Each contains at most 250 decisions; one problem is kept within one batch.

The command reports all conflicts and exits unsuccessfully if any exist. No executable decision files are emitted in that case. Duplicate targets, including replacement destinations and canonical redirects, are rejected across the entire packet, not just within each batch. A protected source, replacement destination or implicitly retired identity blocks the packet.

Output files are created exclusively; existing artifacts are not overwritten. JSON files have mode 0600 and local review directories mode 0700. Snapshot checksums detect corruption and bind artifacts; they are not an authentication signature or authorization to apply decisions.

## Fresh production dry run

Upload `review-packet.json` using **Check a local review packet** on the admin review page. This POST retains admin and CSRF checks and accepts at most 8 MiB of JSON. It returns one downloaded report; it does not apply decisions.

The equivalent command is:

```sh
python manage.py check_concept_review_packet \
  --packet /private/review/review-packet.json \
  --output /private/review/new-live-dry-run.json
```

This command has no `--apply` option. It captures a new consistent snapshot and compares every selected source, assignment before-image (including its last-update marker), published proof and scope membership. No browser pagination or per-row click is required. Local and live preview hashes match when the evidence and state match.

Conflicts include:

| Code | Meaning / next action |
|---|---|
| `SOURCE_CHANGED` | A statement, tag, owner/active flag or other exact source value differs; review the changed source again |
| `ASSIGNMENTS_CHANGED` | A selected assignment was changed, added or removed; reconcile that review |
| `PUBLISHED_EVIDENCE_CHANGED` | Published evidence was edited, published, withdrawn or removed; revalidate the argument |
| `SCOPE_CHANGED` | Selected source membership differs; refresh the scope |
| `REGISTRY_FINGERPRINT_CHANGED` | Concept definitions/memberships/policy differ; review with the matching catalog |
| `ENGINE_FINGERPRINT_CHANGED` | Review code differs; use the same application revision or regenerate the snapshot |
| `PROTECTED_ASSIGNMENT` | A direct, replacement or identity-retirement write touches a protected pair; remove that decision |
| `INVALID_PACKET` / `INVALID_DECISION` | Duplicate targets, bad identities, unsupported roles, invalid excerpts or malformed decisions require correction |

A conflict makes the entire report unready and clears executable batches; non-conflicting rows are not applied partially. The check is intentionally conservative: even an edit to an unrelated selected source requires a refreshed snapshot. Narrow the snapshot scope when independent reviews should proceed separately.

## Application and verification

Review the fresh dry run and obtain the required authorization. Submit only the frozen bounded decision arrays through the existing signed preview/apply workflow. That workflow checks source/assignment freshness again at application time, has a 30-minute preview lifetime, uses atomic transactions and records durable receipts under unique operation IDs. Before clicking Apply, compare each native preview SHA-256 with the corresponding approved bulk-report batch SHA-256. A mismatch requires a new dry run and review; never treat a newly generated preview as approval of changed effects. The bulk-check report is not an apply token and does not bypass those checks. The existing `apply_concept_assignment_audit` command is for automatic refresh reports, not these reviewed-decision packets.

After application, export one new snapshot and compare exact affected pairs, preserved pairs, source/proof fingerprints, counts and receipts. Exported before-images support local diffing; do not restore snapshots or write them directly to database tables. Mathematical source gaps and ambiguous concepts remain held until supported; moving review data locally does not resolve those evidence gaps.

A new tooling release is needed before the snapshot download and bulk-check route are available in production. Implementing or testing this workflow locally does not deploy it or authorize new production assignment changes.
