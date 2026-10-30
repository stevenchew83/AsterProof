"""Public links expose reviewed snapshots, never the changing private editor."""

import uuid
from copy import deepcopy
from http import HTTPStatus
from io import BytesIO

import pytest
from django.test import Client
from django.urls import reverse
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.sharing import public_preview_image
from inspinia.solutions.sharing import snapshot_digest
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
PREVIEW_IMAGE_BUDGET = 150_000


@pytest.fixture
def writing(client, settings):
    settings.PUBLIC_SITE_ORIGIN = "https://asterproof.example"
    author = UserFactory(name="Ada Learner")
    client.force_login(author)
    problem = ProblemSolveRecord.objects.create(
        contest="SHARING TEST", year=2026, problem="P1", topic="ALG", mohs=5,
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=problem.contest, contest_year=2026,
        problem_code="P1", problem_number=1, topic="ALG", statement_latex=r"Prove $x^2\geq 0$.",
    )
    solution = ProblemSolution.objects.create(
        problem=problem, author=author, title="An elegant proof", summary="Look for a square.",
        pdf_show_date=False, pdf_show_footer=False,
    )
    ProblemSolutionBlock.objects.create(
        solution=solution, block_type=SolutionBlockType.objects.get(slug="proof"), position=2,
        title="The argument", body_source=r"SHARED-PROOF: $x^2\geq 0$.",
    )
    ProblemSolutionBlock.objects.create(
        solution=solution, block_type=SolutionBlockType.objects.get(slug="idea"), position=1,
        body_format="plain_text", body_source="LITERAL $x$ <b>stays text</b>.",
    )
    return solution


def share_path(solution):
    return reverse("solutions:problem_solution_share", args=[solution.problem.problem_uuid])


def sharing_data(client, solution, action="create"):
    solution.refresh_from_db()
    review = client.get(share_path(solution))
    share = review.context["share"]
    return {
        "action": action, "source_version": solution.updated_at.isoformat(),
        "share_revision": str(share.revision) if share else "",
        "review_digest": review.context["review_digest"],
    }


def create_share(client, solution):
    response = client.post(share_path(solution), sharing_data(client, solution))
    assert response.status_code == HTTPStatus.FOUND
    return SolutionPublicShare.objects.get(solution=solution)


def public_path(share):
    return reverse("solutions:public_solution", args=[share.token])


def image_path(share):
    return reverse("solutions:public_solution_image", args=[share.token, share.revision])


def saved_editor_data(solution, *, title="PRIVATE-REVISION", body="PRIVATE-PROOF-CHANGES"):
    blocks = list(solution.blocks.order_by("position"))
    data = {
        "action": "save", "solution-title": title, "solution-summary": "PRIVATE-SUMMARY",
        "solution-pdf_options_present": "1", "blocks-TOTAL_FORMS": str(len(blocks)),
        "blocks-INITIAL_FORMS": str(len(blocks)), "blocks-MIN_NUM_FORMS": "0", "blocks-MAX_NUM_FORMS": "1000",
    }
    for index, block in enumerate(blocks):
        data.update({
            f"blocks-{index}-id": str(block.pk), f"blocks-{index}-block_type": str(block.block_type_id),
            f"blocks-{index}-title": block.title, f"blocks-{index}-body_format": block.body_format,
            f"blocks-{index}-body_source": body + str(index), f"blocks-{index}-ORDER": str(index + 1),
        })
    return data


@pytest.mark.parametrize("status", [ProblemSolution.Status.DRAFT, ProblemSolution.Status.PUBLISHED])
def test_saving_or_publishing_does_not_automatically_create_a_public_link(client, writing, status):
    editor = reverse("solutions:problem_solution_edit", args=[writing.problem.problem_uuid])
    data = saved_editor_data(writing)
    data["action"] = "publish" if status == ProblemSolution.Status.PUBLISHED else "save"
    assert client.post(editor, data).status_code == HTTPStatus.FOUND
    writing.refresh_from_db()
    assert writing.status == status
    review = client.get(share_path(writing))
    assert review.status_code == HTTPStatus.OK
    assert "Create public link" in review.content.decode()
    assert not SolutionPublicShare.objects.exists()
    anonymous = Client()
    assert anonymous.get(share_path(writing)).status_code == HTTPStatus.FOUND
    assert anonymous.get(editor).status_code == HTTPStatus.FOUND


def test_creation_is_explicit_keeps_status_and_progress_and_snapshots_order(client, writing):
    review = client.get(share_path(writing))
    assert "Review saved version" in review.content.decode()
    share = create_share(client, writing)
    writing.refresh_from_db()
    assert share.is_active
    assert writing.status == ProblemSolution.Status.DRAFT
    assert writing.published_at is None
    assert not UserProblemCompletion.objects.exists()
    assert [block["label"] for block in share.snapshot["blocks"]] == ["Idea", "Proof"]
    assert share.snapshot["blocks"][0]["format"] == "plain_text"
    assert share.snapshot["blocks"][1]["heading"] == "The argument"
    assert share.snapshot["author"] == "Ada Learner"
    assert share.snapshot["date"] == ""
    assert not share.snapshot["show_footer"]


