"""The student explorer preserves evidence and never changes recorded history."""

# ruff: noqa: PLR2004 - Explicit fixture counts are the acceptance contract.
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inspinia.rankings.imports.olympiad_sheet import HISTORY_COLUMNS
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import AssessmentAnalysisMetadata
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import ResultSchoolAttribution
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.rankings.models import normalize_name
from inspinia.rankings.services.school_display import with_school_display
from inspinia.rankings.services.student_detail import build_student_detail
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
CONTEST_LABELS = ["SST", "APMO", "CST", "JOM January", "SASMO", "Kangaroo", "IMONST1", "IMONST2", "Olympiad"]
YEAR_COUNTS = {2026: 7, 2025: 8, 2024: 4, 2022: 3, 2021: 9, 2020: 6}


def add_result(student, code, year=2026, *, title=None, assessment_date=None, **values):
    assessment = Assessment.objects.create(
        code=code,
        display_name=title or code.replace("_", " "),
        season_year=year,
        assessment_date=assessment_date,
    )
    return StudentResult.objects.create(student=student, assessment=assessment, **values)


def page(student, query=""):
    student = with_school_display(Student.objects.select_related("school")).get(pk=student.pk)
    params = QueryDict(query, mutable=True)
    if not params.get("type"):
        params["type"] = "all"
    return build_student_detail(student, params, reverse("rankings:student_detail", args=[student.pk]))


@pytest.fixture
def alex_history():
    student = Student.objects.create(full_name="ALEXANDER CHEW TIAN YOU", birth_year=2012)
    for code, label in [
        ("SELECTION_2026_08", "SQUAD"),
        ("SELECTION_2026_03", "JUNIOR SQUAD"),
        ("SELECTION_2026_02", "SENIOR"),
    ]:
        add_result(
            student,
            code,
            title=next(c[2] for c in HISTORY_COLUMNS if c[1] == code),
            status_text=label,
            source_file_name="history.tsv",
        )
    for code, label, field in [
        ("ENTRANCE_GROUP_2025", "JUNIOR", "status_text"),
        ("SELECTION_2025", "JUNIOR", "status_text"),
        ("IMONST2_2025", "PRIMARY", "band"),
        ("IMONST_GROUP_2025", "JUNIOR", "band"),
    ]:
        add_result(
            student,
            code,
            2025,
            title=next(c[2] for c in HISTORY_COLUMNS if c[1] == code),
            source_file_name="history.tsv",
            **{field: label},
        )
    add_result(
        student,
        "SELECTION_2024_B",
        2024,
        title="2024 group (source column 36)",
        status_text="PRIMARY",
        source_file_name="history.tsv",
    )
    for year, count in YEAR_COUNTS.items():
        existing = student.results.filter(assessment__season_year=year).count()
        for i in range(count - existing):
            add_result(
                student,
                f"LH_CONTEST_{year}_{i}",
                year,
                title=f"{CONTEST_LABELS[i]} {year} (legacy source {year}-09-01)",
                band="Grade 4" if i % 2 else "Ecolier",
                medal="GOLD" if i % 2 else "SILVER",
                raw_score=Decimal("0") if i == 0 else Decimal("17.50"),
                source_file_name=f"math olympiad.xlsx [Sheet1 row {i + year}; sha256 {'a' * 64}]",
                imported_at=timezone.now(),
            )
    return student


def test_alex_complete_history_and_filter_independence(alex_history):
    context = page(alex_history)
    assert context["summary"]["count"] == 37
    assert context["summary"]["sources"] == 2
    assert context["summary"]["coverage"] == "2020\u20132026"
    assert {g["year"]: g["count"] for g in context["year_groups"]} == YEAR_COUNTS
    assert context["timeline_count"] == 6
    assert [b["label"] for b in context["timeline"]] == ["2024", "2025", "Feb 2026", "Mar 2026", "Aug 2026"]
    assert [b["count"] for b in context["timeline"]] == [1, 2, 1, 1, 1]
    assert context["student"].school_display == ""
    assert not context["rankings"]
    filtered = page(alex_history, "q=Grade+4&type=scores")
    assert filtered["summary"] == context["summary"]
    assert filtered["timeline"] == context["timeline"]
    assert page(alex_history, "type=groups")["page_obj"].paginator.count == 6


