from http import HTTPStatus
from urllib.parse import quote

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import UserProblemDifficultyRating
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.problemsets.models import ProblemListVote
from inspinia.problemsets.services import ProblemListServiceError
from inspinia.problemsets.services import replace_problem_list_items
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
EXPECTED_TWO_PROBLEM_SEARCH_MATCHES = 2


def _problem(**overrides) -> ProblemSolveRecord:
    values = {
        "contest": "IMO",
        "core_ideas": "",
        "is_active": True,
        "mohs": 5,
        "problem": "P1",
        "rationale": "",
        "pitfalls": "",
        "topic": "ALG",
        "topic_tags": "ALG - inequalities",
        "year": 2026,
    } | overrides
    return ProblemSolveRecord.objects.create(
        year=values["year"],
        topic=values["topic"],
        mohs=values["mohs"],
        contest=values["contest"],
        problem=values["problem"],
        contest_year_problem=f"{values['contest']} {values['year']} {values['problem']}",
        core_ideas=values["core_ideas"],
        is_active=values["is_active"],
        topic_tags=values["topic_tags"],
        rationale=values["rationale"],
        pitfalls=values["pitfalls"],
    )


def _statement(problem: ProblemSolveRecord, statement_latex: str = "Prove that $a+b \\ge c$.", **overrides):
    values = {
        "core_ideas": problem.core_ideas,
        "rationale": problem.rationale,
        "pitfalls": problem.pitfalls,
    } | overrides
    return ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=problem.year,
        contest_name=problem.contest,
        core_ideas=values["core_ideas"],
        problem_number=1,
        problem_code=problem.problem,
        rationale=values["rationale"],
        pitfalls=values["pitfalls"],
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


def _assert_problem_list_edit_page_contract(response_html: str, problem_list: ProblemList):
    assert reverse("problemsets:problem_search", args=[problem_list.list_uuid]) in response_html
    assert reverse("problemsets:save_items", args=[problem_list.list_uuid]) in response_html
    assert "problem-list-draft-data" in response_html
    assert "problem-list-search-facets" in response_html
    assert "problem-list-search-contest" in response_html
    assert "problem-list-load-more" in response_html
    assert "problem-list-builder-layout" in response_html
    assert "problem-list-active-filters" in response_html
    assert "problem-list-sequence-panel" in response_html
    assert "problem-list-draft-notes-row" in response_html
    assert "problem-list-note-textarea" in response_html
    assert "problem-list-copy-share-url" in response_html
    assert "problem-list-statement-preview" in response_html
    assert "problem-list-unlinked-confirm-modal" in response_html
    assert "data-preview-problem" in response_html
    assert "data-confirm-unlinked-add" in response_html
    assert "Add problem without a statement?" in response_html
    assert "statementStatusBadge" in response_html
    assert "openStatementPreview" in response_html
    assert "data-copy-share-url" in response_html
    expected_added_button_js = (
        'buttonLabel = isAdded ? "<i class=\\"ti ti-check me-1\\"></i>Added" '
        ': "<i class=\\"ti ti-plus me-1\\"></i>Add";'
    )
    assert expected_added_button_js in response_html
    assert "User MOHS" in response_html
    assert "Curator hint" in response_html
    assert "Curator comment" in response_html
    assert "Hide original source" in response_html
    assert "Optional title for public view" in response_html
    assert "Paste an active problem UUID" not in response_html


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