def test_anonymous_reading_has_server_metadata_and_no_private_context(client, writing):
    share = create_share(client, writing)
    response = Client().get(public_path(share))
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    for expected in ["An elegant proof", "SHARED-PROOF", "SHARING TEST", "Algebra", "MOHS 5", "Ada Learner"]:
        assert expected in html
    assert writing.author.email not in html
    assert "Your progress" not in html
    assert "Edit draft" not in html
    assert "csrfmiddlewaretoken" not in html
    assert 'property="og:type" content="article"' in html
    assert 'property="og:title" content="An elegant proof | AsterProof"' in html
    assert f'property="og:url" content="https://asterproof.example{public_path(share)}"' in html
    assert f'property="og:image" content="https://asterproof.example{image_path(share)}"' in html
    assert 'property="og:description"' in html
    assert 'property="og:image:width" content="1200"' in html
    assert 'property="og:image:alt" content="AsterProof logo"' in html
    assert "https://wa.me/?text=https%3A%2F%2Fasterproof.example" in html
    assert "noindex" in response["X-Robots-Tag"]
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    assert not response.context["snapshot"]["date"]
    assert "Page number" not in html


def test_public_image_is_the_prebuilt_lightweight_website_logo(client, writing, monkeypatch):
    share = create_share(client, writing)

    def must_not_build(*args, **kwargs):
        pytest.fail("Anonymous requests must not render snapshots, compile TeX, or regenerate images")

    monkeypatch.setattr("inspinia.solutions.views._public_snapshot", must_not_build)
    monkeypatch.setattr("inspinia.solutions.views.public_preview_image", must_not_build)
    response = Client().get(image_path(share))
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "image/jpeg"
    assert response.content == public_preview_image() == bytes(share.preview_image)
    assert len(response.content) < PREVIEW_IMAGE_BUDGET
    image = Image.open(BytesIO(response.content))
    assert image.size == (1200, 630)
    assert image.format == "JPEG"
    assert "no-store" in response["Cache-Control"]
    assert Client().get(public_path(share)).status_code == HTTPStatus.OK
    assert Client().head(public_path(share)).status_code == HTTPStatus.OK
    assert Client().head(image_path(share)).status_code == HTTPStatus.OK


def test_existing_links_use_the_logo_without_changing_the_shared_snapshot(client, writing):
    share = create_share(client, writing)
    snapshot, revision = share.snapshot, share.revision
    share.preview_image = b"Previous solution-specific thumbnail"
    share.save(update_fields=["preview_image"])
    response = Client().get(image_path(share))
    assert response.status_code == HTTPStatus.OK
    assert response.content == public_preview_image()
    share.refresh_from_db()
    assert share.snapshot == snapshot
    assert share.revision == revision
    assert bytes(share.preview_image) == b"Previous solution-specific thumbnail"


def test_real_editor_save_stays_private_until_explicit_update(client, writing):
    share = create_share(client, writing)
    initial_url, old_image = public_path(share), image_path(share)
    initial_revision, initial_image = share.revision, bytes(share.preview_image)
    editor = reverse("solutions:problem_solution_edit", args=[writing.problem.problem_uuid])
    saved = client.post(editor, saved_editor_data(writing))
    assert saved.status_code == HTTPStatus.FOUND
    share.refresh_from_db()
    assert share.revision == initial_revision
    assert bytes(share.preview_image) == initial_image
    public_html = Client().get(initial_url).content.decode()
    assert "SHARED-PROOF" in public_html
    assert "PRIVATE-REVISION" not in public_html
    assert "PRIVATE-PROOF" not in public_html
    review = client.get(share_path(writing))
    assert review.context["share_outdated"]
    assert "PRIVATE-REVISION" in review.content.decode()
    updated = client.post(share_path(writing), sharing_data(client, writing, "update"))
    assert updated.status_code == HTTPStatus.FOUND
    share.refresh_from_db()
    assert public_path(share) == initial_url
    assert share.revision != initial_revision
    assert bytes(share.preview_image) == initial_image == public_preview_image()
    assert Client().get(old_image).status_code == HTTPStatus.NOT_FOUND
    new_html = Client().get(initial_url).content.decode()
    assert "PRIVATE-REVISION" in new_html
    assert "PRIVATE-PROOF" in new_html
    assert "SHARED-PROOF" not in new_html
    assert not UserProblemCompletion.objects.exists()


