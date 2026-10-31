"""Collections preserve reviewed sharing, ownership, order, and revocation."""

import re
import uuid
from copy import deepcopy
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions import test_public_sharing as sharing_tests
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.sharing import public_collection_url
from inspinia.solutions.test_public_sharing import create_share
from inspinia.solutions.test_public_sharing import public_path
from inspinia.solutions.test_public_sharing import saved_editor_data
from inspinia.solutions.test_public_sharing import share_path
from inspinia.solutions.test_public_sharing import sharing_data
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def pair(client, settings):
    writing = sharing_tests.writing.__wrapped__(client, settings)
    problem = ProblemSolveRecord.objects.create(
        contest="COLLECTION TEST", year=2026, problem="P2", topic="GEO", mohs=5,
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name=problem.contest,
        contest_year=2026,
        problem_code="P2",
        problem_number=2,
        topic="GEO",
        statement_latex="SECOND-STATEMENT",
    )
    second = ProblemSolution.objects.create(problem=problem, author=writing.author, title="Second proof")
    ProblemSolutionBlock.objects.create(solution=second, position=1, body_source="SECOND-PROOF")
    return writing, second


def edit_path(collection=None):
    return (
        reverse("solutions:collection_edit", args=[collection.pk])
        if collection
        else reverse("solutions:collection_create")
    )


def public_collection_path(collection):
    return reverse("solutions:public_collection", args=[collection.token])


def form_data(solutions, collection=None):
    return {
        "title": "Three useful ideas",
        "introduction": "Start with a square.\nThen try geometry.",
        "solution": [str(solution.pk) for solution in solutions],
        "collection_revision": str(collection.revision) if collection else "",
        "action": "review",
    }


def publish_data(client, solutions, collection=None):
    data = form_data(solutions, collection)
    review = client.post(edit_path(collection), data)
    assert review.status_code == HTTPStatus.OK
    assert review.context["review_rows"]
    return {**data, "action": "publish", "review_token": review.context["review_token"]}


def publish(client, solutions, collection=None):
    response = client.post(edit_path(collection), publish_data(client, solutions, collection))
    assert response.status_code == HTTPStatus.FOUND
    return SolutionCollection.objects.get(pk=collection.pk) if collection else SolutionCollection.objects.get()


def test_review_is_read_only_and_creation_preserves_selection_order(client, pair):
    first, second = pair
    review = client.post(edit_path(), form_data([second, first]))
    assert review.status_code == HTTPStatus.OK
    assert [row["solution"] for row in review.context["review_rows"]] == [second, first]
    assert "saved copy to share" in review.content.decode()
    assert not SolutionCollection.objects.exists()
    assert not SolutionPublicShare.objects.exists()
    collection = publish(client, [second, first])
    entries = list(collection.entries.select_related("share"))
    assert [entry.share.solution_id for entry in entries] == [second.pk, first.pk]
    assert [entry.position for entry in entries] == [1, 2]
    assert all(entry.share_token == entry.share.token for entry in entries)
    assert not UserProblemCompletion.objects.exists()
    first.refresh_from_db()
    assert first.status == ProblemSolution.Status.DRAFT
    html = client.get(reverse("solutions:my_solution_list")).content.decode()
    assert "Your collections" in html
    assert edit_path(collection) in html


def test_anonymous_page_contains_all_proofs_unique_anchors_and_no_private_context(client, pair):
    collection = publish(client, pair)
    response = Client().get(public_collection_path(collection))
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    for text in [collection.title, "An elegant proof", "Second proof", "SHARED-PROOF", "SECOND-PROOF", "Contents"]:
        assert text in html
    assert pair[0].author.email not in html
    assert "csrfmiddlewaretoken" not in html
    assert "Edit draft" not in html
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]
    assert response["Referrer-Policy"] == "same-origin"
    assert f'property="og:url" content="{public_collection_url(collection)}"' in html
    assert html.count("<h1>") == 1
    all_ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(all_ids) == len(set(all_ids))
    for entry in collection.entries.all():
        assert f'href="#solution-{entry.anchor}"' in html
        assert f'id="solution-{entry.anchor}"' in html
        assert f'data-copy-public-link="{public_collection_url(collection)}#solution-{entry.anchor}"' in html
    assert Client().head(public_collection_path(collection)).status_code == HTTPStatus.OK
    assert (
        Client().post(public_collection_path(collection), {"action": "stop"}).status_code
        == HTTPStatus.METHOD_NOT_ALLOWED
    )