def test_replace_problem_list_items_updates_custom_titles_when_provided():
    problem_list = _problem_list()
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)
    ProblemListItem.objects.create(problem_list=problem_list, problem=first_problem, position=1)

    replace_problem_list_items(
        problem_list,
        [str(second_problem.problem_uuid), str(first_problem.problem_uuid)],
        custom_titles=["Challenge A", ""],
    )

    assert list(problem_list.items.order_by("position").values_list("problem_id", "custom_title")) == [
        (second_problem.id, "Challenge A"),
        (first_problem.id, ""),
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
    author_user_mohs = 17
    searchable_year = 2025
    searchable_mohs = 12
    searchable_problem = _problem(
        problem="P2",
        contest="USAMO",
        year=searchable_year,
        topic="GEO",
        mohs=searchable_mohs,
    )
    searchable_statement = _statement(searchable_problem)
    inactive_problem = _problem(problem="P3", contest="USAMO", year=2024, is_active=False)
    ProblemListItem.objects.create(problem_list=problem_list, problem=existing_problem, position=1)
    ProblemTopicTechnique.objects.create(record=searchable_problem, technique="ANGLE CHASE", domains=["GEO"])
    UserProblemDifficultyRating.objects.create(user=author, statement=searchable_statement, rating=author_user_mohs)
    UserProblemDifficultyRating.objects.create(user=other_user, statement=searchable_statement, rating=44)

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
    assert payload["results"][0]["user_mohs"] == author_user_mohs
    assert payload["results"][0]["topic_tags"] == ["ANGLE CHASE"]
    assert payload["results"][0]["has_statement"] is True
    assert payload["results"][0]["statement_status_label"] == "Statement ready"
    assert payload["results"][0]["statement_uuid"] == str(searchable_statement.statement_uuid)
    assert payload["results"][0]["statement_preview"] == "Prove that $a+b \\ge c$."
    assert payload["results"][0]["archive_url"].startswith(reverse("pages:contest_dashboard_listing"))
    assert payload["results"][0]["is_in_list"] is False
    assert str(inactive_problem.problem_uuid) not in response.content.decode("utf-8")

    existing_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": str(existing_problem.problem_uuid)},
    )

    existing_payload = existing_response.json()
    assert existing_payload["results"][0]["is_in_list"] is True
    assert existing_payload["results"][0]["has_statement"] is False
    assert existing_payload["results"][0]["statement_status_label"] == "No statement"
    assert existing_payload["results"][0]["statement_uuid"] == ""
    assert existing_payload["results"][0]["statement_preview"] == ""

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


def test_problem_list_problem_search_filters_facets_ranks_and_paginates(client):
    author = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    first_match = _problem(
        contest="Balkan MO",
        year=2024,
        problem="P3",
        topic="GEO",
        mohs=12,
        topic_tags="GEO - angle chase",
    )
    second_match = _problem(
        contest="Junior Balkan MO",
        year=2024,
        problem="P3",
        topic="NT",
        mohs=14,
        topic_tags="NT - LTE",
    )
    _problem(
        contest="IMO",
        year=2024,
        problem="P3",
        topic="GEO",
        mohs=12,
        topic_tags="GEO - angle chase",
    )
    _problem(
        contest="Balkan MO",
        year=2024,
        problem="P3",
        topic="GEO",
        mohs=12,
        is_active=False,
    )
    ProblemTopicTechnique.objects.create(record=first_match, technique="ANGLE CHASE", domains=["GEO"])
    ProblemTopicTechnique.objects.create(record=second_match, technique="LTE", domains=["NT"])

    first_page = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "contest:balkan year:2024 p3", "limit": "1"},
    )

    assert first_page.status_code == HTTPStatus.OK
    payload = first_page.json()
    assert payload["total"] == EXPECTED_TWO_PROBLEM_SEARCH_MATCHES
    assert payload["count"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is True
    assert payload["results"][0]["problem_uuid"] == str(first_match.problem_uuid)
    assert payload["facets"]["contests"] == [
        {"count": 1, "label": "Balkan MO", "value": "Balkan MO"},
        {"count": 1, "label": "Junior Balkan MO", "value": "Junior Balkan MO"},
    ]
    assert {
        "count": EXPECTED_TWO_PROBLEM_SEARCH_MATCHES,
        "label": "2024",
        "value": "2024",
    } in payload["facets"]["years"]
    assert {"count": 1, "label": "Geometry", "value": "GEO"} in payload["facets"]["topics"]
    assert {"count": 1, "label": "MOHS 12", "value": "12"} in payload["facets"]["mohs"]
    assert {"count": 1, "label": "ANGLE CHASE", "value": "ANGLE CHASE"} in payload["facets"]["tags"]

    next_page = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "contest:balkan year:2024 p3", "limit": "1", "offset": "1"},
    )

    assert next_page.status_code == HTTPStatus.OK
    next_payload = next_page.json()
    assert next_payload["offset"] == 1
    assert next_payload["has_more"] is False
    assert [row["problem_uuid"] for row in next_payload["results"]] == [str(second_match.problem_uuid)]


