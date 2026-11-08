from datetime import timedelta
from http import HTTPStatus
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.admin_reviews import take_down
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
CONTEST = "IMO Shortlist"


def _statement(code, *, year=2025, day="", linked=True, active=True):
    problem = (
        ProblemSolveRecord.objects.create(contest=CONTEST, year=year, problem=code)
        if linked else None
    )
    return ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=CONTEST, contest_year=year,
        problem_code=code, problem_number=1, day_label=day, is_active=active,
        statement_latex="Prove that every square is nonnegative.",
    )


def _review(author, statement, score, *, published=True, self_requested=False):
    solution, created = ProblemSolution.objects.get_or_create(
        problem=statement.linked_problem, author=author,
        defaults={"status": ProblemSolution.Status.SUBMITTED},
    )
    if created:
        solution.blocks.create(position=1, body_source="This private source must stay out of dashboard HTML.")
    data = forum.current_target_data(solution)
    target = forum._target(solution, {"target_key": data["key"]})  # noqa: SLF001
    review = AdminSolutionReview.objects.create(
        target=target, solver=author, problem_label=problem_label(solution),
        batch_id=uuid4(), key_version=uuid4(), model="gpt-6.1-sol", output_limit=1000,
        status=AdminSolutionReview.Status.COMPLETED, score=score,
        published_at=timezone.now() if published else None,
        feedback="This private feedback must stay out of dashboard HTML.",
    )
    if self_requested:
        SelfSolutionReviewUsage.objects.create(
            user=author, review=review, problem_uuid=statement.problem_uuid, batch_id=review.batch_id,
        )
    return review


def _dashboard(client, **params):
    return client.get(reverse("pages:contest_advanced_dashboard"), {"contest": CONTEST, **params})


def _cells(response):
    return {
        (row["year"], cell["problem_code"]): cell
        for row in response.context["contest_completion_heatmap"]["rows"]
        for cell in row["cells"]
    }


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.TRAINER, User.Role.MODERATOR])
def test_nonadmins_cannot_request_learner_selection_or_lookup(client, settings, debug, role):
    settings.DEBUG = debug
    subject = UserFactory()
    client.force_login(UserFactory(role=role))
    assert _dashboard(client, learner=subject.pk).status_code == HTTPStatus.FORBIDDEN
    lookup = reverse("pages:contest_progress_learner_options")
    assert client.get(lookup, {"q": subject.email}).status_code == HTTPStatus.FORBIDDEN


def test_django_staff_flag_does_not_grant_learner_access(client):
    client.force_login(UserFactory(is_staff=True, role=User.Role.NORMAL))
    assert _dashboard(client, learner=UserFactory().pk).status_code == HTTPStatus.FORBIDDEN
    lookup = reverse("pages:contest_progress_learner_options")
    assert client.get(lookup, {"q": "demo"}).status_code == HTTPStatus.FORBIDDEN


def test_dashboard_preserves_login_and_approval_guards(client):
    dashboard = reverse("pages:contest_advanced_dashboard")
    lookup = reverse("pages:contest_progress_learner_options")
    assert client.get(dashboard).url.startswith(reverse(settings.LOGIN_URL))
    assert client.get(lookup).url.startswith(reverse(settings.LOGIN_URL))
    client.force_login(UserFactory(is_approved=False))
    assert client.get(dashboard).url == reverse("users:approval_pending")
    assert client.get(lookup).url == reverse("users:approval_pending")


@pytest.mark.parametrize("superuser", [False, True])
def test_admin_lookup_is_bounded_private_and_includes_zero_activity_accounts(client, superuser):
    client.force_login(UserFactory(role=User.Role.NORMAL if superuser else User.Role.ADMIN, is_superuser=superuser))
    named = UserFactory(name="Unique Learner", email="demo-hidden@example.test")
    first = UserFactory(name="Shared Learner", email="demo-first@example.test")
    second = UserFactory(name=" shared learner ", email="demo-second@example.test")
    UserFactory(name="Unapproved Learner", is_approved=False, email="demo-blocked@example.test")
    UserFactory(name="Inactive Learner", is_active=False, email="demo-inactive@example.test")
    unapproved_admin = UserFactory(role=User.Role.ADMIN, is_approved=False, name="Active Admin")
    lookup = reverse("pages:contest_progress_learner_options")

    response = client.get(lookup, {"q": "learner"})
    assert response.status_code == HTTPStatus.OK
    assert {"no-store", "private"} <= set(response["Cache-Control"].split(", "))
    results = {row["id"]: row["label"] for row in response.json()["results"]}
    assert set(results) == {named.pk, first.pk, second.pk}
    assert results[named.pk] == named.name
    assert results[first.pk] == "Shared Learner (demo-first@example.test)"
    assert client.get(lookup, {"q": "demo-hidden@"}).json()["results"] == [{"id": named.pk, "label": named.name}]
    assert client.get(lookup, {"q": "Active Admin"}).json()["results"] == [
        {"id": unapproved_admin.pk, "label": unapproved_admin.name},
    ]
    assert client.get(lookup, {"q": "a"}).json() == {"results": [], "has_more": False}
    for i in range(21):
        UserFactory(name=f"Lookup sample {i}")
    results = client.get(lookup, {"q": "Lookup sample"}).json()
    assert len(results["results"]) == 20  # noqa: PLR2004 - The external lookup cap.
    assert results["has_more"]
    assert client.post(lookup).status_code == HTTPStatus.METHOD_NOT_ALLOWED

    _statement("A1", linked=False)
    response = _dashboard(client, learner=named.pk)
    assert response.status_code == HTTPStatus.OK
    assert response.context["selected_learner_label"] == named.name
    assert response.context["contest_stats"]["solved_problem_total"] == 0