def test_stop_disables_page_and_all_image_revisions_and_reshare_uses_new_link(client, writing):
    share = create_share(client, writing)
    old_url, old_image = public_path(share), image_path(share)
    saved_blocks = list(writing.blocks.values())
    stale_update = sharing_data(client, writing, "update")
    stopped = client.post(share_path(writing), sharing_data(client, writing, "stop"))
    assert stopped.status_code == HTTPStatus.FOUND
    share.refresh_from_db()
    assert not share.is_active
    assert share.snapshot == {}
    assert bytes(share.preview_image) == b""
    for path in [old_url, old_image]:
        response = Client().get(path)
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "no-store" in response["Cache-Control"]
        assert "An elegant proof" not in response.content.decode()
    # An old open tab cannot quietly reactivate a revoked link.
    client.post(share_path(writing), stale_update)
    share.refresh_from_db()
    assert not share.is_active
    writing.refresh_from_db()
    assert list(writing.blocks.values()) == saved_blocks
    new_share = create_share(client, writing)
    assert new_share.pk == share.pk
    assert public_path(new_share) != old_url
    assert Client().get(old_url).status_code == HTTPStatus.NOT_FOUND
    assert Client().get(public_path(new_share)).status_code == HTTPStatus.OK


@pytest.mark.parametrize("action", ["create", "update"])
def test_stale_saved_version_cannot_share_content_not_reviewed(client, writing, action):
    share = create_share(client, writing) if action == "update" else None
    stale = sharing_data(client, writing, action)
    writing.title = "Saved elsewhere"
    writing.save()
    response = client.post(share_path(writing), stale, follow=True)
    assert "Review its latest saved version" in response.content.decode()
    if share:
        share.refresh_from_db()
        assert share.snapshot["title"] == "An elegant proof"
    else:
        assert not SolutionPublicShare.objects.exists()


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("changed", ["author", "statement", "block"])
def test_changed_review_content_cannot_be_shared_from_an_old_tab(client, writing, action, changed):
    share = create_share(client, writing) if action == "update" else None
    stale = sharing_data(client, writing, action)
    if changed == "author":
        writing.author.name = "New private profile name"
        writing.author.save()
    elif changed == "statement":
        statement = ContestProblemStatement.objects.get(linked_problem=writing.problem)
        statement.statement_latex = "Changed catalogue statement"
        statement.save()
    else:
        block = writing.blocks.first()
        block.body_source = "Changed block without touching parent timestamp"
        block.save()
    response = client.post(share_path(writing), stale, follow=True)
    assert "The saved preview changed" in response.content.decode()
    if share:
        share.refresh_from_db()
        assert share.snapshot["author"] == "Ada Learner"
        assert "Changed" not in str(share.snapshot)
    else:
        assert not SolutionPublicShare.objects.exists()


def test_review_digest_accepts_svg_renderer_variations_but_detects_changed_diagram_source(client, writing):
    snapshot = client.get(share_path(writing)).context["snapshot"]
    snapshot["problem"]["segments"].append({
        "kind": "image", "src": "rendered SVG one", "diagram_source": "draw(A--B);",
    })
    another_renderer = deepcopy(snapshot)
    another_renderer["problem"]["segments"][-1]["src"] = "rendered SVG with different IDs"
    assert snapshot_digest(snapshot) == snapshot_digest(another_renderer)
    another_renderer["problem"]["segments"][-1]["diagram_source"] = "draw(A--C);"
    assert snapshot_digest(snapshot) != snapshot_digest(another_renderer)


@pytest.mark.parametrize("action", ["create", "update", "stop"])
def test_other_users_cannot_manage_anyone_elses_share(client, writing, action):
    share = create_share(client, writing)
    other = Client()
    other.force_login(UserFactory())
    assert other.get(share_path(writing)).status_code == HTTPStatus.NOT_FOUND
    assert other.post(share_path(writing), sharing_data(client, writing, action)).status_code == HTTPStatus.NOT_FOUND
    share.refresh_from_db()
    assert share.is_active
    assert share.snapshot["title"] == "An elegant proof"


def test_csrf_required_and_public_routes_cannot_mutate(client, writing):
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(writing.author)
    assert guarded.post(share_path(writing), sharing_data(client, writing)).status_code == HTTPStatus.FORBIDDEN
    share = create_share(client, writing)
    for path in [public_path(share), image_path(share)]:
        assert Client().post(path, {"action": "stop"}).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    share.refresh_from_db()
    assert share.is_active
    client.get(share_path(writing), {"action": "stop"})
    share.refresh_from_db()
    assert share.is_active


def test_pending_accounts_can_read_public_copy_but_not_open_editor(client, writing):
    share = create_share(client, writing)
    pending = Client()
    pending.force_login(UserFactory(is_approved=False))
    assert pending.get(public_path(share)).status_code == HTTPStatus.OK
    assert pending.get(image_path(share)).status_code == HTTPStatus.OK
    response = pending.get(share_path(writing))
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


