"""Reviewed school changes appear in fresh Results and History reads."""

from decimal import Decimal

import pytest
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ResultSchoolAttribution
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.school_display import SOURCE_SCHOOL_PREFIX
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def school_record(client):
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    current = School.objects.create(name="Current school")
    event = Assessment.objects.create(code="SCHOOL_2026", display_name="School event", season_year=2026)
    student = Student.objects.create(full_name="School fixture", school=current)
    result = StudentResult.objects.create(
        student=student, assessment=event, raw_score=Decimal(0), band="PIONEER",
        remarks=SOURCE_SCHOOL_PREFIX + "Source school",
    )
    StudentResult.objects.create(
        student=Student.objects.create(full_name="Higher score"), assessment=event,
        raw_score=Decimal(10), band="PIONEER",
    )
    return result


@pytest.mark.parametrize("verified", [False, True])
def test_only_verified_attribution_overrides_source_school(client, school_record, verified):
    result = school_record
    original_links = (result.student_id, result.assessment_id, result.remarks)
    reviewed = School.objects.create(name="Reviewed event school")
    ResultSchoolAttribution.objects.create(result=result, school=reviewed, verified=verified, evidence="Review")
    response = client.get(reverse("rankings:assessment_results"), {"q": "School fixture"})
    row = response.context["page_obj"][0]
    assert row.school_display == (reviewed.name if verified else "Source school")
    assert row.category_rank == 2  # noqa: PLR2004
    assert row.raw_score == 0
    result.refresh_from_db()
    assert (result.student_id, result.assessment_id, result.remarks) == original_links
    history = client.get(reverse("rankings:result_history"), {"q": "School fixture"})
    assert history.context["rows"][0]["student"].school_display == "Current school"


@pytest.mark.parametrize("active", [False, True])
def test_aliases_are_visible_and_searchable_without_rewriting_links(client, school_record, active):
    result = school_record
    canonical = School.objects.create(name="Canonical school")
    for alias in ("Source school", "Current school"):
        SchoolAlias.objects.create(alias=alias, normalized_name=alias.casefold(), school=canonical, active=active)
    for route, original in (("assessment_results", "Source school"), ("result_history", "Current school")):
        url = reverse(f"rankings:{route}")
        response = client.get(url, {"q": "School fixture", "school": canonical.name if active else original})
        assert response.context["page_obj"].paginator.count == 1
        if route == "assessment_results":
            label = response.context["page_obj"][0].school_display
        else:
            label = response.context["rows"][0]["student"].school_display
        assert label == (canonical.name if active else original)
        assert client.get(url, {"school": original}).context["page_obj"].paginator.count == 1
    detail = client.get(reverse("rankings:student_detail", args=[result.student_id]))
    assert detail.context["student"].school_display == (canonical.name if active else "Current school")
    result.student.refresh_from_db()
    assert result.student.school.name == "Current school"
