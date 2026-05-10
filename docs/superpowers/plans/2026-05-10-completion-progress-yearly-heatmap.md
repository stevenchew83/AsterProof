# Completion Progress Yearly Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub-like yearly daily completion heatmap to `/dashboard/completion-progress/` and `/dashboard/my-progress/`, positioned immediately before the existing contest `Completion heatmap` card.

**Architecture:** Add a small payload helper in `inspinia/pages/completion_progress.py` that converts the already filtered completion rows into a rolling 365-day, week-column heatmap. Wire that payload through `_render_completion_progress_analytics`, render the grid with page-local Bootstrap/Inspinia-aligned CSS in `completion-progress-analytics.html`, and initialize Bootstrap tooltips for accessible day-level detail.

**Tech Stack:** Django, Python `date` / `timedelta` / `Counter`, Bootstrap 5 / Inspinia cards and utilities, Tabler icons, page-local CSS/JS, pytest.

---

## Context And Design Direction

**Existing system:** This is an established Inspinia 4.x / Bootstrap 5 dashboard. The page extends `layouts/vertical.html`, uses `container-fluid`, `row g-3`, `card`, `header-title`, `text-muted fs-xs`, Bootstrap badges/alerts, Tabler `ti` icons, page-local CSS, ApexCharts, and DataTables.

**Visual thesis:** A dense, GitHub-familiar activity strip that feels native to the existing Inspinia dashboard: compact square cells, restrained green intensity, muted labels, and no new visual system.

**Content plan:** Keep the existing page order through filters, KPI tiles, and charts; insert one full-width `Yearly completion heatmap` card immediately before the current `Completion heatmap` contest grid; keep the existing contest heatmap and filtered rows table unchanged below it.

**Interaction plan:** Cells expose Bootstrap tooltips with exact day/count labels, keyboard focus via `tabindex="0"`, and the current window end date is outlined. No new chart library is needed.

## Product Decisions

- The new heatmap uses the same `filtered_rows` collection as the current charts and stats. That means user, range, contest, topic, MOHS, solution status, and search filters all apply consistently.
- The heatmap is a rolling 365-day window ending at `completion_progress_date_range.end_date` when available, otherwise `today`. For the shared URL with `range=all`, the end date is `today`, so the grid shows the latest year of exact-date completions.
- Rows with `completion_date=None` are excluded from the heatmap cells but counted in `missing_date_total` for the card copy.
- No route, permission, model, migration, global SCSS, or compiled asset changes are needed.

## File Structure

- Modify: `inspinia/pages/completion_progress.py`
  - Add `completion_progress_yearly_heatmap_payload`.
  - Add `_completion_progress_yearly_heatmap_level`.
  - Reuse existing `CompletionProgressRow` data and `Counter`.
- Modify: `inspinia/pages/views.py`
  - Import the new helper.
  - Add `completion_progress_yearly_heatmap` to the shared completion progress context.
- Modify: `inspinia/templates/pages/completion-progress-analytics.html`
  - Add page-local CSS for the yearly grid.
  - Render the new card before the existing `Completion heatmap` card.
  - Initialize Bootstrap tooltips for the new cells.
- Modify: `inspinia/pages/tests.py`
  - Import the new helper plus `normalize_completion_progress_rows`.
  - Add direct helper coverage.
  - Add view/template ordering and scoping assertions.

---

### Task 1: Add The Yearly Heatmap Payload

