"""Admin curation reuses only active public copies and preserves author control."""

import uuid
from copy import deepcopy
from http import HTTPStatus
from types import SimpleNamespace

import pytest
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import connection
from django.db import transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.solutions import admin_collections
from inspinia.solutions import test_public_sharing as sharing_tests
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionCollectionEntry
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.models import SolutionShareDailyViews
from inspinia.solutions.test_public_sharing import create_share
from inspinia.solutions.test_public_sharing import saved_editor_data
from inspinia.solutions.test_public_sharing import share_path
from inspinia.solutions.test_public_sharing import sharing_data
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def mixed(client, settings):
    first = sharing_tests.writing.__wrapped__(client, settings)
    first_share = create_share(client, first)
    second_author = UserFactory(name="Hidden author")
    second = ProblemSolution.objects.create(
        problem=first.problem, author=second_author, title="Another public proof", pdf_show_author=False,
    )
    ProblemSolutionBlock.objects.create(solution=second, position=1, body_source="SECOND-PUBLIC-PROOF")
    second_client = Client()
    second_client.force_login(second_author)
    second_share = create_share(second_client, second)
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    return SimpleNamespace(
        first=first, second=second, shares=[first_share, second_share], admin=admin,
        second_client=second_client,
    )


def ref(share):
    return f"{share.pk}:{share.token}"


def edit_path(collection=None):
    return reverse("solutions:admin_collection_edit", args=[collection.pk]) if collection else reverse(
        "solutions:admin_collection_create",
    )


def public_path(collection):
    return reverse("solutions:public_collection", args=[collection.token])


def form_data(shares, collection=None):
    return {
        "share": [ref(share) for share in shares],
        "title": "Two ways to prove it", "introduction": "Compare the ideas.",
        "collection_revision": str(collection.revision) if collection else "", "action": "review",
        "flow": str(uuid.uuid4()),
    }


def confirm_data(client, shares, collection=None):
    data = form_data(shares, collection)
    response = client.post(edit_path(collection), data)
    assert response.status_code == HTTPStatus.OK, response.content.decode()
    assert response.context["review_rows"]
    return {**data, "action": "publish", "review_token": response.context["review_token"]}


def publish(client, shares, collection=None):
    response = client.post(edit_path(collection), confirm_data(client, shares, collection))
    assert response.status_code == HTTPStatus.FOUND
    return SolutionCollection.objects.get(pk=collection.pk) if collection else SolutionCollection.objects.get(
        kind=SolutionCollection.Kind.ADMIN_CURATED,
    )


def test_review_is_read_only_and_publish_reuses_mixed_authors_same_problem(client, mixed):
    before = list(SolutionPublicShare.objects.order_by("pk").values())
    review = client.post(edit_path(), form_data(mixed.shares[::-1]))
    assert review.status_code == HTTPStatus.OK
    assert [row["share"].pk for row in review.context["review_rows"]] == [share.pk for share in mixed.shares[::-1]]
    assert not SolutionCollection.objects.exists()
    collection = publish(client, mixed.shares[::-1])
    assert collection.kind == SolutionCollection.Kind.ADMIN_CURATED
    assert collection.owner_id is None
    assert list(collection.entries.values_list("share_id", flat=True)) == [share.pk for share in mixed.shares[::-1]]
    assert len(set(collection.entries.values_list("anchor", flat=True))) == 2  # noqa: PLR2004
    assert list(SolutionPublicShare.objects.order_by("pk").values()) == before
    html = Client().get(public_path(collection)).content.decode()
    assert "SHARED-PROOF" in html
    assert "SECOND-PUBLIC-PROOF" in html
    assert "Hidden author" not in html
    assert mixed.first.author.email not in html
    assert mixed.second.author.email not in html


def test_admin_flow_never_calls_private_snapshot_or_share_writes(client, mixed, monkeypatch):
    def prohibited(*args, **kwargs):
        pytest.fail("Curation must not publish or inspect private saved work")

    monkeypatch.setattr("inspinia.solutions.views._public_snapshot", prohibited)
    monkeypatch.setattr("inspinia.solutions.views._write_shared_snapshot", prohibited)
    monkeypatch.setattr("inspinia.solutions.collection_views._public_snapshot", prohibited)
    monkeypatch.setattr("inspinia.solutions.collection_views._write_shared_snapshot", prohibited)
    assert publish(client, mixed.shares).entries.count() == 2  # noqa: PLR2004