@pytest.mark.parametrize("name", ["", "looks-like-email@example.test"])
def test_public_author_credit_never_uses_email_fallback(client, writing, name):
    writing.author.name = name
    writing.author.save()
    share = create_share(client, writing)
    html = Client().get(public_path(share)).content.decode()
    assert "By AsterProof learner" in html
    assert writing.author.email not in html
    assert "looks-like-email@example.test" not in html


def test_display_settings_apply_to_page_and_metadata(client, writing):
    writing.pdf_show_author = False
    writing.pdf_show_date = True
    writing.pdf_show_footer = True
    writing.save()
    share = create_share(client, writing)
    html = Client().get(public_path(share)).content.decode()
    assert "Ada Learner" not in html
    assert "By " not in html
    assert share.snapshot["date"] in html
    assert 'aria-label="Page number"' in html
    assert writing.author.email not in html


def test_untrusted_content_is_escaped_and_public_math_uses_safe_extension(client, writing):
    writing.title = '<script>alert("title")</script>'
    writing.summary = '<img src=x onerror="alert(1)">'
    writing.save()
    block = writing.blocks.first()
    block.body_source = '<script>alert("body")</script> $x$'
    block.save()
    share = create_share(client, writing)
    html = Client().get(public_path(share)).content.decode()
    assert '<script>alert("title")' not in html
    assert '<script>alert("body")' not in html
    assert "<img src=x onerror=" not in html
    assert "&lt;script&gt;" in html
    assert "tex2jax_ignore" in html
    assert "'ui/safe'" in html
    assert "javascript: false" in html
    assert "styles: 'none'" in html


def test_snapshot_does_not_change_when_problem_or_author_changes(client, writing):
    share = create_share(client, writing)
    statement = ContestProblemStatement.objects.get(linked_problem=writing.problem)
    statement.statement_latex = "UNSHARED-CATALOGUE-CHANGE"
    statement.save()
    writing.author.name = "UNSHARED-AUTHOR-CHANGE"
    writing.author.save()
    response = Client().get(public_path(share))
    html = response.content.decode()
    assert "UNSHARED-CATALOGUE-CHANGE" not in html
    assert "UNSHARED-AUTHOR-CHANGE" not in html
    assert "Ada Learner" in html
    assert r"Prove $x^2\geq 0$." in html


def test_unknown_or_deleted_links_reveal_no_solution(client, writing):
    share = create_share(client, writing)
    old_url, old_image = public_path(share), image_path(share)
    writing.delete()
    paths = [old_url, old_image, reverse("solutions:public_solution", args=[uuid.uuid4()])]
    for path in paths:
        response = Client().get(path)
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "An elegant proof" not in response.content.decode()


@pytest.mark.parametrize("invalid", ["empty", "oversized"])
def test_invalid_snapshot_never_replaces_an_active_shared_version(client, writing, invalid):
    share = create_share(client, writing)
    if invalid == "empty":
        writing.blocks.all().delete()
    else:
        block = writing.blocks.first()
        block.body_source = "x" * (1024 * 1024 + 1)
        block.save()
    response = client.post(share_path(writing), sharing_data(client, writing, "update"), follow=True)
    assert response.status_code == HTTPStatus.OK
    share.refresh_from_db()
    assert share.snapshot["title"] == "An elegant proof"
    assert share.is_active
    # Revocation must still work even if the saved proof is no longer shareable.
    client.post(share_path(writing), sharing_data(client, writing, "stop"))
    share.refresh_from_db()
    assert not share.is_active


def test_editor_exposes_sharing_only_after_save(client, writing):
    editor = reverse("solutions:problem_solution_edit", args=[writing.problem.problem_uuid])
    html = client.get(editor).content.decode()
    assert share_path(writing) in html
    assert "Share solution" in html
    create_share(client, writing)
    assert "Manage the public link" in client.get(editor).content.decode()
    writing.delete()
    html = client.get(editor).content.decode()
    assert "Share solution</a>" not in html


def test_my_solutions_labels_public_copy_separately_and_keeps_correct_block_count(client, writing):
    path = reverse("solutions:my_solution_list")
    share = create_share(client, writing)
    response = client.get(path)
    row = response.context["my_solution_rows"][0]
    assert row["has_public_link"]
    assert row["block_count"] == writing.blocks.count()
    assert row["status_label"] == "Draft"
    assert "Public link active" in response.content.decode()
    assert share_path(writing) in response.content.decode()
    client.post(share_path(writing), sharing_data(client, writing, "stop"))
    response = client.get(path)
    assert "Public link active" not in response.content.decode()
    assert "Manage link" not in response.content.decode()
    share.refresh_from_db()
    assert not share.is_active