def test_classification_dates_and_separate_records():
    student = Student.objects.create(full_name="Recorded Labels")
    for code, band in [
        ("GRADE", "Grade 4"),
        ("MIDDLE", "Middle Primary"),
        ("CADET", "Cadet"),
        ("UNKNOWN", "Junior beginner candidate"),
        ("ECOLIER", "Ecolier"),
    ]:
        add_result(student, code, band=band)
    add_result(student, "PROGRAM", 2024, band="PRIMARY", status_text="Merit")
    add_result(student, "PROGRAM_2", 2024, band="PRIMARY", source_file_name="other.tsv")
    add_result(student, "SELECTION_2026_02", status_text="Recorded decision", assessment_date=date(2026, 1, 1))
    verified = add_result(student, "DATED", 2025, status_text="Squad", assessment_date=date(2025, 6, 10))
    AssessmentAnalysisMetadata.objects.create(assessment=verified.assessment, date_verified=True)
    add_result(
        student,
        "LH_SOURCE_DATE",
        2022,
        title="Contest (legacy source 2022-02-12)",
        status_text="Junior",
        assessment_date=date(2022, 2, 12),
    )
    StudentSelectionStatus.objects.create(student=student, season_year=2024, status="primary")
    context = page(student)
    assert context["timeline_count"] == 3
    assert [b["label"] for b in context["timeline"]] == ["2024", "10 Jun 2025", "Feb 2026"]
    assert context["timeline"][0]["count"] == 1
    assert context["timeline"][0]["precision"] == "Year only"
    assert context["timeline"][1]["precision"] == "Verified date"
    assert page(student, "type=outcomes")["page_obj"].paginator.count == 1


def test_scores_aliases_qualifications_conflicts_and_safe_details(client):
    school = School.objects.create(name="Current school")
    student = Student.objects.create(
        full_name="Stored NAME", school=school, notes="PRIVATE PROFILE NOTE",
        full_nric="120101-01-1234", masked_nric="120101-**-****", date_of_birth=date(2001, 8, 9),
    )
    zero = add_result(student, "ZERO", raw_score=0, medal="GOLD", status_text="High Distinction Gold")
    conflict = add_result(
        student,
        "CONFLICT",
        raw_score=Decimal("1.25"),
        medal="GOLD",
        status_text="SILVER",
        remarks='<script>alert("notes")</script>',
        source_url="javascript:alert(1)",
    )
    alias_result = add_result(student, "ALIAS", medal="GD", remarks="School in source result: Old school")
    OutcomeAlias.objects.create(
        assessment=alias_result.assessment,
        field="medal",
        alias="GD",
        normalized_alias=normalize_name("GD"),
        canonical="GOLD",
    )
    historical = School.objects.create(name="Reviewed historical school")
    SchoolAlias.objects.create(alias="Old school", normalized_name=normalize_name("Old school"), school=historical)
    ResultSchoolAttribution.objects.create(result=zero, school=historical, evidence="Reviewed fixture")
    add_result(student, "NO_SCORE", source_url="https://example.com/results")
    context = page(student)
    rows = {row["id"]: row for row in context["results"]}
    assert rows[zero.pk]["score"] == 0
    assert [o["label"] for o in rows[zero.pk]["outcomes"]] == ["High Distinction Gold"]
    assert [o["label"] for o in rows[conflict.pk]["outcomes"]] == ["GOLD", "SILVER"]
    assert rows[conflict.pk]["school"] == ""
    assert rows[conflict.pk]["url"] == ""
    assert rows[zero.pk]["school"] == historical.name
    assert rows[alias_result.pk]["school"] == historical.name
    assert rows[alias_result.pk]["original_medal"] == "GD"
    assert rows[alias_result.pk]["medal"] == "GOLD"
    assert page(student, "type=scores")["page_obj"].paginator.count == 2
    assert page(student, "type=outcomes")["page_obj"].paginator.count == 3
    assert page(student, "q=ALIAS+GD")["page_obj"].paginator.count == 1
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    response = client.get(reverse("rankings:student_detail", args=[student.pk]), {"type": "all"})
    html = response.content.decode()
    assert '<script>alert("notes")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "PRIVATE PROFILE NOTE" not in html
    assert "120101-01-1234" not in html
    assert "120101-**-****" not in html
    assert "2001-08-09" not in html
    assert "9 Aug 2001" not in html
    assert "javascript:alert" not in html
    assert 'rel="noopener noreferrer"' in html
    assert 'data-label="Score">0.00</td>' in html
    assert "Stored NAME" in html
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "student-trend-chart" not in html
    assert "apexcharts" not in html.lower()


def test_source_identity_and_legacy_name_disambiguation():
    student = Student.objects.create(full_name="Provenance")
    for i, filename in enumerate(
        [
            f"math.xlsx [Sheet1 row 2; sha256 {'a' * 64}]",
            f"math.xlsx [Sheet1 row 3; sha256 {'a' * 64}]",
            f"math.xlsx [Sheet1 row 4; sha256 {'b' * 64}]",
            "math.xlsx",
            "other/math.xlsx",
            "math.xlsx copy",
        ],
    ):
        add_result(
            student,
            f"LH_{i}",
            2024,
            title=f"Contest (legacy source 2024-02-{i + 1:02d})",
            source_file_name=filename,
        )
    context = page(student)
    assert len(context["sources"]) == 5
    assert sorted(s["count"] for s in context["sources"]) == [1, 1, 1, 1, 2]
    assert all(row["title"] == "Contest" and row["disambiguation"] for row in context["results"])
    assert all(row["source_date"] and row["time"][2] == "Year only" for row in context["results"])


