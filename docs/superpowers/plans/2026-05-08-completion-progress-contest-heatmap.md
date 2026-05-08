# Completion Progress Contest Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a statement-backed contest completion heatmap to completion progress analytics before the filtered rows table, using the existing `contest` query parameter.

**Architecture:** Build the heatmap payload in `inspinia/pages/completion_progress.py` so it is testable outside the large view module. Wire the helper into `_render_completion_progress_analytics`, then render the card in `completion-progress-analytics.html` using the existing ApexCharts stack and the visual pattern from `contest-advanced-analytics`.

**Tech Stack:** Django views/templates, Django ORM, pytest, ApexCharts, Bootstrap 5/Inspinia, Tabler icons.

---

## File Structure

- Modify `inspinia/pages/completion_progress.py`
  - Add `ContestProblemStatement` import.
  - Add a natural problem-code sort helper.
  - Add `completion_progress_contest_heatmap_payload`.
  - Add a private chart-payload helper for ApexCharts.
- Modify `inspinia/pages/views.py`
  - Import `completion_progress_contest_heatmap_payload`.
  - Add `completion_progress_contest_heatmap` to the completion progress context.
- Modify `inspinia/templates/pages/completion-progress-analytics.html`
  - Add page-local heatmap CSS.
  - Render the heatmap card before `Filtered completion rows`.
  - Add a JSON payload script.
  - Render the heatmap with ApexCharts.
- Modify `inspinia/pages/tests.py`
  - Import `completion_progress_contest_heatmap_payload`.
  - Add focused helper tests.
  - Add view/template integration tests for admin selected-user mode and my-progress mode.

---

### Task 1: Add Failing Helper Tests

**Files:**
- Modify: `inspinia/pages/tests.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add the helper import**

Add this import near the other `inspinia.pages` imports:

```python
from inspinia.pages.completion_progress import completion_progress_contest_heatmap_payload
```

- [ ] **Step 2: Add a small statement fixture helper near the completion progress tests**

Place this helper before `test_completion_progress_analytics_dashboard`:

```python
def _create_heatmap_statement(
    *,
    contest: str,
    year: int,
    problem_code: str,
    problem_number: int,
    day_label: str = "",
    mohs: int = 10,
) -> tuple[ProblemSolveRecord, ContestProblemStatement]:
    problem = ProblemSolveRecord.objects.create(
        year=year,
        topic="ALG",
        mohs=mohs,
        contest=contest,
        problem=problem_code,
        contest_year_problem=f"{contest} {year} {problem_code}",
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=year,
        contest_name=contest,
        problem_number=problem_number,
        problem_code=problem_code,
        day_label=day_label,
        statement_latex=f"{contest} {year} {problem_code} statement",
    )
    return problem, statement
```

- [ ] **Step 3: Add a failing payload state test**

Place this test near the existing completion progress analytics tests:

```python
def test_completion_progress_contest_heatmap_payload_marks_cell_states():
    user = UserFactory()
    other_user = UserFactory()
    contest = "APMO"
    solved_problem, solved_statement = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P1",
        problem_number=1,
    )
    _unsolved_problem, _unsolved_statement = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P2",
        problem_number=2,
    )
    _partial_problem_one, partial_statement_one = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P3",
        problem_number=3,
        day_label="Day 1",
    )
    _partial_problem_two, _partial_statement_two = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P3",
        problem_number=3,
        day_label="Day 2",
    )
    _older_problem, _older_statement = _create_heatmap_statement(
        contest=contest,
        year=2025,
        problem_code="P2",
        problem_number=2,
    )

    UserProblemCompletion.objects.create(user=user, problem=solved_problem, completion_date=date(2026, 1, 1))
    UserProblemCompletion.objects.create(user=user, statement=partial_statement_one, completion_date=date(2026, 1, 2))
    UserProblemCompletion.objects.create(user=other_user, statement=solved_statement, completion_date=date(2026, 1, 3))

    heatmap = completion_progress_contest_heatmap_payload(contest=contest, user=user)

    assert heatmap["selected_contest"] == contest
    assert heatmap["problem_codes"] == ["P1", "P2", "P3"]
    assert heatmap["year_total"] == 2
    assert heatmap["problem_code_total"] == 3
    assert heatmap["filled_cell_total"] == 4
    assert heatmap["has_partial_cells"] is True
    row_2026 = next(row for row in heatmap["rows"] if row["year"] == 2026)
    row_2025 = next(row for row in heatmap["rows"] if row["year"] == 2025)
    cell_2026_p1 = next(cell for cell in row_2026["cells"] if cell["problem_code"] == "P1")
    cell_2026_p2 = next(cell for cell in row_2026["cells"] if cell["problem_code"] == "P2")
    cell_2026_p3 = next(cell for cell in row_2026["cells"] if cell["problem_code"] == "P3")
    cell_2025_p1 = next(cell for cell in row_2025["cells"] if cell["problem_code"] == "P1")
    assert cell_2026_p1["state"] == "solved"
    assert cell_2026_p1["display"] == "✓"
    assert cell_2026_p1["solution_url"] == reverse("solutions:problem_solution_list", args=[solved_problem.problem_uuid])
    assert cell_2026_p2["state"] == "unsolved"
    assert cell_2026_p2["display"] == "•"
    assert cell_2026_p3["state"] == "partial"
    assert cell_2026_p3["display"] == "1/2"
    assert cell_2025_p1["state"] == "empty"
    assert cell_2025_p1["display"] == ""
    assert heatmap["chart"]["series"][0]["name"] == "2026"
    assert heatmap["chart"]["series"][0]["data"][0]["y"] == 3
