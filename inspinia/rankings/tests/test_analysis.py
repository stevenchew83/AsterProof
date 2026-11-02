"""Ranking analysis calculations, private reads, cohorts and complete exports."""
# ruff: noqa: PLR2004 - explicit fixture counts and HTTP response expectations

import csv
import io
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import AssessmentAnalysisMetadata
from inspinia.rankings.models import AssessmentCategoryScale
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import ResultSchoolAttribution
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.analysis import cohort_ranks
from inspinia.rankings.services.analysis import histogram
from inspinia.rankings.services.analysis import load_records
from inspinia.rankings.services.analysis import quantile
from inspinia.rankings.services.analysis import score_summary
from inspinia.rankings.services.analysis import spearman
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def assessment(code="IMONST2_2026", year=2026):
    return Assessment.objects.create(
        code=code, display_name=code.replace("_", " "), season_year=year, category="contest",
    )


def result(event, name, score, band="PIONEER", school=None, student=None):  # noqa: PLR0913
    student = student or Student.objects.create(
        full_name=name,
        school=school,
        full_nric="PRIVATE-NRIC",
        date_of_birth="2012-02-03",
        notes="PRIVATE-FAMILY-NOTE",
    )
    return StudentResult.objects.create(
        student=student, assessment=event, raw_score=score, band=band, remarks="PRIVATE-REMARK",
    )


def login(client, role=User.Role.MODERATOR):
    user = UserFactory(role=role)
    client.force_login(user)
    return user


def test_decimal_quartiles_and_histogram_preserve_zero_and_missing():
    summary = score_summary([Decimal(0), Decimal(2), Decimal(10), None])
    assert summary["count"] == 3
    assert summary["median"] == Decimal(2)
    assert summary["q1"] == Decimal(1)
    assert summary["q3"] == Decimal(6)
    assert quantile([], 0.5) is None
    assert histogram([Decimal(0), Decimal(0), None]) == [
        {"low": Decimal(0), "high": Decimal(0), "count": 2, "inclusive": True, "label": "0"},
    ]
    bins = histogram([Decimal(0), Decimal(10)])
    assert sum(value["count"] for value in bins) == 2
    assert bins[0]["count"] == bins[-1]["count"] == 1
    assert bins[-1]["inclusive"]


def test_global_category_competition_ranks_and_tie_aware_percentiles():
    rows = [
        {"assessment_id": 1, "band": "PIONEER", "score": score, "rank": None, "percentile": None}
        for score in [Decimal(36), Decimal(34), Decimal(34), Decimal(0), None]
    ]
    rows.append({"assessment_id": 1, "band": "BEGINNER", "score": Decimal(0), "rank": None, "percentile": None})
    cohort_ranks(rows)
    assert [row["rank"] for row in rows] == [1, 2, 2, 4, None, 1]
    assert [row["percentile"] for row in rows] == [
        Decimal("87.5"),
        Decimal(50),
        Decimal(50),
        Decimal("12.5"),
        None,
        Decimal(50),
    ]


