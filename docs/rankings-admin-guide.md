# Rankings Admin Guide

This guide covers the day-to-day workflow for the olympiad ranking system.

## 1. Student Master Import

1. Open Import Center from the Rankings menu.
2. In **Student Master Import**, upload a `.csv` or `.xlsx` file.
3. Click **Preview student import**.
4. Review matched/create/ambiguous/error counts.
5. Click **Apply student import**.

Matching order:

1. `external_code`
2. `full_nric` (admin privilege required)
3. `normalized_name + birth_year`

## 2. Assessment Result Import

1. Open **Import Center**.
2. In **Assessment Result Import**, upload the result file.
3. Select an existing assessment, or provide new assessment code/name/season.
4. Map the source columns (`student_identifier`, score, medal, band, status, remarks, source URL).
5. Click **Preview result import**.
6. Click **Apply result import**.

Rows are upserted by `(student, assessment)` into `StudentResult`.

## 3. Legacy Wide-Sheet Migration

1. Open **Import Center**.
2. In **Legacy Wide-Sheet Import**, upload the legacy spreadsheet and set `season_year`.
3. Click **Preview legacy import**.
4. Check ambiguous-column warnings and issue counts.
5. Click **Apply legacy import**.

Behavior:

1. Student-like columns update student master.
2. Numeric assessment-like columns become `StudentResult` rows.
3. Team/squad/watchlist-like labels become `StudentSelectionStatus`.
4. Missing assessments are created automatically.

## 4. Recompute Rankings

From project root:

```bash
uv run python manage.py recompute_rankings --formula <FORMULA_ID>
```

or by scope:

```bash
uv run python manage.py recompute_rankings --season <YEAR> --division <DIVISION>
```

Notes:

1. Formulas with no items are skipped and stale snapshots are cleared.
2. Snapshot recompute writes `RankingSnapshot` rows and version metadata.

## 5. Main Operator Pages

1. Assessment results (without a formula): `/rankings/results/`
2. Student season history matrix: `/rankings/history/`
3. Olympiad text-sheet import: `/rankings/imports/olympiad/`

The assessment results page ranks raw scores separately within each recorded category.
Equal scores share a competition rank (1, 2, 2, 4). Search and school filters preserve
the original category rank. Blank scores have no rank; zero is a recorded score.
Both new tables search the full dataset before server pagination (50 rows per page).
All pages retain the moderator/admin role boundary.

### Olympiad history and IMONST2 text imports

Upload UTF-8 `.txt`, `.tsv`, or `.csv`, or paste the sheet with its header. Supported
layouts are the original 40-column history sheet and the four-column IMONST2 result
list. The history adapter uses column positions to distinguish duplicate headers.
It keeps score, medal, category and dated group history as assessment results; the
two original 2024 group columns remain separate. Scores and categories are not
combined into an overall ranking or inferred selection decision.

Review the mapping, exclusions, every student match, and any replacement result
values before confirming **Apply reviewed import**. Name-only matches are labelled;
ambiguous identities block preview. A preview belongs to its creator, applies once,
and refuses changed student matches or result values. Empty source values preserve existing data.
New school information only fills an empty student school; existing schools remain.
The preview itself makes no student, school, assessment or result changes.

NRICs, arbitrary links, unlabelled school columns and free-form notes are excluded
from the stored preview; the raw upload is never saved. Yearless MMOS entrance,
APMO qualifier and TST-point columns are held for manual mapping. The existing
TOTAL column is excluded to avoid double counting. School values explicitly tied
to IMONST2 2025 or KMC 2026 are kept as notes on those results. Blank separators and
repeated IMONST2 headers are skipped. Imports are limited to 2 MB and 2,000 rows.

### Existing formula and management pages

1. Ranking table: `/rankings/`
2. Ranking dashboard: `/rankings/dashboard/`
3. Students: `/rankings/students/`
4. Assessments: `/rankings/assessments/`
5. Formulas: `/rankings/formulas/`
6. Import center (admin): `/rankings/imports/`

## 6. Privacy Rules

1. Ranking pages and exports mask NRIC by default.
2. Full NRIC visibility is restricted to admin-role users.

### Student achievement profiles

The student profile opens on **Achievements**, with **Scores & participation**,
**Selection history**, **All records**, and **Sources & notes** alongside it.
Research context does not count as an award. Year sections remain complete across
pagination; a year with more than 50 records stays on one page.
Year groups and selection history remain visible in their selected view.
Profile details, record evidence and import history use keyboard-accessible
expand/collapse controls. Source notes appear with expanded record evidence.
Record links open their details, and filtering preserves details that remain on the page.

The Achievements view includes yearly counts by discipline and an award/placing
evidence chart. Both use all matching achievement records before pagination. Counts
include titles, recognition and contributions; they are not medal totals. Unreviewed
disciplines appear as **Not classified**. Year, discipline and evidence chart links
apply the existing GET filters and can toggle their selection off, including without
JavaScript. On phones the charts stack vertically and long year ranges scroll within
the chart. A count table and labelled links provide access without relying on colour.

Evidence chart bars count one primary award or placing claim per achievement record.
They use the explicit **Award/placing** filter options (`evidence=achievement_…`),
so verified score evidence cannot inflate an award's evidence count. The existing
any-claim filter options still include separate score and ranking reviews. Pending
reviews after result changes stay pending in the chart.

Each result's **Review classification** link prepares a correction for its record
type, discipline, exact competition scope/stage, individual/team/joint attribution
and optional highlight selection. Original results, identities and source notes
are preserved. Display classifications on older records are conservative defaults,
not reviewed facts. A Primary/Junior competition category is not a selection event.

**Review claim evidence** creates separate award, score and ranking reviews. Award
classification distinguishes medals, titles, distinctions, school recognition and
community contributions while preserving the exact award wording. A checked medal
does not verify a national ranking or the contest score. Score claims must match
the recorded raw score; a denominator still requires a reviewed category scale.

Evidence states are Not reviewed, Reported, Pending verification, Verified and
Conflicting evidence. Family records and supplied research remain reported until
checked against an identified organizer, news or other direct source. A source link,
an import filename or prose saying "verified" does not establish verification.
Source labels and evidence notes support private certificates without requiring a
public URL. URLs with embedded credentials are rejected.

Moderators prepare proposals; admins apply submitted proposals with the existing
permanent correction receipt. Classification and claim reviews bind to the original
result values and source provenance. Changed values or provenance make those reviews
stale; a no-op reimport preserves them. Stale, conflicting, family-only and unreviewed
claims are excluded from selected highlights. No medal totals or overall achievement
ranking are calculated. Import-file counts are labelled separately from claim evidence.

Migration `rankings.0006_student_achievement_profiles` adds the two metadata tables
without backfilling or rewriting student results. New correction kinds require a
compatible review reader; the release registry conservatively disables ordinary
code rollback. This local implementation does not prepare or authorize a production
schema allowance, deployment, public sharing or evidence backfill.

## 7. Verification Commands

```bash
uv run ruff check inspinia/rankings
uv run pytest inspinia/rankings/tests -q
uv run python manage.py check
```