```

- [ ] **Step 4: Add a failing empty-input test**

Place this test after the payload state test:

```python
def test_completion_progress_contest_heatmap_payload_requires_contest_and_user():
    user = UserFactory()

    no_contest = completion_progress_contest_heatmap_payload(contest="", user=user)
    no_user = completion_progress_contest_heatmap_payload(contest="APMO", user=None)

    assert no_contest["selected_contest"] == ""
    assert no_contest["problem_codes"] == []
    assert no_contest["chart"]["series"] == []
    assert no_user["selected_contest"] == "APMO"
    assert no_user["problem_codes"] == []
    assert no_user["chart"]["series"] == []
```

- [ ] **Step 5: Run the helper tests and verify they fail**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_contest_heatmap_payload_marks_cell_states inspinia/pages/tests.py::test_completion_progress_contest_heatmap_payload_requires_contest_and_user -q
```

Expected: FAIL because `completion_progress_contest_heatmap_payload` is not importable yet.

- [ ] **Step 6: Commit the failing tests**

```bash
git add inspinia/pages/tests.py
git commit -m "test: cover completion progress contest heatmap payload"
```

---

### Task 2: Implement The Heatmap Payload Helper

**Files:**
- Modify: `inspinia/pages/completion_progress.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add imports**

In `inspinia/pages/completion_progress.py`, add `re` and `ContestProblemStatement`:

```python
import re
```

```python
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import UserProblemCompletion
```

- [ ] **Step 2: Add the payload helper**

Place this code after `completion_progress_charts_payload`:

```python
def completion_progress_contest_heatmap_payload(
    *,
    contest: str,
    user,
) -> dict[str, object]:
    selected_contest = (contest or "").strip()
    empty_payload = {
        "chart": _completion_progress_contest_heatmap_chart_payload([]),
        "filled_cell_total": 0,
        "has_partial_cells": False,
        "problem_code_total": 0,
        "problem_codes": [],
        "rows": [],
        "selected_contest": selected_contest,
        "year_total": 0,
    }
    if not selected_contest or user is None:
        return empty_payload

    statement_rows = list(
        ContestProblemStatement.objects.filter(is_active=True, contest_name=selected_contest)
        .select_related("linked_problem")
        .values(
            "id",
            "linked_problem_id",
            "linked_problem__problem_uuid",
            "problem_code",
            "contest_year",
        ),
    )
    if not statement_rows:
        return empty_payload

    statement_ids = [int(row["id"]) for row in statement_rows]
    direct_solved_statement_ids = set(
        UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).values_list("statement_id", flat=True),
    )
    linked_problem_ids = sorted(
        {
            int(row["linked_problem_id"])
            for row in statement_rows
            if row["linked_problem_id"] is not None
        },
    )
    legacy_solved_problem_ids = set(
        UserProblemCompletion.objects.filter(
            user=user,
            statement__isnull=True,
            problem_id__in=linked_problem_ids,
        ).values_list("problem_id", flat=True),
    )

    heatmap_problem_codes = sorted(
        {
            str(row["problem_code"] or "").strip()
            for row in statement_rows
            if row["problem_code"]
        },
        key=_completion_progress_problem_sort_key,
    )
    heatmap_years = sorted(
        {
            int(row["contest_year"])
            for row in statement_rows
            if row["contest_year"] is not None
        },
        reverse=True,
    )

    heatmap_solution_urls: dict[tuple[int, str], str] = {}
    heatmap_counts: dict[tuple[int, str], dict[str, int]] = {}
    for row in statement_rows:
        problem_code = str(row["problem_code"] or "").strip()
        year = row["contest_year"]
        if not problem_code or year is None:
            continue
        heatmap_key = (int(year), problem_code)
        cell_counts = heatmap_counts.setdefault(
            heatmap_key,
            {
                "problem_total": 0,
                "solved_total": 0,
            },
        )
        cell_counts["problem_total"] += 1
        linked_problem_id = row["linked_problem_id"]
        linked_problem_uuid = row["linked_problem__problem_uuid"]
        if linked_problem_uuid is not None:
            heatmap_solution_urls.setdefault(
                heatmap_key,
                reverse("solutions:problem_solution_list", args=[linked_problem_uuid]),
            )
        if row["id"] in direct_solved_statement_ids or (
            linked_problem_id is not None and int(linked_problem_id) in legacy_solved_problem_ids
        ):
            cell_counts["solved_total"] += 1

    heatmap_rows: list[dict[str, object]] = []
    has_partial_heatmap_cells = False
    for year in heatmap_years:
        row_cells: list[dict[str, object]] = []
        for problem_code in heatmap_problem_codes:
            counts = heatmap_counts.get((year, problem_code))
            if counts is None:
                row_cells.append(
                    {
                        "display": "",
                        "problem_code": problem_code,
                        "solution_url": "",
                        "state": "empty",
                        "title": f"{selected_contest} {year} {problem_code}: no statement row",
                    },
                )
                continue

            problem_total = int(counts["problem_total"])
            solved_total = int(counts["solved_total"])
            if solved_total == 0:
                state = "unsolved"
            elif solved_total == problem_total:
                state = "solved"
            else:
                state = "partial"
                has_partial_heatmap_cells = True

            rows_word = "statement row" if problem_total == 1 else "statement rows"
            row_cells.append(
                {
                    "display": (
                        "✓"
                        if problem_total == 1 and state == "solved"
                        else ("•" if problem_total == 1 else f"{solved_total}/{problem_total}")
                    ),
                    "problem_code": problem_code,
                    "solution_url": heatmap_solution_urls.get((year, problem_code), ""),
                    "state": state,
                    "title": (
                        f"{selected_contest} {year} {problem_code}: "
                        f"{solved_total} of {problem_total} {rows_word} solved by you"
                    ),
                },
            )
        heatmap_rows.append({"cells": row_cells, "year": year})

    return {
        "chart": _completion_progress_contest_heatmap_chart_payload(heatmap_rows),
        "filled_cell_total": len(heatmap_counts),
        "has_partial_cells": has_partial_heatmap_cells,
        "problem_code_total": len(heatmap_problem_codes),
        "problem_codes": heatmap_problem_codes,
        "rows": heatmap_rows,
        "selected_contest": selected_contest,
        "year_total": len(heatmap_rows),
    }