def test_spearman_uses_average_tie_ranks_and_explicit_unavailable_states():
    values = [1, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    coefficient, _ = spearman(values, values)
    assert coefficient == pytest.approx(1)
    assert spearman(values[:9], values[:9])[0] is None
    assert spearman([1] * 10, values)[0] is None


@pytest.mark.parametrize("route", ["analysis", "analysis_export"])
def test_analysis_role_boundaries_and_private_cache(client, route):
    url = reverse(f"rankings:{route}")
    assert client.get(url).status_code == 302
    for role in [User.Role.NORMAL, User.Role.TRAINER]:
        login(client, role)
        assert client.get(url).status_code == 403
    staff = UserFactory(role=User.Role.NORMAL, is_staff=True)
    client.force_login(staff)
    assert client.get(url).status_code == 403
    login(client)
    response = client.get(url)
    assert response.status_code == 200
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert client.post(url).status_code == 405


@pytest.mark.parametrize("tab", ["overview", "students", "schools", "compare", "quality"])
def test_all_five_tabs_render_without_sensitive_values(client, tab):
    login(client)
    event = assessment()
    result(event, "Student A", Decimal(0))
    response = client.get(reverse("rankings:analysis"), {"tab": tab})
    assert response.status_code == 200
    html = response.content.decode()
    assert "Ranking analysis" in html
    assert 'name="school_basis"' in html
    for private in ["PRIVATE-NRIC", "PRIVATE-FAMILY-NOTE", "PRIVATE-REMARK", "2012-02-03"]:
        assert private not in html
    assert response.context["summary"]["records"] == 1


def test_filtering_does_not_recalculate_reference_rank_or_percentile(client):
    login(client)
    event = assessment()
    result(event, "A", Decimal(30))
    selected = result(event, "B", Decimal(20))
    result(event, "C", Decimal(10))
    response = client.get(reverse("rankings:analysis"), {"q": "B"})
    assert response.status_code == 200
    row = response.context["all_rows"][0]
    assert row["key"] == selected.pk
    assert row["rank"] == 2
    assert row["percentile"] == Decimal(50)
    assert response.context["summary"]["students"] == 1


def test_summary_and_header_sorting_use_full_filtered_dataset_before_pagination(client):
    login(client)
    event = assessment()
    for index in range(56):
        result(event, f"Student {index:02}", Decimal(index))
    response = client.get(reverse("rankings:analysis"), {"order": "score", "page": 2})
    assert response.status_code == 200
    assert response.context["summary"]["students"] == 56
    assert response.context["cohorts"][0]["median"] == Decimal("27.5")
    assert [row["score"] for row in response.context["page_obj"]] == [Decimal(value) for value in range(50, 56)]
    assert response.context["page_obj"].paginator.per_page == 50


def test_school_basis_never_falls_back_from_unverified_attribution(client):
    login(client)
    event = assessment()
    current, original = School.objects.create(name="Current school"), School.objects.create(name="Assessment school")
    row = result(event, "A", Decimal(10), school=current)
    response = client.get(reverse("rankings:analysis"), {"tab": "schools"})
    assert response.context["school_coverage"] == {"known": 0, "total": 1, "basis": "Verified school at assessment"}
    assert response.context["all_rows"][0]["school"] == "Unknown / unverified"
    ResultSchoolAttribution.objects.create(result=row, school=original, evidence="Checked source")
    response = client.get(reverse("rankings:analysis"), {"tab": "schools"})
    assert response.context["all_rows"][0]["school"] == "Assessment school"
    assert response.context["school_coverage"]["known"] == 1
    response = client.get(reverse("rankings:analysis"), {"tab": "schools", "school_basis": "current"})
    assert response.context["all_rows"][0]["school"] == "Current school"
    ResultSchoolAttribution.objects.filter(result=row).update(verified=False)
    assert load_records(assessment_ids=[event.pk])[0]["assessment_school_id"] is None


def test_school_aliases_and_outcome_aliases_are_explicit_and_active_only():
    event = assessment()
    alternate = School.objects.create(name="School alias")
    canonical = School.objects.create(name="Canonical school")
    result(event, "A", Decimal(10), band="pioneer", school=alternate)
    SchoolAlias.objects.create(alias=alternate.name, normalized_name=alternate.normalized_name, school=canonical)
    alias = OutcomeAlias.objects.create(
        assessment=event, field="band", alias="pioneer", normalized_alias="pioneer", canonical="PIONEER",
    )
    loaded = load_records(assessment_ids=[event.pk])[0]
    assert loaded["band"] == "PIONEER"
    assert loaded["current_school_id"] == canonical.pk
    alias.active = False
    alias.save()
    assert load_records(assessment_ids=[event.pk])[0]["band"] == "pioneer"


def test_compare_matches_ids_not_names_and_missing_is_not_zero(client):
    login(client)
    first, second = assessment(), assessment("OTHER_2025", 2025)
    result(first, "Same Name", Decimal(10))
    result(second, "Same Name", Decimal(12))
    shared = result(first, "Matched", Decimal(0)).student
    result(second, "Matched", None, student=shared)
    response = client.get(
        reverse("rankings:analysis"), {"tab": "compare", "assessment": first.pk, "compare_assessment": second.pk},
    )
    comparison = response.context["comparison"]
    assert comparison["matched"] == 1
    assert comparison["numeric"] == 0
    assert comparison["left_only"] == comparison["right_only"] == 1
    assert comparison["correlation"] is None


def test_verified_metadata_gates_percentage_comparison(client):
    login(client)
    first, second = assessment(), assessment("OTHER_2025", 2025)
    student = result(first, "A", Decimal(20)).student
    result(second, "A", Decimal(10), student=student)
    params = {"tab": "compare", "assessment": first.pk, "compare_assessment": second.pk, "compare_mode": "percentage"}
    response = client.get(reverse("rankings:analysis"), params)
    assert response.context["comparison"]["mode"] == "percentile"
    for event, maximum in [(first, Decimal(40)), (second, Decimal(20))]:
        AssessmentAnalysisMetadata.objects.create(
            assessment=event, family="MATCHED", definition="Reviewed paper", definition_verified=True,
        )
        AssessmentCategoryScale.objects.create(
            assessment=event,
            band="PIONEER",
            max_score=maximum,
            verified=True,
            comparable_scope="same level",
            evidence="Reviewed maximum",
        )
    response = client.get(reverse("rankings:analysis"), params)
    assert response.context["comparison"]["mode"] == "percentage"
    assert response.context["panels"][0]["points"][0]["x"] == 50
    assert response.context["panels"][0]["points"][0]["y"] == 50


def test_student_history_percentiles_reference_full_cohort_and_undated_records_stay_undated(client):
    login(client)
    event = assessment()
    selected = result(event, "A", Decimal(30))
    result(event, "B", Decimal(10))
    response = client.get(reverse("rankings:analysis"), {"tab": "students", "student": selected.student_id})
    history = response.context["student_panel"]["rows"][0]
    assert history["percentile"] == Decimal(75)
    assert history["date"] is None
    assert "date not recorded" in response.content.decode()


@pytest.mark.parametrize(
    "params",
    [
        {"assessment": "9999999999999999999"},
        {"band": "forged"},
        {"tab": "forged"},
        {"order": "full_nric"},
        {"school_basis": "source_notes"},
        {"season": "invalid"},
        {"birth_year": 9999},
    ],
)
def test_invalid_filters_are_explicit_and_never_fall_back_silently(client, params):
    login(client)
    event = assessment()
    result(event, "A", Decimal(10))
    response = client.get(reverse("rankings:analysis"), params)
    assert response.status_code == 400
    assert "Correct the highlighted filters" in response.content.decode()


def test_full_export_sort_order_scope_metadata_formula_safety_and_privacy(client):
    login(client)
    event = assessment()
    for index in range(52):
        result(event, f"Student {index:02}", Decimal(index))
    dangerous = result(event, '=HYPERLINK("bad")', Decimal(99))
    params = {"order": "-score", "page": 2, "format": "csv"}
    response = client.get(reverse("rankings:analysis_export"), params)
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:2] == ["Category rank", "Student"]
    assert rows[1][1].startswith("'=HYPERLINK")
    assert rows[1][4] == "99.00"
    assert rows[54] == []
    text = response.content.decode()
    assert "Full filtered table, all pages" in text
    assert all(value not in text for value in ["PRIVATE-NRIC", "PRIVATE-FAMILY-NOTE", "PRIVATE-REMARK", "2012-02-03"])
    params["format"] = "xlsx"
    response = client.get(reverse("rankings:analysis_export"), params)
    book = load_workbook(io.BytesIO(response.content))
    assert book["Analysis"].max_row == 54
    assert book["Analysis"].cell(2, 2).value.startswith("'=HYPERLINK")
    assert "Report metadata" in book.sheetnames
    assert dangerous.student_id