def test_existing_shared_copies_are_reused_and_editor_saves_stay_private(client, pair):
    first, second = pair
    share = create_share(client, first)
    revision, snapshot = share.revision, deepcopy(share.snapshot)
    editor = reverse("solutions:problem_solution_edit", args=[first.problem.problem_uuid])
    assert client.post(editor, saved_editor_data(first)).status_code == HTTPStatus.FOUND
    collection = publish(client, [first, second])
    share.refresh_from_db()
    assert share.revision == revision
    assert share.snapshot == snapshot
    html = Client().get(public_collection_path(collection)).content.decode()
    assert "SHARED-PROOF" in html
    assert "PRIVATE-PROOF" not in html
    assert client.post(share_path(first), sharing_data(client, first, "update")).status_code == HTTPStatus.FOUND
    html = Client().get(public_collection_path(collection)).content.decode()
    assert "PRIVATE-PROOF" in html
    assert "SHARED-PROOF" not in html


def test_reorder_preserves_deep_links_and_removing_entry_preserves_single_link(client, pair):
    first, second = pair
    collection = publish(client, pair)
    initial_token = collection.token
    anchors = dict(collection.entries.values_list("share__solution_id", "anchor"))
    collection = publish(client, [second, first], collection)
    assert collection.token == initial_token
    assert list(collection.entries.values_list("share__solution_id", flat=True)) == [second.pk, first.pk]
    assert dict(collection.entries.values_list("share__solution_id", "anchor")) == anchors
    collection = publish(client, [second], collection)
    html = Client().get(public_collection_path(collection)).content.decode()
    assert "SHARED-PROOF" not in html
    assert "SECOND-PROOF" in html
    assert Client().get(public_path(SolutionPublicShare.objects.get(solution=first))).status_code == HTTPStatus.OK


def test_solution_revocation_and_later_resharing_do_not_revive_collection_entry(client, pair):
    first, second = pair
    collection = publish(client, pair)
    assert client.post(share_path(first), sharing_data(client, first, "stop")).status_code == HTTPStatus.FOUND
    html = Client().get(public_collection_path(collection)).content.decode()
    assert "SHARED-PROOF" not in html
    assert "An elegant proof" not in html
    assert "SECOND-PROOF" in html
    create_share(client, first)
    assert "SHARED-PROOF" not in Client().get(public_collection_path(collection)).content.decode()
    # Explicitly reviewing and updating this collection may include it again.
    publish(client, pair, collection)
    assert "SHARED-PROOF" in Client().get(public_collection_path(collection)).content.decode()


def test_stopping_collection_only_revokes_its_link_and_resharing_rotates_it(client, pair):
    collection = publish(client, pair)
    old_path = public_collection_path(collection)
    stale = publish_data(client, pair, collection)
    response = client.post(edit_path(collection), {"action": "stop", "collection_revision": str(collection.revision)})
    assert response.status_code == HTTPStatus.FOUND
    assert Client().get(old_path).status_code == HTTPStatus.NOT_FOUND
    assert all(share.is_active for share in SolutionPublicShare.objects.all())
    assert client.post(edit_path(collection), stale).status_code == HTTPStatus.CONFLICT
    collection.refresh_from_db()
    collection = publish(client, pair, collection)
    assert public_collection_path(collection) != old_path
    assert Client().get(old_path).status_code == HTTPStatus.NOT_FOUND
    assert Client().get(public_collection_path(collection)).status_code == HTTPStatus.OK


@pytest.mark.parametrize("change", ["save", "block", "profile", "statement", "first-share"])
def test_changed_unshared_content_rejects_old_review_without_partial_sharing(client, pair, change):
    first, second = pair
    data = publish_data(client, pair)
    if change == "save":
        second.title = "Changed privately"
        second.save()
    elif change == "block":
        second.blocks.update(body_source="PRIVATE-CHANGES")
    elif change == "profile":
        first.author.name = "Changed author name"
        first.author.save()
    elif change == "statement":
        ContestProblemStatement.objects.filter(linked_problem=second.problem).update(
            statement_latex="PRIVATE-STATEMENT",
        )
    else:
        create_share(client, second)
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()
    assert not SolutionPublicShare.objects.filter(solution=first).exists()