```

- [ ] **Step 3: Add private chart and sort helpers**

Place these helpers near the other private payload helpers:

```python
def _completion_progress_contest_heatmap_chart_payload(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    state_values = {
        "empty": 0,
        "unsolved": 1,
        "partial": 2,
        "solved": 3,
    }
    if not rows:
        return {"max_value": 3, "series": []}

    return {
        "max_value": 3,
        "series": [
            {
                "name": str(row["year"]),
                "data": [
                    {
                        "display": str(cell["display"]),
                        "solution_url": str(cell.get("solution_url", "")),
                        "state": str(cell["state"]),
                        "title": str(cell["title"]),
                        "x": str(cell["problem_code"]),
                        "y": state_values[str(cell["state"])],
                    }
                    for cell in row["cells"]
                ],
            }
            for row in rows
        ],
    }


def _completion_progress_problem_sort_key(problem_label: str | None) -> list[tuple[int, int | str]]:
    parts = re.split(r"(\d+)", str(problem_label or ""))
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in parts
        if part
    ]
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_contest_heatmap_payload_marks_cell_states inspinia/pages/tests.py::test_completion_progress_contest_heatmap_payload_requires_contest_and_user -q
```

Expected: PASS.

- [ ] **Step 5: Run ruff on the helper file**

Run:

```bash
uv run ruff check inspinia/pages/completion_progress.py inspinia/pages/tests.py
```

Expected: PASS.

- [ ] **Step 6: Commit the helper**

```bash
git add inspinia/pages/completion_progress.py inspinia/pages/tests.py
git commit -m "feat: build completion progress contest heatmap payload"
```

---

### Task 3: Wire The Payload Into The Completion Progress View

**Files:**
- Modify: `inspinia/pages/views.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add the view import**