def test_quality_review_preserves_confirmed_separate_identities(client):
    login(client)
    event = assessment()
    first = result(event, "Same Name", Decimal(10)).student
    second = result(event, "Same Name", Decimal(12)).student
    StudentIdentityReview.objects.create(
        first_student=first, second_student=second, decision="confirmed_separate", evidence="Explicit instruction",
    )
    response = client.get(reverse("rankings:analysis"), {"tab": "quality", "issue": "duplicate"})
    assert response.status_code == 200
    assert "Confirmed separate" in response.content.decode()
    assert response.context["page_obj"].paginator.count == 1
    assert Student.objects.count() == 2


def test_data_loading_query_count_does_not_grow_per_result():
    event = assessment()
    for index in range(5):
        result(event, str(index), Decimal(index))
    with CaptureQueriesContext(connection) as small:
        load_records(assessment_ids=[event.pk])
    for index in range(5, 30):
        result(event, str(index), Decimal(index))
    with CaptureQueriesContext(connection) as larger:
        loaded = load_records(assessment_ids=[event.pk])
    assert len(loaded) == 30
    assert len(small) == len(larger)
    assert len(larger) <= 5


def test_undated_multiple_assessments_do_not_invent_latest_outcome(client):
    login(client)
    first, second = assessment(), assessment("CST_2026")
    student = result(first, "A", Decimal(10)).student
    result(second, "A", Decimal(12), student=student)
    response = client.get(reverse("rankings:analysis"), {"tab": "students", "assessment": ""})
    assert "chronological order not verified" in response.content.decode()


def test_invalid_student_id_is_an_explicit_filter_error(client):
    login(client)
    event = assessment()
    result(event, "A", Decimal(10))
    response = client.get(reverse("rankings:analysis"), {"tab": "students", "student": 999999})
    assert response.status_code == 400
    assert "does not exist" in response.content.decode()


