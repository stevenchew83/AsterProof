"""Managed images obey the same private/member/shared-copy boundary as proof text."""

import uuid
from http import HTTPStatus
from io import BytesIO

import pytest
from django.conf.urls.static import static
from django.core.files.base import ContentFile
from django.test import Client
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.image_access import editor_image_base_url
from inspinia.solutions.image_access import image_paths
from inspinia.solutions.image_access import internal_image_base_url
from inspinia.solutions.image_access import public_image_base_url
from inspinia.solutions.image_access import raw_image_urlpatterns
from inspinia.solutions.image_access import snapshot_image_paths
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionCollectionEntry
from inspinia.solutions.models import SolutionPublicShare
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def images(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    owner = UserFactory()
    problem = ProblemSolveRecord.objects.create(contest="IMAGE ACCESS", year=2026, problem="P1", topic="GEO")
    solution = ProblemSolution.objects.create(problem=problem, author=owner, status=ProblemSolution.Status.PUBLISHED)
    rows = []
    for _index in range(2):
        output = BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, "PNG")
        row = SolutionBodyImage(solution=solution, uploaded_by=owner)
        row.file.save("paste.png", ContentFile(output.getvalue()), save=True)
        rows.append(row)
    solution.blocks.create(position=1, body_source=rf"The figure: \includegraphics{{{rows[0].file.name}}}")
    return owner, solution, rows


def fetch(client, path):
    response = client.get(path)
    if response.streaming:
        response.image_bytes = b"".join(response.streaming_content)
    return response


def snapshot(path, *, legacy=False):
    value = {
        "version": 1 if legacy else 2, "title": "Public image proof", "author": "Learner", "date": "",
        "summary": "", "show_footer": False,
        "problem": {"label": "Synthetic P1", "topic": "Geometry", "segments": []},
    }
    if legacy:
        value["blocks"] = [{"heading": "Proof", "format": "latex", "source": rf"\includegraphics{{{path}}}"}]
    else:
        value["document"] = {"format": "latex", "source": rf"\includegraphics{{{path}}}"}
    return value


def make_share(solution, path, **changes):
    values = {"is_active": True, "snapshot": snapshot(path), "source_updated_at": solution.updated_at}
    return SolutionPublicShare.objects.create(solution=solution, **{**values, **changes})


def test_private_image_requires_authentication(images):
    _owner, solution, rows = images
    response = Client().get(internal_image_base_url(solution.pk) + rows[0].file.name)
    assert response.status_code == HTTPStatus.FOUND
    assert "/accounts/login/" in response.url


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.TRAINER, User.Role.MODERATOR])
def test_members_can_read_only_referenced_images_of_published_solutions(client, images, role):
    _owner, solution, rows = images
    client.force_login(UserFactory(role=role))
    base = internal_image_base_url(solution.pk)
    response = fetch(client, base + rows[0].file.name)
    assert response.status_code == HTTPStatus.OK
    assert response.image_bytes.startswith(b"\x89PNG")
    assert response["Content-Type"] == "image/png"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]
    assert client.get(base + rows[1].file.name).status_code == HTTPStatus.NOT_FOUND
    solution.status = ProblemSolution.Status.DRAFT
    solution.save()
    assert client.get(base + rows[0].file.name).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("admin", [False, True])
def test_owner_and_admin_can_preview_unused_draft_images(client, images, admin):
    owner, solution, rows = images
    solution.status = ProblemSolution.Status.DRAFT
    solution.save()
    client.force_login(UserFactory(role=User.Role.ADMIN) if admin else owner)
    assert fetch(client, internal_image_base_url(solution.pk) + rows[1].file.name).status_code == HTTPStatus.OK


def test_editor_route_is_owner_scoped_and_supports_unused_uploads(client, images):
    owner, solution, rows = images
    path = editor_image_base_url(solution.problem.problem_uuid) + rows[1].file.name
    client.force_login(owner)
    assert fetch(client, path).status_code == HTTPStatus.OK
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assert client.get(path).status_code == HTTPStatus.NOT_FOUND


def test_pending_account_cannot_read_own_image(client, images):
    owner, solution, rows = images
    owner.is_approved = False
    owner.save()
    client.force_login(owner)
    response = client.get(internal_image_base_url(solution.pk) + rows[0].file.name)
    assert response.status_code == HTTPStatus.FOUND
    assert "approval" in response.url


def test_image_ownership_is_checked_even_when_proof_references_another_solution(client, images):
    _owner, solution, rows = images
    foreign = ProblemSolution.objects.create(problem=solution.problem, author=UserFactory(), status="published")
    foreign.blocks.create(position=1, body_source=rf"\includegraphics{{{rows[0].file.name}}}")
    client.force_login(UserFactory())
    assert client.get(internal_image_base_url(foreign.pk) + rows[0].file.name).status_code == HTTPStatus.NOT_FOUND