@pytest.mark.parametrize("query", ["q=" + "a" * 256, "year=abc", "year=1900", "type=unknown"])
def test_invalid_filters_return_errors_not_changed_filter(query):
    student = Student.objects.create(full_name="Filters")
    add_result(student, "SCORE", raw_score=0)
    context = page(student, query)
    assert context["form"].errors
    assert not context["filters_valid"]
    assert context["page_obj"].paginator.count == 0
    assert context["summary"]["count"] == 1


def test_pagination_literal_search_and_query_budget():
    student = Student.objects.create(full_name="Large History")
    add_result(student, "LITERAL", title="A [B].* C", raw_score=0)
    with CaptureQueriesContext(connection) as small:
        page(student)
    for i in range(115):
        add_result(student, f"RESULT_{i}", raw_score=i)
    with CaptureQueriesContext(connection) as large:
        context = page(student, "type=scores&page=2")
    assert len(large) == len(small)
    assert len(large) <= 7
    assert len(context["page_obj"]) == 116
    assert context["year_groups"][0]["count"] == 116
    assert context["year_groups"][0]["shown"] == 116
    assert "type=scores" in context["pagination_query"]
    assert page(student, "page=garbage")["page_obj"].number == 1
    assert page(student, "page=999")["page_obj"].number == 1
    assert page(student, "q=%5BB%5D.*+c")["page_obj"].paginator.count == 1
    assert page(student, "q=A+missing")["page_obj"].paginator.count == 0
    assert page(student, "q=%EF%BC%A1")["page_obj"].paginator.count == 1


def test_empty_and_saved_rankings(client):
    student = Student.objects.create(full_name="No History")
    assert not page(student)["timeline"]
    client.force_login(UserFactory(role=User.Role.ADMIN))
    url = reverse("rankings:student_detail", args=[student.pk])
    assert b"No ranking snapshots recorded" in client.get(url).content
    for division, version in [("junior", "v1"), ("senior", "v2")]:
        formula = RankingFormula.objects.create(name=division, season_year=2026, division=division)
        RankingSnapshot.objects.create(
            student=student,
            ranking_formula=formula,
            total_score=Decimal("12.3456"),
            rank_overall=3,
            formula_version_label=version,
        )
    response = client.get(url)
    assert len(response.context["rankings"]) == 2
    assert b"12.3456" in response.content
    assert b"Saved rankings" in response.content


@pytest.mark.parametrize(
    ("role", "expected"),
    [(None, 302), (User.Role.NORMAL, 403), (User.Role.MODERATOR, 200), (User.Role.ADMIN, 200)],
)
def test_access_and_read_only_requests(client, alex_history, role, expected):
    if role:
        client.force_login(UserFactory(role=role))
    models = [
        Student,
        StudentResult,
        StudentSelectionStatus,
        Assessment,
        AssessmentAnalysisMetadata,
        OutcomeAlias,
        SchoolAlias,
        ResultSchoolAttribution,
        RankingSnapshot,
        ImportBatch,
    ]
    before = {m: list(m.objects.order_by("pk").values()) for m in models}
    url = reverse("rankings:student_detail", args=[alex_history.pk])
    for query in ["", "?type=groups", "?q=x&year=invalid", "?page=2"]:
        response = client.get(url + query)
        assert response.status_code == expected
    assert before == {m: list(m.objects.order_by("pk").values()) for m in models}


def test_timeline_includes_every_recorded_bucket():
    student = Student.objects.create(full_name="Long Timeline")
    for year in range(2016, 2024):
        StudentSelectionStatus.objects.create(student=student, season_year=year, status="primary")
    context = page(student)
    assert len(context["timeline"]) == 8
    assert [b["label"] for b in context["timeline"]] == [str(year) for year in range(2016, 2024)]
    assert context["timeline_count"] == 8


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,example", "ftp://example.com/file",
                                 "https://user:password@example.com/file", "https://"])
def test_untrusted_source_urls_are_not_linked(url):
    student = Student.objects.create(full_name="Source Links")
    add_result(student, "LINK", source_url=url)
    assert page(student)["results"][0]["url"] == ""


def test_invalid_filter_html_has_associated_errors_and_get_fallback(client):
    student = Student.objects.create(full_name="Filter Errors")
    add_result(student, "ENTRY", medal="GOLD", status_text="Gold Medal")
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    response = client.get(reverse("rankings:student_detail", args=[student.pk]), {"q": "x" * 256})
    assert response.status_code == 200
    assert b'aria-invalid="true"' in response.content
    assert b'id="id_q_error"' in response.content
    assert b'<form method="get"' in response.content
    assert b'type="submit"' in response.content
    assert b'data-default-open="' not in response.content
    assert [o["label"] for o in page(student)["results"][0]["outcomes"]] == ["GOLD"]


def test_conflicting_status_is_not_treated_as_a_medal_qualification():
    student = Student.objects.create(full_name="Conflicting outcome")
    add_result(student, "CONFLICT", medal="GOLD", status_text="Not awarded Gold")
    assert [o["label"] for o in page(student)["results"][0]["outcomes"]] == ["GOLD", "Not awarded Gold"]
