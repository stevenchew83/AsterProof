from datetime import timedelta
from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.shared_progress_views import shared_progress_comparison_view
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
    assert reverse("pages:shared_progress_comparison_section", kwargs={"section": "completions"}) in html
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


def test_shared_heading_uses_learner_label_when_display_name_is_blank(client, learners):
    ben = learners["ben"]
    ben.name = ""
    ben.save(update_fields=["name"])
    client.force_login(learners["alex"])
    response = client.get(progress_url("ben"))
    assert response.status_code == HTTPStatus.OK
    assert "Viewing Ben · Read-only progress" in response.content.decode()


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
    assert "Compare Alex &amp; Ben" in nav
    assert reverse("pages:shared_progress_comparison") in nav
    assert "Training overview" in nav
    assert "Record completions" in nav
    response = client.get(reverse("pages:completion_quick_update"), {"target_user_id": learners["ben"].pk})
    assert response.context["completion_quick_update_selected_user"] == learners["alex"]
    assert client.get(reverse("pages:completion_progress_analytics")).status_code == HTTPStatus.FORBIDDEN


def test_duplicate_configured_identities_fail_closed(client, learners, settings):
    settings.SHARED_PROGRESS_LEARNERS = {"alex": "alex@example.com", "ben": "alex@example.com"}
    client.force_login(learners["alex"])
    assert client.get(progress_url("ben")).status_code == HTTPStatus.FORBIDDEN


def compare_url(section="completions"):
    return reverse("pages:shared_progress_comparison_section", kwargs={"section": section})


@pytest.mark.parametrize("viewer", ["alex", "ben"])
@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
def test_comparison_is_available_to_both_learners_with_fixed_subjects(client, learners, completions, viewer, section):
    client.force_login(learners[viewer])
    response = client.get(compare_url(section), {"user": learners["other"].pk, "target_user_id": learners["other"].pk})
    assert response.status_code == HTTPStatus.OK
    assert response.context["shared_progress_is_comparison"] is True
    assert [row["user"] for row in response.context["shared_progress_learners"]] == [learners["alex"], learners["ben"]]
    assert "no-store" in response.headers["Cache-Control"]
    html = response.content.decode()
    assert "Read-only progress" in html
    assert '<h3 class="mb-1">Alex &amp; Ben</h3>' in html
    assert "Continue my training" in html
    assert "other@example.com" not in html
    assert "target_user_id" not in html
    assert progress_url("alex", section) in html
    assert progress_url("ben", section) in html


@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.ADMIN])
def test_comparison_denies_outsiders_including_admins(client, learners, section, role):
    outsider = learners["other"]
    outsider.role = role
    outsider.save()
    client.force_login(outsider)
    assert client.get(compare_url(section)).status_code == HTTPStatus.FORBIDDEN


def test_comparison_requires_login_and_approval(client, learners):
    response = client.get(reverse("pages:shared_progress_comparison"))
    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("account_login"))
    alex = learners["alex"]
    alex.is_approved = False
    alex.save()
    client.force_login(alex)
    assert client.get(compare_url()).url == reverse("users:approval_pending")


@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
@pytest.mark.parametrize("field", ["is_active", "is_approved"])
def test_comparison_requires_both_available_learners_and_hides_navigation(client, learners, section, field):
    ben = learners["ben"]
    setattr(ben, field, False)
    ben.save()
    client.force_login(learners["alex"])
    assert client.get(compare_url(section)).status_code == HTTPStatus.NOT_FOUND
    response = client.get(progress_url("alex", section))
    assert "Compare Alex &amp; Ben" not in response.content.decode()
    assert response.context["shared_progress_compare_url"] == ""


@pytest.mark.parametrize("peer_email", ["", "alex@example.com"])
def test_comparison_fails_closed_for_incomplete_or_duplicate_configuration(client, learners, settings, peer_email):
    settings.SHARED_PROGRESS_LEARNERS["ben"] = peer_email
    client.force_login(learners["alex"])
    assert client.get(compare_url()).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