def test_inventory_helpers_project_only_public_metadata(client, mixed):
    first = mixed.first
    first.title = "PRIVATE-TITLE-SHOULD-NOT-LEAK"
    first.save(update_fields=["title"])
    with CaptureQueriesContext(connection) as queries:
        rows = admin_collections.selection_rows([ref(share) for share in mixed.shares[::-1]])
    assert [row["id"] for row in rows] == [share.pk for share in mixed.shares[::-1]]
    assert rows[0]["author"] == ""
    assert rows[1]["label"] == "An elegant proof"
    sql = " ".join(query["sql"] for query in queries)
    assert "preview_image" not in sql
    assert '"solutions_problemsolution"."title"' not in sql
    assert '"solutions_solutionpublicshare"."snapshot" AS' not in sql
    response = client.get(edit_path(), {"share": [ref(share) for share in mixed.shares]})
    assert response.status_code == HTTPStatus.OK
    assert "PRIVATE-TITLE-SHOULD-NOT-LEAK" not in response.content.decode()
    assert "SHARED-PROOF" not in response.content.decode()


def test_inline_picker_browse_preserves_draft_without_writing(client, mixed):
    data = {**form_data(mixed.shares[::-1]), "action": "browse", "picker_q": "Another", "picker_page": "2"}
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"]["title"].value() == data["title"]
    assert response.context["form"]["introduction"].value() == data["introduction"]
    assert [row["ref"] for row in response.context["selected_shares"]] == data["share"]
    assert response.context["picker_page"].paginator.count == 1
    assert not SolutionCollection.objects.exists()


def test_native_picker_pagination_does_not_override_subsequent_review(client, mixed):
    data = {**form_data(mixed.shares), "picker_page": "2"}
    data.pop("action")
    browse = client.post(edit_path(), data)
    assert browse.status_code == HTTPStatus.OK
    assert not browse.context["review_rows"]
    assert browse.context["form"].data["title"] == data["title"]
    assert not SolutionCollection.objects.exists()
    review = client.post(edit_path(), {**data, "action": "review"})
    assert review.status_code == HTTPStatus.OK
    assert len(review.context["review_rows"]) == len(mixed.shares)
    assert b'type="hidden" name="action" value="browse"' not in browse.content
    assert not SolutionCollection.objects.exists()


def test_selection_metadata_endpoint_is_admin_only_bounded_and_read_only(client, mixed):
    path = reverse("solutions:admin_collection_selection")
    before = list(SolutionPublicShare.objects.values())
    response = client.get(path, {"share": [ref(share) for share in mixed.shares[::-1]]})
    assert response.status_code == HTTPStatus.OK
    assert [row["ref"] for row in response.json()["shares"]] == [ref(share) for share in mixed.shares[::-1]]
    assert all("snapshot" not in row for row in response.json()["shares"])
    assert "SHARED-PROOF" not in response.content.decode()
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]
    assert client.get(path, {"share": ["invalid"]}).status_code == HTTPStatus.BAD_REQUEST
    assert list(SolutionPublicShare.objects.values()) == before
    assert not SolutionCollection.objects.exists()
    assert Client().get(path).status_code == HTTPStatus.FOUND
    client.force_login(mixed.second.author)
    assert client.get(path).status_code == HTTPStatus.FORBIDDEN


def test_empty_draft_is_editable_but_review_requires_sources_and_valid_metadata(client, mixed):
    data = {**form_data([]), "action": "browse"}
    assert client.post(edit_path(), data).status_code == HTTPStatus.OK
    data["action"] = "review"
    assert client.post(edit_path(), data).status_code == HTTPStatus.BAD_REQUEST
    data = {**form_data(mixed.shares), "title": ""}
    assert client.post(edit_path(), data).status_code == HTTPStatus.BAD_REQUEST
    data = {**form_data(mixed.shares), "introduction": "x" * 2001}
    assert client.post(edit_path(), data).status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionCollection.objects.exists()


def test_review_size_limit_does_not_publish_sources_or_collection(client, mixed, monkeypatch):
    before = list(SolutionPublicShare.objects.values())
    monkeypatch.setattr(admin_collections, "MAX_COLLECTION_BYTES", 1)
    response = client.post(edit_path(), form_data(mixed.shares))
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "too large" in response.context["selection_error"]
    assert list(SolutionPublicShare.objects.values()) == before
    assert not SolutionCollection.objects.exists()


