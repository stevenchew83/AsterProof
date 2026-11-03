# Achievement paste imports

Admins can open **Students → Student profile → Paste achievements** for one existing student. This workflow does not create identities or change school, birth year, selection groups, ranking formulas or verified scoring scales.

1. Paste plain text, bullets, a tab-separated table or a Markdown table. Give the source a label and choose supplied research or family provenance. The saved preview retains the exact submitted text. Parsing runs locally without provider calls.
2. Review the suggested rows. Select an exact event year, record type, discipline and evidence label. Keep awards, raw scores and rankings separate. Uncertain or aggregate years are not expanded. Add manual rows when extraction misses an event. Excluded and unparsed text stays in the original source.
3. Review the final summary and explicitly confirm the import. The summary distinguishes new records from existing records linked for context. Links preserve existing result values and evidence reviews; use the correction workflow to change those records.

Pasted evidence can be reported, pending or conflicting, with family provenance retained. The paste workflow cannot mark any claim Verified, even when the source says “official” or “verified.” Checking organizer results or certificates remains a separate evidence correction. Each imported award, score and ranking receives its own claim; medal classification and highlights are not inferred.

Every successful import creates one research/context record containing the complete original text. Its year is the source-capture year, not a competition year, and it is excluded from achievement charts. New event records are excluded from ranking by default. The batch retains reviewed rows, source excerpts, source hash, linked/new result IDs and its classification correction receipt. Open **Sources & notes** for the original context and **Classification audit** for reviewed metadata.

Limits are 200,000 UTF-8 bytes, 2,000 source lines and 80 review rows. Matching uses event name or known competition series plus year; ambiguous matches require a manual link or exclusion. Semantic duplicates with unrelated names may still need human review. The full source remains available when the suggestion limit is reached.

Application is atomic under the shared ranking write lock. A changed student/result/evidence snapshot, superseded confirmation, duplicate event or already-imported source prevents application. Repeating a consumed confirmation never adds records twice. A failed transaction rolls back event results, context and classification metadata together. A correction receipt covers classification changes; it does not delete imported source/results.

No schema migration or external parsing dependency is needed. Preview text is available only through the existing ranking/admin access boundaries; review batches are restricted to their creating admin.