**Files:**
- Modify: `inspinia/pages/completion_progress.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Update test imports**

In `inspinia/pages/tests.py`, replace the existing single completion progress import:

```python
from inspinia.pages.completion_progress import completion_progress_contest_heatmap_payload
```

with:

```python
from inspinia.pages.completion_progress import completion_progress_contest_heatmap_payload
from inspinia.pages.completion_progress import completion_progress_yearly_heatmap_payload
from inspinia.pages.completion_progress import normalize_completion_progress_rows
```

- [ ] **Step 2: Add direct helper test**

Place this test after `test_completion_progress_contest_heatmap_payload_requires_contest_and_user`:

```python
def test_completion_progress_yearly_heatmap_payload_counts_exact_dates_in_window():
    user = UserFactory()
    end_date = date(2026, 5, 10)
    active_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=10,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )
    second_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=15,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2026 P2",
    )
    old_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=20,
        contest="BMO",
        problem="P3",
        contest_year_problem="BMO 2025 P3",
    )
    missing_date_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="COMB",
        mohs=25,
        contest="EGMO",
        problem="P4",
        contest_year_problem="EGMO 2026 P4",
    )
    completions = [
        UserProblemCompletion.objects.create(user=user, problem=active_problem, completion_date=end_date),
        UserProblemCompletion.objects.create(user=user, problem=second_problem, completion_date=end_date),
        UserProblemCompletion.objects.create(user=user, problem=old_problem, completion_date=date(2025, 4, 1)),
        UserProblemCompletion.objects.create(user=user, problem=missing_date_problem, completion_date=None),
    ]
    rows = normalize_completion_progress_rows(completions)

    payload = completion_progress_yearly_heatmap_payload(rows, end_date=end_date)

    assert payload["start_label"] == "2025-05-11"
    assert payload["end_label"] == "2026-05-10"
    assert payload["exact_total"] == 2
    assert payload["missing_date_total"] == 1
    assert payload["max_count"] == 2
    end_cell = next(
        day
        for week in payload["weeks"]
        for day in week["days"]
        if day["date"] == "2026-05-10"
    )
    assert end_cell["count"] == 2
    assert end_cell["level"] == 4
    assert end_cell["is_today"] is True
    outside_cell = payload["weeks"][0]["days"][0]
    assert outside_cell["is_blank"] is True
    assert outside_cell["level"] == -1
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_yearly_heatmap_payload_counts_exact_dates_in_window -q
```

Expected: FAIL because `completion_progress_yearly_heatmap_payload` is not importable yet.

- [ ] **Step 4: Add the helper implementation**

In `inspinia/pages/completion_progress.py`, place this code after `completion_progress_charts_payload` and before `completion_progress_contest_heatmap_payload`:

```python
def completion_progress_yearly_heatmap_payload(
    rows: Iterable[CompletionProgressRow],
    *,
    end_date: date,
    day_window: int = 365,
) -> dict[str, object]:
    row_list = list(rows)
    start_date = end_date - timedelta(days=day_window - 1)
    grid_start = start_date - timedelta(days=start_date.weekday())
    grid_end = end_date + timedelta(days=(6 - end_date.weekday()))
    exact_counts_by_day = Counter(
        row.completion_date
        for row in row_list
        if row.completion_date is not None and start_date <= row.completion_date <= end_date
    )
    max_count = max(exact_counts_by_day.values(), default=0)
    weeks: list[dict[str, object]] = []
    current_day = grid_start
    first_visible_month_labeled = False

    while current_day <= grid_end:
        week_days: list[dict[str, object]] = []
        week_dates = [current_day + timedelta(days=offset) for offset in range(7)]
        in_range_week_days = [
            week_day for week_day in week_dates if start_date <= week_day <= end_date
        ]
        month_label = ""
        if in_range_week_days:
            if not first_visible_month_labeled:
                month_label = in_range_week_days[0].strftime("%b")
                first_visible_month_labeled = True
            else:
                month_start_day = next(
                    (week_day for week_day in in_range_week_days if week_day.day == 1),
                    None,
                )
                if month_start_day is not None:
                    month_label = month_start_day.strftime("%b")

        for week_day in week_dates:
            in_range = start_date <= week_day <= end_date
            count = exact_counts_by_day.get(week_day, 0) if in_range else 0
            title = ""
            if in_range:
                title = (
                    f"{week_day.strftime('%a, %d %b %Y')}: "
                    f"{count} completion{'s' if count != 1 else ''}"
                )
            week_days.append(
                {
                    "count": count,
                    "date": week_day.isoformat(),
                    "display_date": week_day.isoformat(),
                    "in_range": in_range,
                    "is_blank": not in_range,
                    "is_today": week_day == end_date,
                    "label": week_day.strftime("%a"),
                    "level": _completion_progress_yearly_heatmap_level(count, max_count)
                    if in_range
                    else -1,
                    "title": title,
                    "value": count if in_range else None,
                },
            )
        weeks.append({"days": week_days, "month_label": month_label})
        current_day += timedelta(days=7)

    return {
        "day_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "end_label": end_date.isoformat(),
        "exact_total": sum(exact_counts_by_day.values()),
        "max_count": max_count,
        "missing_date_total": sum(1 for row in row_list if row.completion_date is None),
        "start_label": start_date.isoformat(),
        "total_in_window": sum(exact_counts_by_day.values()),
        "weeks": weeks,
    }