def test_append_existing_preserves_original_order_and_skips_duplicates(client, mixed):
    collection = publish(client, [mixed.shares[1]])
    response = client.get(edit_path(), {
        "target_collection": collection.pk, "share": [ref(share) for share in mixed.shares],
    })
    assert response.status_code == HTTPStatus.FOUND
    page = client.get(response["Location"])
    assert [row["ref"] for row in page.context["selected_shares"]] == [ref(share) for share in mixed.shares[::-1]]
    assert collection.entries.count() == 1


def test_append_overflow_retains_incoming_batch_and_target(client, mixed):
    collection = publish(client, mixed.shares)
    incoming = [f"{1000 + index}:{uuid.uuid4()}" for index in range(20)]
    response = client.get(edit_path(), {"target_collection": collection.pk, "share": incoming})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert [row["ref"] for row in response.context["selected_shares"]] == incoming
    assert response.context["target_collection"] == str(collection.pk)
    assert "exceed 20" in response.context["selection_error"]
    assert collection.entries.count() == 2  # noqa: PLR2004


@pytest.mark.parametrize("values", [
    ["not-a-reference"], ["0:" + str(uuid.uuid4())], ["-1:" + str(uuid.uuid4())],
    ["9999999999999999999999:" + str(uuid.uuid4())], ["1:no-token"],
    [f"{index}:{uuid.uuid4()}" for index in range(1, 22)],
])
def test_malformed_selection_returns_validation_error(client, mixed, values):
    response = client.get(edit_path(), {"share": values})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionCollection.objects.exists()


def test_duplicate_share_rejected_but_same_problem_allowed(client, mixed):
    data = form_data([mixed.shares[0], mixed.shares[0]])
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not SolutionCollection.objects.exists()
    assert publish(client, mixed.shares).entries.count() == 2  # noqa: PLR2004


def test_missing_stopped_and_rotated_sources_are_unavailable_without_fallback(client, mixed):
    share = mixed.shares[0]
    old_ref = ref(share)
    share.is_active = False
    share.snapshot = {}
    share.save()
    response = client.get(edit_path(), {"share": [old_ref]})
    assert not response.context["selected_shares"][0]["available"]
    assert "An elegant proof" not in response.content.decode()
    response = client.post(edit_path(), form_data([share]))
    assert response.status_code == HTTPStatus.BAD_REQUEST
    share.token, share.is_active = uuid.uuid4(), True
    share.save()
    assert not admin_collections.selection_rows([old_ref])[0]["available"]
    share.delete()
    assert not admin_collections.selection_rows([old_ref])[0]["available"]


@pytest.mark.parametrize("change", ["snapshot", "stop", "rotate", "delete"])
def test_source_changes_after_review_fail_atomically(client, mixed, change):
    data = confirm_data(client, mixed.shares)
    share = mixed.shares[0]
    if change == "snapshot":
        share.snapshot = {**share.snapshot, "summary": "Changed public copy"}
        share.revision = uuid.uuid4()
        share.save()
    elif change == "stop":
        share.is_active, share.snapshot = False, {}
        share.save()
    elif change == "rotate":
        share.token = uuid.uuid4()
        share.save()
    else:
        share.delete()
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()
    assert response.context["form"]["title"].value() == data["title"]
    assert [row["ref"] for row in response.context["selected_shares"]] == data["share"]


def test_failed_update_preserves_existing_collection_and_entries(client, mixed):
    collection = publish(client, mixed.shares)
    data = form_data(mixed.shares[::-1], collection)
    data["title"] = "Reviewed replacement title"
    review = client.post(edit_path(collection), data)
    before_collection = SolutionCollection.objects.values().get(pk=collection.pk)
    before_entries = list(collection.entries.values())
    share = mixed.shares[0]
    share.revision = uuid.uuid4()
    share.save()
    response = client.post(edit_path(collection), {
        **data, "action": "publish", "review_token": review.context["review_token"],
    })
    assert response.status_code == HTTPStatus.CONFLICT
    assert SolutionCollection.objects.values().get(pk=collection.pk) == before_collection
    assert list(collection.entries.values()) == before_entries


def test_storage_failure_during_publication_rolls_back_container_and_entries(client, mixed, monkeypatch):
    data = confirm_data(client, mixed.shares)
    original = SolutionCollectionEntry.save
    calls = []

    def fail_second_entry(entry, *args, **kwargs):
        calls.append(entry.share_id)
        if len(calls) == len(mixed.shares):
            message = "Synthetic entry storage failure"
            raise RuntimeError(message)
        return original(entry, *args, **kwargs)

    monkeypatch.setattr(SolutionCollectionEntry, "save", fail_second_entry)
    with pytest.raises(RuntimeError, match="Synthetic entry storage failure"):
        client.post(edit_path(), data)
    assert not SolutionCollection.objects.exists()
    assert not SolutionCollectionEntry.objects.exists()


