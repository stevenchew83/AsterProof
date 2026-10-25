from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_progress_catalog import sync_technique_progress_facts_for_statement
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def learners(settings):
    settings.DEBUG = False
    settings.SHARED_PROGRESS_LEARNERS = {"alex": "alex@example.com", "ben": "ben@example.com"}
    return {
        "alex": UserFactory(name="Alexander Chew", email="alex@example.com"),
        "ben": UserFactory(name="Ben", email="ben@example.com"),
        "other": UserFactory(name="Alex", email="other@example.com"),
    }


@pytest.fixture
def completions(learners):
    rows = {}
    for index, (slug, user) in enumerate(learners.items(), start=1):
        statement = ContestProblemStatement.objects.create(
            contest_name="IMO",
            contest_year=2026,
            problem_code=f"P{index}",
            problem_number=index,
            statement_latex=f"Problem for {slug}",
            topic="ALG",
        )
        rows[slug] = UserProblemCompletion.objects.create(
            user=user,
            statement=statement,
            completion_date=timezone.localdate(),
            status=UserProblemCompletion.Status.SOLVED,
        )
    return rows


def progress_url(learner, section="completions"):
    return reverse("pages:shared_progress_section", kwargs={"learner": learner, "section": section})


@pytest.mark.parametrize(("viewer", "subject"), [("alex", "ben"), ("ben", "alex")])
def test_shared_completions_use_subject_and_ignore_user_parameters(client, learners, completions, viewer, subject):
    client.force_login(learners[viewer])
    response = client.get(progress_url(subject), {"user": learners["other"].pk, "range": "all"})

    assert response.status_code == HTTPStatus.OK
    assert response.context["completion_progress_selected_user"] == learners[subject]
    assert response.context["completion_progress_can_edit_difficulty"] is False
    assert response.context["completion_progress_can_select_user"] is False
    assert response.context["completion_progress_reset_url"] == progress_url(subject)
    rows = response.context["completion_progress_rows"]
    assert [row["statement_uuid"] for row in rows] == [str(completions[subject].statement.statement_uuid)]
    html = response.content.decode()
    assert "Read-only progress" in html
    assert "Continue my training" in html
    assert "Compare" not in html
    assert 'id="completion-progress-user"' not in html
    assert 'data-can-edit-difficulty="false"' in html
    assert progress_url(viewer) in html


def test_shared_completion_export_is_scoped_to_subject(client, learners, completions):
    client.force_login(learners["alex"])
    response = client.get(progress_url("ben"), {"range": "all", "export": "csv", "user": learners["other"].pk})

    assert response.status_code == HTTPStatus.OK
    csv = response.content.decode()
    assert "ben@example.com" in csv
    assert "alex@example.com" not in csv
    assert "other@example.com" not in csv


@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.ADMIN])
def test_unrelated_accounts_cannot_access_shared_progress(client, learners, section, role):
    outsider = learners["other"]
    outsider.role = role
    outsider.save()
    client.force_login(outsider)
    response = client.get(progress_url("ben", section))
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_shared_progress_requires_login_and_approval(client, learners):
    response = client.get(progress_url("ben"))
    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("account_login"))
    alex = learners["alex"]
    alex.is_approved = False
    alex.save()
    client.force_login(alex)
    response = client.get(progress_url("ben"))
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


@pytest.mark.parametrize("field", ["is_active", "is_approved"])
def test_unavailable_peer_is_not_exposed(client, learners, field):
    ben = learners["ben"]
    setattr(ben, field, False)
    ben.save()
    client.force_login(learners["alex"])
    assert client.get(progress_url("ben")).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
def test_shared_progress_rejects_writes(client, learners, completions, section):
    client.force_login(learners["alex"])
    response = client.post(progress_url("ben", section), {"action": "import_completions", "status": "solved"})
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert UserProblemCompletion.objects.count() == len(completions)
    completions["ben"].refresh_from_db()
    assert completions["ben"].status == UserProblemCompletion.Status.SOLVED


def test_unknown_learner_and_section_return_not_found(client, learners):
    client.force_login(learners["alex"])
    assert client.get(progress_url("other")).status_code == HTTPStatus.NOT_FOUND
    assert client.get(progress_url("ben", "compare")).status_code == HTTPStatus.NOT_FOUND


