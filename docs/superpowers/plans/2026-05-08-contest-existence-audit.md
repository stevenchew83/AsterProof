# Contest Existence Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only admin page that parses year-prefixed contest headers from pasted scrape text and checks exact contest-year existence in both statement and analytics tables.

**Architecture:** Put parsing, checking, status summaries, suggestions, and TSV generation in a focused helper module under `inspinia/pages/`. Keep the Django view thin: validate form input, call the helper, show messages, and render the existing Inspinia dashboard shell. Add the new tool beside existing admin utilities and cover behavior through parser/helper tests plus view/template smoke tests.

**Tech Stack:** Django 5, Python dataclasses/typed dicts, `difflib.SequenceMatcher`, Bootstrap 5/Inspinia templates, Tabler icons, `uv run pytest`, `uv run ruff`.

---

## File Map

- Create `inspinia/pages/contest_existence_audit.py`
  - Owns pure parsing, duplicate-header normalization, database inventory checks, suggestion ranking, summary counts, and TSV output.
- Modify `inspinia/pages/forms.py`
  - Adds `ContestExistenceAuditForm`, matching existing textarea form patterns.
- Modify `inspinia/pages/views.py`
  - Imports the form/helper and adds `contest_existence_audit_view`.
- Modify `inspinia/pages/urls.py`
  - Imports the new view and registers `/tools/contest-existence-audit/`.
- Create `inspinia/templates/pages/contest-existence-audit.html`
  - Renders paste form, summary KPIs, result table, TSV export, and clear/copy JavaScript.
- Modify `inspinia/templates/partials/sidenav.html`
  - Adds a Utilities link near `Handle parser`.
- Modify `inspinia/pages/tests.py`
  - Adds parser/helper tests, access tests, view POST test, and sidebar ordering assertion.

## Task 1: Parser And Checker Helper

**Files:**
- Create: `inspinia/pages/contest_existence_audit.py`
- Modify: `inspinia/pages/tests.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add failing parser and checker tests**

Add this import block to `inspinia/pages/tests.py` near the existing pages helper imports:

```python
from inspinia.pages.contest_existence_audit import ContestExistenceAuditValidationError
from inspinia.pages.contest_existence_audit import build_contest_existence_audit_payload
from inspinia.pages.contest_existence_audit import parse_contest_existence_audit_text
```

Add these tests near the existing handle summary parser tests:

```python
def test_contest_existence_audit_parser_reads_year_prefixed_contest_headers():
    parsed_headers = parse_contest_existence_audit_text(
        "\n".join(
            [
                "2026 Contests3",
                " 2026 Abelkonkurransen Finale",
                "1a\tDetermine all pairs of positive integers.",
                "RANDOM__USER",
                "view topic",
                " 2026 AIMEAIME 2026",
                "I",
                "February 5",
                "1\tPatrick started walking.",
                " 2026 All-Russian OlympiadAll-Russian Olympiad 2026",
                "Grade 9",
                "9.1\tInitially, there are 75 candies.",
                " 2026 Austrian MO National Competition2026 Austrian MO National Competition",
                "Preliminary round (May 2, 2026)",
                "1\tProve that for all integers.",
                " 2026 Abelkonkurransen Finale",
            ]
        )
    )

    assert [
        (
            header.year,
            header.contest_name,
            header.first_line_number,
            header.occurrence_count,
        )
        for header in parsed_headers
    ] == [
        (2026, "Abelkonkurransen Finale", 2, 2),
        (2026, "AIME", 6, 1),
        (2026, "All-Russian Olympiad", 10, 1),
        (2026, "Austrian MO National Competition", 13, 1),
    ]


def test_contest_existence_audit_parser_rejects_text_without_contest_headers():
    with pytest.raises(
        ContestExistenceAuditValidationError,
        match="No year-prefixed contest headers were detected.",
    ):
        parse_contest_existence_audit_text(
            "\n".join(
                [
                    "Day 1",
                    "1\tLet ABC be a triangle.",
                    "RANDOM__USER",
                    "view topic",
                ]
            )
        )


