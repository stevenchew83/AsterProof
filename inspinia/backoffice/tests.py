from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from inspinia.backoffice.models import ProblemIngestionStatus
from inspinia.backoffice.models import ProblemSubmission
from inspinia.backoffice.models import Report
from inspinia.catalog.models import Contest
from inspinia.catalog.models import Problem
from inspinia.community.models import PublicSolution
from inspinia.core.permissions import ADMIN_GROUP
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


def test_accept_submission_copies_statement_format_and_plaintext(client):
    admin_user = UserFactory(is_staff=True)
    admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
    admin_user.groups.add(admin_group)
    client.force_login(admin_user)

    submission = ProblemSubmission.objects.create(
        submitter=admin_user,
        title="Latex P",
        statement=r"Prove that $\frac{a}{b} > 0$.",
        statement_format=ProblemSubmission.StatementFormat.LATEX,
        statement_plaintext="Prove that a b > 0.",
        proposed_difficulty=4,
    )

    response = client.post(
        reverse("backoffice:ingestion_problem_submission_action", kwargs={"submission_id": submission.id}),
        data={"action": "accept"},
    )
    assert response.status_code == 302

    submission.refresh_from_db()
    assert submission.status == ProblemIngestionStatus.ACCEPTED
    assert submission.linked_problem is not None
    assert submission.linked_problem.statement_format == Problem.StatementFormat.LATEX
    assert submission.linked_problem.statement_plaintext == "Prove that a b > 0."


def test_accept_submission_rejects_disallowed_latex_commands(client):
    admin_user = UserFactory(is_staff=True)
    admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
    admin_user.groups.add(admin_group)
    client.force_login(admin_user)

    submission = ProblemSubmission.objects.create(
        submitter=admin_user,
        title="Dangerous Latex",
        statement=r"\input{secret.tex}",
        statement_format=ProblemSubmission.StatementFormat.LATEX,
        proposed_difficulty=4,
    )

    response = client.post(
        reverse("backoffice:ingestion_problem_submission_action", kwargs={"submission_id": submission.id}),
        data={"action": "accept"},
    )
    assert response.status_code == 302

    submission.refresh_from_db()
    assert submission.status == ProblemIngestionStatus.NEW
    assert submission.linked_problem is None


def test_problem_set_import_requires_admin(client):
    moderator = UserFactory(is_staff=True)
    mod_group, _ = Group.objects.get_or_create(name="moderator")
    moderator.groups.add(mod_group)
    client.force_login(moderator)

    response = client.get(reverse("backoffice:problem_set_import"))
    assert response.status_code == 403


def test_problem_set_import_creates_problem_submissions(client):
    admin_user = UserFactory(is_staff=True)
    admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
    admin_user.groups.add(admin_group)
    client.force_login(admin_user)

    short_code = f"CSV-{uuid4().hex[:8]}"
    csv_content = (
        "title,statement,statement_format,source_reference,proposed_tags,proposed_difficulty,contest_short_code,contest_name,contest_year\n"
        f"CSV Plain,Prove 1+1=2.,plain,https://example.com/a,\"algebra,number theory\",2,{short_code},CSV Contest,2025\n"
        f"CSV Latex,\"Prove that $a=b$.\",latex,https://example.com/b,algebra,4,{short_code},CSV Contest,2025\n"
    )
    upload = SimpleUploadedFile("problem_import.csv", csv_content.encode("utf-8"), content_type="text/csv")

    response = client.post(reverse("backoffice:problem_set_import"), data={"problem_csv": upload})
    assert response.status_code == 200

    imported_rows = ProblemSubmission.objects.filter(submitter=admin_user).order_by("title")
    assert imported_rows.count() == 2
    assert imported_rows[0].contest is not None
    assert imported_rows[0].contest.short_code == short_code