def test_problem_list_problem_search_applies_advanced_filters(client):
    author = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    matching_problem = _problem(
        contest="Balkan MO",
        year=2024,
        problem="P4",
        topic="GEO",
        mohs=11,
        topic_tags="GEO - spiral similarity",
    )
    wrong_topic = _problem(
        contest="Balkan MO",
        year=2024,
        problem="P5",
        topic="ALG",
        mohs=11,
        topic_tags="ALG - inequalities",
    )
    wrong_mohs = _problem(
        contest="Balkan MO",
        year=2024,
        problem="P6",
        topic="GEO",
        mohs=16,
        topic_tags="GEO - spiral similarity",
    )
    ProblemTopicTechnique.objects.create(record=matching_problem, technique="SPIRAL SIMILARITY", domains=["GEO"])
    ProblemTopicTechnique.objects.create(record=wrong_topic, technique="INEQUALITIES", domains=["ALG"])
    ProblemTopicTechnique.objects.create(record=wrong_mohs, technique="SPIRAL SIMILARITY", domains=["GEO"])

    response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {
            "contest": "balkan",
            "mohs_max": "12",
            "mohs_min": "10",
            "tag": "spiral",
            "topic": "Geometry",
        },
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["total"] == 1
    assert [row["problem_uuid"] for row in payload["results"]] == [str(matching_problem.problem_uuid)]


def test_problem_list_problem_search_includes_problem_and_statement_note_content(client):
    author = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    archive_note_problem = _problem(
        contest="Balkan MO",
        core_ideas="Core ideas: Use telescoping after pairing the fractions.",
        problem="P4",
        year=2024,
    )
    statement_note_problem = _problem(
        contest="USAMO",
        problem="P5",
        rationale="",
        year=2025,
    )
    _statement(
        statement_note_problem,
        rationale="Rationale: Inversion makes the cyclic angles visible.",
    )

    archive_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "telescoping"},
    )
    statement_response = client.get(
        reverse("problemsets:problem_search", args=[problem_list.list_uuid]),
        {"q": "inversion"},
    )

    assert archive_response.status_code == HTTPStatus.OK
    assert [row["problem_uuid"] for row in archive_response.json()["results"]] == [
        str(archive_note_problem.problem_uuid),
    ]
    assert statement_response.status_code == HTTPStatus.OK
    assert [row["problem_uuid"] for row in statement_response.json()["results"]] == [
        str(statement_note_problem.problem_uuid),
    ]


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