In `inspinia/pages/views.py`, extend the existing completion progress import block:

```python
from inspinia.pages.completion_progress import completion_progress_contest_heatmap_payload
```

- [ ] **Step 2: Add the context key**

Inside `_render_completion_progress_analytics`, add this entry to `context` near `completion_progress_charts_payload`:

```python
"completion_progress_contest_heatmap": completion_progress_contest_heatmap_payload(
    contest=selected_contest,
    user=selected_user,
),
```

- [ ] **Step 3: Add an admin selected-user integration test**

Place this test near the completion progress analytics tests:

```python
def test_completion_progress_analytics_contest_heatmap_uses_selected_user(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    selected_user = UserFactory(email="selected@example.com")
    other_user = UserFactory(email="other@example.com")
    client.force_login(admin_user)
    contest = "APMO"
    problem, statement = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P1",
        problem_number=1,
    )
    UserProblemCompletion.objects.create(user=selected_user, problem=problem, completion_date=date(2026, 1, 1))
    UserProblemCompletion.objects.create(user=other_user, statement=statement, completion_date=date(2026, 1, 2))

    response = client.get(
        reverse("pages:completion_progress_analytics"),
        {"contest": contest, "range": "all", "user": str(selected_user.pk)},
    )

    assert response.status_code == HTTPStatus.OK
    heatmap = response.context["completion_progress_contest_heatmap"]
    row_2026 = next(row for row in heatmap["rows"] if row["year"] == 2026)
    cell_p1 = next(cell for cell in row_2026["cells"] if cell["problem_code"] == "P1")
    assert heatmap["selected_contest"] == contest
    assert cell_p1["state"] == "solved"
    response_html = response.content.decode("utf-8")
    assert response_html.index("Completion heatmap") < response_html.index("Filtered completion rows")
```

- [ ] **Step 4: Add a my-progress scoping test**

Place this test after the admin selected-user test:

```python
def test_my_completion_progress_contest_heatmap_uses_signed_in_user(client):
    user = UserFactory()
    other_user = UserFactory()
    client.force_login(user)
    contest = "APMO"
    _problem, statement = _create_heatmap_statement(
        contest=contest,
        year=2026,
        problem_code="P1",
        problem_number=1,
    )
    UserProblemCompletion.objects.create(user=other_user, statement=statement, completion_date=date(2026, 1, 2))

    response = client.get(
        reverse("pages:my_completion_progress_analytics"),
        {"contest": contest, "range": "all"},
    )

    assert response.status_code == HTTPStatus.OK
    heatmap = response.context["completion_progress_contest_heatmap"]
    row_2026 = next(row for row in heatmap["rows"] if row["year"] == 2026)
    cell_p1 = next(cell for cell in row_2026["cells"] if cell["problem_code"] == "P1")
    assert heatmap["selected_contest"] == contest
    assert cell_p1["state"] == "unsolved"
```