def test_private_draft_profile_and_catalogue_edits_do_not_invalidate_review(client, mixed):
    data = confirm_data(client, mixed.shares)
    first = mixed.first
    first.title, first.summary = "PRIVATE-TITLE", "PRIVATE-SUMMARY"
    first.save()
    first.blocks.update(body_source="PRIVATE-PROOF")
    first.author.name = "NEW-PRIVATE-PROFILE"
    first.author.save(update_fields=["name"])
    first.problem.contest = "NEW-PRIVATE-CATALOGUE"
    first.problem.save(update_fields=["contest"])
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.FOUND
    collection = SolutionCollection.objects.get()
    html = Client().get(public_path(collection)).content.decode()
    assert "SHARED-PROOF" in html
    assert "PRIVATE-PROOF" not in html
    assert "NEW-PRIVATE-PROFILE" not in html
    assert "NEW-PRIVATE-CATALOGUE" not in html


def test_author_workflow_updates_and_revokes_every_curated_reference(client, mixed):
    collection = publish(client, mixed.shares)
    owner_client = Client()
    owner_client.force_login(mixed.first.author)
    editor = reverse("solutions:problem_solution_edit", args=[mixed.first.problem.problem_uuid])
    response = owner_client.post(editor, saved_editor_data(mixed.first, body="NEW-PRIVATE-PROOF"))
    assert response.status_code == HTTPStatus.FOUND
    assert "NEW-PRIVATE-PROOF" not in Client().get(public_path(collection)).content.decode()
    response = owner_client.post(share_path(mixed.first), sharing_data(owner_client, mixed.first, "update"))
    assert response.status_code == HTTPStatus.FOUND
    assert "NEW-PRIVATE-PROOF" in Client().get(public_path(collection)).content.decode()
    response = owner_client.post(share_path(mixed.first), sharing_data(owner_client, mixed.first, "stop"))
    assert response.status_code == HTTPStatus.FOUND
    assert "NEW-PRIVATE-PROOF" not in Client().get(public_path(collection)).content.decode()
    create_share(owner_client, mixed.first)
    assert "NEW-PRIVATE-PROOF" not in Client().get(public_path(collection)).content.decode()


@pytest.mark.parametrize("tamper", ["title", "order", "token", "actor", "personal_salt", "expired"])
def test_review_is_bound_to_content_order_actor_context_and_expiry(client, mixed, monkeypatch, tamper):
    data = confirm_data(client, mixed.shares)
    if tamper == "title":
        data["title"] = "Unreviewed title"
    elif tamper == "order":
        data["share"] = data["share"][::-1]
    elif tamper == "token":
        data["review_token"] += "tamper"
    elif tamper == "actor":
        client.force_login(UserFactory(role=User.Role.ADMIN))
    elif tamper == "personal_salt":
        payload = signing.loads(data["review_token"], salt=admin_collections.REVIEW_SALT)
        data["review_token"] = signing.dumps(payload, salt="solutions.collection-review")
    else:
        expired_time = signing.time.time() + 3601
        monkeypatch.setattr(signing, "time", SimpleNamespace(time=lambda: expired_time))
    response = client.post(edit_path(), data)
    assert response.status_code == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()


def test_reordering_preserves_anchors_and_sources_remain_unchanged(client, mixed):
    collection = publish(client, mixed.shares)
    before_sources = list(SolutionPublicShare.objects.order_by("pk").values())
    anchors = dict(collection.entries.values_list("share_id", "anchor"))
    token = collection.token
    collection = publish(client, mixed.shares[::-1], collection)
    assert dict(collection.entries.values_list("share_id", "anchor")) == anchors
    assert list(collection.entries.values_list("share_id", flat=True)) == [share.pk for share in mixed.shares[::-1]]
    assert collection.token == token
    assert list(SolutionPublicShare.objects.order_by("pk").values()) == before_sources


