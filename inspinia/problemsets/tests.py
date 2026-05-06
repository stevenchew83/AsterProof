from http import HTTPStatus

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.problemsets.models import ProblemListVote
from inspinia.problemsets.services import ProblemListServiceError
from inspinia.problemsets.services import replace_problem_list_items
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _problem(**overrides) -> ProblemSolveRecord:
    values = {
        "contest": "IMO",
        "is_active": True,
        "mohs": 5,
        "problem": "P1",
        "topic": "ALG",
        "year": 2026,
    } | overrides
    return ProblemSolveRecord.objects.create(
        year=values["year"],
        topic=values["topic"],
        mohs=values["mohs"],
        contest=values["contest"],
        problem=values["problem"],
        contest_year_problem=f"{values['contest']} {values['year']} {values['problem']}",
        is_active=values["is_active"],
        topic_tags="ALG - inequalities",
    )


def _statement(problem: ProblemSolveRecord, statement_latex: str = "Prove that $a+b \\ge c$."):
    return ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=problem.year,
        contest_name=problem.contest,
        problem_number=1,
        problem_code=problem.problem,
        statement_latex=statement_latex,
        topic=problem.topic,
        mohs=problem.mohs,
        topic_tags=problem.topic_tags,
    )


def _problem_list(*, author=None, title: str = "Geometry warmups", visibility: str = ProblemList.Visibility.PRIVATE):
    return ProblemList.objects.create(
        author=author or UserFactory(),
        title=title,
        description="A short ordered practice list.",
        visibility=visibility,
    )


