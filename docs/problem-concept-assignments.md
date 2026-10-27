# Reviewed problem-to-concept assignments

This feature introduces an assignment authority for Algebra, Number Theory, Geometry, and Combinatorics. It is disabled by default. Catalog consolidation alone never establishes that a specialist concept is actually used in a problem.

## Acceptance contract

- An exact, unambiguous headline `technique` caption may be accepted automatically when the source is valid, the concept belongs to the problem's subject, and no contextual or specialist review rule applies. The basis is **Exact legacy tag**, not a claim that the proof has been mathematically reviewed.
- Structured object, method, lemma/theorem, proof-role and canonical-subtopic fields produce suggestions. Contextual, ambiguous, cross-subject and specialist matches also require review. Farey and Beatty remain suggestions until supported by a statement or published solution.
- A concept counts once per problem UUID. Roles and subject memberships are metadata. A reviewed `area_context` selects an existing area within a subject membership of the concept for this problem only; analytics/progress include that observed context without changing the global catalog. The context of the problem selects the displayed area; unrelated catalog memberships do not create extra problem areas.
- Statement tags take precedence over archive tags, including invalid/suppressed statement tags. Suppression cannot accidentally trigger an archive fallback. Inactive sources and mismatched UUID links do not contribute accepted coverage.
- Confirmation/addition requires an existing canonical ID, supported roles, rationale and an exact statement or published-solution excerpt. Private drafts cannot establish global coverage. Hold/reject also requires a rationale. Replacement rejects the old identity and confirms an existing destination with evidence.
- Reviewed rejections and holds survive automated refreshes. An edited statement, withdrawn/edited published solution or changed concept definition revalidates the evidence. Unsupported decisions stop contributing coverage until reviewed. Equivalent JSON-array reordering does not invalidate otherwise current evidence.

## Registry and provenance

`concept_assignment_registry.py` builds an assignment registry from the existing subject catalogs. The versioned identity manifest now includes the previously reviewed floor/ceiling merge plus the 29 reviewed shared-identity groups (30 additional legacy IDs redirected), yielding 1,109 canonical identities. The source definitions describe the same floor/ceiling family; subject areas, aliases, legacy IDs and assessment references survive. Floor/ceiling direction remains a variant. Seven scope groups remain held: rounding, log-concavity, generating functions, convolution, subadditivity, Sidon sets and triangulation. Equal names generate proposals, never automatic merges.

Each trace includes problem UUID, effective source model/row, original headline caption, exact field and JSON member index, role, source subject, alias rule, resolution status and source fingerprint. Supported and unresolved occurrences remain inspectable separately. Sources and assessment profiles are not rewritten.

Four additive tables store current decisions, batches, per-decision before/after events, and activation state. Approved equivalent identities normalize to a single current row; old rows are retired with `is_current=False`, without deleting source records or review history. Conflicting human dispositions block automatic normalization and require an explicit review decision.

## Admin workflow

User-delegated agent reviews may prepare decision manifests in bulk. Record the agent and origin in each decision's `review_metadata` and rationale; the applying admin remains the authenticated execution actor. Public coverage says **Evidence reviewed**, rather than attributing agent decisions to a human mathematical reviewer. Delegation does not bypass evidence, access, preview or production-release controls.

The existing admin boundary protects `/tools/concept-assignments/`, including in DEBUG. The queue supports subject, year, contest, problem search, concept, disposition and reason filters. The **No mapped concepts** view finds problems without materialized assignments. Each detail page places the rendered statement beside expandable source traces and decision forms. Published solution evidence is available; private drafts are excluded.

All decisions follow **preview -> apply -> receipt**. A signed preview expires after 30 minutes. Agent-origin decisions must carry the reviewed full-statement hash; preview checks it and the optional statement UUID before accepting even an unchanged excerpt. Apply recomputes source/assignment evidence and rejects a stale or tampered preview. A unique operation ID returns its existing receipt on replay and cannot be reused for different decisions. CSRF protection is retained. Bulk hold/reject is available; bulk confirmation requires individually supported decisions in the JSON manifest.

The review queue and provenance audit work before the new schema is installed; application is unavailable. CSV/JSON exports cover the loaded page; the audit command produces complete bounded bundles. CSV values are protected against spreadsheet formulas. Public coverage payloads never include historical solution excerpts.

## Shared consumers

After activation, library/editor areas and counts, canonical concept filters, analytics, progress, practice lists and legacy gap URLs use the same fresh accepted-assignment projection. Suggestions appear separately and do not count. Library TSV adds separate suggestion, reason and acceptance-basis columns. Completion remains connected through the existing `problem_uuid` and user permissions. When disabled, existing pages retain their legacy behavior without querying the new assignment tables.

Source/published-solution signals mark affected decisions for refresh. The existing catalog-refresh job refreshes the assignment projection only when activated. Public reads validate current evidence, including when an importer uses bulk updates that bypass signals. Bounded batch reads avoid per-problem queries.