@pytest.mark.parametrize("legacy", [False, True])
def test_public_image_is_bound_to_shared_snapshot_not_current_private_content(images, legacy):
    _owner, solution, rows = images
    share = make_share(solution, rows[0].file.name, snapshot=snapshot(rows[0].file.name, legacy=legacy))
    solution.status = "draft"
    solution.save()
    solution.blocks.update(body_source=rf"PRIVATE: \includegraphics{{{rows[1].file.name}}}")
    client = Client()
    base = public_image_base_url(share)
    assert fetch(client, base + rows[0].file.name).status_code == HTTPStatus.OK
    assert client.get(base + rows[1].file.name).status_code == HTTPStatus.NOT_FOUND


def test_public_image_revision_and_revocation_are_rechecked(images):
    _owner, solution, rows = images
    share = make_share(solution, rows[0].file.name)
    old_path = public_image_base_url(share) + rows[0].file.name
    client = Client()
    assert fetch(client, old_path).status_code == HTTPStatus.OK
    share.revision = uuid.uuid4()
    share.save()
    assert client.get(old_path).status_code == HTTPStatus.NOT_FOUND
    new_path = public_image_base_url(share) + rows[0].file.name
    assert fetch(client, new_path).status_code == HTTPStatus.OK
    share.is_active = False
    share.save()
    assert client.get(new_path).status_code == HTTPStatus.NOT_FOUND


def test_public_image_rejects_cross_solution_snapshot_reference(images):
    _owner, solution, rows = images
    foreign = ProblemSolution.objects.create(problem=solution.problem, author=UserFactory())
    share = make_share(foreign, rows[0].file.name)
    assert Client().get(public_image_base_url(share) + rows[0].file.name).status_code == HTTPStatus.NOT_FOUND


def test_public_readers_and_collections_scope_each_paper_without_mutating_snapshots(images):
    owner, solution, rows = images
    share = make_share(solution, rows[0].file.name)
    collection = SolutionCollection.objects.create(owner=owner, title="Images", is_active=True)
    SolutionCollectionEntry.objects.create(collection=collection, share=share, share_token=share.token, position=1)
    client = Client()
    for path in [
        reverse("solutions:public_solution", args=[share.token]),
        reverse("solutions:public_collection", args=[collection.token]),
    ]:
        response = client.get(path)
        assert response.status_code == HTTPStatus.OK
        assert f'data-solution-image-base-url="{public_image_base_url(share)}"' in response.content.decode()
    share.refresh_from_db()
    assert share.snapshot == snapshot(rows[0].file.name)


def test_missing_and_corrupt_image_files_fail_closed(client, images):
    owner, solution, rows = images
    client.force_login(owner)
    missing = rows[0].file.name
    rows[0].file.delete(save=False)
    assert client.get(internal_image_base_url(solution.pk) + missing).status_code == HTTPStatus.NOT_FOUND
    path = rows[1].file.name
    with rows[1].file.storage.open(path, "wb") as stream:
        stream.write(b"<script>alert(1)</script>")
    assert client.get(internal_image_base_url(solution.pk) + path).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("path", [
    "/media/solution_body_images/" + "a" * 32 + ".png",
    "/media/solution_body_images/../solution_body_images/" + "a" * 32 + ".png",
    "/media/solution_body_images/%2e%2e/solution_body_images/" + "a" * 32 + ".png",
])
def test_direct_media_paths_never_serve_solution_images(path):
    assert Client().get(path).status_code == HTTPStatus.NOT_FOUND


def test_development_deny_precedes_static_serving_even_for_existing_files(images, settings):
    _owner, _solution, rows = images
    with override_settings(DEBUG=True, MEDIA_URL="/media/"):
        urls = type("ImageTestUrls", (), {"urlpatterns": [
            *raw_image_urlpatterns(), *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        ]})
        with override_settings(ROOT_URLCONF=urls):
            assert Client().get("/media/" + rows[0].file.name).status_code == HTTPStatus.NOT_FOUND
            # Other media still uses the existing serving route.
            original = rows[0].file.storage.open(rows[0].file.name, "rb").read()
            rows[0].file.storage.save("unrelated.png", ContentFile(original))
            assert fetch(Client(), "/media/unrelated.png").status_code == HTTPStatus.OK


def test_managed_references_reject_urls_traversal_and_plain_text_blocks():
    valid = "solution_body_images/" + "a" * 32 + ".png"
    assert image_paths(rf"\includegraphics[width=0.9\linewidth]{{{valid}}}") == [valid]
    assert image_paths(r"\includegraphics{../secret.png} \includegraphics{https://example.com/secret.png}") == []
    plain = {"blocks": [{"format": "plain_text", "source": rf"\includegraphics{{{valid}}}"}]}
    assert snapshot_image_paths(plain) == []


def test_managed_reference_extraction_obeys_unescaped_tex_comments():
    valid = "solution_body_images/" + "a" * 32 + ".png"
    graphics = rf"\includegraphics{{{valid}}}"
    assert image_paths("Mentioning " + valid + " does not reference an image.") == []
    assert image_paths("Proof.\n% " + graphics) == []
    assert image_paths("Proof.\n" + graphics + " % visible diagram") == [valid]
    assert image_paths(r"\% " + graphics) == [valid]
    assert image_paths(r"\\% " + graphics) == []