def test_problem_list_item_enforces_unique_problem_and_position():
    problem_list = _problem_list()
    first_problem = _problem()
    second_problem = _problem(year=2025, contest="USAMO", problem="P2")
    ProblemListItem.objects.create(problem_list=problem_list, problem=first_problem, position=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProblemListItem.objects.create(problem_list=problem_list, problem=first_problem, position=2)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProblemListItem.objects.create(problem_list=problem_list, problem=second_problem, position=1)


def test_problem_list_vote_enforces_one_valid_vote_per_user():
    voter = UserFactory()
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListVote.objects.create(problem_list=problem_list, user=voter, value=ProblemListVote.Value.UP)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProblemListVote.objects.create(problem_list=problem_list, user=voter, value=ProblemListVote.Value.DOWN)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProblemListVote.objects.create(problem_list=problem_list, user=UserFactory(), value=0)


@pytest.mark.parametrize(
    "url_name",
    [
        "problemsets:my_lists",
        "problemsets:discover",
        "problemsets:create",
    ],
)
def test_problem_list_workspace_routes_require_login(client, url_name):
    url = reverse(url_name)

    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_problem_list_detail_and_edit_require_login(client):
    problem_list = _problem_list()

    for url in [
        reverse("problemsets:detail", args=[problem_list.list_uuid]),
        reverse("problemsets:edit", args=[problem_list.list_uuid]),
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        reverse("problemsets:reorder_items", args=[problem_list.list_uuid]),
        reverse("problemsets:toggle_visibility", args=[problem_list.list_uuid]),
        reverse("problemsets:vote", args=[problem_list.list_uuid]),
    ]:
        response = client.post(url)
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_create_list_and_add_active_problem_workflow(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    inactive_problem = _problem(year=2024, contest="BMO", problem="P3", is_active=False)

    response = client.post(
        reverse("problemsets:create"),
        {"title": "Algebra ladder", "description": "Start gentle, then climb."},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    problem_list = ProblemList.objects.get(author=user, title="Algebra ladder")
    assert response.redirect_chain[-1][0] == reverse("problemsets:edit", args=[problem_list.list_uuid])

    add_response = client.post(
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        {"problem_uuid": str(problem.problem_uuid)},
        follow=True,
    )

    assert add_response.status_code == HTTPStatus.OK
    assert list(problem_list.items.values_list("problem_id", "position")) == [(problem.id, 1)]

    duplicate_response = client.post(
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        {"problem_uuid": str(problem.problem_uuid)},
        follow=True,
    )
    assert duplicate_response.status_code == HTTPStatus.OK
    assert problem_list.items.count() == 1

    inactive_response = client.post(
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        {"problem_uuid": str(inactive_problem.problem_uuid)},
        follow=True,
    )
    assert inactive_response.status_code == HTTPStatus.OK
    assert problem_list.items.count() == 1


def test_replace_problem_list_items_sets_full_order_and_membership():
    problem_list = _problem_list()
    removed_problem = _problem(problem="P1")
    first_problem = _problem(problem="P2", contest="USAMO", year=2025)
    second_problem = _problem(problem="P3", contest="BMO", year=2024)
    ProblemListItem.objects.create(problem_list=problem_list, problem=removed_problem, position=1)
    ProblemListItem.objects.create(problem_list=problem_list, problem=second_problem, position=2)

    replace_problem_list_items(
        problem_list,
        [str(first_problem.problem_uuid), str(second_problem.problem_uuid)],
    )

    assert list(problem_list.items.order_by("position").values_list("problem_id", "position")) == [
        (first_problem.id, 1),
        (second_problem.id, 2),
    ]


def test_replace_problem_list_items_rejects_duplicate_unknown_and_new_inactive_problem():
    problem_list = _problem_list()
    active_problem = _problem(problem="P1")
    inactive_problem = _problem(problem="P2", contest="USAMO", year=2025, is_active=False)

    with pytest.raises(ProblemListServiceError, match="more than once"):
        replace_problem_list_items(
            problem_list,
            [str(active_problem.problem_uuid), str(active_problem.problem_uuid)],
        )

    with pytest.raises(ProblemListServiceError, match="active contest problems"):
        replace_problem_list_items(problem_list, ["00000000-0000-0000-0000-000000000000"])

    with pytest.raises(ProblemListServiceError, match="active contest problems"):
        replace_problem_list_items(problem_list, [str(inactive_problem.problem_uuid)])

    assert problem_list.items.count() == 0


def test_replace_problem_list_items_preserves_existing_inactive_rows_when_submitted_and_can_clear():
    problem_list = _problem_list()
    active_problem = _problem(problem="P1")
    inactive_problem = _problem(problem="P2", contest="USAMO", year=2025, is_active=False)
    ProblemListItem.objects.create(problem_list=problem_list, problem=active_problem, position=1)
    ProblemListItem.objects.create(problem_list=problem_list, problem=inactive_problem, position=2)

    replace_problem_list_items(
        problem_list,
        [str(inactive_problem.problem_uuid), str(active_problem.problem_uuid)],
    )

    assert list(problem_list.items.order_by("position").values_list("problem_id", "position")) == [
        (inactive_problem.id, 1),
        (active_problem.id, 2),
    ]

    replace_problem_list_items(problem_list, [])

    assert problem_list.items.count() == 0


def test_problem_list_problem_search_requires_author_and_returns_active_problem_rows(client):
    author = UserFactory()
    other_user = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    existing_problem = _problem(problem="P1", topic="ALG", mohs=5)
    searchable_year = 2025
    searchable_mohs = 12
    searchable_problem = _problem(
        problem="P2",
        contest="USAMO",
        year=searchable_year,
        topic="GEO",
        mohs=searchable_mohs,
    )
    inactive_problem = _problem(problem="P3", contest="USAMO", year=2024, is_active=False)
    ProblemListItem.objects.create(problem_list=problem_list, problem=existing_problem, position=1)
    ProblemTopicTechnique.objects.create(record=searchable_problem, technique="ANGLE CHASE", domains=["GEO"])

    response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "angle"},
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["problem_uuid"] == str(searchable_problem.problem_uuid)
    assert payload["results"][0]["problem_label"] == "USAMO 2025 P2"
    assert payload["results"][0]["contest"] == "USAMO"
    assert payload["results"][0]["year"] == searchable_year
    assert payload["results"][0]["problem_code"] == "P2"
    assert payload["results"][0]["topic_label"] == "Geometry"
    assert payload["results"][0]["mohs"] == searchable_mohs
    assert payload["results"][0]["topic_tags"] == ["ANGLE CHASE"]
    assert payload["results"][0]["archive_url"].startswith(reverse("pages:contest_dashboard_listing"))
    assert payload["results"][0]["is_in_list"] is False
    assert str(inactive_problem.problem_uuid) not in response.content.decode("utf-8")

    existing_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": str(existing_problem.problem_uuid)},
    )

    assert existing_response.json()["results"][0]["is_in_list"] is True

    topic_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "geometry"},
    )
    assert [row["problem_uuid"] for row in topic_response.json()["results"]] == [str(searchable_problem.problem_uuid)]

    mohs_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "MOHS 12"},
    )
    assert [row["problem_uuid"] for row in mohs_response.json()["results"]] == [str(searchable_problem.problem_uuid)]

    client.force_login(other_user)
    forbidden_response = client.get(reverse("problemsets:problem_search", args=[problem_list.list_uuid]))

    assert forbidden_response.status_code == HTTPStatus.NOT_FOUND