def test_generation_replacement_requires_explicit_reselection_and_new_anchor(client, mixed):
    collection = publish(client, mixed.shares)
    entry = collection.entries.get(share=mixed.shares[0])
    old_anchor = entry.anchor
    share = mixed.shares[0]
    share.token, share.revision = uuid.uuid4(), uuid.uuid4()
    share.save()
    html = Client().get(public_path(collection)).content.decode()
    assert "SHARED-PROOF" not in html
    response = client.get(edit_path(), {"target_collection": collection.pk, "share": [ref(share)]})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Remove the unavailable entry" in response.context["selection_error"]
    response = client.get(edit_path(collection))
    assert not response.context["selected_shares"][0]["available"]
    # The final ordered draft explicitly replaces the old generation after removal/reselection.
    collection = publish(client, mixed.shares, collection)
    entry.refresh_from_db()
    assert entry.anchor != old_anchor
    assert entry.share_token == share.token
    assert "SHARED-PROOF" in Client().get(public_path(collection)).content.decode()


def test_concurrent_admin_edit_preserves_attempted_draft_and_rejects_stale_confirmation(client, mixed):
    collection = publish(client, mixed.shares)
    stale_data = confirm_data(client, mixed.shares[::-1], collection)
    stale_data["title"] = "Attempt from another tab"
    original_revision = collection.revision
    collection = publish(client, [mixed.shares[0]], collection)
    response = client.post(edit_path(collection), stale_data)
    assert response.status_code == HTTPStatus.CONFLICT
    assert response.context["conflict"]
    assert response.context["collection_revision"] == str(original_revision)
    assert response.context["form"]["title"].value() == "Attempt from another tab"
    collection.refresh_from_db()
    assert collection.title == "Two ways to prove it"
    assert collection.entries.count() == 1


def test_stopping_with_unavailable_entries_and_resharing_rotates_only_collection_token(client, mixed):
    collection = publish(client, mixed.shares)
    old_path = public_path(collection)
    original_source_tokens = [share.token for share in mixed.shares]
    SolutionPublicShare.objects.filter(pk__in=[share.pk for share in mixed.shares]).update(is_active=False)
    assert Client().get(old_path).status_code == HTTPStatus.OK
    assert "No solutions are currently available" in Client().get(old_path).content.decode()
    response = client.post(edit_path(collection), {"action": "stop", "collection_revision": str(collection.revision)})
    assert response.status_code == HTTPStatus.FOUND
    assert Client().get(old_path).status_code == HTTPStatus.NOT_FOUND
    collection.refresh_from_db()
    SolutionPublicShare.objects.filter(pk__in=[share.pk for share in mixed.shares]).update(is_active=True)
    collection = publish(client, mixed.shares, collection)
    assert public_path(collection) != old_path
    assert list(SolutionPublicShare.objects.order_by("pk").values_list("token", flat=True)) == original_source_tokens


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.MODERATOR, User.Role.TRAINER])
def test_non_admin_roles_and_staff_cannot_manage(client, mixed, role):
    client.force_login(UserFactory(role=role, is_staff=True))
    for path in [reverse("solutions:admin_collections"), edit_path()]:
        assert client.get(path).status_code == HTTPStatus.FORBIDDEN
    assert client.post(edit_path(), form_data(mixed.shares)).status_code == HTTPStatus.FORBIDDEN


def test_superuser_and_other_admin_can_manage_shared_workspace(client, mixed):
    collection = publish(client, mixed.shares)
    client.force_login(UserFactory(role=User.Role.NORMAL, is_superuser=True))
    assert client.get(edit_path(collection)).status_code == HTTPStatus.OK
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assert publish(client, mixed.shares[::-1], collection).entries.count() == 2  # noqa: PLR2004


def test_anonymous_requests_require_login_and_csrf_is_enforced(client, mixed):
    anonymous = Client()
    assert anonymous.get(edit_path()).status_code == HTTPStatus.FOUND
    assert anonymous.post(edit_path(), form_data(mixed.shares)).status_code == HTTPStatus.FOUND
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(mixed.admin)
    assert strict.post(edit_path(), form_data(mixed.shares)).status_code == HTTPStatus.FORBIDDEN


def test_demotion_after_review_denies_confirmation_and_keeps_publication(client, mixed):
    collection = publish(client, mixed.shares)
    data = confirm_data(client, mixed.shares, collection)
    User.objects.filter(pk=mixed.admin.pk).update(role=User.Role.NORMAL)
    assert client.post(edit_path(collection), data).status_code == HTTPStatus.FORBIDDEN
    assert Client().get(public_path(collection)).status_code == HTTPStatus.OK