def test_unavailable_admin_targets_have_the_same_recovery(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    inactive, pending = UserFactory(is_active=False), UserFactory(is_approved=False)
    recovery = reverse("pages:contest_advanced_dashboard") + "?contest=IMO+Shortlist"
    for value in ("invalid", "-1", "9999999999999999999", inactive.pk, pending.pk, 999999):
        response = _dashboard(client, learner=value)
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "no-store" in response["Cache-Control"]
        assert response.context["my_progress_url"] == recovery
        assert response.context["learner_unavailable"]


def test_selected_learner_and_self_use_separate_completion_and_published_scores(client):
    admin = UserFactory(role=User.Role.ADMIN, name="Admin Demo")
    subject = UserFactory(name="Learner Demo")
    other = UserFactory()
    reviewed, done, draft = _statement("A1"), _statement("C1"), _statement("G1")
    inactive = _statement("N1", active=False)
    UserProblemCompletion.objects.create(user=subject, problem=reviewed.linked_problem)
    UserProblemCompletion.objects.create(
        user=subject, statement=reviewed, status=UserProblemCompletion.Status.ATTEMPTED,
    )
    UserProblemCompletion.objects.create(user=subject, problem=done.linked_problem)
    UserProblemCompletion.objects.create(user=subject, statement=inactive)
    UserProblemCompletion.objects.create(user=admin, statement=reviewed)
    UserProblemCompletion.objects.create(user=other, statement=draft)
    _review(subject, reviewed, 0)
    _review(subject, reviewed, 7, published=False)
    _review(subject, draft, 7, published=False)
    _review(subject, inactive, 6)
    admin_review = _review(admin, reviewed, 5)
    _review(other, draft, 6)
    client.force_login(admin)

    response = _dashboard(client, learner=subject.pk)
    assert response.status_code == HTTPStatus.OK
    assert {"no-store", "private"} <= set(response["Cache-Control"].split(", "))
    stats = response.context["contest_stats"]
    assert (stats["solved_problem_total"], stats["problem_count"], stats["ai_reviewed_total"]) == (1, 3, 1)
    assert stats["average_ai_score"] == 0
    assert stats["solution_problem_total"] == 1  # The admin's solution, independent of selected learner.
    assert response.context["year_rows"][0]["solved_problem_total"] == 1
    cells = _cells(response)
    first = cells[2025, "A1"]
    assert (first["display"], first["state"], first["tone"]) == (0, "unsolved", "low")
    assert cells[2025, "C1"]["tone"] == "unscored"
    assert cells[2025, "G1"]["entries"][0]["review_label"] == "No published score"
    assert not cells[2025, "A1"]["entries"][0]["workspace_url"]
    assert b"Read-only learner view" in response.content
    assert b"This private" not in response.content
    # The shared sidebar still links to Quick completions; the learner view itself must not.
    assert response.context["contest_quick_update_url"] == ""
    assert reverse("pages:contest_dashboard_listing") in response.context["year_rows"][0]["year_detail_url"]

    own = _dashboard(client, learner=admin.pk)
    assert own.context["selected_learner_id"] == ""
    assert own.context["contest_quick_update_url"]
    assert _cells(own)[2025, "A1"]["display"] == admin_review.score
    assert _cells(own)[2025, "A1"]["show_completion_mark"]

    client.force_login(subject)
    own = _dashboard(client)
    assert not own.context["can_select_learner"]
    assert not own.context["learner_options_url"]
    assert _cells(own)[2025, "A1"]["display"] == 0


def test_shortlist_groups_duplicate_cells_modes_and_score_boundaries(client):
    subject = UserFactory()
    client.force_login(subject)
    for code, score in [("A1", 0), ("A2", 2), ("C1", 3), ("C2", 5), ("G1", 6), ("N1", 7)]:
        _review(subject, _statement(code), score)
    first = _statement("A3", day="Day 1")
    second = _statement("A3", day="Day 2")
    UserProblemCompletion.objects.create(user=subject, statement=first)
    _review(subject, first, 7)
    _review(subject, second, 2)
    _statement("P1", year=2024, linked=False)

    response = _dashboard(client)
    cells = _cells(response)
    assert [cells[2025, c]["tone"] for c in ("A1", "A2", "C1", "C2", "G1", "N1")] == [
        "low", "low", "mid", "mid", "high", "high",
    ]
    assert cells[2025, "P1"]["state"] == "empty"
    assert [group["label"] for group in response.context["contest_completion_heatmap"]["problem_code_groups"]] == [
        "Algebra", "Combinatorics", "Geometry", "Number theory", "Other",
    ]
    multiple = cells[2025, "A3"]
    assert (multiple["display"], multiple["tone"], multiple["state"], multiple["score"]) == (
        "1/2", "multiple", "partial", None,
    )
    assert [(entry["day_label"], entry["score"]) for entry in multiple["entries"]] == [("Day 1", 7), ("Day 2", 2)]

    completion = _dashboard(client, mode="completion", focus="low")
    assert completion.context["focus"] == ""
    assert _cells(completion)[2025, "A1"]["tone"] == "incomplete"
    assert _cells(completion)[2025, "A1"]["entries"][0]["score"] == 0
    assert _cells(_dashboard(client, focus="low"))[2025, "A3"]["highlighted"]


def test_suggestions_find_older_years_and_keep_summary_for_the_whole_contest(client):
    learner, admin = UserFactory(), UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    for year in range(2015, 2026):
        _statement("A1", year=year, linked=False)
    oldest = _statement("G1", year=2015)
    scored = _statement("C1", year=2025)
    _review(learner, oldest, 2)
    _review(learner, scored, 6)
    UserProblemCompletion.objects.create(user=learner, statement=oldest)
    UserProblemCompletion.objects.create(user=learner, statement=_statement("N1", year=2016))

    response = _dashboard(client, learner=learner.pk)
    years = [row["year"] for row in response.context["contest_completion_heatmap"]["rows"]]
    assert years == list(range(2025, 2017, -1))
    assert parse_qs(urlsplit(response.context["next_year_page_url"]).query) == {
        "contest": [CONTEST], "learner": [str(learner.pk)], "year_page": ["2"],
    }
    earlier = client.get(response.context["next_year_page_url"])
    assert (2015, "G1") in _cells(earlier)

    low = client.get(response.context["low_focus_url"])
    assert {key for key, cell in _cells(low).items() if cell.get("highlighted")} == {(2015, "G1")}
    assert low.context["contest_stats"] == response.context["contest_stats"]
    unscored = client.get(response.context["unscored_focus_url"])
    assert {key for key, cell in _cells(unscored).items() if cell.get("highlighted")} == {(2016, "N1")}
    invalid = _dashboard(client, learner=learner.pk, mode="other", focus="other", year_page="200")
    assert (invalid.context["mode"], invalid.context["focus"], invalid.context["year_page"]) == ("score", "", 1)


def test_restricted_self_review_does_not_leak_through_admin_dashboard_metrics_or_suggestions(client):
    learner, admin = UserFactory(), UserFactory(role=User.Role.ADMIN)
    statement = _statement("A1")
    _review(learner, statement, 2, self_requested=True)
    UserProblemCompletion.objects.create(user=learner, statement=statement)
    now = timezone.now()
    AssistancePolicy.objects.create(
        problem_uuid=statement.problem_uuid, actor_id_scope=learner.pk, mode="restricted_assessment",
        starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=5),
    )
    client.force_login(admin)
    response = _dashboard(client, learner=learner.pk, focus="low")
    assert response.context["contest_stats"]["ai_reviewed_total"] == 0
    assert response.context["contest_stats"]["average_ai_score"] is None
    assert response.context["low_score_total"] == 0
    assert not _cells(response)
    unscored = _dashboard(client, learner=learner.pk, focus="unscored")
    assert unscored.context["unscored_completed_total"] == 1
    assert _cells(unscored)[2025, "A1"]["entries"][0]["review_label"] == "No published score"


def test_taken_down_review_disappears_from_the_learner_heatmap_and_totals(client):
    learner = UserFactory()
    admin = UserFactory(role=User.Role.ADMIN)
    statement = _statement("A1")
    review = _review(learner, statement, 0)
    client.force_login(admin)

    before = _dashboard(client, learner=learner.pk)
    assert _cells(before)[2025, "A1"]["score"] == 0
    assert before.context["low_score_total"] == 1

    assert take_down(admin, review.target.solution_id, review.pk, review.published_at.isoformat())

    after = _dashboard(client, learner=learner.pk)
    assert _cells(after)[2025, "A1"]["entries"][0]["review_label"] == "No published score"
    assert after.context["contest_stats"]["ai_reviewed_total"] == 0
    assert after.context["contest_stats"]["average_ai_score"] is None
    assert after.context["low_score_total"] == 0

    client.force_login(learner)
    assert _cells(_dashboard(client))[2025, "A1"]["score"] is None