def test_problem_list_save_items_endpoint_requires_author_and_replaces_sequence(client):
    author = UserFactory()
    other_user = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)
    ProblemListItem.objects.create(problem_list=problem_list, problem=first_problem, position=1)

    response = client.post(
        reverse("problemsets:save_items", args=[problem_list.list_uuid]),
        {"problem_uuid_order": [str(second_problem.problem_uuid), str(first_problem.problem_uuid)]},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert list(problem_list.items.order_by("position").values_list("problem_id", flat=True)) == [
        second_problem.id,
        first_problem.id,
    ]

    client.force_login(other_user)
    forbidden_response = client.post(
        reverse("problemsets:save_items", args=[problem_list.list_uuid]),
        {"problem_uuid_order": [str(first_problem.problem_uuid)]},
    )

    assert forbidden_response.status_code == HTTPStatus.NOT_FOUND


def test_problem_list_edit_page_exposes_picker_payload_and_save_urls(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(problem="P1")
    problem_list = _problem_list(author=user)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    response = client.get(reverse("problemsets:edit", args=[problem_list.list_uuid]))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert reverse("problemsets:problem_search", args=[problem_list.list_uuid]) in response_html
    assert reverse("problemsets:save_items", args=[problem_list.list_uuid]) in response_html
    assert "problem-list-draft-data" in response_html
    assert "Paste an active problem UUID" not in response_html


def test_reorder_items_requires_author_and_reorders_exact_item_set(client):
    author = UserFactory()
    other_user = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    first = ProblemListItem.objects.create(problem_list=problem_list, problem=_problem(problem="P1"), position=1)
    second = ProblemListItem.objects.create(problem_list=problem_list, problem=_problem(problem="P2"), position=2)

    response = client.post(
        reverse("problemsets:reorder_items", args=[problem_list.list_uuid]),
        {"item_order": [str(second.id), str(first.id)]},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert list(problem_list.items.order_by("position").values_list("id", flat=True)) == [second.id, first.id]

    bad_response = client.post(
        reverse("problemsets:reorder_items", args=[problem_list.list_uuid]),
        {"item_order": [str(first.id)]},
        follow=True,
    )

    assert bad_response.status_code == HTTPStatus.OK
    assert list(problem_list.items.order_by("position").values_list("id", flat=True)) == [second.id, first.id]

    client.force_login(other_user)
    forbidden_response = client.post(
        reverse("problemsets:reorder_items", args=[problem_list.list_uuid]),
        {"item_order": [str(first.id), str(second.id)]},
    )

    assert forbidden_response.status_code == HTTPStatus.NOT_FOUND


def test_public_share_page_is_read_only_without_dashboard_chrome(client):
    author = UserFactory(name="List Author")
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Find all triangles with $AB=AC$.")
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Geometry warmups" in response_html
    assert "List Author" in response_html
    assert "Find all triangles" in response_html
    assert "MOHS 12" in response_html
    assert "sidenav-menu" not in response_html
    assert "side-nav" not in response_html
    assert "content-page" not in response_html
    assert "Edit my draft" not in response_html
    assert "Start my draft" not in response_html
    assert "completion-editor" not in response_html
    assert "<form" not in response_html


def test_private_list_share_url_returns_not_found(client):
    problem_list = _problem_list(visibility=ProblemList.Visibility.PRIVATE)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_discover_lists_shows_public_lists_sorted_by_vote_score_and_search(client):
    user = UserFactory()
    client.force_login(user)
    low_score = _problem_list(title="Algebra picks", visibility=ProblemList.Visibility.PUBLIC)
    high_score = _problem_list(title="Geometry gems", visibility=ProblemList.Visibility.PUBLIC)
    _problem_list(title="Hidden gems", visibility=ProblemList.Visibility.PRIVATE)
    ProblemListItem.objects.create(problem_list=high_score, problem=_problem(contest="IMO", problem="P4"), position=1)
    ProblemListVote.objects.create(problem_list=low_score, user=UserFactory(), value=ProblemListVote.Value.DOWN)
    ProblemListVote.objects.create(problem_list=high_score, user=UserFactory(), value=ProblemListVote.Value.UP)
    ProblemListVote.objects.create(problem_list=high_score, user=UserFactory(), value=ProblemListVote.Value.UP)

    response = client.get(reverse("problemsets:discover"))

    assert response.status_code == HTTPStatus.OK
    rows = response.context["problem_list_rows"]
    assert [row["title"] for row in rows] == ["Geometry gems", "Algebra picks"]
    response_html = response.content.decode("utf-8")
    assert "Hidden gems" not in response_html

    search_response = client.get(reverse("problemsets:discover"), {"q": "IMO"})

    assert [row["title"] for row in search_response.context["problem_list_rows"]] == ["Geometry gems"]


def test_vote_endpoint_toggles_and_changes_vote_for_non_author(client):
    author = UserFactory()
    voter = UserFactory()
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    client.force_login(voter)

    up_response = client.post(
        reverse("problemsets:vote", args=[problem_list.list_uuid]),
        {"value": "1"},
        follow=True,
    )

    assert up_response.status_code == HTTPStatus.OK
    assert ProblemListVote.objects.get(problem_list=problem_list, user=voter).value == ProblemListVote.Value.UP

    down_response = client.post(
        reverse("problemsets:vote", args=[problem_list.list_uuid]),
        {"value": "-1"},
        follow=True,
    )

    assert down_response.status_code == HTTPStatus.OK
    assert ProblemListVote.objects.get(problem_list=problem_list, user=voter).value == ProblemListVote.Value.DOWN

    clear_response = client.post(
        reverse("problemsets:vote", args=[problem_list.list_uuid]),
        {"value": "-1"},
        follow=True,
    )

    assert clear_response.status_code == HTTPStatus.OK
    assert not ProblemListVote.objects.filter(problem_list=problem_list, user=voter).exists()


def test_author_cannot_vote_on_own_list(client):
    author = UserFactory()
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    client.force_login(author)

    response = client.post(
        reverse("problemsets:vote", args=[problem_list.list_uuid]),
        {"value": "1"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert not ProblemListVote.objects.filter(problem_list=problem_list, user=author).exists()