def test_contest_existence_audit_payload_checks_both_tables_and_suggests_same_year_names():
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="Canadian National Olympiad",
        problem="P1",
        contest_year_problem="Canadian National Olympiad 2026 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=7,
        contest="All-Russian Olympiad",
        problem="P1",
        contest_year_problem="All-Russian Olympiad 2026 P1",
    )
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Canadian National Olympiad",
        day_label="",
        problem_number=1,
        problem_code="P1",
        statement_latex="Canadian statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="AIME",
        day_label="",
        problem_number=1,
        problem_code="P1",
        statement_latex="AIME statement",
    )

    parsed_headers = parse_contest_existence_audit_text(
        "\n".join(
            [
                "2026 Canadian National Olympiad",
                "2026 AIMEAIME 2026",
                "2026 All-Russian OlympiadAll-Russian Olympiad 2026",
                "2026 Abelkonkurransen Finale",
            ]
        )
    )
    payload = build_contest_existence_audit_payload(parsed_headers)
    rows_by_contest = {row["contest_name"]: row for row in payload["rows"]}

    assert payload["row_count"] == 4
    assert payload["summary"] == {
        "analytics_only_total": 1,
        "both_found_total": 1,
        "missing_total": 1,
        "partial_total": 2,
        "parsed_total": 4,
        "statements_only_total": 1,
    }
    assert rows_by_contest["Canadian National Olympiad"]["overall_status"] == "both_found"
    assert rows_by_contest["Canadian National Olympiad"]["statement_count"] == 1
    assert rows_by_contest["Canadian National Olympiad"]["analytics_count"] == 1
    assert rows_by_contest["AIME"]["overall_status"] == "statements_only"
    assert rows_by_contest["AIME"]["statement_count"] == 1
    assert rows_by_contest["AIME"]["analytics_count"] == 0
    assert rows_by_contest["All-Russian Olympiad"]["overall_status"] == "analytics_only"
    assert rows_by_contest["All-Russian Olympiad"]["statement_count"] == 0
    assert rows_by_contest["All-Russian Olympiad"]["analytics_count"] == 1
    assert rows_by_contest["Abelkonkurransen Finale"]["overall_status"] == "missing"
    assert rows_by_contest["Abelkonkurransen Finale"]["suggestions"]
    assert payload["export_tsv"].splitlines()[0] == (
        "LINE\tYEAR\tCONTEST\tOCCURRENCES\tSTATEMENT STATUS\tSTATEMENT COUNT\t"
        "ANALYTICS STATUS\tANALYTICS COUNT\tOVERALL STATUS\tSUGGESTIONS"
    )
```

- [ ] **Step 2: Run parser/checker tests to verify they fail**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_reads_year_prefixed_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_rejects_text_without_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_payload_checks_both_tables_and_suggests_same_year_names \
  -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'inspinia.pages.contest_existence_audit'`.

- [ ] **Step 3: Create the helper module**

Create `inspinia/pages/contest_existence_audit.py` with this content:

```python
from __future__ import annotations

import csv
import re
from collections import OrderedDict
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import StringIO
from typing import TypedDict

from django.db.models import Count

from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord


class ContestExistenceAuditValidationError(ValueError):
    """Raised when pasted contest-audit text cannot be parsed."""


@dataclass(frozen=True)
class ParsedContestHeader:
    year: int
    contest_name: str
    first_line_number: int
    occurrence_count: int


class ContestExistenceAuditRow(TypedDict):
    analytics_count: int
    analytics_status: str
    contest_name: str
    first_line_number: int
    occurrence_count: int
    overall_status: str
    statement_count: int
    statement_status: str
    suggestions: list[str]
    suggestions_label: str
    year: int


class ContestExistenceAuditPayload(TypedDict):
    export_tsv: str
    row_count: int
    rows: list[ContestExistenceAuditRow]
    summary: dict[str, int]


YEAR_HEADER_RE = re.compile(r"^(?P<year>\d{4})\s+(?P<title>.+?)\s*$")
TRAILING_YEAR_RE = re.compile(r"\s+\d{4}\s*$")
GENERIC_HEADER_WORDS = {"contest", "contests"}
SUGGESTION_LIMIT = 3
SUGGESTION_MIN_RATIO = 0.35


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _is_generic_header(title: str) -> bool:
    letters_only = re.sub(r"[^a-z]", "", title.lower())
    return letters_only in GENERIC_HEADER_WORDS


def _dedupe_concatenated_title(title: str) -> str:
    for split_index in range(1, len(title)):
        prefix = title[:split_index].strip()
        suffix = title[split_index:].strip()
        if not prefix or not suffix:
            continue
        if suffix == prefix:
            return prefix
        if re.fullmatch(rf"\d{{4}}\s*{re.escape(prefix)}", suffix):
            return prefix
    return title


def _clean_parsed_contest_name(raw_title: str) -> str:
    title = _collapse_whitespace(raw_title)
    title = TRAILING_YEAR_RE.sub("", title).strip()
    title = _dedupe_concatenated_title(title)
    return normalize_contest_name(title)


def parse_contest_existence_audit_text(raw_text: str) -> tuple[ParsedContestHeader, ...]:
    if not raw_text.strip():
        msg = "Paste contest text before checking."
        raise ContestExistenceAuditValidationError(msg)

    headers_by_key: OrderedDict[tuple[int, str], dict[str, int | str]] = OrderedDict()
    skipped_year_lines = 0
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.lstrip()
        match = YEAR_HEADER_RE.match(line)
        if match is None:
            continue

        raw_title = match.group("title")
        if _is_generic_header(raw_title):
            skipped_year_lines += 1
            continue

        contest_name = _clean_parsed_contest_name(raw_title)
        if not contest_name or _is_generic_header(contest_name):
            skipped_year_lines += 1
            continue

        key = (int(match.group("year")), contest_name)
        if key not in headers_by_key:
            headers_by_key[key] = {
                "contest_name": contest_name,
                "first_line_number": line_number,
                "occurrence_count": 0,
                "year": key[0],
            }
        headers_by_key[key]["occurrence_count"] = int(headers_by_key[key]["occurrence_count"]) + 1

    if not headers_by_key:
        if skipped_year_lines:
            msg = "Only generic year headings were detected; paste contest header lines such as '2026 USAMO'."
            raise ContestExistenceAuditValidationError(msg)
        msg = "No year-prefixed contest headers were detected."
        raise ContestExistenceAuditValidationError(msg)

    return tuple(
        ParsedContestHeader(
            year=int(row["year"]),
            contest_name=str(row["contest_name"]),
            first_line_number=int(row["first_line_number"]),
            occurrence_count=int(row["occurrence_count"]),
        )
        for row in headers_by_key.values()
    )


def _statement_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ContestProblemStatement.objects.values("contest_year", "contest_name")
        .annotate(row_count=Count("id"))
        .order_by("contest_year", "contest_name")
    )
    for row in rows:
        key = (int(row["contest_year"]), normalize_contest_name(str(row["contest_name"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _analytics_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ProblemSolveRecord.objects.values("year", "contest")
        .annotate(row_count=Count("id"))
        .order_by("year", "contest")
    )
    for row in rows:
        key = (int(row["year"]), normalize_contest_name(str(row["contest"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _contest_names_by_year(
    statement_counts: dict[tuple[int, str], int],
    analytics_counts: dict[tuple[int, str], int],
) -> dict[int, list[str]]:
    names_by_year: dict[int, set[str]] = defaultdict(set)
    for year, contest_name in list(statement_counts) + list(analytics_counts):
        names_by_year[year].add(contest_name)
    return {
        year: sorted(contest_names)
        for year, contest_names in names_by_year.items()
    }


def _status_for_counts(statement_count: int, analytics_count: int) -> str:
    if statement_count and analytics_count:
        return "both_found"
    if statement_count:
        return "statements_only"
    if analytics_count:
        return "analytics_only"
    return "missing"


def _suggest_contests(*, contest_name: str, year: int, names_by_year: dict[int, list[str]]) -> list[str]:
    scored_names: list[tuple[float, str]] = []
    needle = contest_name.lower()
    for candidate in names_by_year.get(year, []):
        if candidate == contest_name:
            continue
        ratio = SequenceMatcher(None, needle, candidate.lower()).ratio()
        if ratio >= SUGGESTION_MIN_RATIO:
            scored_names.append((ratio, candidate))
    scored_names.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _ratio, candidate in scored_names[:SUGGESTION_LIMIT]]


def _build_export_tsv(rows: list[ContestExistenceAuditRow]) -> str:
    output = StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "LINE",
            "YEAR",
            "CONTEST",
            "OCCURRENCES",
            "STATEMENT STATUS",
            "STATEMENT COUNT",
            "ANALYTICS STATUS",
            "ANALYTICS COUNT",
            "OVERALL STATUS",
            "SUGGESTIONS",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["first_line_number"],
                row["year"],
                row["contest_name"],
                row["occurrence_count"],
                row["statement_status"],
                row["statement_count"],
                row["analytics_status"],
                row["analytics_count"],
                row["overall_status"],
                row["suggestions_label"],
            ]
        )
    return output.getvalue().rstrip("\n")


def build_contest_existence_audit_payload(
    parsed_headers: tuple[ParsedContestHeader, ...],
) -> ContestExistenceAuditPayload:
    statement_counts = _statement_counts_by_key()
    analytics_counts = _analytics_counts_by_key()
    names_by_year = _contest_names_by_year(statement_counts, analytics_counts)
    rows: list[ContestExistenceAuditRow] = []
    summary = {
        "analytics_only_total": 0,
        "both_found_total": 0,
        "missing_total": 0,
        "partial_total": 0,
        "parsed_total": len(parsed_headers),
        "statements_only_total": 0,
    }

    for header in parsed_headers:
        key = (header.year, normalize_contest_name(header.contest_name))
        statement_count = statement_counts.get(key, 0)
        analytics_count = analytics_counts.get(key, 0)
        overall_status = _status_for_counts(statement_count, analytics_count)
        statement_status = "found" if statement_count else "missing"
        analytics_status = "found" if analytics_count else "missing"
        suggestions = (
            []
            if overall_status == "both_found"
            else _suggest_contests(
                contest_name=header.contest_name,
                year=header.year,
                names_by_year=names_by_year,
            )
        )

        if overall_status == "both_found":
            summary["both_found_total"] += 1
        elif overall_status == "statements_only":
            summary["statements_only_total"] += 1
            summary["partial_total"] += 1
        elif overall_status == "analytics_only":
            summary["analytics_only_total"] += 1
            summary["partial_total"] += 1
        else:
            summary["missing_total"] += 1

        rows.append(
            {
                "analytics_count": analytics_count,
                "analytics_status": analytics_status,
                "contest_name": header.contest_name,
                "first_line_number": header.first_line_number,
                "occurrence_count": header.occurrence_count,
                "overall_status": overall_status,
                "statement_count": statement_count,
                "statement_status": statement_status,
                "suggestions": suggestions,
                "suggestions_label": ", ".join(suggestions),
                "year": header.year,
            }
        )

    return {
        "export_tsv": _build_export_tsv(rows),
        "row_count": len(rows),
        "rows": rows,
        "summary": summary,
    }
```