def test_problem_list_save_items_endpoint_persists_custom_titles(client):
    author = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)
    ProblemListItem.objects.create(problem_list=problem_list, problem=first_problem, position=1)

    response = client.post(
        reverse("problemsets:save_items", args=[problem_list.list_uuid]),
        {
            "custom_title": ["Mock paper problem", ""],
            "problem_uuid_order": [str(second_problem.problem_uuid), str(first_problem.problem_uuid)],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert list(problem_list.items.order_by("position").values_list("problem_id", "custom_title")) == [
        (second_problem.id, "Mock paper problem"),
        (first_problem.id, ""),
    ]


def test_problem_list_save_items_endpoint_persists_hints_and_comments(client):
    author = UserFactory()
    client.force_login(author)
    problem_list = _problem_list(author=author)
    problem = _problem(problem="P1")
    hint_text = "Try applying AM-GM to the symmetric pair."
    comment_text = "Good first inequality problem for warm-up."

    response = client.post(
        reverse("problemsets:save_items", args=[problem_list.list_uuid]),
        {
            "comment": [comment_text],
            "hint": [hint_text],
            "problem_uuid_order": [str(problem.problem_uuid)],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    item = ProblemListItem.objects.get(problem_list=problem_list, problem=problem)
    assert item.hint == hint_text
    assert item.comment == comment_text


def test_problem_list_edit_page_exposes_picker_payload_and_save_urls(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(problem="P1")
    statement = _statement(problem)
    problem_list = _problem_list(author=user, visibility=ProblemList.Visibility.PUBLIC)
    user_mohs = 19
    hint_text = "Start by bounding each term."
    comment_text = "Use after students have seen AM-GM."
    ProblemListItem.objects.create(
        comment=comment_text,
        hint=hint_text,
        problem_list=problem_list,
        problem=problem,
        position=1,
    )
    unlinked_problem = _problem(problem="P2", contest="USAMO", year=2025)
    ProblemListItem.objects.create(
        problem_list=problem_list,
        problem=unlinked_problem,
        position=2,
    )
    UserProblemDifficultyRating.objects.create(user=user, statement=statement, rating=user_mohs)

    response = client.get(reverse("problemsets:edit", args=[problem_list.list_uuid]))

    assert response.status_code == HTTPStatus.OK
    assert response.context["problem_list_draft_rows"][0]["user_mohs"] == user_mohs
    assert response.context["problem_list_draft_rows"][0]["hint"] == hint_text
    assert response.context["problem_list_draft_rows"][0]["comment"] == comment_text
    draft_rows = response.context["problem_list_draft_rows"]
    assert draft_rows[0]["has_statement"] is True
    assert draft_rows[0]["statement_status_label"] == "Statement ready"
    assert draft_rows[0]["statement_uuid"] == str(statement.statement_uuid)
    assert draft_rows[0]["statement_preview"] == "Prove that $a+b \\ge c$."
    assert draft_rows[1]["has_statement"] is False
    assert draft_rows[1]["statement_status_label"] == "No statement"
    assert draft_rows[1]["statement_uuid"] == ""
    assert draft_rows[1]["statement_preview"] == ""
    response_html = response.content.decode("utf-8")
    _assert_problem_list_edit_page_contract(response_html, problem_list)


def test_problem_list_edit_page_stacks_panels_and_initializes_datatables(client):
    user = UserFactory()
    client.force_login(user)
    problem_list = _problem_list(author=user)

    response = client.get(reverse("problemsets:edit", args=[problem_list.list_uuid]))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    panel_positions = [
        response_html.index("List settings"),
        response_html.index("Sharing"),
        response_html.index("Find problems"),
        response_html.index("Problem sequence"),
    ]
    assert panel_positions == sorted(panel_positions)
    assert 'id="problem-list-search-results-table"' in response_html
    assert 'id="problem-list-sequence-table"' in response_html
    assert 'new DataTable("#problem-list-search-results-table"' in response_html
    assert 'new DataTable("#problem-list-sequence-table"' in response_html
    assert "problem-list-sticky-panel" not in response_html


def test_add_item_view_redirects_to_safe_next_and_rejects_external_next(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(contest="Balkan MO", year=2024, problem="P3")
    second_problem = _problem(contest="Balkan MO", year=2024, problem="P4")
    problem_list = _problem_list(author=user)
    safe_next = reverse("pages:contest_dashboard_listing") + "?contest=Balkan+MO#balkan-mo-2024-p3"

    response = client.post(
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        {"next": safe_next, "problem_uuid": str(problem.problem_uuid)},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == safe_next
    assert list(problem_list.items.values_list("problem_id", "position")) == [(problem.id, 1)]

    unsafe_response = client.post(
        reverse("problemsets:add_item", args=[problem_list.list_uuid]),
        {"next": "https://example.com/phishing", "problem_uuid": str(second_problem.problem_uuid)},
    )

    assert unsafe_response.status_code == HTTPStatus.FOUND
    assert unsafe_response.url == reverse("problemsets:edit", args=[problem_list.list_uuid])


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
    assert "tex-mml-chtml.js" in response_html
    assert "Sign in to submit solution" in response_html
    assert (
        f"{reverse('account_login')}?next="
        f"{quote(reverse('solutions:problem_solution_edit', args=[problem.problem_uuid]), safe='')}"
    ) in response_html
    assert f">{problem.problem_uuid}<" not in response_html
    assert "sidenav-menu" not in response_html
    assert "side-nav" not in response_html
    assert "content-page" not in response_html
    assert "Download PDF" not in response_html
    assert "Edit my draft" not in response_html
    assert "Start my draft" not in response_html
    assert "completion-editor" not in response_html
    assert "<form" not in response_html


def test_public_share_page_respects_display_options_and_custom_title(client):
    author = UserFactory(name="Exam Maker")
    problem = _problem(topic="GEO", mohs=12, topic_tags="GEO - angle chase")
    ProblemTopicTechnique.objects.create(record=problem, technique="ANGLE CHASE", domains=["GEO"])
    _statement(problem, "Find all triangles with $AB=AC$.")
    problem_list = _problem_list(
        author=author,
        title="Mock paper",
        visibility=ProblemList.Visibility.PUBLIC,
    )
    problem_list.hide_source = True
    problem_list.hide_topic = True
    problem_list.hide_mohs = True
    problem_list.hide_subtopics = True
    problem_list.save()
    ProblemListItem.objects.create(
        problem_list=problem_list,
        problem=problem,
        position=1,
        custom_title="Challenge 1",
    )

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Challenge 1" in response_html
    assert "Find all triangles" in response_html
    assert "IMO 2026 P1" not in response_html
    assert "Geometry" not in response_html
    assert "MOHS 12" not in response_html
    assert "ANGLE CHASE" not in response_html


def test_public_share_page_shows_problem_notes_when_allowed(client):
    author = UserFactory(name="Exam Maker")
    problem = _problem(
        core_ideas="Core ideas: Use a hidden symmetry.",
        rationale="Rationale: The symmetry explains why the bound is sharp.",
        pitfalls="Common pitfalls: Expanding too early.",
        topic="GEO",
        mohs=12,
    )
    _statement(
        problem,
        "Find all triangles with $AB=AC$.",
        core_ideas="Core ideas: Prefer the statement copy.",
        rationale="Rationale: The statement row is the curated source.",
        pitfalls="Common pitfalls: Ignoring the equal sides.",
    )
    fallback_problem = _problem(
        contest="USAMO",
        core_ideas="Core ideas: Track the invariant.",
        rationale="Rationale: The invariant controls every move.",
        pitfalls="Common pitfalls: Missing the terminal case.",
        mohs=9,
        problem="P2",
        topic="COM",
        year=2025,
    )
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)
    ProblemListItem.objects.create(problem_list=problem_list, problem=fallback_problem, position=2)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Core idea" in response_html
    assert "Rationale" in response_html
    assert "Common pitfalls" in response_html
    assert "Prefer the statement copy." in response_html
    assert "The statement row is the curated source." in response_html
    assert "Ignoring the equal sides." in response_html
    assert "Use a hidden symmetry." not in response_html
    assert "Track the invariant." in response_html
    assert "The invariant controls every move." in response_html
    assert "Missing the terminal case." in response_html


def test_problem_list_edit_options_hide_problem_notes_from_public_page(client):
    author = UserFactory(name="Exam Maker")
    client.force_login(author)
    problem = _problem(
        core_ideas="Core ideas: Use a hidden symmetry.",
        rationale="Rationale: The symmetry explains why the bound is sharp.",
        pitfalls="Common pitfalls: Expanding too early.",
        topic="GEO",
        mohs=12,
    )
    _statement(problem, "Find all triangles with $AB=AC$.")
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    edit_response = client.get(reverse("problemsets:edit", args=[problem_list.list_uuid]))

    assert edit_response.status_code == HTTPStatus.OK
    edit_html = edit_response.content.decode("utf-8")
    assert "Hide core idea" in edit_html
    assert "Hide rationale" in edit_html
    assert "Hide common pitfalls" in edit_html

    save_response = client.post(
        reverse("problemsets:edit", args=[problem_list.list_uuid]),
        {
            "title": problem_list.title,
            "description": problem_list.description,
            "hide_core_ideas": "on",
            "hide_rationale": "on",
            "hide_pitfalls": "on",
        },
        follow=True,
    )

    assert save_response.status_code == HTTPStatus.OK
    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Core idea" not in response_html
    assert "Rationale" not in response_html
    assert "Common pitfalls" not in response_html
    assert "Use a hidden symmetry." not in response_html
    assert "The symmetry explains why the bound is sharp." not in response_html
    assert "Expanding too early." not in response_html


def test_public_share_page_shows_comments_and_collapsed_hints(client):
    author = UserFactory(name="Exam Maker")
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Find all triangles with $AB=AC$.")
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    hint_text = "Draw the altitude from the apex first."
    comment_text = "A short opener before angle chasing."
    ProblemListItem.objects.create(
        comment=comment_text,
        hint=hint_text,
        problem_list=problem_list,
        problem=problem,
        position=1,
    )

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert comment_text in response_html
    assert hint_text in response_html
    assert "Show hint" in response_html
    assert "<details open" not in response_html


def test_public_share_page_links_authenticated_users_to_solution_editor(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Submit solution" in response_html
    assert reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]) in response_html
    assert "Sign in to submit solution" not in response_html


def test_public_share_page_links_authenticated_users_to_pdf_download(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Download PDF" in response_html
    assert (
        reverse("problemsets:public_pdf", args=[problem_list.share_token, problem_list.public_slug])
        in response_html
    )


@pytest.mark.parametrize(
    "viewer_kwargs",
    [
        {"is_approved": True},
        {"role": User.Role.ADMIN, "is_approved": False},
        {"is_superuser": True, "is_approved": False},
    ],
)
def test_public_share_page_shows_vote_controls_to_eligible_non_authors(client, viewer_kwargs):
    viewer = UserFactory(**viewer_kwargs)
    client.force_login(viewer)
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert reverse("problemsets:vote", args=[problem_list.list_uuid]) in response_html
    assert f'<input type="hidden" name="next" value="{problem_list.public_url()}">' in response_html
    assert 'name="value" value="1"' in response_html
    assert 'name="value" value="-1"' in response_html
    assert "Thumbs up" in response_html
    assert "Thumbs down" in response_html


def test_public_share_page_hides_vote_controls_from_anonymous_users_and_authors(client):
    author = UserFactory()
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(author=author, visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    anonymous_response = client.get(problem_list.public_url())
    assert anonymous_response.status_code == HTTPStatus.OK
    anonymous_html = anonymous_response.content.decode("utf-8")
    assert reverse("problemsets:vote", args=[problem_list.list_uuid]) not in anonymous_html
    assert "Thumbs up" not in anonymous_html
    assert "Thumbs down" not in anonymous_html

    client.force_login(author)
    author_response = client.get(problem_list.public_url())
    assert author_response.status_code == HTTPStatus.OK
    author_html = author_response.content.decode("utf-8")
    assert reverse("problemsets:vote", args=[problem_list.list_uuid]) not in author_html
    assert "Thumbs up" not in author_html
    assert "Thumbs down" not in author_html


def test_public_share_page_does_not_display_vote_stats(client):
    voter = UserFactory()
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)
    ProblemListVote.objects.create(problem_list=problem_list, user=voter, value=ProblemListVote.Value.UP)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert '<div class="problem-list-public-stats">' not in response_html
    assert ">Score<" not in response_html
    assert ">Up<" not in response_html
    assert ">Down<" not in response_html
    assert ">Problems<" not in response_html


def test_public_share_pdf_returns_attachment_when_compile_succeeds(monkeypatch, client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(title="Mock paper", visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(
        problem_list=problem_list,
        problem=problem,
        position=1,
        custom_title="Challenge 1",
    )
    captured = {}

    def _compile_problem_list(problem_list_arg, item_rows, params):
        captured["problem_list"] = problem_list_arg
        captured["item_rows"] = item_rows
        captured["params"] = params
        return b"%PDF-1.4\n"

    monkeypatch.setattr("inspinia.problemsets.views.compile_problem_list_to_pdf", _compile_problem_list)

    response = client.get(reverse("problemsets:public_pdf", args=[problem_list.share_token, problem_list.public_slug]))

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]
    assert "mock-paper.pdf" in response["Content-Disposition"]
    assert captured["problem_list"] == problem_list
    assert captured["item_rows"][0]["display_label"] == "Challenge 1"
    assert captured["params"].latex_binary == settings.SOLUTION_PDF_LATEX_BINARY


def test_public_share_pdf_requires_login(client):
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    url = reverse("problemsets:public_pdf", args=[problem_list.share_token, problem_list.public_slug])

    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_public_share_pdf_tool_missing_returns_503(monkeypatch, client):
    from inspinia.solutions.pdf_latex import SolutionPdfToolError

    user = UserFactory()
    client.force_login(user)
    problem = _problem(topic="GEO", mohs=12)
    _statement(problem, "Prove that $AB=AC$.")
    problem_list = _problem_list(visibility=ProblemList.Visibility.PUBLIC)
    ProblemListItem.objects.create(problem_list=problem_list, problem=problem, position=1)

    def _boom(*args, **kwargs):
        msg = "latexmk not found"
        raise SolutionPdfToolError(msg)

    monkeypatch.setattr("inspinia.problemsets.views.compile_problem_list_to_pdf", _boom)

    response = client.get(reverse("problemsets:public_pdf", args=[problem_list.share_token, problem_list.public_slug]))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert b"PDF unavailable" in response.content
    assert b"latexmk not found" in response.content


def test_problem_list_pdf_source_respects_display_options_and_custom_titles():
    from inspinia.problemsets.pdf_latex import build_problem_list_tex_source
    from inspinia.problemsets.selectors import problem_list_item_rows

    author = UserFactory(name="Exam Maker")
    problem = _problem(topic="GEO", mohs=12, topic_tags="GEO - angle chase")
    ProblemTopicTechnique.objects.create(record=problem, technique="ANGLE CHASE", domains=["GEO"])
    _statement(problem, "Find all triangles with $AB=AC$.")
    problem_list = _problem_list(
        author=author,
        title="Mock paper",
        visibility=ProblemList.Visibility.PUBLIC,
    )
    problem_list.hide_source = True
    problem_list.hide_topic = True
    problem_list.hide_mohs = True
    problem_list.hide_subtopics = True
    problem_list.save()
    ProblemListItem.objects.create(
        problem_list=problem_list,
        problem=problem,
        position=1,
        custom_title="Challenge 1",
    )

    tex_source = build_problem_list_tex_source(problem_list, problem_list_item_rows(problem_list))

    assert r"\documentclass[11pt]{scrartcl}" in tex_source
    assert r"\usepackage[sexy,noasy]{evan}" in tex_source
    assert r"\title{Mock paper}" in tex_source
    assert "Curated by Exam Maker" in tex_source
    assert "Challenge 1" in tex_source
    assert "Find all triangles with $AB=AC$." in tex_source
    assert "IMO 2026 P1" not in tex_source
    assert "Geometry" not in tex_source
    assert "MOHS 12" not in tex_source
    assert "ANGLE CHASE" not in tex_source


def test_private_list_share_url_returns_not_found(client):
    problem_list = _problem_list(visibility=ProblemList.Visibility.PRIVATE)

    response = client.get(problem_list.public_url())

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_discover_lists_shows_public_lists_sorted_by_vote_score_and_search(client):
    user = UserFactory()
    client.force_login(user)
    low_score = _problem_list(
        author=UserFactory(email="algebra-author@example.test", name="Algebra Author"),
        title="Algebra picks",
        visibility=ProblemList.Visibility.PUBLIC,
    )
    high_score = _problem_list(
        author=UserFactory(email="geometry-author@example.test", name="Geometry Author"),
        title="Geometry gems",
        visibility=ProblemList.Visibility.PUBLIC,
    )
    _problem_list(
        author=UserFactory(email="hidden-author@example.test", name="Hidden Author"),
        title="Hidden gems",
        visibility=ProblemList.Visibility.PRIVATE,
    )
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


def test_admin_discover_lists_shows_all_lists_in_datatable(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    public_list = _problem_list(
        author=UserFactory(email="public-author@example.test", name="Public Author"),
        title="Public geometry",
        visibility=ProblemList.Visibility.PUBLIC,
    )
    _problem_list(
        author=UserFactory(email="private-author@example.test", name="Private Author"),
        title="Private algebra",
        visibility=ProblemList.Visibility.PRIVATE,
    )
    ProblemListVote.objects.create(problem_list=public_list, user=UserFactory(), value=ProblemListVote.Value.UP)

    response = client.get(reverse("problemsets:discover"), {"q": "author"})

    assert response.status_code == HTTPStatus.OK
    rows = response.context["problem_list_rows"]
    assert [row["title"] for row in rows] == ["Public geometry", "Private algebra"]
    assert response.context["problem_list_discover_is_admin"] is True
    response_html = response.content.decode("utf-8")
    assert "All problem lists" in response_html
    assert "Private" in response_html
    assert 'id="problem-list-discover-table"' in response_html
    assert 'new DataTable("#problem-list-discover-table"' in response_html


def test_admin_can_open_private_problem_list_without_editing_it(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    author = UserFactory()
    problem_list = _problem_list(
        author=author,
        title="Private shortlist",
        visibility=ProblemList.Visibility.PRIVATE,
    )
    client.force_login(admin_user)

    response = client.get(reverse("problemsets:detail", args=[problem_list.list_uuid]))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Private shortlist" in response_html
    assert "Private" in response_html
    assert reverse("problemsets:edit", args=[problem_list.list_uuid]) not in response_html


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