@pytest.mark.parametrize("change", ["demote", "deactivate"])
def test_admin_authority_is_refreshed_after_waiting_for_source_locks(client, mixed, monkeypatch, change):
    data = confirm_data(client, mixed.shares)
    original = admin_collections._review_rows  # noqa: SLF001 - deliberate mutation-boundary regression

    def demote_after_read(refs, *, lock=False):
        rows = original(refs, lock=lock)
        if lock:
            changes = {"role": User.Role.NORMAL} if change == "demote" else {"is_active": False}
            User.objects.filter(pk=mixed.admin.pk).update(**changes)
        return rows

    monkeypatch.setattr(admin_collections, "_review_rows", demote_after_read)
    assert client.post(edit_path(), data).status_code == HTTPStatus.FORBIDDEN
    assert not SolutionCollection.objects.exists()


def test_curator_deletion_keeps_container_and_contributor_deletion_removes_only_their_entries(client, mixed):
    collection = publish(client, mixed.shares)
    mixed.admin.delete()
    assert SolutionCollection.objects.filter(pk=collection.pk).exists()
    assert Client().get(public_path(collection)).status_code == HTTPStatus.OK
    mixed.first.author.delete()
    assert collection.entries.count() == 1
    html = Client().get(public_path(collection)).content.decode()
    assert "SECOND-PUBLIC-PROOF" in html
    assert "SHARED-PROOF" not in html


def test_personal_and_curated_management_routes_are_isolated(client, mixed):
    personal = SolutionCollection.objects.create(owner=mixed.admin, title="Personal collection")
    assert client.get(edit_path(personal)).status_code == HTTPStatus.NOT_FOUND
    collection = publish(client, mixed.shares)
    personal_path = reverse("solutions:collection_edit", args=[collection.pk])
    assert client.get(personal_path).status_code == HTTPStatus.NOT_FOUND
    response = client.post(personal_path, {"action": "stop", "collection_revision": str(collection.revision)})
    assert response.status_code == HTTPStatus.NOT_FOUND
    html = client.get(reverse("solutions:my_solution_list")).content.decode()
    assert "Personal collection" in html
    assert "Two ways to prove it" not in html


def test_list_counts_availability_filters_and_headers(client, mixed):
    collection = publish(client, mixed.shares)
    SolutionPublicShare.objects.filter(pk=mixed.shares[0].pk).update(is_active=False)
    SolutionCollection.objects.create(owner=mixed.admin, title="Other personal collection")
    response = client.get(reverse("solutions:admin_collections"), {"q": "Two ways", "status": "active"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["page_obj"].paginator.count == 1
    row = response.context["page_obj"][0]
    assert row.total_entries == 2  # noqa: PLR2004
    assert row.available_entries == 1
    assert row.pk == collection.pk
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]
    assert response["Referrer-Policy"] == "same-origin"


def test_management_list_is_paginated_and_excludes_personal_containers(client, mixed):
    for index in range(26):
        SolutionCollection.objects.create(kind=SolutionCollection.Kind.ADMIN_CURATED, title=f"Curated {index}")
    SolutionCollection.objects.create(owner=mixed.admin, title="Curated personal")
    response = client.get(reverse("solutions:admin_collections"), {"q": "Curated", "page": "2"})
    assert response.context["page_obj"].paginator.count == 26  # noqa: PLR2004
    assert len(response.context["page_obj"]) == 1
    assert response.context["page_obj"][0].title == "Curated 0"


def test_curation_does_not_change_source_views_or_completion(client, mixed):
    SolutionShareDailyViews.objects.create(share=mixed.shares[0], day="2026-10-31", views=11)
    before = deepcopy(list(SolutionShareDailyViews.objects.values()))
    collection = publish(client, mixed.shares)
    Client().get(public_path(collection))
    assert list(SolutionShareDailyViews.objects.values()) == before
    assert mixed.first.problem.user_completions.count() == 0


def test_ownership_constraint_rejects_unknown_kind_and_invalid_owner_combinations(mixed):
    for kind, owner in [("unknown", None), ("personal", None), ("admin_curated", mixed.admin)]:
        with transaction.atomic(), pytest.raises(IntegrityError):
            SolutionCollection.objects.create(title="Invalid", kind=kind, owner=owner)


def test_selection_parser_handles_empty_and_canonical_references(mixed):
    assert admin_collections.parse_refs([]) == []
    with pytest.raises(ValidationError):
        admin_collections.parse_refs([], allow_empty=False)
    share = mixed.shares[0]
    assert admin_collections.parse_refs([f"00{share.pk}:{str(share.token).upper()}"]) == [ref(share)]
