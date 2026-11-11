# Problem Library AI evidence schema

`pages.0048_statement_ai_concept_suggestions` adds one nullable JSONB column to
`pages_contestproblemstatement`. It has no default, index or backfill. Compatible
code recovery retains the column and any saved suggestions.

The frozen allowance in `scripts/deployment/library_ai_schema.py` pins the exact
migration file and prior migration tree. The isolated PostgreSQL 17.9 rehearsal
proves the single-column catalog delta, preservation of existing records,
sequences and triggers, and compatibility with the prior active revision.

After the PR passes CI and merges, run CI on the exact merged SHA with the
verified active production SHA as `baseline_sha`. Preserve the original
rehearsal proof and prepare the disclosure using the starting catalog-only
snapshot and `library_ai_schema.expected_catalog_audit`.

Install the exact reviewed allowance through the separately authorized
[production bootstrap procedure](production-bootstrap.md). The application
workflow cannot install its own authority. After the installed hashes and
preserved controls are verified, dispatch **Production deploy** with
`backward-compatible-schema` and the exact disclosure. Preserve the migration
lock and statement timeouts, protected environment review and normal postflight.

After deployment, an administrator can test **Suggest with AI** on the requested
Problem Library row. Confirm that the row updates in place and that a browser
refresh shows the same saved values.
