"""Shared problem identity, independent progress, and history-preserving reads."""

from datetime import date
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionRevision
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def problem(number=1, **fields):
    return ProblemSolveRecord.objects.create(
        year=2026, contest="Shared Cup", problem=f"P{number}", topic="ALG", mohs=5, **fields,
    )


def statement(number=1, **fields):
    return ContestProblemStatement.objects.create(
        contest_year=2026, contest_name="Shared Cup", problem_number=number,
        problem_code=f"P{number}", statement_latex="Prove $a=a$.", **fields,
    )


def library(client, **params):
    response = client.get(reverse("pages:problem_statement_list"), params)
    assert response.status_code == HTTPStatus.OK
    return response


def rows_by_uuid(response):
    return {row["problem_uuid"]: row for row in response.context["statement_table_rows"]}


def history_snapshot():
    return {
        model.__name__: list(model.objects.order_by("pk").values())
        for model in (
            ProblemSolveRecord, ContestProblemStatement, UserProblemCompletion,
            ProblemSolution, ProblemSolutionBlock, SolutionRevision,
        )
    }


def test_library_contains_all_sources_without_merging_matching_labels(client):
    client.force_login(UserFactory())
    attached = problem()
    uploaded = statement(linked_problem=attached)
    standalone = statement(2)
    older = problem(3)
    # Equal human labels are not proof of shared identity, even across the two stores.
    distinct_same_label = problem(2)

    response = library(client)

    assert set(rows_by_uuid(response)) == {
        str(row.problem_uuid) for row in (uploaded, standalone, older, distinct_same_label)
    }
    assert response.context["statement_total"] == len(rows_by_uuid(response))
    assert response.context["library_stats"]["missing_statements"] == 2  # noqa: PLR2004
    assert rows_by_uuid(response)[str(older.problem_uuid)]["has_statement"] is False
    html = response.content.decode()
    assert "Problem library" in html
    assert "My progress" in html
    assert "Statement missing" in html
    assert "Not linked" not in html
    assert "Recheck links" not in html
    assert ">Linked<" not in html
    assert ">Unlinked<" not in html