- [ ] **Step 4: Run parser/checker tests to verify they pass**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_reads_year_prefixed_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_rejects_text_without_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_payload_checks_both_tables_and_suggests_same_year_names \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit parser/checker work**

Run:

```bash
git add inspinia/pages/contest_existence_audit.py inspinia/pages/tests.py
git commit -m "feat: add contest existence audit parser"
```

## Task 2: Form, Route, And View

**Files:**
- Modify: `inspinia/pages/forms.py`
- Modify: `inspinia/pages/views.py`
- Modify: `inspinia/pages/urls.py`
- Modify: `inspinia/pages/tests.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add failing access and view tests**

Add these tests near the existing `test_handle_summary_parser_requires_login` and `test_handle_summary_parser_forbids_non_admin_when_debug_is_off` tests:

```python
def test_contest_existence_audit_requires_login(client):
    response = client.get(reverse("pages:contest_existence_audit"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:contest_existence_audit')}"


@override_settings(DEBUG=False)
def test_contest_existence_audit_forbids_non_admin_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:contest_existence_audit"))

    assert response.status_code == HTTPStatus.FORBIDDEN
```

Add this view test near `test_handle_summary_parser_allows_admin_access`:

```python
def test_contest_existence_audit_allows_admin_and_posts_audit_results(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="Canadian National Olympiad",
        problem="P1",
        contest_year_problem="Canadian National Olympiad 2026 P1",
    )
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Canadian National Olympiad",
        day_label="",
        problem_number=1,
        problem_code="P1",
        statement_latex="Canadian statement",
    )

    get_response = client.get(reverse("pages:contest_existence_audit"))
    assert get_response.status_code == HTTPStatus.OK
    assert "Contest existence audit" in get_response.content.decode("utf-8")
    assert get_response.context["preview_payload"] is None

    response = client.post(
        reverse("pages:contest_existence_audit"),
        {
            "source_text": "\n".join(
                [
                    "2026 Contests3",
                    "2026 Canadian National Olympiad",
                    "2026 Canadian National Olympiad",
                    "2026 Canada National Olympiad",
                ]
            )
        },
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.context["preview_payload"]
    assert payload["row_count"] == 2
    rows_by_contest = {row["contest_name"]: row for row in payload["rows"]}
    assert rows_by_contest["Canadian National Olympiad"]["overall_status"] == "both_found"
    assert rows_by_contest["Canadian National Olympiad"]["occurrence_count"] == 2
    assert rows_by_contest["Canada National Olympiad"]["overall_status"] == "missing"
    assert rows_by_contest["Canada National Olympiad"]["suggestions"] == [
        "Canadian National Olympiad",
    ]
    assert "Canadian National Olympiad" in payload["export_tsv"]
    response_html = response.content.decode("utf-8")
    assert 'id="contest-existence-audit-form"' in response_html
    assert 'id="contest-existence-audit-results-table"' in response_html
    assert 'id="contest-existence-audit-export"' in response_html
```

- [ ] **Step 2: Run new view tests to verify they fail**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_requires_login \
  inspinia/pages/tests.py::test_contest_existence_audit_forbids_non_admin_when_debug_is_off \
  inspinia/pages/tests.py::test_contest_existence_audit_allows_admin_and_posts_audit_results \
  -v
```

Expected: FAIL with `NoReverseMatch` for `pages:contest_existence_audit`.

- [ ] **Step 3: Add the Django form**

In `inspinia/pages/forms.py`, add this class after `HandleSummaryParserForm`:

```python
class ContestExistenceAuditForm(forms.Form):
    source_text = forms.CharField(
        label="Contest scrape",
        strip=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "form": "contest-existence-audit-form",
                "id": "contest-existence-audit-input",
                "rows": 24,
                "spellcheck": "false",
                "placeholder": (
                    "2026 Contests3\n"
                    " 2026 Abelkonkurransen Finale\n"
                    "1a\tDetermine all pairs of positive integers...\n"
                    "RANDOM__USER\n"
                    "view topic\n"
                    " 2026 AIMEAIME 2026"
                ),
            },
        ),
    )

    def clean_source_text(self):
        text = self.cleaned_data["source_text"]
        if not text.strip():
            msg = "Paste contest text before checking."
            raise forms.ValidationError(msg)
        return text
```

- [ ] **Step 4: Add view imports and view function**

In `inspinia/pages/views.py`, add these imports with the related page imports:

```python
from inspinia.pages.contest_existence_audit import ContestExistenceAuditValidationError
from inspinia.pages.contest_existence_audit import build_contest_existence_audit_payload
from inspinia.pages.contest_existence_audit import parse_contest_existence_audit_text
from inspinia.pages.forms import ContestExistenceAuditForm
```

Add this view function near `handle_summary_parser_view`:

```python
@login_required
def contest_existence_audit_view(request):
    _require_admin_tools_access(request)
    preview_payload = None

    if request.method == "POST":
        form = ContestExistenceAuditForm(request.POST)
        if form.is_valid():
            try:
                parsed_headers = parse_contest_existence_audit_text(form.cleaned_data["source_text"])
            except ContestExistenceAuditValidationError as exc:
                messages.error(request, str(exc))
            else:
                preview_payload = build_contest_existence_audit_payload(parsed_headers)
                messages.info(
                    request,
                    f'Checked {preview_payload["row_count"]} parsed contest-year row(s).',
                )
    else:
        form = ContestExistenceAuditForm()

    return render(
        request,
        "pages/contest-existence-audit.html",
        {
            "form": form,
            "preview_payload": preview_payload,
        },
    )
```

- [ ] **Step 5: Register the route**

In `inspinia/pages/urls.py`, add this import with the other view imports:

```python
from inspinia.pages.views import contest_existence_audit_view
```

Add this path near the other `tools/` utility routes:

```python
path("tools/contest-existence-audit/", contest_existence_audit_view, name="contest_existence_audit"),
```

- [ ] **Step 6: Run the view tests**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_requires_login \
  inspinia/pages/tests.py::test_contest_existence_audit_forbids_non_admin_when_debug_is_off \
  inspinia/pages/tests.py::test_contest_existence_audit_allows_admin_and_posts_audit_results \
  -v
```

Expected: FAIL with `TemplateDoesNotExist: pages/contest-existence-audit.html`.

- [ ] **Step 7: Keep form, route, and view changes for the template task**

Do not commit after this step. The view intentionally cannot render until
`inspinia/templates/pages/contest-existence-audit.html` is created in Task 3.

## Task 3: Template And Sidebar Navigation

**Files:**
- Create: `inspinia/templates/pages/contest-existence-audit.html`
- Modify: `inspinia/templates/partials/sidenav.html`
- Modify: `inspinia/pages/tests.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add failing sidebar assertion**

In `test_sidebar_groups_links_in_product_order_for_admin`, insert `"Contest audit"` after `"Handle parser"` in the `expected_order` list:

```python
        "LaTeX preview",
        "Handle parser",
        "Contest audit",
        "User roles",
```

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_sidebar_groups_links_in_product_order_for_admin -v
```

Expected: FAIL because `"Contest audit"` is not in the rendered sidebar.

- [ ] **Step 2: Create the template**

Create `inspinia/templates/pages/contest-existence-audit.html` with this content:

```django
{% extends 'layouts/vertical.html' %}

{% load i18n %}

{% block title %}Contest existence audit{% endblock title %}

{% block extra_css %}
<style>
  .contest-audit-export {
    min-height: 14rem;
  }

  .contest-audit-suggestions {
    min-width: 18rem;
    white-space: normal;
  }
</style>
{% endblock extra_css %}

{% block page_content %}
<div class="container-fluid">
  {% include 'partials/page-title.html' with title='Contest existence audit' subtitle='Workspace tool' %}

  {% if messages %}
  <div class="mt-3">
    {% for message in messages %}
      <div class="alert alert-{% if message.tags == 'error' %}danger{% elif message.tags == 'debug' %}secondary{% else %}{{ message.tags }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="{% translate 'Close' %}"></button>
      </div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="row g-3 mt-0">
    <div class="col-12">
      <form id="contest-existence-audit-form" method="post" class="card">
        {% csrf_token %}
        <div class="card-header border-0 pb-0">
          <h4 class="header-title mb-0">Paste contest scrape text and check exact contest-year existence</h4>
          <p class="text-muted fs-xs mb-0">Only lines starting with a 4-digit year are parsed. Suggestions are same-year hints and do not count as existing rows.</p>
        </div>
        <div class="card-body pt-2">
          {% if form.non_field_errors %}
          <div class="alert alert-danger">{{ form.non_field_errors }}</div>
          {% endif %}
          <div class="d-flex flex-wrap gap-2 align-items-center">
            <button type="submit" class="btn btn-primary">
              <i class="ti ti-database-search me-1"></i>Check contests
            </button>
            <button type="button" class="btn btn-outline-secondary" id="contest-existence-audit-clear">
              <i class="ti ti-eraser me-1"></i>Clear
            </button>
            {% if preview_payload %}
            <button type="button" class="btn btn-outline-secondary" id="contest-existence-audit-copy">
              <i class="ti ti-copy me-1"></i>Copy TSV
            </button>
            {% endif %}
          </div>
        </div>
      </form>
    </div>
  </div>

  <div class="row g-3 mt-0 mb-4">
    <div class="col-xl-6">
      <div class="card h-100">
        <div class="card-header border-bottom">
          <h4 class="header-title mb-0">Raw input</h4>
        </div>
        <div class="card-body">
          <label class="form-label" for="contest-existence-audit-input">Input</label>
          {{ form.source_text }}
          {% for error in form.source_text.errors %}
          <div class="invalid-feedback d-block">{{ error }}</div>
          {% endfor %}
          <div class="form-text">Generic headings such as <code>2026 Contests3</code> are skipped.</div>
        </div>
      </div>
    </div>

    <div class="col-xl-6">
      <div class="card h-100">
        <div class="card-header border-bottom">
          <h4 class="header-title mb-0">Audit summary</h4>
          <p class="text-muted fs-xs mb-0">Exact matches across statement and analytics data.</p>
        </div>
        <div class="card-body">
          {% if preview_payload %}
          <div class="row g-3">
            <div class="col-6 col-lg-3">
              <p class="text-muted mb-0 fs-xs text-uppercase fw-semibold">Parsed</p>
              <h3 class="mb-0">{{ preview_payload.summary.parsed_total }}</h3>
            </div>
            <div class="col-6 col-lg-3">
              <p class="text-muted mb-0 fs-xs text-uppercase fw-semibold">Both</p>
              <h3 class="mb-0 text-success">{{ preview_payload.summary.both_found_total }}</h3>
            </div>
            <div class="col-6 col-lg-3">
              <p class="text-muted mb-0 fs-xs text-uppercase fw-semibold">Partial</p>
              <h3 class="mb-0 text-warning">{{ preview_payload.summary.partial_total }}</h3>
            </div>
            <div class="col-6 col-lg-3">
              <p class="text-muted mb-0 fs-xs text-uppercase fw-semibold">Missing</p>
              <h3 class="mb-0 text-danger">{{ preview_payload.summary.missing_total }}</h3>
            </div>
          </div>
          <textarea
            id="contest-existence-audit-export"
            class="form-control font-monospace contest-audit-export mt-4"
            readonly
          >{{ preview_payload.export_tsv }}</textarea>
          {% else %}
          <div class="alert alert-info mb-0" role="status">
            Paste contest text and run the check to see statement-table and analytics-table status.
          </div>
          {% endif %}
        </div>
      </div>
    </div>
  </div>

  {% if preview_payload %}
  <div class="row g-3 mt-0">
    <div class="col-12">
      <div class="card">
        <div class="card-header border-bottom d-flex flex-wrap align-items-center justify-content-between gap-2">
          <div>
            <h4 class="header-title mb-0">Parsed contests</h4>
            <p class="text-muted fs-xs mb-0">Status is based on exact normalized contest-year matches.</p>
          </div>
          <span class="badge bg-primary-subtle text-primary">{{ preview_payload.row_count }} row{{ preview_payload.row_count|pluralize }}</span>
        </div>
        <div class="card-body p-0">
          <div class="table-responsive">
            <table id="contest-existence-audit-results-table" class="table table-striped table-bordered align-middle mb-0">
              <thead class="table-light">
                <tr>
                  <th scope="col">Line</th>
                  <th scope="col">Year</th>
                  <th scope="col">Contest</th>
                  <th scope="col">Seen</th>
                  <th scope="col">Statements</th>
                  <th scope="col">Analytics</th>
                  <th scope="col">Status</th>
                  <th scope="col">Suggestions</th>
                </tr>
              </thead>
              <tbody>
                {% for row in preview_payload.rows %}
                <tr>
                  <td>{{ row.first_line_number }}</td>
                  <td>{{ row.year }}</td>
                  <td>{{ row.contest_name }}</td>
                  <td>{{ row.occurrence_count }}</td>
                  <td>
                    <span class="badge {% if row.statement_status == 'found' %}bg-success-subtle text-success{% else %}bg-secondary-subtle text-secondary{% endif %}">
                      {{ row.statement_status }} - {{ row.statement_count }}
                    </span>
                  </td>
                  <td>
                    <span class="badge {% if row.analytics_status == 'found' %}bg-success-subtle text-success{% else %}bg-secondary-subtle text-secondary{% endif %}">
                      {{ row.analytics_status }} - {{ row.analytics_count }}
                    </span>
                  </td>
                  <td>
                    <span class="badge {% if row.overall_status == 'both_found' %}bg-success-subtle text-success{% elif row.overall_status == 'missing' %}bg-danger-subtle text-danger{% else %}bg-warning-subtle text-warning{% endif %}">
                      {{ row.overall_status }}
                    </span>
                  </td>
                  <td class="contest-audit-suggestions">
                    {% if row.suggestions %}
                    {{ row.suggestions_label }}
                    {% else %}
                    <span class="text-muted">-</span>
                    {% endif %}
                  </td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
  {% endif %}
</div>
{% endblock page_content %}

{% block extra_javascript %}
<script>
  (function() {
    var clearButton = document.getElementById("contest-existence-audit-clear");
    var copyButton = document.getElementById("contest-existence-audit-copy");
    var input = document.getElementById("contest-existence-audit-input");
    var exportBox = document.getElementById("contest-existence-audit-export");

    if (clearButton && input) {
      clearButton.addEventListener("click", function() {
        input.value = "";
        input.focus();
      });
    }

    if (copyButton && exportBox) {
      copyButton.addEventListener("click", function() {
        exportBox.select();
        exportBox.setSelectionRange(0, exportBox.value.length);
        navigator.clipboard.writeText(exportBox.value).catch(function() {});
      });
    }
  })();
</script>
{% endblock extra_javascript %}
```

- [ ] **Step 3: Add sidebar link**

In `inspinia/templates/partials/sidenav.html`, add this link immediately after the `Handle parser` link:

```django
            <li class="side-nav-item">
                <a href="{% url 'pages:contest_existence_audit' %}" class="side-nav-link">
                    <span class="menu-icon"><i class="ti ti-database-search"></i></span>
                    <span class="menu-text">Contest audit</span>
                </a>
            </li>
```

- [ ] **Step 4: Run template/sidebar tests**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_allows_admin_and_posts_audit_results \
  inspinia/pages/tests.py::test_sidebar_groups_links_in_product_order_for_admin \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit template and sidebar work**

Run:

```bash
git add \
  inspinia/pages/forms.py \
  inspinia/pages/views.py \
  inspinia/pages/urls.py \
  inspinia/templates/pages/contest-existence-audit.html \
  inspinia/templates/partials/sidenav.html \
  inspinia/pages/tests.py
git commit -m "feat: add contest existence audit page"
```

## Task 4: Final Verification And Cleanup

**Files:**
- Verify: `inspinia/pages/contest_existence_audit.py`
- Verify: `inspinia/pages/forms.py`
- Verify: `inspinia/pages/views.py`
- Verify: `inspinia/pages/urls.py`
- Verify: `inspinia/templates/pages/contest-existence-audit.html`
- Verify: `inspinia/templates/partials/sidenav.html`
- Verify: `inspinia/pages/tests.py`

- [ ] **Step 1: Run focused page tests**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_reads_year_prefixed_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_parser_rejects_text_without_contest_headers \
  inspinia/pages/tests.py::test_contest_existence_audit_payload_checks_both_tables_and_suggests_same_year_names \
  inspinia/pages/tests.py::test_contest_existence_audit_requires_login \
  inspinia/pages/tests.py::test_contest_existence_audit_forbids_non_admin_when_debug_is_off \
  inspinia/pages/tests.py::test_contest_existence_audit_allows_admin_and_posts_audit_results \
  inspinia/pages/tests.py::test_sidebar_groups_links_in_product_order_for_admin \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run project checks for touched area**

Run:

```bash
uv run ruff check inspinia/pages
```

Expected: PASS.

Run:

```bash
uv run pytest inspinia/pages/tests.py -v
```

Expected: PASS.

- [ ] **Step 3: Review the final diff**

Run:

```bash
git status --short
git diff --stat
git diff -- inspinia/pages/contest_existence_audit.py inspinia/pages/forms.py inspinia/pages/views.py inspinia/pages/urls.py inspinia/templates/pages/contest-existence-audit.html inspinia/templates/partials/sidenav.html inspinia/pages/tests.py
```

Expected:

- `package-lock.json` remains unrelated and is not staged.
- No model, migration, or global static asset files are changed.
- The helper module is read-only with no writes to `ContestProblemStatement` or `ProblemSolveRecord`.
- The template extends `layouts/vertical.html`.
- The sidebar link is under Utilities.

- [ ] **Step 4: Commit final cleanup only if Task 4 changed files**

If Task 4 required edits, run:

```bash
git add inspinia/pages/contest_existence_audit.py inspinia/pages/forms.py inspinia/pages/views.py inspinia/pages/urls.py inspinia/templates/pages/contest-existence-audit.html inspinia/templates/partials/sidenav.html inspinia/pages/tests.py
git commit -m "test: verify contest existence audit"
```

If Task 4 did not require edits, do not create an empty commit.