## Schema prerequisite and staged rollout

`0036_concept_assignment_reviews` is additive. The current managed deployer supports migration classification `none`; this implementation deliberately does not change that protection. A separately reviewed schema release is required before enabling or writing assignment tables in production. These instructions describe a procedure, not authorization to execute it.

1. Review and release the additive schema through an approved migration-capable procedure. Keep `CONCEPT_ASSIGNMENTS_ENABLED=false` and the database state disabled. Confirm all four tables and the exact code/registry revision.
2. Run a fresh production provenance audit through the approved read-only application channel. Do not retrieve secrets or bypass the diagnostic account's environment-file restriction. The native metadata export has been reviewed for 945 selected UUIDs. It does not contain active flags or stored structured tag rows, so it cannot establish an exact source-level dry run. Use the bounded native source snapshot export for those fields.
3. Review source-level changes, identity conflicts and count deltas. Use bounded bundles, at most 250 problems each. Keep held proposals and excluded source tags unchanged.
4. Apply only the approved frozen bundles to the new tables, using the file hash and one operation ID per bundle. Application recomputes the report, aborts on evidence drift and never writes tags, authored solutions, completions, benchmarks or ratings. Reconcile the operation receipt before any retry.
5. Verify the entire active population has zero pending refresh changes and no identity conflicts. Unresolved suggestions may remain: activation does not convert them to accepted concepts. Inspect count reductions and representative examples in all four subjects.
6. Set the deployment flag only after the schema prerequisite. Run the read-only activation verification again, review its hash, then explicitly activate that exact verification. Check representative library/editor/progress/search/gap counts and private-evidence exclusions.

Examples below target an explicitly selected local/test environment. Production use requires the reviewed operational procedure and authorization.

```sh
python manage.py audit_concept_assignments --subject Algebra --output-directory /tmp/new-assignment-audit
python manage.py audit_concept_assignments --problem-uuid PROBLEM_UUID

# SHA256_OF_REPORT_FILE is the file's digest, distinct from the embedded report SHA.
python manage.py apply_concept_assignment_audit --report /tmp/new-assignment-audit/batch-00001.json --expected-report-sha256 SHA256_OF_REPORT_FILE --operation-id NEW_UUID
# Add --apply only for an approved frozen batch.

python manage.py activate_concept_assignments
# Apply only with the reviewed verification hash, unique operation ID and --apply.
python manage.py activate_concept_assignments --expected-verification-sha256 VERIFICATION_SHA --operation-id NEW_UUID --apply
```

Deactivation has a separate preview using `activate_concept_assignments --disable`; applying that exact verification requires `--disable --apply` and its hash/operation ID. It switches the projection without deleting review evidence. Any production deactivation requires its applicable authorization. Re-enabling requires fresh full verification. Do not roll back the new tables after decisions have been recorded.

## Validation and current limitation

Focused regression tests cover four subjects, source precedence, specialist holds, shared identity normalization/conflicts, rejection persistence, stale evidence, published/private solution boundaries, admin/CSRF controls, immutable previews/replays, activation, query bounds and cross-page coverage parity. Browser verification uses a disposable local SQLite database and synthetic examples; it does not certify production data or PostgreSQL deployment readiness.

No production schema, assignments, configuration, catalog definitions or benchmark scores have been changed by this implementation. The exact live source audit remains a rollout prerequisite. The native source export was deployed separately in PR #303. Nineteen read-only snapshots captured exact stored source rows, owner/active flags, suppression status and full-statement hashes for 945 selected problem identities. All 1,029 reviewed decisions matched those sources; five suppressed source rows remained excluded. The frozen selected-scope dry run proposes 4,466 assignment rows: 1,550 accepted, 2,908 suggested and eight rejected, with zero conflicts and no source writes. A local SQLite migration/application rehearsal reproduced those counts and verified unchanged original-table content hashes and receipt replay. This is a selected-scope result, not a full-library seed or PostgreSQL execution proof. A fresh full-population audit, a successful PostgreSQL rehearsal, fingerprint-bound schema disclosure and the approved deployment channel remain prerequisites for production activation.

## Native source snapshot prerequisite

`/tools/concept-assignment-sources/` is a separate, strictly admin-only GET export using only existing archive/statement/tag models. It exposes exact source row IDs, active flags, suppression status, ownership, text hashes and stored structured fields. It needs no review tables and does not retrieve environment files or credentials. PostgreSQL reads run in a non-request-atomic repeatable-read/read-only transaction with a 15-second statement timeout and one-second lock timeout. Explicit UUID requests are bounded; missing identities are reported. Responses are private/no-store. The separately frozen export-only release shipped in PR #303 without the assignment schema or mapping writes. Its release approval was completed and does not authorize a later authority, schema or assignment operation.