def test_record_only_workspace_keeps_compact_layout_without_link_diagnostics(client):
    client.force_login(UserFactory())
    older = problem()

    response = client.get(reverse("solutions:problem_solution_list", args=[older.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert 'class="solution-problem-layout' in html
    assert "Statement missing. Existing progress and solutions are retained." in html
    assert "A statement is needed before rating difficulty." in html
    assert "linked statement" not in html
    assert "Link a statement" not in html


def test_library_reads_preserve_uuids_completion_history_and_solution_revisions(client):
    viewer = UserFactory()
    client.force_login(viewer)
    older = problem()
    standalone = statement(2)
    UserProblemCompletion.objects.create(
        user=viewer, problem=older, completion_date=date(2024, 8, 2), post_mortem="Keep my notes",
    )
    UserProblemCompletion.objects.create(user=viewer, statement=standalone, completion_date=None)
    solution = ProblemSolution.objects.create(problem=older, author=viewer, title="Saved proof")
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="Original block")
    revision = SolutionRevision.objects.create(
        solution=solution, sequence=1, body_source="Original document", source_digest="a" * 64,
    )
    solution.current_revision = revision
    solution.save(update_fields=["current_revision"])
    before = history_snapshot()

    response = library(client)
    row = rows_by_uuid(response)[str(older.problem_uuid)]
    assert row["user_completion_date"] == "2024-08-02"
    assert row["problem_destination_url"] == reverse(
        "solutions:problem_solution_list", args=[older.problem_uuid],
    )
    library(client, q=str(standalone.problem_uuid))
    picker = client.get(reverse("solutions:problem_solution_create"))
    assert picker.status_code == HTTPStatus.OK
    assert any(row["editor_button_label"] == "My solutions" for row in picker.context["statement_problem_rows"])
    assert history_snapshot() == before


def test_existing_exact_uuid_reuses_history_without_relinking_on_get(client):
    viewer = UserFactory()
    client.force_login(viewer)
    older = problem()
    uploaded = statement(problem_uuid=older.problem_uuid)
    UserProblemCompletion.objects.create(user=viewer, problem=older, completion_date=date(2023, 2, 1))
    ProblemSolution.objects.create(problem=older, author=viewer, title="My original proof")
    before = history_snapshot()

    response = library(client)

    assert response.context["statement_total"] == 1
    row = rows_by_uuid(response)[str(older.problem_uuid)]
    assert row["user_completion_display"] == "2023-02-01"
    assert row["problem_destination_label"] == "View"
    assert response.context["library_stats"]["solved_total"] == 1
    assert history_snapshot() == before
    uploaded.refresh_from_db()
    assert uploaded.linked_problem_id is None


@pytest.mark.parametrize("status", [UserProblemCompletion.Status.ATTEMPTED, UserProblemCompletion.Status.UNATTEMPTED])
def test_personal_statement_progress_overrides_legacy_solved_state(client, status):
    viewer, other = UserFactory(), UserFactory()
    client.force_login(viewer)
    older = problem()
    uploaded = statement(linked_problem=older)
    UserProblemCompletion.objects.create(user=viewer, problem=older, completion_date=date(2025, 1, 1))
    UserProblemCompletion.objects.create(user=viewer, statement=uploaded, status=status)
    UserProblemCompletion.objects.create(user=other, statement=uploaded)

    response = library(client)

    assert response.context["library_stats"]["solved_total"] == 0
    assert rows_by_uuid(response)[str(uploaded.problem_uuid)]["user_completion_is_solved"] is False
    contest = client.get(reverse("pages:contest_advanced_dashboard"), {"contest": "Shared Cup"})
    assert contest.status_code == HTTPStatus.OK
    assert contest.context["contest_stats"]["solved_problem_total"] == 0
    assert contest.context["contest_completion_heatmap"]["rows"][0]["cells"][0]["state"] == "unsolved"


def test_selected_learner_changes_only_progress_and_never_exposes_private_solutions(client, settings):
    viewer = UserFactory(role=User.Role.ADMIN)
    alex, ben = UserFactory(), UserFactory()
    settings.SHARED_PROGRESS_LEARNERS = {"alex": alex.email, "ben": ben.email}
    client.force_login(viewer)
    older = problem()
    uploaded = statement(linked_problem=older)
    record_only = problem(2)
    UserProblemCompletion.objects.create(user=alex, statement=uploaded, completion_date=date(2024, 3, 1))
    UserProblemCompletion.objects.create(user=ben, problem=record_only)
    ProblemSolution.objects.create(problem=older, author=alex, title="Alex private title")
    ProblemSolution.objects.create(problem=record_only, author=ben, title="Ben private title")
    before = history_snapshot()

    own = library(client)
    alex_page = library(client, learner="alex", q="Shared")
    ben_page = library(client, learner="ben")

    assert own.context["library_stats"]["solved_total"] == 0
    assert alex_page.context["library_progress_label"] == "Alex's progress"
    assert alex_page.context["library_stats"]["solved_total"] == 1
    assert rows_by_uuid(alex_page)[str(older.problem_uuid)]["user_completion_display"] == "2024-03-01"
    assert rows_by_uuid(ben_page)[str(record_only.problem_uuid)]["user_completion_is_solved"] is True
    for response in (own, alex_page, ben_page):
        assert all(row["problem_destination_label"] == "Start" for row in rows_by_uuid(response).values())
        assert "private title" not in response.content.decode()
    assert alex_page.context["library_clear_url"].endswith("?learner=alex")
    assert "learner=alex" in alex_page.context["statement_active_filter_chips"][0]["remove_url"]
    assert "Alex's progress" in alex_page.context["statement_copy_tsv"].splitlines()[0]
    assert history_snapshot() == before


def test_ajax_filters_return_the_same_scoped_results_as_a_shareable_url(client, settings):
    viewer = UserFactory(role=User.Role.ADMIN, email="library-admin@example.test")
    alex = UserFactory(email="library-alex@example.test")
    ben = UserFactory(email="library-ben@example.test")
    settings.SHARED_PROGRESS_LEARNERS = {"alex": alex.email, "ben": ben.email}
    client.force_login(viewer)
    target = statement()
    problem(2)
    UserProblemCompletion.objects.create(user=alex, statement=target, completion_date=date(2026, 1, 1))
    params = {"q": str(target.problem_uuid), "year": "2026", "learner": "alex"}
    page = library(client, **params)

    fragment = client.get(
        reverse("pages:problem_statement_list"), params, headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert fragment.status_code == HTTPStatus.OK
    assert "X-Requested-With" in fragment.headers["Vary"]
    assert "no-store" in fragment.headers["Cache-Control"]
    assert rows_by_uuid(fragment) == rows_by_uuid(page)
    assert list(rows_by_uuid(fragment)) == [str(target.problem_uuid)]
    assert fragment.context["library_stats"]["solved_total"] == 1
    assert fragment.context["statement_copy_tsv"] == page.context["statement_copy_tsv"]
    assert b'id="statement-library"' in fragment.content
    assert b'id="statement-library-search"' in fragment.content
    assert b"Loaded 1 matching row" in fragment.content
    assert b"<html" not in fragment.content.lower()


@pytest.mark.parametrize("headers", [{}, {"X-Requested-With": "XMLHttpRequest"}])
@pytest.mark.parametrize("selector", ["alex", "999", "not-a-learner"])
def test_progress_selector_cannot_resolve_unapproved_users(client, settings, selector, headers):
    viewer, alex, ben = UserFactory(), UserFactory(), UserFactory()
    settings.SHARED_PROGRESS_LEARNERS = {"alex": alex.email, "ben": ben.email}
    client.force_login(viewer)
    response = client.get(reverse("pages:problem_statement_list"), {"learner": selector}, headers=headers)
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("slug", ["alex", "ben"])
def test_configured_learner_can_open_a_link_to_their_own_progress(client, settings, slug):
    learners = {name: UserFactory() for name in ("alex", "ben")}
    settings.SHARED_PROGRESS_LEARNERS = {name: user.email for name, user in learners.items()}
    viewer = learners[slug]
    client.force_login(viewer)
    older = problem()
    UserProblemCompletion.objects.create(user=viewer, problem=older, completion_date=date(2025, 1, 1))

    response = library(client, learner=slug)

    assert response.context["library_progress_user"] == viewer
    assert response.context["library_progress_selection"] == "my"
    assert response.context["library_progress_label"] == "My progress"
    assert rows_by_uuid(response)[str(older.problem_uuid)]["user_completion_display"] == "2025-01-01"


def test_record_only_search_and_metadata_filters_apply_before_cap(client):
    client.force_login(UserFactory())
    target = problem(1, confidence="High")
    ProblemTopicTechnique.objects.create(record=target, technique="AM-GM", main_topic="ALG", domains=["ALG"])
    ProblemSolveRecord.objects.filter(pk=target.pk).update(created_at=timezone.now() - timedelta(days=1))
    ProblemSolveRecord.objects.bulk_create([
        ProblemSolveRecord(year=2025, contest="Other Cup", problem=f"P{i}", topic="GEO", mohs=20)
        for i in range(105)
    ])
    assert str(target.problem_uuid) not in rows_by_uuid(library(client))
    for params in (
        {"q": str(target.problem_uuid)}, {"q": "AM-GM"}, {"q": "Inequalities"}, {"concept": "am-gm"},
        {"year": "2026", "topic": "Algebra", "confidence": "High", "mohs_min": "5", "mohs_max": "5"},
    ):
        response = library(client, **params)
        assert set(rows_by_uuid(response)) == {str(target.problem_uuid)}, params
        assert response.context["statement_filtered_total"] == 1
        assert rows_by_uuid(response)[str(target.problem_uuid)]["concept_coverage"][0]["id"] == "am-gm"


def test_record_only_difficulty_link_keeps_the_problem_in_the_shared_library(client):
    client.force_login(UserFactory())
    older = problem()
    statement(2)
    row = rows_by_uuid(library(client))[str(older.problem_uuid)]

    filtered = client.get(row["linked_problem_mohs_url"])

    assert filtered.status_code == HTTPStatus.OK
    assert set(rows_by_uuid(filtered)) == {str(older.problem_uuid)}


def test_future_upload_is_immediately_in_the_shared_library_and_start_reuses_uuid(client):
    viewer = UserFactory()
    client.force_login(viewer)
    assert library(client).context["statement_total"] == 0
    uploaded = statement()
    UserProblemCompletion.objects.create(user=viewer, statement=uploaded)
    identity = uploaded.problem_uuid
    before = history_snapshot()
    row = rows_by_uuid(library(client))[str(identity)]
    assert row["solution_start_url"]
    assert history_snapshot() == before

    result = client.post(row["solution_start_url"])

    assert result.status_code == HTTPStatus.FOUND
    uploaded.refresh_from_db()
    assert uploaded.problem_uuid == identity
    assert uploaded.linked_problem.problem_uuid == identity
    assert UserProblemCompletion.objects.get(user=viewer).statement_id == uploaded.pk
    assert not ProblemSolution.objects.exists()
    assert library(client).context["statement_total"] == 1


def test_library_query_count_is_bounded_as_record_only_rows_grow(client):
    client.force_login(UserFactory())
    problem()
    library(client)  # Warm template/registry caches.
    with CaptureQueriesContext(connection) as small:
        library(client)
    ProblemSolveRecord.objects.bulk_create([
        ProblemSolveRecord(year=2025, contest="Scale Cup", problem=f"P{i}", topic="ALG", mohs=5)
        for i in range(120)
    ])
    with CaptureQueriesContext(connection) as large:
        response = library(client)
    assert len(large) <= len(small) + 2
    assert response.context["statement_visible_total"] == 100  # noqa: PLR2004


def test_record_only_coverage_and_search_use_the_existing_accepted_projection(client, settings):
    from inspinia.pages.concept_assignment_service import apply_refresh
    from inspinia.pages.concept_assignment_service import audit_sources
    from inspinia.pages.concept_assignment_trace import load_sources
    from inspinia.pages.models import ConceptAssignmentState

    client.force_login(UserFactory())
    older = problem()
    ProblemTopicTechnique.objects.create(record=older, technique="AM-GM", main_topic="ALG", domains=["ALG"])
    ProblemTopicTechnique.objects.create(
        record=older, technique="GENERIC FLOOR", main_topic="ALG", domains=["ALG"], object_tags=["FLOOR FUNCTION"],
    )
    apply_refresh(audit_sources(load_sources([older.problem_uuid])))
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    ConceptAssignmentState.objects.update_or_create(
        singleton_key=1, defaults={"enabled": True, "initial_seed_complete": True},
    )
    before = history_snapshot()

    response = library(client, concept="am-gm")

    row = rows_by_uuid(response)[str(older.problem_uuid)]
    assert [c["id"] for c in row["concept_coverage"]] == ["am-gm"]
    assert row["assignment_projection"] is True
    assert 'name="concept" value="am-gm"' in response.content.decode()
    assert library(client, concept="floor-ceiling").context["statement_filtered_total"] == 0
    assert history_snapshot() == before
