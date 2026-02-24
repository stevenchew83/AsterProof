from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from inspinia.backoffice.models import Report
from inspinia.catalog.models import Contest
from inspinia.catalog.models import Problem
from inspinia.community.models import PublicSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _make_problem():
    code = f"MOCK-{uuid4().hex[:8]}"
    contest = Contest.objects.create(name="Mock", short_code=code, contest_type="custom", year=2025)
    return Problem.objects.create(contest=contest, label="P1", title="Sample", statement="Sample statement")


def test_backoffice_dashboard_requires_moderator(client):
    user = UserFactory()
    client.force_login(user)
    response = client.get(reverse("backoffice:dashboard"))
    assert response.status_code == 403


def test_backoffice_dashboard_for_moderator(client):
    user = UserFactory(is_staff=True)
    group, _ = Group.objects.get_or_create(name="moderator")
    user.groups.add(group)
    client.force_login(user)
    response = client.get(reverse("backoffice:dashboard"))
    assert response.status_code == 200


def test_muted_user_cannot_create_solution(client):
    user = UserFactory()
    user.mute_expires_at = timezone.now() + timedelta(days=1)
    user.save(update_fields=["mute_expires_at"])
    problem = _make_problem()
    client.force_login(user)
    response = client.post(
        reverse("community:create_solution", kwargs={"problem_id": problem.id}),
        data={"title": "T", "content": "C"},
    )
    assert response.status_code == 403


def test_shadow_ban_hides_solution_from_others(client):
    shadow_user = UserFactory(is_shadow_banned=True)
    other_user = UserFactory()
    problem = _make_problem()

    PublicSolution.objects.create(
        problem=problem,
        author=shadow_user,
        title="Hidden",
        content="Hidden content",
        is_hidden=True,
    )

    client.force_login(other_user)
    response = client.get(reverse("community:problem_solutions", kwargs={"problem_id": problem.id}))
    assert "Hidden content" not in response.content.decode()


def test_problem_report_creation(client):
    reporter = UserFactory()
    problem = _make_problem()
    client.force_login(reporter)
    response = client.post(reverse("catalog:report_problem", kwargs={"problem_id": problem.id}), data={"reason_code": "spam"})
    assert response.status_code == 302
    assert Report.objects.filter(
        reporter=reporter,
        content_type=ContentType.objects.get_for_model(Problem),
        object_id=problem.id,
    ).exists()


def test_readonly_user_cannot_update_progress(client):
    user = UserFactory(is_readonly=True)
    problem = _make_problem()
    client.force_login(user)
    response = client.post(
        reverse("progress:update_status", kwargs={"problem_id": problem.id}),
        data={"status": "attempted"},
    )
    assert response.status_code == 403
