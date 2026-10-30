"""Editor popover uses the same owner-only, explicitly reviewed snapshots."""

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions import test_public_sharing as sharing_tests
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.test_public_sharing import image_path
from inspinia.solutions.test_public_sharing import public_path
from inspinia.solutions.test_public_sharing import saved_editor_data
from inspinia.solutions.test_public_sharing import share_path
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
JSON_ACCEPT = {"HTTP_ACCEPT": "application/json"}
# Exercise HTML and JSON sharing with the same saved-solution fixture.
writing = sharing_tests.writing


def state(client, solution):
    response = client.get(share_path(solution), **JSON_ACCEPT)
    assert response.status_code == HTTPStatus.OK
    assert "no-store" in response["Cache-Control"]
    return response.json()


def post(client, solution, settings, action, **extra):
    data = {key: settings[key] for key in ("source_version", "share_revision", "review_digest")}
    return client.post(share_path(solution), {**data, "action": action, **extra}, **JSON_ACCEPT)


def test_opening_popover_never_enables_sharing_or_returns_proof_text(client, writing):
    settings = state(client, writing)
    assert not settings["is_active"]
    assert settings["can_share"]
    assert settings["saved_title"] == writing.title
    assert settings["share_url"] == ""
    assert settings["whatsapp_url"] == ""
    assert settings["preview_url"] == share_path(writing)
    assert settings["review_digest"]
    assert "SHARED-PROOF" not in str(settings)
    assert writing.author.email not in str(settings)
    assert not SolutionPublicShare.objects.exists()


def test_popover_create_ignores_unsaved_editor_content_and_does_not_record_progress(client, writing):
    response = post(client, writing, state(client, writing), "create", **{
        "solution-title": "UNSAVED-TITLE", "blocks-0-body_source": "UNSAVED-PROOF",
    })
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"ok": True, "message": "Public link created."}
    share = SolutionPublicShare.objects.get(solution=writing)
    assert share.snapshot["title"] == "An elegant proof"
    assert "UNSAVED" not in str(share.snapshot)
    writing.refresh_from_db()
    assert writing.status == ProblemSolution.Status.DRAFT
    assert not UserProblemCompletion.objects.exists()
    latest = state(client, writing)
    assert latest["is_active"]
    assert not latest["has_saved_changes"]
    assert latest["preview_url"] == latest["share_url"]
    assert latest["share_url"] == "https://asterproof.example" + public_path(share)
    assert "https://wa.me/?text=" in latest["whatsapp_url"]


def test_popover_update_and_stop_preserve_private_source_and_revoke_image(client, writing):
    assert post(client, writing, state(client, writing), "create").json()["ok"]
    share = SolutionPublicShare.objects.get(solution=writing)
    old_token, old_image = share.token, image_path(share)
    editor = reverse("solutions:problem_solution_edit", args=[writing.problem.problem_uuid])
    assert client.post(editor, saved_editor_data(writing)).status_code == HTTPStatus.FOUND
    before = state(client, writing)
    assert before["has_saved_changes"]
    assert before["saved_title"] == "PRIVATE-REVISION"
    share.refresh_from_db()
    assert share.snapshot["title"] == "An elegant proof"
    assert post(client, writing, before, "update").json()["ok"]
    share.refresh_from_db()
    assert share.token == old_token
    assert share.snapshot["title"] == "PRIVATE-REVISION"
    assert Client().get(old_image).status_code == HTTPStatus.NOT_FOUND
    new_image = image_path(share)
    assert post(client, writing, state(client, writing), "stop").json()["ok"]
    share.refresh_from_db()
    assert not share.is_active
    assert Client().get(public_path(share)).status_code == HTTPStatus.NOT_FOUND
    assert Client().get(new_image).status_code == HTTPStatus.NOT_FOUND
    writing.refresh_from_db()
    assert writing.title == "PRIVATE-REVISION"
    assert writing.blocks.exists()
    assert not state(client, writing)["is_active"]


@pytest.mark.parametrize("changed", ["source", "author", "sharing"])
def test_popover_conflicts_return_json_and_never_retry_or_replace_snapshot(client, writing, changed):
    assert post(client, writing, state(client, writing), "create").json()["ok"]
    stale = state(client, writing)
    if changed == "source":
        writing.title = "Newer saved work"
        writing.save()
    elif changed == "author":
        writing.author.name = "New profile name"
        writing.author.save()
    else:
        assert post(client, writing, stale, "stop").json()["ok"]
    response = post(client, writing, stale, "update")
    assert response.status_code == HTTPStatus.CONFLICT
    assert not response.json()["ok"]
    share = SolutionPublicShare.objects.get(solution=writing)
    if changed == "sharing":
        assert not share.is_active
    else:
        assert share.snapshot["title"] == "An elegant proof"
        assert share.snapshot["author"] == "Ada Learner"


@pytest.mark.parametrize("identity", ["anonymous", "other", "pending"])
def test_json_mode_preserves_owner_and_approval_boundaries(client, writing, identity):
    outsider = Client()
    if identity != "anonymous":
        outsider.force_login(UserFactory(is_approved=identity != "pending"))
    expected = HTTPStatus.NOT_FOUND if identity == "other" else HTTPStatus.FOUND
    assert outsider.get(share_path(writing), **JSON_ACCEPT).status_code == expected
    assert post(outsider, writing, state(client, writing), "create").status_code == expected
    assert not SolutionPublicShare.objects.exists()


def test_json_mutations_require_csrf_and_reject_unknown_actions(client, writing):
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(writing.author)
    settings = state(client, writing)
    assert post(guarded, writing, settings, "create").status_code == HTTPStatus.FORBIDDEN
    response = post(client, writing, settings, "unexpected")
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not response.json()["ok"]
    assert not SolutionPublicShare.objects.exists()


def test_unshareable_saved_content_still_allows_copy_and_stop_without_flashes(client, writing):
    assert post(client, writing, state(client, writing), "create").json()["ok"]
    writing.blocks.all().delete()
    settings = state(client, writing)
    assert settings["is_active"]
    assert not settings["can_share"]
    assert settings["share_url"]
    assert settings["error"]
    assert "_messages" not in client.session
    assert post(client, writing, settings, "stop").json()["ok"]


def test_dialog_is_outside_editor_form_and_has_native_focus_and_mobile_hooks(client, writing):
    editor = reverse("solutions:problem_solution_edit", args=[writing.problem.problem_uuid])
    html = client.get(editor).content.decode()
    assert 'id="solution-share-trigger"' in html
    assert 'aria-haspopup="dialog"' in html
    assert 'aria-controls="solution-share-dialog"' in html
    assert "data-share-fallback" in html
    assert html.index("</dialog>") < html.index('id="solution-editor-form"')
    assert "Copy link" in html
    assert "WhatsApp" in html
    assert "Update shared version" in html
    assert "Stop sharing" in html
    assert "Unsaved editor changes are excluded" in html
    writing.delete()
    html = client.get(editor).content.decode()
    assert 'id="solution-share-trigger"' in html
    assert "data-share-url=" not in html