def _completion_progress_yearly_heatmap_level(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    return min(4, max(1, -(-count * 4 // max_count)))
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_yearly_heatmap_payload_counts_exact_dates_in_window -q
```

Expected: PASS.

- [ ] **Step 6: Run ruff on touched Python files**

Run:

```bash
uv run ruff check inspinia/pages/completion_progress.py inspinia/pages/tests.py
```

Expected: PASS.

- [ ] **Step 7: Commit payload work**

```bash
git add inspinia/pages/completion_progress.py inspinia/pages/tests.py
git commit -m "feat: add completion progress yearly heatmap payload"
```

---

### Task 2: Wire The Payload Into The Completion Progress View

**Files:**
- Modify: `inspinia/pages/views.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Import the helper**

In `inspinia/pages/views.py`, add this import near the other `completion_progress` imports:

```python
from inspinia.pages.completion_progress import completion_progress_yearly_heatmap_payload
```

- [ ] **Step 2: Add context**

Inside `_render_completion_progress_analytics`, add this context entry immediately after `completion_progress_date_range`:

```python
"completion_progress_yearly_heatmap": completion_progress_yearly_heatmap_payload(
    filtered_rows,
    end_date=date_range.end_date or today,
),
```

The surrounding block should read:

```python
"completion_progress_date_range": date_range,
"completion_progress_yearly_heatmap": completion_progress_yearly_heatmap_payload(
    filtered_rows,
    end_date=date_range.end_date or today,
),
"completion_progress_filter_options": completion_progress_filter_options(date_scoped_rows),
```

- [ ] **Step 3: Add view scoping assertions**

Extend `test_completion_progress_analytics_renders_admin_dashboard` after the existing `chart_payload` assertions:

```python
    yearly_heatmap = response.context["completion_progress_yearly_heatmap"]
    assert yearly_heatmap["end_label"] == today.isoformat()
    assert yearly_heatmap["exact_total"] == 2
    assert yearly_heatmap["missing_date_total"] == 1
    today_cell = next(
        day
        for week in yearly_heatmap["weeks"]
        for day in week["days"]
        if day["date"] == today.isoformat()
    )
    assert today_cell["count"] == 1
```

Extend `test_completion_progress_analytics_filters_by_completion_date_not_updated_at` after the chart assertion:

```python
    assert response.context["completion_progress_yearly_heatmap"]["exact_total"] == 1
```

Extend `test_my_completion_progress_analytics_renders_only_signed_in_user_rows` after the `solutionStatus` assertion:

```python
    assert response.context["completion_progress_yearly_heatmap"]["exact_total"] == 1
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_analytics_renders_admin_dashboard inspinia/pages/tests.py::test_completion_progress_analytics_filters_by_completion_date_not_updated_at inspinia/pages/tests.py::test_my_completion_progress_analytics_renders_only_signed_in_user_rows -q
```

Expected: PASS.

- [ ] **Step 5: Commit view wiring**

```bash
git add inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "feat: expose completion progress yearly heatmap"
```

---

### Task 3: Render The Yearly Heatmap Card Before The Existing Completion Heatmap

**Files:**
- Modify: `inspinia/templates/pages/completion-progress-analytics.html`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add page-local CSS**

In `inspinia/templates/pages/completion-progress-analytics.html`, add this CSS after `.completion-progress-chart`:

```css
  .completion-progress-yearly-heatmap-wrap {
    overflow-x: auto;
    padding-bottom: 0.35rem;
  }

  .completion-progress-yearly-heatmap-canvas {
    display: inline-block;
    min-width: max-content;
  }

  .completion-progress-yearly-heatmap {
    --completion-progress-yearly-cell-size: 0.86rem;
    --completion-progress-yearly-gap: 0.22rem;
    --completion-progress-yearly-weekday-width: 2rem;
    --completion-progress-yearly-border: rgba(27, 31, 35, 0.06);
    --completion-progress-yearly-empty: #ebedf0;
    --completion-progress-yearly-level-1: #9be9a8;
    --completion-progress-yearly-level-2: #40c463;
    --completion-progress-yearly-level-3: #30a14e;
    --completion-progress-yearly-level-4: #216e39;
  }

  [data-bs-theme="dark"] .completion-progress-yearly-heatmap {
    --completion-progress-yearly-border: rgba(240, 246, 252, 0.08);
    --completion-progress-yearly-empty: #161b22;
    --completion-progress-yearly-level-1: #0e4429;
    --completion-progress-yearly-level-2: #006d32;
    --completion-progress-yearly-level-3: #26a641;
    --completion-progress-yearly-level-4: #39d353;
  }

  .completion-progress-yearly-months {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: var(--completion-progress-yearly-cell-size);
    gap: var(--completion-progress-yearly-gap);
    margin-left: calc(var(--completion-progress-yearly-weekday-width) + 0.45rem);
    margin-bottom: 0.45rem;
    color: var(--ins-secondary-color);
    font-size: 0.72rem;
    line-height: 1;
  }

  .completion-progress-yearly-months > span {
    min-width: var(--completion-progress-yearly-cell-size);
    white-space: nowrap;
  }

  .completion-progress-yearly-body {
    display: flex;
    align-items: flex-start;
    gap: 0.45rem;
  }

  .completion-progress-yearly-weekdays {
    display: grid;
    grid-template-rows: repeat(7, var(--completion-progress-yearly-cell-size));
    gap: var(--completion-progress-yearly-gap);
    width: var(--completion-progress-yearly-weekday-width);
    color: var(--ins-secondary-color);
    font-size: 0.72rem;
    line-height: var(--completion-progress-yearly-cell-size);
    text-align: right;
  }

  .completion-progress-yearly-grid {
    display: grid;
    grid-template-rows: repeat(7, var(--completion-progress-yearly-cell-size));
    grid-auto-flow: column;
    grid-auto-columns: var(--completion-progress-yearly-cell-size);
    gap: var(--completion-progress-yearly-gap);
  }

  .completion-progress-yearly-cell {
    display: block;
    width: var(--completion-progress-yearly-cell-size);
    height: var(--completion-progress-yearly-cell-size);
    border-radius: 0.18rem;
    border: 1px solid var(--completion-progress-yearly-border);
    background: var(--completion-progress-yearly-empty);
  }

  .completion-progress-yearly-cell[data-bs-toggle="tooltip"] {
    cursor: pointer;
  }

  .completion-progress-yearly-cell.is-outside {
    border-color: transparent;
    background: transparent;
  }

  .completion-progress-yearly-cell.is-today {
    outline: 1px solid rgba(9, 105, 218, 0.55);
    outline-offset: 1px;
  }

  .completion-progress-yearly-cell.level-0,
  .completion-progress-yearly-legend-swatch.level-0 {
    background: var(--completion-progress-yearly-empty);
  }

  .completion-progress-yearly-cell.level-1,
  .completion-progress-yearly-legend-swatch.level-1 {
    background: var(--completion-progress-yearly-level-1);
  }

  .completion-progress-yearly-cell.level-2,
  .completion-progress-yearly-legend-swatch.level-2 {
    background: var(--completion-progress-yearly-level-2);
  }

  .completion-progress-yearly-cell.level-3,
  .completion-progress-yearly-legend-swatch.level-3 {
    background: var(--completion-progress-yearly-level-3);
  }

  .completion-progress-yearly-cell.level-4,
  .completion-progress-yearly-legend-swatch.level-4 {
    background: var(--completion-progress-yearly-level-4);
  }

  .completion-progress-yearly-legend {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--ins-secondary-color);
    font-size: 0.82rem;
    margin-top: 0.9rem;
  }

  .completion-progress-yearly-legend-scale {
    display: inline-flex;
    gap: var(--completion-progress-yearly-gap);
  }

  .completion-progress-yearly-legend-swatch {
    width: var(--completion-progress-yearly-cell-size);
    height: var(--completion-progress-yearly-cell-size);
    border-radius: 0.18rem;
    border: 1px solid var(--completion-progress-yearly-border);
    display: inline-block;
  }
```

- [ ] **Step 2: Insert the heatmap card before the contest completion heatmap**

In `completion-progress-analytics.html`, insert this block immediately before the existing row whose header is `<h4 class="header-title mb-0">Completion heatmap</h4>`:

```django
  <div class="row g-3 mt-0">
    <div class="col-12">
      <div class="card">
        <div class="card-header border-bottom d-flex flex-wrap align-items-center gap-2">
          <div class="flex-grow-1">
            <h4 class="header-title mb-0">Yearly completion heatmap</h4>
            <p class="text-muted fs-xs mb-0">GitHub-style daily solve density for the current filtered row set. Unknown-date rows stay out of the grid.</p>
          </div>
          <span class="badge text-bg-light">
            {{ completion_progress_yearly_heatmap.start_label }} to {{ completion_progress_yearly_heatmap.end_label }}
          </span>
        </div>
        <div class="card-body">
          {% if completion_progress_yearly_heatmap.exact_total == 0 %}
          <div class="alert alert-info py-2 mb-3" role="alert">
            No exact completion dates match the current filters in this yearly window.
            {% if completion_progress_yearly_heatmap.missing_date_total %}
            {{ completion_progress_yearly_heatmap.missing_date_total }} unknown-date row{{ completion_progress_yearly_heatmap.missing_date_total|pluralize }} remain visible in the table.
            {% endif %}
          </div>
          {% endif %}
          <div class="completion-progress-yearly-heatmap">
            <div class="completion-progress-yearly-heatmap-wrap">
              <div class="completion-progress-yearly-heatmap-canvas">
                <div class="completion-progress-yearly-months" aria-hidden="true">
                  {% for week in completion_progress_yearly_heatmap.weeks %}
                  <span>{{ week.month_label }}</span>
                  {% endfor %}
                </div>
                <div class="completion-progress-yearly-body">
                  <div class="completion-progress-yearly-weekdays" aria-hidden="true">
                    {% for day_label in completion_progress_yearly_heatmap.day_labels %}
                    <span>{{ day_label }}</span>
                    {% endfor %}
                  </div>
                  <div class="completion-progress-yearly-grid" role="img" aria-label="Yearly completion heatmap">
                    {% for week in completion_progress_yearly_heatmap.weeks %}
                    {% for day in week.days %}
                    <span
                      class="completion-progress-yearly-cell{% if day.is_blank %} is-outside{% else %} level-{{ day.level }}{% endif %}{% if day.is_today %} is-today{% endif %}"
                      {% if day.is_blank %}
                      aria-hidden="true"
                      {% else %}
                      data-bs-toggle="tooltip"
                      data-bs-placement="top"
                      data-bs-title="{{ day.title }}"
                      title="{{ day.title }}"
                      aria-label="{{ day.title }}"
                      tabindex="0"
                      {% endif %}
                    ></span>
                    {% endfor %}
                    {% endfor %}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="completion-progress-yearly-legend">
            <span>Less</span>
            <span class="completion-progress-yearly-legend-scale" aria-hidden="true">
              <span class="completion-progress-yearly-legend-swatch level-0"></span>
              <span class="completion-progress-yearly-legend-swatch level-1"></span>
              <span class="completion-progress-yearly-legend-swatch level-2"></span>
              <span class="completion-progress-yearly-legend-swatch level-3"></span>
              <span class="completion-progress-yearly-legend-swatch level-4"></span>
            </span>
            <span>More</span>
          </div>
          <p class="text-muted fs-xs mt-3 mb-0">
            {{ completion_progress_yearly_heatmap.exact_total }} exact-date completion{{ completion_progress_yearly_heatmap.exact_total|pluralize }} shown.
            {% if completion_progress_yearly_heatmap.missing_date_total %}
            {{ completion_progress_yearly_heatmap.missing_date_total }} unknown-date row{{ completion_progress_yearly_heatmap.missing_date_total|pluralize }} excluded from the grid.
            {% endif %}
          </p>
        </div>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Initialize tooltips**

In the existing page script, add this helper after `hasValues`:

```javascript
  function initCompletionProgressTooltips() {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      window.bootstrap.Tooltip.getOrCreateInstance(el);
    });
  }
```

Then call it after `renderContestHeatmap();`:

```javascript
  renderContestHeatmap();
  initCompletionProgressTooltips();
  renderDonut("#chart-completion-progress-solutions", charts.solutionStatus);
```

- [ ] **Step 4: Add template assertions**

Extend `test_completion_progress_analytics_renders_admin_dashboard` after `response_html = response.content.decode("utf-8")`:

```python
    assert "Yearly completion heatmap" in response_html
    assert 'class="completion-progress-yearly-grid"' in response_html
    assert 'data-bs-toggle="tooltip"' in response_html
    assert "initCompletionProgressTooltips();" in response_html
    assert response_html.index("Yearly completion heatmap") < response_html.index("Completion heatmap")
    assert response_html.index("Completion heatmap") < response_html.index("Filtered completion rows")
```

Extend `test_completion_progress_contest_heatmap_prompts_for_contest` after `response_html = response.content.decode("utf-8")`:

```python
    assert "Yearly completion heatmap" in response_html
```

- [ ] **Step 5: Run focused rendering tests**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_completion_progress_analytics_renders_admin_dashboard inspinia/pages/tests.py::test_completion_progress_contest_heatmap_prompts_for_contest -q
```

Expected: PASS.

- [ ] **Step 6: Commit template rendering**

```bash
git add inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
git commit -m "feat: render completion progress yearly heatmap"
```

---

### Task 4: Final Verification

**Files:**
- Verify: `inspinia/pages/completion_progress.py`
- Verify: `inspinia/pages/views.py`
- Verify: `inspinia/templates/pages/completion-progress-analytics.html`
- Verify: `inspinia/pages/tests.py`

- [ ] **Step 1: Run completion progress tests**

Run:

```bash
uv run pytest inspinia/pages/tests.py -q -k "completion_progress"
```

Expected: PASS.

- [ ] **Step 2: Run ruff**

Run:

```bash
uv run ruff check inspinia/pages/completion_progress.py inspinia/pages/views.py inspinia/pages/tests.py
```

Expected: PASS.

- [ ] **Step 3: Run Django system check**

Run:

```bash
uv run python manage.py check
```

Expected: PASS.

- [ ] **Step 4: Verify visually**

Open this page in the in-app browser while logged in with access to the target user:

```text
http://18.142.249.181/dashboard/completion-progress/?user=7&range=all&start=2026-04-11&end=2026-05-10&contest=&topic=&mohs_min=&mohs_max=&solution_status=&q=
```

Confirm:

- The new `Yearly completion heatmap` card appears before the existing `Completion heatmap` card.
- The grid scrolls horizontally on narrow screens instead of widening the page.
- Tooltip text appears on day cells.
- Unknown-date copy only appears when the filtered row set includes unknown-date rows.
- The existing contest `Completion heatmap` and `Filtered completion rows` table still render.

- [ ] **Step 5: Review final diff**

Run:

```bash
git diff HEAD -- inspinia/pages/completion_progress.py inspinia/pages/views.py inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
```

Expected: only the yearly heatmap helper, context wiring, template card/CSS/tooltips, and related tests changed.

- [ ] **Step 6: Commit final polish if needed**

If Step 5 shows any small polish edits after the previous task commits, commit them:

```bash
git add inspinia/pages/completion_progress.py inspinia/pages/views.py inspinia/templates/pages/completion-progress-analytics.html inspinia/pages/tests.py
git commit -m "fix: polish completion progress yearly heatmap"
```

---

## Self-Review

**Spec coverage:** The plan adds a GitHub-like yearly daily completion grid before the existing `Completion heatmap` card on the shared completion progress template. Because both admin selected-user and personal progress pages share `_render_completion_progress_analytics`, both routes are covered without route duplication.

**Placeholder scan:** The implementation steps include concrete file paths, test functions, helper code, template markup, JavaScript, commands, and expected outcomes.

**Risk check:** The largest risk is visual clutter from a wide day-grid inside an already chart-heavy dashboard. The plan controls this with a single full-width card, compact cells, horizontal scrolling, and existing Inspinia card/header typography.