def test_shared_technique_coverage_uses_peer_without_admin_controls(client, learners, completions):
    cache.clear()
    for completion in completions.values():
        StatementTopicTechnique.objects.create(
            statement=completion.statement,
            technique="POLYNOMIALS",
            domains=["ALG"],
            main_topic="ALG",
            canonical_subtopic="Polynomials",
        )
        sync_technique_progress_facts_for_statement(completion.statement_id)
    client.force_login(learners["alex"])
    response = client.get(progress_url("ben", "techniques"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["coverage"]["stats"]["completed_statement_total"] == 1
    assert response.context["coverage"]["subtopic_rows"][0]["solved"] == 1
    html = response.content.decode()
    assert "POLYNOMIALS" in html
    assert "Request rebuild" not in html
    assert "target_user_id" not in html
    assert progress_url("alex", "techniques") in html
    assert client.post(reverse("pages:technique_progress_catalog_rebuild")).status_code == HTTPStatus.FORBIDDEN


def test_shared_training_uses_subject_published_progress_and_distinct_accepted_problems(client, learners):
    topic = Topic.objects.create(title="Shared Algebra")
    subtopic = Subtopic.objects.create(topic=topic, title="Polynomials")
    material = Material.objects.create(subtopic=subtopic, title="Roots", content_markdown="Notes")
    problem = Problem.objects.create(subtopic=subtopic, title="Find roots", statement_markdown="Solve")
    MaterialCompletion.objects.create(user=learners["ben"], material=material, points_awarded=10)
    for _ in range(2):
        Submission.objects.create(
            user=learners["ben"],
            problem=problem,
            status=Submission.Status.PARTIALLY_ACCEPTED,
            solution_markdown="Private",
        )
    hidden = Subtopic.objects.create(topic=topic, title="Unpublished subtopic", is_published=False)
    Material.objects.create(subtopic=hidden, title="Private notes", content_markdown="Private")
    client.force_login(learners["alex"])
    response = client.get(progress_url("ben", "training"))

    assert response.status_code == HTTPStatus.OK
    row = next(row for row in response.context["training"]["topics"] if row["title"] == topic.title)
    assert row["completed"] == row["total"] == 2  # noqa: PLR2004
    assert row["percent"] == 100  # noqa: PLR2004
    assert response.context["training"]["next_subtopic"] is None
    html = response.content.decode()
    assert "Unpublished subtopic" not in html
    assert "Private" not in html
    assert "target_user_id" not in html
    own_response = client.get(progress_url("alex", "training"))
    own_topic = next(row for row in own_response.context["training"]["topics"] if row["title"] == topic.title)
    assert own_topic["completed"] == 0
    assert own_response.context["training"]["next_subtopic"]["title"] == "Polynomials"


def test_shared_sidebar_and_existing_editing_boundaries(client, learners, completions):
    client.force_login(learners["alex"])
    response = client.get(reverse("training:dashboard"))
    nav = response.content.decode().split('<ul class="side-nav">', 1)[1].split("<!-- Sidenav Menu End -->", 1)[0]
    assert "Alex's progress" in nav
    assert "Ben's progress" in nav
    assert reverse("pages:shared_progress", kwargs={"learner": "ben"}) in nav
    assert "Management" not in nav
    assert "My account" not in nav
    assert "Compare" not in nav
    assert "Training overview" in nav
    assert "Record completions" in nav
    response = client.get(reverse("pages:completion_quick_update"), {"target_user_id": learners["ben"].pk})
    assert response.context["completion_quick_update_selected_user"] == learners["alex"]
    assert client.get(reverse("pages:completion_progress_analytics")).status_code == HTTPStatus.FORBIDDEN


def test_duplicate_configured_identities_fail_closed(client, learners, settings):
    settings.SHARED_PROGRESS_LEARNERS = {"alex": "alex@example.com", "ben": "alex@example.com"}
    client.force_login(learners["alex"])
    assert client.get(progress_url("ben")).status_code == HTTPStatus.FORBIDDEN