def test_chart_drilldown_filters_preserve_exact_zero_and_reference_rank(client):
    from urllib.parse import urlsplit

    login(client)
    event = assessment()
    result(event, "A", Decimal(0))
    result(event, "B", Decimal(0))
    response = client.get(reverse("rankings:analysis"))
    url = response.context["panels"][0]["links"][0]
    response = client.get(urlsplit(url).path + "?" + urlsplit(url).query)
    assert response.status_code == 200
    assert response.context["summary"]["records"] == 2
    assert [row["rank"] for row in response.context["all_rows"]] == [1, 1]


def test_unknown_category_histogram_drilldown_is_distinct_from_all_categories(client):
    from urllib.parse import urlsplit

    login(client)
    event = assessment()
    result(event, "Unknown A", Decimal(5), band="")
    result(event, "Unknown B", Decimal(5), band="")
    result(event, "Pioneer", Decimal(5), band="PIONEER")
    response = client.get(reverse("rankings:analysis"))
    assert response.context["summary"]["records"] == 3
    assert not response.context["has_drilldown"]
    panel = next(
        panel for panel in response.context["panels"]
        if panel["id"].startswith("hist-") and "Category not recorded" in panel["title"]
    )
    assert "band_missing=True" in panel["links"][0]
    target = urlsplit(panel["links"][0])
    response = client.get(target.path + "?" + target.query)
    assert response.status_code == 200
    assert response.context["summary"]["records"] == 2
    assert {row["name"] for row in response.context["all_rows"]} == {"Unknown A", "Unknown B"}
    assert response.context["has_drilldown"]


def test_unknown_comparison_categories_have_their_own_matched_cohorts(client):
    login(client)
    first, second = assessment(), assessment("CST_2026")
    for index in range(10):
        student = result(first, f"Unknown {index}", Decimal(index), band="").student
        result(second, student.full_name, Decimal(index + 1), band="", student=student)
    pioneer = result(first, "Pioneer", Decimal(99), band="PIONEER").student
    result(second, pioneer.full_name, Decimal(0), band="PIONEER", student=pioneer)
    params = {
        "tab": "compare", "assessment": first.pk, "compare_assessment": second.pk,
        "band_missing": True, "compare_band_missing": True,
    }
    response = client.get(reverse("rankings:analysis"), params)
    assert response.status_code == 200
    assert response.context["comparison"]["matched"] == 10
    assert response.context["comparison"]["correlation"] == pytest.approx(1)
    assert all(row["name"].startswith("Unknown") for row in response.context["all_rows"])
    params["band"] = "PIONEER"
    assert client.get(reverse("rankings:analysis"), params).status_code == 400


@pytest.mark.parametrize("mode", ["raw", "percentage"])
def test_multiple_verified_category_scales_are_not_pooled_in_raw_or_percentage_view(client, mode):
    login(client)
    first, second = assessment(), assessment("CST_2026")
    for event in (first, second):
        AssessmentAnalysisMetadata.objects.create(
            assessment=event, family="Competition", definition="Reviewed", definition_verified=True,
        )
        for band, maximum in [("GROUP A", 40), ("GROUP B", 100)]:
            AssessmentCategoryScale.objects.create(
                assessment=event, band=band, max_score=maximum, verified=True,
                comparable_scope=band, evidence="Verified paper definition",
            )
    for band, start in [("GROUP A", 5), ("GROUP B", 80)]:
        for index in range(12):
            student = result(first, f"{band} Student {index}", Decimal(start + index), band=band).student
            result(second, student.full_name, Decimal(start + index + 1), band=band, student=student)
    params = {
        "tab": "compare", "assessment": first.pk, "compare_assessment": second.pk, "compare_mode": mode,
    }
    response = client.get(reverse("rankings:analysis"), params)
    assert response.status_code == 200
    comparison = response.context["comparison"]
    assert comparison["matched"] == 24
    assert comparison["mode"] == "percentile"
    assert not comparison["comparable"]
    assert comparison["correlation"] is None
    assert "exactly one matched category pair" in comparison["note"]
    assert response.context["panels"][0]["unit"] == "percentile"
    params.update(band="GROUP A", compare_band="GROUP A")
    response = client.get(reverse("rankings:analysis"), params)
    assert response.context["comparison"]["mode"] == mode
    assert response.context["comparison"]["matched"] == 12
    assert response.context["comparison"]["correlation"] == pytest.approx(1)


def test_school_review_preserves_chinese_names_in_similarity_keys(client):
    event = assessment()
    first = School.objects.create(name="SJKC 中华")
    second = School.objects.create(name="SJKC 新华")
    result(event, "Synthetic A", 10, school=first)
    result(event, "Synthetic B", 20, school=second)
    login(client)
    response = client.get(reverse("rankings:analysis"), {"tab": "quality", "issue": "aliases"})
    assert response.status_code == 200
    assert b"Similar school labels" not in response.content