- [ ] **Step 5: Run the view integration tests and verify they pass**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_analytics_contest_heatmap_uses_selected_user inspinia/pages/tests.py::test_my_completion_progress_contest_heatmap_uses_signed_in_user -q
```

Expected: PASS.

- [ ] **Step 6: Commit the view wiring**

```bash
git add inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "feat: wire completion progress contest heatmap context"
```

---

### Task 4: Render The Heatmap Card Before The Table

**Files:**
- Modify: `inspinia/templates/pages/completion-progress-analytics.html`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add heatmap CSS**

In the template `extra_css` block, add this CSS after `.completion-progress-chart`:

```css
  .completion-progress-contest-legend {
    gap: 0.75rem;
  }

  .completion-progress-contest-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--bs-secondary-color);
    font-size: 0.78rem;
  }

  .completion-progress-contest-legend-swatch {
    width: 0.95rem;
    height: 0.95rem;
    display: inline-flex;
    border-radius: 0.3rem;
    border: 1px solid rgba(17, 32, 59, 0.12);
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  }

  .completion-progress-contest-legend-swatch-solved {
    background: #2fbf71;
  }

  .completion-progress-contest-legend-swatch-partial {
    background: #f1b44c;
  }

  .completion-progress-contest-legend-swatch-unsolved {
    background: #e25563;
  }

  .completion-progress-contest-legend-swatch-empty {
    background: #d6d9e0;
  }

  .completion-progress-contest-heatmap-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 0.25rem;
  }

  #chart-completion-progress-contest-heatmap {
    min-height: 240px;
  }

  #chart-completion-progress-contest-heatmap.completion-progress-contest-heatmap-clickable .apexcharts-heatmap-rect,
  #chart-completion-progress-contest-heatmap.completion-progress-contest-heatmap-clickable .apexcharts-series rect {
    cursor: pointer;
  }
```

- [ ] **Step 2: Add the heatmap card before the table card**

Place this block immediately before the row containing `Filtered completion rows`:

```django
  <div class="row g-3 mt-0">
    <div class="col-12">
      <div class="card">
        <div class="card-header border-bottom d-flex flex-wrap align-items-center gap-2">
          <div class="flex-grow-1">
            <h4 class="header-title mb-0">Completion heatmap</h4>
            <p class="text-muted fs-xs mb-0">Year-by-problem completion coverage for this contest. Green shows your completions on those rows; red means you have not completed any row in that cell yet.</p>
          </div>
          <span class="badge text-bg-light">
            {{ completion_progress_contest_heatmap.year_total }} years · {{ completion_progress_contest_heatmap.problem_code_total }} codes
          </span>
        </div>
        <div class="card-body">
          {% if not completion_progress_contest_heatmap.selected_contest %}
          <div class="alert alert-info mb-0" role="alert">
            Select a contest in the filters to load year-by-problem completion coverage.
          </div>
          {% elif completion_progress_contest_heatmap.problem_codes %}
          <div class="d-flex flex-wrap align-items-center completion-progress-contest-legend mb-3">
            <span class="completion-progress-contest-legend-item">
              <span class="completion-progress-contest-legend-swatch completion-progress-contest-legend-swatch-solved"></span>
              Your completions
            </span>
            <span class="completion-progress-contest-legend-item">
              <span class="completion-progress-contest-legend-swatch completion-progress-contest-legend-swatch-unsolved"></span>
              No completion from you yet
            </span>
            {% if completion_progress_contest_heatmap.has_partial_cells %}
            <span class="completion-progress-contest-legend-item">
              <span class="completion-progress-contest-legend-swatch completion-progress-contest-legend-swatch-partial"></span>
              Mixed coverage when a year/code has multiple rows
            </span>
            {% endif %}
            <span class="completion-progress-contest-legend-item">
              <span class="completion-progress-contest-legend-swatch completion-progress-contest-legend-swatch-empty"></span>
              No statement row for that year/code
            </span>
          </div>
          <div class="completion-progress-contest-heatmap-scroll">
            <div id="chart-completion-progress-contest-heatmap"></div>
          </div>
          {% else %}
          <div class="alert alert-info mb-0" role="alert">
            No statement-backed problem codes are available for this contest yet.
          </div>
          {% endif %}
        </div>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Add the JSON payload script**

After `{{ completion_progress_table_rows|json_script:"completion-progress-table-data" }}`, add:

```django
{{ completion_progress_contest_heatmap.chart|json_script:"completion-progress-contest-heatmap-data" }}
```

- [ ] **Step 4: Add template assertions to the admin integration test**

Extend `test_completion_progress_analytics_contest_heatmap_uses_selected_user` with:

```python
    assert 'id="chart-completion-progress-contest-heatmap"' in response_html
    assert "completion-progress-contest-heatmap-data" in response_html
    assert "Your completions" in response_html
    assert "No completion from you yet" in response_html
    assert "No statement row for that year/code" in response_html
```

- [ ] **Step 5: Add a no-contest template test**

Place this test near the completion progress analytics tests:

```python
def test_completion_progress_contest_heatmap_prompts_for_contest(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    completion_user = UserFactory()
    client.force_login(admin_user)
    problem, _statement = _create_heatmap_statement(
        contest="APMO",
        year=2026,
        problem_code="P1",
        problem_number=1,
    )
    UserProblemCompletion.objects.create(user=completion_user, problem=problem, completion_date=date(2026, 1, 1))

    response = client.get(
        reverse("pages:completion_progress_analytics"),
        {"range": "all", "user": str(completion_user.pk)},
    )

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Select a contest in the filters to load year-by-problem completion coverage." in response_html
    assert 'id="chart-completion-progress-contest-heatmap"' not in response_html
```

- [ ] **Step 6: Run the template tests and verify they pass**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_analytics_contest_heatmap_uses_selected_user inspinia/pages/tests.py::test_completion_progress_contest_heatmap_prompts_for_contest -q
```

Expected: PASS.

- [ ] **Step 7: Commit the template card**

```bash
git add inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
git commit -m "feat: render completion progress contest heatmap card"
```

---

### Task 5: Add Heatmap JavaScript Rendering

**Files:**
- Modify: `inspinia/templates/pages/completion-progress-analytics.html`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Read the heatmap JSON element in JavaScript**

At the top of the existing script, after `tableDataEl`, add:

```javascript
  var contestHeatmapDataEl = document.getElementById("completion-progress-contest-heatmap-data");
```

- [ ] **Step 2: Add the contest heatmap renderer**

Place this function after the existing `renderHeatmap` function:

```javascript
  function renderContestHeatmap() {
    var dataEl = contestHeatmapDataEl;
    var chartEl = document.getElementById("chart-completion-progress-contest-heatmap");
    if (!dataEl || !chartEl || typeof ApexCharts === "undefined") return;

    var payload = JSON.parse(dataEl.textContent || "{}");
    if (!payload.series || !payload.series.length) return;

    function pointFromOptions(opts) {
      if (!opts || opts.seriesIndex < 0 || opts.dataPointIndex < 0) return null;
      var row = payload.series[opts.seriesIndex];
      if (!row || !row.data) return null;
      return row.data[opts.dataPointIndex] || null;
    }

    function hasLinkedPoints() {
      for (var rowIndex = 0; rowIndex < payload.series.length; rowIndex += 1) {
        var row = payload.series[rowIndex];
        var data = row && row.data ? row.data : [];
        for (var pointIndex = 0; pointIndex < data.length; pointIndex += 1) {
          if (data[pointIndex].solution_url) return true;
        }
      }
      return false;
    }

    function openProblemSolution(opts) {
      var point = pointFromOptions(opts);
      if (!point || !point.solution_url) return;
      window.location.assign(point.solution_url);
    }

    var pointCount = payload.series[0] && payload.series[0].data ? payload.series[0].data.length : 0;
    chartEl.style.minWidth = String(Math.max(480, pointCount * 48 + 96)) + "px";

    if (hasLinkedPoints()) {
      chartEl.classList.add("completion-progress-contest-heatmap-clickable");
    }

    new ApexCharts(chartEl, {
      chart: {
        type: "heatmap",
        height: Math.max(260, payload.series.length * 30 + 72),
        toolbar: { show: false },
        fontFamily: "inherit",
        events: {
          dataPointSelection: function (_event, _chartContext, opts) {
            openProblemSolution(opts);
          }
        }
      },
      series: payload.series,
      dataLabels: {
        enabled: true,
        style: {
          fontSize: "9px",
          fontWeight: 700,
          colors: ["#11203b"]
        },
        formatter: function (_value, opts) {
          var point = opts.w.config.series[opts.seriesIndex].data[opts.dataPointIndex];
          return point.display || "";
        }
      },
      stroke: {
        width: 1,
        colors: ["rgba(255,255,255,0.72)"]
      },
      plotOptions: {
        heatmap: {
          radius: 3,
          enableShades: false,
          useFillColorAsStroke: false,
          colorScale: {
            ranges: [
              { from: 0, to: 0, color: "#d6d9e0", name: "Empty" },
              { from: 1, to: 1, color: "#e25563", name: "Unsolved" },
              { from: 2, to: 2, color: "#f1b44c", name: "Partial" },
              { from: 3, to: 3, color: "#2fbf71", name: "Solved" }
            ]
          }
        }
      },
      legend: { show: false },
      xaxis: {
        type: "category",
        position: "top",
        labels: {
          rotate: 0,
          style: { fontSize: "10px" }
        }
      },
      yaxis: {
        labels: {
          maxWidth: 72,
          style: { fontSize: "10px" }
        }
      },
      tooltip: {
        custom: function (opts) {
          var point = opts.w.config.series[opts.seriesIndex].data[opts.dataPointIndex];
          return '<div class="apexcharts-theme-light p-2 fs-xs">' + escapeHtml(point.title || "") + "</div>";
        }
      },
      grid: {
        borderColor: "rgba(108,117,125,0.15)"
      }
    }).render();
  }