def test_comparison_rejects_unsafe_methods(client, learners, completions, method, section):
    client.force_login(learners["alex"])
    response = getattr(client, method)(compare_url(section), {"status": "solved"})
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert UserProblemCompletion.objects.count() == len(completions)


@pytest.mark.parametrize("section", ["completions", "techniques", "training"])
def test_comparison_view_does_not_write_database_records(learners, completions, section):
    request = RequestFactory().get(compare_url(section))
    request.user = learners["alex"]
    request.session = {}
    with CaptureQueriesContext(connection) as queries:
        response = shared_progress_comparison_view(request, section=section)
    assert response.status_code == HTTPStatus.OK
    writes = [
        query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []


def test_comparison_deduplicates_each_learners_completions_independently(client, learners, completions):
    original = completions["alex"].statement
    duplicate = ContestProblemStatement.objects.create(
        contest_name="Duplicate",
        contest_year=2026,
        problem_code="P1",
        problem_number=1,
        statement_latex=original.statement_latex,
    )
    UserProblemCompletion.objects.create(user=learners["alex"], statement=duplicate)
    UserProblemCompletion.objects.create(
        user=learners["ben"], statement=original, completion_date=timezone.localdate(),
    )
    client.force_login(learners["alex"])
    response = client.get(compare_url(), {"range": "all"})
    stats = response.context["comparison_completion_stats"]
    assert stats["alex"]["solved_total"] == 1
    assert stats["ben"]["solved_total"] == 2  # noqa: PLR2004


def test_comparison_applies_identical_completion_filters_and_preserves_drilldowns(client, learners, completions):
    today = timezone.localdate()
    for slug, mohs in (("alex", 10), ("ben", 20)):
        statement = completions[slug].statement
        statement.mohs = mohs
        statement.save()
    old = ContestProblemStatement.objects.create(
        contest_name="IMO",
        contest_year=2025,
        problem_code="OLD",
        problem_number=1,
        statement_latex="Old completion",
        topic="ALG",
        mohs=12,
    )
    for slug in ("alex", "ben"):
        UserProblemCompletion.objects.create(
            user=learners[slug], statement=old, completion_date=today - timedelta(days=60),
        )
    client.force_login(learners["ben"])
    response = client.get(
        compare_url(),
        {
            "range": "custom",
            "start": today.isoformat(),
            "end": today.isoformat(),
            "contest": "IMO",
            "mohs_min": "15",
            "user": learners["other"].pk,
            "export": "csv",
        },
    )
    stats = response.context["comparison_completion_stats"]
    assert stats["alex"]["solved_total"] == 0
    assert stats["alex"]["average_mohs"] is None
    assert stats["ben"]["solved_total"] == 1
    assert stats["ben"]["average_mohs"] == 20  # noqa: PLR2004
    for learner in response.context["shared_progress_learners"]:
        assert "mohs_min=15" in learner["url"]
        assert "user=" not in learner["url"]
        assert "export=" not in learner["url"]
    assert response.headers["Content-Type"].startswith("text/html")
    individual = client.get(progress_url("alex"), {"range": "all", "contest": "IMO", "user": learners["other"].pk})
    assert individual.context["shared_progress_compare_url"] == compare_url() + "?range=all&contest=IMO"


def test_comparison_keeps_undated_records_visible_and_reports_empty_filters(client, learners, completions):
    ben = completions["ben"]
    ben.completion_date = None
    ben.save()
    client.force_login(learners["alex"])
    response = client.get(compare_url(), {"range": "7d"})
    assert response.context["comparison_completion_stats"]["ben"]["solved_total"] == 1
    assert response.context["comparison_completion_stats"]["ben"]["missing_date_total"] == 1
    response = client.get(compare_url(), {"q": "NO_MATCHING_PROBLEM"})
    assert "Neither learner has completion records matching these filters." in response.content.decode()


def test_comparison_pairs_technique_labels_and_reflects_changed_completions(client, learners, completions):
    cache.clear()
    for slug, technique in (("alex", "POLYNOMIALS"), ("ben", "ANGLE CHASE"), ("other", "MODULAR ARITHMETIC")):
        completion = completions[slug]
        StatementTopicTechnique.objects.create(
            statement=completion.statement,
            technique=technique,
            domains=["ALG"],
            main_topic="ALG",
            canonical_subtopic=technique.title(),
        )
        sync_technique_progress_facts_for_statement(completion.statement_id)
    client.force_login(learners["alex"])
    response = client.get(compare_url("techniques"))
    groups = {group["label"]: group["rows"] for group in response.context["comparison_coverage_groups"]}
    rows = {row["label"]: row for row in groups["Techniques"]}
    assert rows["POLYNOMIALS"]["alex"]["solved"] == 1
    assert rows["POLYNOMIALS"]["ben"]["solved"] == 0
    assert rows["ANGLE CHASE"]["alex"]["solved"] == 0
    assert rows["ANGLE CHASE"]["ben"]["solved"] == 1
    html = response.content.decode()
    assert "Request rebuild" not in html
    completions["ben"].status = UserProblemCompletion.Status.ATTEMPTED
    completions["ben"].save()
    response = client.get(compare_url("techniques"))
    assert response.context["comparison_coverage"]["ben"]["stats"]["completed_statement_total"] == 0


def test_comparison_training_uses_ids_and_counts_distinct_published_items(client, learners):
    first_topic = Topic.objects.create(title="Comparison Algebra", slug="comparison-algebra")
    second_topic = Topic.objects.create(title="Comparison Geometry", slug="comparison-geometry")
    first = Subtopic.objects.create(topic=first_topic, title="Foundations", slug="comparison-foundations-a")
    second = Subtopic.objects.create(topic=second_topic, title="Foundations", slug="comparison-foundations-b")
    first_material = Material.objects.create(subtopic=first, title="Algebra notes", content_markdown="Notes")
    second_material = Material.objects.create(subtopic=second, title="Geometry notes", content_markdown="Notes")
    problem = Problem.objects.create(subtopic=first, title="Checkpoint", statement_markdown="Solve")
    MaterialCompletion.objects.create(user=learners["alex"], material=first_material)
    for material in (first_material, second_material):
        MaterialCompletion.objects.create(user=learners["ben"], material=material)
    for _ in range(2):
        Submission.objects.create(
            user=learners["ben"],
            problem=problem,
            status=Submission.Status.PARTIALLY_ACCEPTED,
            solution_markdown="PRIVATE_SUBMISSION_MARKER",
        )
    hidden = Subtopic.objects.create(topic=first_topic, title="HIDDEN_SUBTOPIC_MARKER", is_published=False)
    Material.objects.create(subtopic=hidden, title="Hidden notes", content_markdown="Private")
    client.force_login(learners["alex"])
    response = client.get(compare_url("training"))
    totals = response.context["comparison_training_totals"][0]
    assert totals["alex"]["completed"] == 1
    assert totals["ben"]["completed"] == 3  # noqa: PLR2004
    assert totals["alex"]["total"] == totals["ben"]["total"] == 3  # noqa: PLR2004
    topics = {topic["title"]: topic for topic in response.context["comparison_training_topics"]}
    assert topics[first_topic.title]["subtopics"][0]["alex"]["completed"] == 1
    assert topics[second_topic.title]["subtopics"][0]["alex"]["completed"] == 0
    assert topics[second_topic.title]["subtopics"][0]["ben"]["completed"] == 1
    assert response.context["comparison_training"]["ben"]["next_subtopic"] is None
    html = response.content.decode()
    assert "PRIVATE_SUBMISSION_MARKER" not in html
    assert "HIDDEN_SUBTOPIC_MARKER" not in html


def test_comparison_default_and_unknown_routes(client, learners):
    client.force_login(learners["alex"])
    response = client.get(reverse("pages:shared_progress_comparison"))
    assert response.status_code == HTTPStatus.OK
    assert response.context["shared_progress_section"] == "completions"
    assert client.get(compare_url("unknown")).status_code == HTTPStatus.NOT_FOUND
    assert client.head(compare_url()).status_code == HTTPStatus.OK