@pytest.mark.parametrize("change", ["stop", "update"])
def test_changed_shared_copy_rejects_review_and_never_reshare_silently(client, pair, change):
    first, second = pair
    create_share(client, first)
    data = publish_data(client, pair)
    client.post(share_path(first), sharing_data(client, first, change))
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()
    assert not SolutionPublicShare.objects.filter(solution=second).exists()
    if change == "stop":
        assert not SolutionPublicShare.objects.get(solution=first).is_active


@pytest.mark.parametrize("change", ["title", "introduction", "order", "token", "missing-token"])
def test_review_cannot_be_tampered_with(client, pair, change):
    data = publish_data(client, pair)
    if change == "order":
        data["solution"].reverse()
    elif change == "token":
        data["review_token"] += "bad"
    elif change == "missing-token":
        del data["review_token"]
    else:
        data[change] = "Not reviewed"
    assert client.post(edit_path(), data).status_code == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()
    assert not SolutionPublicShare.objects.exists()


def test_ownership_approval_csrf_and_safe_gets(client, pair):
    collection = publish(client, pair)
    other = Client()
    other.force_login(UserFactory())
    assert other.get(edit_path(collection)).status_code == HTTPStatus.NOT_FOUND
    assert other.post(edit_path(collection), {"action": "stop"}).status_code == HTTPStatus.NOT_FOUND
    assert other.get(edit_path(), {"solution": [pair[0].pk]}).status_code == HTTPStatus.NOT_FOUND
    assert other.post(edit_path(), form_data(pair)).status_code == HTTPStatus.NOT_FOUND
    assert other.get(edit_path(), {"target_collection": collection.pk}).status_code == HTTPStatus.NOT_FOUND
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(pair[0].author)
    assert guarded.post(edit_path(), form_data(pair)).status_code == HTTPStatus.FORBIDDEN
    assert Client().get(edit_path()).status_code == HTTPStatus.FOUND
    pending = Client()
    pending.force_login(UserFactory(is_approved=False))
    assert pending.get(public_collection_path(collection)).status_code == HTTPStatus.OK
    assert pending.get(edit_path(collection)).url == reverse("users:approval_pending")
    client.get(edit_path(collection), {"action": "stop"})
    collection.refresh_from_db()
    assert collection.is_active


@pytest.mark.parametrize("values", [[], ["not-an-id"], ["0"], ["1", "1"], [str(i) for i in range(1, 22)]])
def test_invalid_selections_are_rejected(client, pair, values):
    data = form_data(pair)
    data["solution"] = values
    assert client.post(edit_path(), data).status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionCollection.objects.exists()


def test_invalid_or_oversized_new_copy_cannot_partially_publish(client, pair, monkeypatch):
    pair[1].blocks.all().delete()
    assert client.post(edit_path(), form_data(pair)).status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionPublicShare.objects.exists()
    monkeypatch.setattr("inspinia.solutions.collection_views.MAX_COLLECTION_BYTES", 1)
    assert client.post(edit_path(), form_data([pair[0]])).status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionCollection.objects.exists()


def test_add_to_existing_appends_without_duplicates_and_deletion_removes_proof(client, pair):
    collection = publish(client, [pair[0]])
    response = client.get(edit_path(collection), {"solution": [pair[1].pk, pair[0].pk]})
    assert [solution.pk for solution in response.context["selected_solutions"]] == [pair[0].pk, pair[1].pk]
    response = client.get(edit_path(), {"solution": [pair[1].pk], "target_collection": collection.pk})
    assert response.url == edit_path(collection) + f"?solution={pair[1].pk}"
    publish(client, pair, collection)
    pair[0].delete()
    html = Client().get(public_collection_path(collection)).content.decode()
    assert "SHARED-PROOF" not in html
    assert "SECOND-PROOF" in html
    collection.delete()
    assert Client().get(public_collection_path(collection)).status_code == HTTPStatus.NOT_FOUND
    assert (
        Client().get(reverse("solutions:public_collection", args=[uuid.uuid4()])).status_code == HTTPStatus.NOT_FOUND
    )


def test_untrusted_collection_text_is_escaped(client, pair):
    data = form_data(pair)
    data.update(title='<script>alert("title")</script>', introduction='<img src=x onerror="alert(1)">')
    review = client.post(edit_path(), data)
    response = client.post(edit_path(), {**data, "action": "publish", "review_token": review.context["review_token"]})
    assert response.status_code == HTTPStatus.FOUND
    html = Client().get(public_collection_path(SolutionCollection.objects.get())).content.decode()
    assert '<script>alert("title")' not in html
    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;script&gt;" in html