```

- [ ] **Step 3: Call the contest heatmap renderer**

After `renderHeatmap("#chart-completion-progress-topic-mohs", charts.topicMohsHeatmap);`, add:

```javascript
  renderContestHeatmap();
```

- [ ] **Step 4: Add JavaScript rendering assertions**

Extend `test_completion_progress_analytics_contest_heatmap_uses_selected_user` with:

```python
    assert "renderContestHeatmap();" in response_html
    assert "dataPointSelection" in response_html
    assert "point.solution_url" in response_html
```

- [ ] **Step 5: Run the JavaScript template assertion test**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_analytics_contest_heatmap_uses_selected_user -q
```

Expected: PASS.

- [ ] **Step 6: Commit the JavaScript**

```bash
git add inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
git commit -m "feat: render completion progress contest heatmap chart"
```

---

### Task 6: Final Verification

**Files:**
- Verify: `inspinia/pages/completion_progress.py`
- Verify: `inspinia/pages/views.py`
- Verify: `inspinia/templates/pages/completion-progress-analytics.html`
- Verify: `inspinia/pages/tests.py`

- [ ] **Step 1: Run all focused completion progress tests**

Run:

```bash
uv run pytest inspinia/pages/tests.py -q -k "completion_progress"
```

Expected: PASS.

- [ ] **Step 2: Run page app lint**

Run:

```bash
uv run ruff check inspinia/pages
```

Expected: PASS.

- [ ] **Step 3: Run Django system checks**

Run:

```bash
uv run python manage.py check
```

Expected: PASS.

- [ ] **Step 4: Visually verify the page**

Start the Django development server with the repository's normal command if one is available. If the project uses `uv run python manage.py runserver`, run:

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

Open `/dashboard/completion-progress/?contest=APMO&range=all` in the in-app browser while logged in as a user with completion data. Confirm:

- The `Completion heatmap` card appears before `Filtered completion rows`.
- The legend is readable in the current theme.
- The heatmap is not blank.
- The table still initializes.
- The page remains horizontally usable on a narrow viewport because the heatmap scrolls inside its card.

- [ ] **Step 5: Review the final diff**

Run:

```bash
git diff --stat HEAD
git diff HEAD -- inspinia/pages/completion_progress.py inspinia/pages/views.py inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
```

Expected: only the heatmap helper, view context, template card/renderer, and related tests changed.

- [ ] **Step 6: Commit final verification adjustments**

If Step 4 or Step 5 leads to small fixes, stage and commit those exact files:

```bash
git add inspinia/pages/completion_progress.py inspinia/pages/views.py inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
git commit -m "fix: polish completion progress heatmap"
```

If there are no fixes after Task 5, do not create an empty commit.
