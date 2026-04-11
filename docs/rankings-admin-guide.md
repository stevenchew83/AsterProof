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

1. Ranking table: `/rankings/`
2. Ranking dashboard: `/rankings/dashboard/`
3. Students: `/rankings/students/`
4. Assessments: `/rankings/assessments/`
5. Formulas: `/rankings/formulas/`
6. Import center (admin): `/rankings/imports/`

## 6. Privacy Rules

1. Ranking pages and exports mask NRIC by default.
2. Full NRIC visibility is restricted to admin-role users.

## 7. Verification Commands

```bash
uv run ruff check inspinia/rankings
uv run pytest inspinia/rankings/tests -q
uv run python manage.py check
```
