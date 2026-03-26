from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.body_image_paths import is_allowed_includegraphics_path
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionSourceArtifact
from inspinia.solutions.pdf_latex import SolutionPdfCompileError
from inspinia.solutions.pdf_latex import SolutionPdfToolError
from inspinia.solutions.pdf_latex import _latex_log_user_excerpt
from inspinia.solutions.pdf_latex import _merge_latex_fail_detail
from inspinia.solutions.pdf_latex import build_solution_tex_source
from inspinia.solutions.views import STATEMENT_BACKED_PROBLEM_LIST_LIMIT
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_DEFAULT_BLOCK_TYPES = {
    "plain",
    "section",
    "idea",
    "claim",
    "proof",
    "case",
    "subcase",
    "part",
    "observation",
    "computation",
    "conclusion",
    "remark",
}
EXPECTED_VISIBLE_SOLUTION_TOTAL = 2
EXPECTED_STATEMENT_BACKED_PROBLEM_TOTAL = 2


def _problem(*, year: int = 2026, contest: str = "IMO", problem: str = "P1") -> ProblemSolveRecord:
    return ProblemSolveRecord.objects.create(
        year=year,
        topic="ALG",
        mohs=5,
        contest=contest,
        problem=problem,
        contest_year_problem=f"{contest} {year} {problem}",
    )


def _solution_with_blocks(  # noqa: PLR0913
    *,
    problem: ProblemSolveRecord,
    author,
    status: str = ProblemSolution.Status.DRAFT,
    title: str = "Untitled solution",
    summary: str = "",
    blocks: list[tuple[str, str, str]] | None = None,
) -> ProblemSolution:
    solution = ProblemSolution.objects.create(
        problem=problem,
        author=author,
        status=status,
        title=title,
        summary=summary,
    )
    default_block_type = SolutionBlockType.objects.get(slug="proof")
    for position, block in enumerate(blocks or [], start=1):
        block_title, body_source, block_type_slug = block
        ProblemSolutionBlock.objects.create(
            solution=solution,
            block_type=SolutionBlockType.objects.get(slug=block_type_slug) if block_type_slug else default_block_type,
            position=position,
            title=block_title,
            body_source=body_source,
        )
    return solution


def test_default_solution_block_types_are_seeded():
    assert EXPECTED_DEFAULT_BLOCK_TYPES.issubset(
        set(SolutionBlockType.objects.values_list("slug", flat=True)),
    )


def test_problem_solution_is_unique_per_problem_and_author():
    user = UserFactory()
    problem = _problem()
    ProblemSolution.objects.create(problem=problem, author=user, title="First solution")

    with pytest.raises(IntegrityError):
        ProblemSolution.objects.create(problem=problem, author=user, title="Duplicate solution")


def test_problem_solution_block_position_is_unique_within_solution():
    user = UserFactory()
    solution = ProblemSolution.objects.create(problem=_problem(), author=user)
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="First block")

    with pytest.raises(IntegrityError):
        ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="Duplicate block")


def test_problem_solution_block_parent_must_belong_to_same_solution():
    user = UserFactory()
    first_solution = ProblemSolution.objects.create(problem=_problem(), author=user)
    second_solution = ProblemSolution.objects.create(
        problem=_problem(year=2025, contest="USAMO", problem="P2"),
        author=UserFactory(),
    )
    parent_block = ProblemSolutionBlock.objects.create(
        solution=first_solution,
        position=1,
        body_source="Parent block",
    )
    child_block = ProblemSolutionBlock(
        solution=second_solution,
        parent_block=parent_block,
        position=1,
        body_source="Child block",
    )

    with pytest.raises(ValidationError, match="Parent block must belong to the same solution."):
        child_block.full_clean()


def test_solution_source_artifact_requires_payload():
    user = UserFactory()
    artifact = SolutionSourceArtifact(
        solution=ProblemSolution.objects.create(problem=_problem(), author=user),
        uploaded_by=user,
        artifact_type=SolutionSourceArtifact.ArtifactType.TEXT,
    )

    with pytest.raises(ValidationError, match="Provide a file, source text, or source URL."):
        artifact.full_clean()


@pytest.mark.parametrize(
    ("url_name", "problem_kwargs"),
    [
        ("solutions:my_solution_list", None),
        ("solutions:problem_solution_create", None),
        ("solutions:problem_solution_list", {"problem": "P1"}),
        ("solutions:problem_solution_edit", {"problem": "P2"}),
        ("solutions:problem_solution_pdf", {"problem": "P1"}),
    ],
)
def test_solution_pages_require_login(client, url_name, problem_kwargs):
    if problem_kwargs is None:
        url = reverse(url_name)
    else:
        url = reverse(url_name, args=[_problem(**problem_kwargs).problem_uuid])

    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_my_solution_list_shows_only_current_users_solutions(client):
    user = UserFactory()
    other_user = UserFactory()
    client.force_login(user)
    my_problem = _problem()
    other_problem = _problem(year=2025, contest="USAMO", problem="P2")
    _solution_with_blocks(
        problem=my_problem,
        author=user,
        title="My draft",
        blocks=[("Idea", "Start with a key invariant.", "idea")],
    )
    _solution_with_blocks(
        problem=other_problem,
        author=other_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Other published solution",
        blocks=[("Proof", "Other author's proof.", "proof")],
    )

    response = client.get(reverse("solutions:my_solution_list"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["my_solution_stats"]["total"] == 1
    assert len(response.context["my_solution_rows"]) == 1
    response_html = response.content.decode("utf-8")
    assert reverse("solutions:problem_solution_create") in response_html
    assert "My draft" in response_html
    assert "Other published solution" not in response_html


def test_problem_solution_create_view_lists_only_statement_backed_problems(client):
    user = UserFactory()
    other_user = UserFactory()
    client.force_login(user)
    linked_problem_with_solution = _problem()
    linked_problem_without_solution = _problem(year=2025, contest="USAMO", problem="P2")
    _problem(year=2024, contest="BMO", problem="P3")
    ContestProblemStatement.objects.create(
        linked_problem=linked_problem_with_solution,
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Prove that $a=b$.",
    )
    ContestProblemStatement.objects.create(
        linked_problem=linked_problem_without_solution,
        contest_year=2025,
        contest_name="USAMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 2",
        statement_latex="Show that $n^2=n$.",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="Unlinked contest",
        problem_number=3,
        problem_code="P3",
        day_label="Day 1",
        statement_latex="This row is not linked to a problem.",
    )
    _solution_with_blocks(
        problem=linked_problem_with_solution,
        author=user,
        title="Existing draft",
        blocks=[("Idea", "Existing solution body.", "idea")],
    )
    _solution_with_blocks(
        problem=linked_problem_with_solution,
        author=other_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Other published solution",
        blocks=[("Proof", "Other user's proof.", "proof")],
    )

    response = client.get(reverse("solutions:problem_solution_create"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_problem_list_is_capped"] is False
    assert response.context["create_stats"]["statement_problem_total"] == EXPECTED_STATEMENT_BACKED_PROBLEM_TOTAL
    assert response.context["create_stats"]["started_total"] == 1
    assert response.context["create_stats"]["ready_total"] == 1
    assert [row["problem_label"] for row in response.context["statement_problem_rows"]] == [
        "IMO 2026 P1",
        "USAMO 2025 P2",
    ]
    first_row, second_row = response.context["statement_problem_rows"]
    assert first_row["editor_button_label"] == "Continue solution"
    assert first_row["solution_status_label"] == "Draft"
    assert second_row["editor_button_label"] == "Start solution"
    assert second_row["solution_status_label"] == "Not started"
    response_html = response.content.decode("utf-8")
    first_editor_url = reverse("solutions:problem_solution_edit", args=[linked_problem_with_solution.problem_uuid])
    second_editor_url = reverse("solutions:problem_solution_edit", args=[linked_problem_without_solution.problem_uuid])
    assert first_editor_url in response_html
    assert second_editor_url in response_html
    assert "Unlinked contest" not in response_html


def test_problem_solution_create_view_shows_empty_state_without_linked_statements(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("solutions:problem_solution_create"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["create_stats"]["statement_problem_total"] == 0
    assert response.context["statement_problem_list_is_capped"] is False
    assert "No linked problem statements are available yet." in response.content.decode("utf-8")


def test_problem_solution_create_view_caps_statement_rows_at_100(client):
    user = UserFactory()
    client.force_login(user)
    now = timezone.now()
    for i in range(STATEMENT_BACKED_PROBLEM_LIST_LIMIT + 1):
        problem = ProblemSolveRecord.objects.create(
            year=2026,
            topic="ALG",
            mohs=3,
            contest="IMO",
            problem=f"P{i}",
            contest_year_problem=f"IMO 2026 P{i}",
        )
        stmt = ContestProblemStatement.objects.create(
            linked_problem=problem,
            contest_year=2026,
            contest_name="IMO",
            problem_number=i + 1,
            problem_code=f"P{i}",
            day_label="Day 1",
            statement_latex=f"Problem {i} body.",
        )
        ContestProblemStatement.objects.filter(pk=stmt.pk).update(updated_at=now - timedelta(seconds=i))

    response = client.get(reverse("solutions:problem_solution_create"))

    assert response.status_code == HTTPStatus.OK
    rows = response.context["statement_problem_rows"]
    assert len(rows) == STATEMENT_BACKED_PROBLEM_LIST_LIMIT
    assert response.context["statement_problem_list_is_capped"] is True
    assert response.context["statement_problem_list_limit"] == STATEMENT_BACKED_PROBLEM_LIST_LIMIT
    assert response.context["create_stats"]["statement_problem_total"] == STATEMENT_BACKED_PROBLEM_LIST_LIMIT
    labels = {row["problem_label"] for row in rows}
    assert "IMO 2026 P0" in labels
    assert f"IMO 2026 P{STATEMENT_BACKED_PROBLEM_LIST_LIMIT}" not in labels


def test_problem_solution_list_shows_my_solution_and_only_other_published_solutions(client):
    user = UserFactory()
    other_user = UserFactory()
    third_user = UserFactory()
    client.force_login(user)
    problem = _problem()
    _solution_with_blocks(
        problem=problem,
        author=user,
        title="My working draft",
        blocks=[("Claim", "My private draft block.", "claim")],
    )
    _solution_with_blocks(
        problem=problem,
        author=other_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Published proof",
        blocks=[("Proof", "A published proof block.", "proof")],
    )
    _solution_with_blocks(
        problem=problem,
        author=third_user,
        title="Hidden draft",
        blocks=[("Idea", "This should stay private.", "idea")],
    )

    response = client.get(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    assert response.context["admin_view"] is False
    assert response.context["my_solution_row"]["title"] == "My working draft"
    assert [row["title"] for row in response.context["visible_solution_rows"]] == ["Published proof"]
    assert response.context["visible_solution_title"] == "Published solutions"
    assert response.context["solution_stats"]["published_total"] == 1
    assert response.context["solution_stats"]["visible_total"] == EXPECTED_VISIBLE_SOLUTION_TOTAL
    response_html = response.content.decode("utf-8")
    assert "My working draft" in response_html
    assert "Published proof" in response_html
    assert "Hidden draft" not in response_html
    assert 'textbullet: "\\\\bullet"' in response_html


def test_problem_solution_list_shows_all_user_solutions_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    other_user = UserFactory()
    third_user = UserFactory()
    client.force_login(admin_user)
    problem = _problem()
    _solution_with_blocks(
        problem=problem,
        author=other_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Published proof",
        blocks=[("Proof", "A published proof block.", "proof")],
    )
    _solution_with_blocks(
        problem=problem,
        author=third_user,
        title="Hidden draft",
        blocks=[("Idea", "This should be visible to admin.", "idea")],
    )

    response = client.get(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    assert response.context["admin_view"] is True
    assert {row["title"] for row in response.context["visible_solution_rows"]} == {"Published proof", "Hidden draft"}
    assert response.context["visible_solution_title"] == "All user solutions"
    assert response.context["solution_stats"]["visible_total"] == EXPECTED_VISIBLE_SOLUTION_TOTAL
    response_html = response.content.decode("utf-8")
    assert "All user solutions" in response_html
    assert "Published proof" in response_html
    assert "Hidden draft" in response_html


def test_problem_solution_list_highlights_selected_solution_from_query_string_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    other_user = UserFactory()
    client.force_login(admin_user)
    problem = _problem()
    selected_solution = _solution_with_blocks(
        problem=problem,
        author=other_user,
        title="Hidden draft",
        blocks=[("Idea", "This should be highlighted.", "idea")],
    )
    _solution_with_blocks(
        problem=problem,
        author=admin_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Admin proof",
        blocks=[("Proof", "Another visible solution.", "proof")],
    )

    response = client.get(
        reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
        {"solution": str(selected_solution.id)},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["selected_solution_id"] == selected_solution.id
    response_html = response.content.decode("utf-8")
    assert f'id="solution-{selected_solution.id}"' in response_html
    assert "solution-card-selected" in response_html


def test_problem_solution_edit_creates_and_publishes_ordered_blocks(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    claim_block_type = SolutionBlockType.objects.get(slug="claim")
    proof_block_type = SolutionBlockType.objects.get(slug="proof")

    response = client.post(
        reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
        {
            "action": "publish",
            "solution-title": "Invariant solution",
            "solution-summary": "A two-step argument.",
            "blocks-TOTAL_FORMS": "2",
            "blocks-INITIAL_FORMS": "0",
            "blocks-MIN_NUM_FORMS": "0",
            "blocks-MAX_NUM_FORMS": "1000",
            "blocks-0-id": "",
            "blocks-0-ORDER": "2",
            "blocks-0-block_type": str(proof_block_type.id),
            "blocks-0-title": "Proof",
            "blocks-0-body_format": ProblemSolutionBlock.BodyFormat.LATEX,
            "blocks-0-body_source": "Now we finish the proof.",
            "blocks-1-id": "",
            "blocks-1-ORDER": "1",
            "blocks-1-block_type": str(claim_block_type.id),
            "blocks-1-title": "Claim 1",
            "blocks-1-body_format": ProblemSolutionBlock.BodyFormat.LATEX,
            "blocks-1-body_source": "First establish the key claim.",
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    solution = ProblemSolution.objects.get(problem=problem, author=user)
    assert solution.status == ProblemSolution.Status.PUBLISHED
    assert solution.published_at is not None
    assert solution.summary == "A two-step argument."
    assert [block.title for block in solution.blocks.order_by("position")] == ["Claim 1", "Proof"]
    assert [block.position for block in solution.blocks.order_by("position")] == [1, 2]


def test_problem_solution_edit_reorders_and_deletes_existing_blocks(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        title="Editable draft",
        blocks=[
            ("Case 1", "Old first block.", "case"),
            ("Case 2", "Old second block.", "case"),
        ],
    )
    first_block, second_block = list(solution.blocks.order_by("position"))
    proof_block_type = SolutionBlockType.objects.get(slug="proof")

    response = client.post(
        reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
        {
            "action": "save_draft",
            "solution-title": "Editable draft",
            "solution-summary": "Updated ordering.",
            "blocks-TOTAL_FORMS": "3",
            "blocks-INITIAL_FORMS": "2",
            "blocks-MIN_NUM_FORMS": "0",
            "blocks-MAX_NUM_FORMS": "1000",
            "blocks-0-id": str(first_block.id),
            "blocks-0-ORDER": "2",
            "blocks-0-block_type": str(first_block.block_type_id),
            "blocks-0-title": "Case 1",
            "blocks-0-body_format": first_block.body_format,
            "blocks-0-body_source": "Moved to second.",
            "blocks-1-id": str(second_block.id),
            "blocks-1-ORDER": "1",
            "blocks-1-block_type": str(second_block.block_type_id),
            "blocks-1-title": "Case 2",
            "blocks-1-body_format": second_block.body_format,
            "blocks-1-body_source": "Delete this block.",
            "blocks-1-DELETE": "on",
            "blocks-2-id": "",
            "blocks-2-ORDER": "1",
            "blocks-2-block_type": str(proof_block_type.id),
            "blocks-2-title": "Final proof",
            "blocks-2-body_format": ProblemSolutionBlock.BodyFormat.LATEX,
            "blocks-2-body_source": "New leading block.",
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    solution.refresh_from_db()
    assert solution.status == ProblemSolution.Status.DRAFT
    remaining_blocks = list(solution.blocks.order_by("position"))
    assert [block.title for block in remaining_blocks] == ["Final proof", "Case 1"]
    assert [block.body_source for block in remaining_blocks] == [
        "New leading block.",
        "Moved to second.",
    ]
    assert [block.position for block in remaining_blocks] == [1, 2]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("solution_body_images/abcdef0123456789abcdef0123456789.png", True),
        ("solution_body_images/ABCDEF0123456789ABCDEF0123456789.JPG", True),
        ("solution_body_images/abcdef0123456789abcdef0123456789.jpeg", True),
        ("../solution_body_images/abcdef0123456789abcdef0123456789.png", False),
        ("solution_body_images/not-a-uuid.png", False),
        ("solution_body_images/abcdef0123456789abcdef0123456789.exe", False),
        ("http://evil.com/x.png", False),
        ("solution_body_images/abcdef0123456789abcdef0123456789.png//x", False),
    ],
)
def test_includegraphics_path_allowlist(path, expected):
    assert is_allowed_includegraphics_path(path) is expected


def _png_upload() -> SimpleUploadedFile:
    buf = BytesIO()
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(buf, format="PNG")
    return SimpleUploadedFile("x.png", buf.getvalue(), content_type="image/png")


def test_solution_body_image_upload_requires_login(client):
    problem = _problem()
    url = reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid])
    response = client.post(url, {"image": _png_upload()})
    assert response.status_code == HTTPStatus.FOUND


def test_solution_body_image_upload_creates_draft_and_returns_path(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    url = reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid])
    response = client.post(url, {"image": _png_upload()})
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["path"].startswith("solution_body_images/")
    assert is_allowed_includegraphics_path(payload["path"])
    assert "/media/" in payload["url"] or payload["url"].startswith("http")
    solution = ProblemSolution.objects.get(problem=problem, author=user)
    assert solution.status == ProblemSolution.Status.DRAFT
    assert SolutionBodyImage.objects.filter(solution=solution).count() == 1


def test_solution_body_image_upload_rejects_non_image(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    url = reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid])
    bad = SimpleUploadedFile("x.txt", b"not an image", content_type="text/plain")
    response = client.post(url, {"image": bad})
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_solution_body_image_upload_rejects_oversized(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    url = reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid])
    buf = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buf, format="PNG")
    png = buf.getvalue()
    huge = SimpleUploadedFile("huge.png", png + b"\x00" * (4 * 1024 * 1024), content_type="image/png")
    response = client.post(url, {"image": huge})
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_build_solution_tex_wrapper_uses_11pt_sexy_and_problem_title():
    user = UserFactory(name="Test User")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        title="My Title",
        blocks=[
            ("A", r"$\alpha$", "claim"),
            ("B", "Second body.", "proof"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\documentclass[11pt]{scrartcl}" in tex
    assert r"\usepackage[sexy,noasy]{evan}" in tex
    assert r"\graphicspath{" in tex
    assert r"\title{USAMO 2026 P4}" in tex
    assert r"\subtitle{My Title}" in tex
    assert r"\author{Test User}" in tex


def test_build_solution_tex_omits_subtitle_for_placeholder_title():
    user = UserFactory(name="Test User")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        title="Untitled solution",
        blocks=[],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\title{USAMO 2026 P4}" in tex
    assert r"\subtitle{" not in tex


def test_build_solution_tex_date_uses_published_at_as_local_date_only():
    user = UserFactory()
    problem = _problem()
    solution = _solution_with_blocks(problem=problem, author=user, blocks=[])
    fixed = datetime(2026, 3, 24, 15, 36, 0, tzinfo=timezone.get_current_timezone())
    solution.published_at = fixed
    solution.save(update_fields=["published_at"])
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="X",
    )
    assert r"\date{2026-03-24}" in tex
    assert "15:36" not in tex
    assert "UTC" not in tex


def test_build_solution_tex_never_puts_email_in_author_when_name_empty():
    user = UserFactory()
    user.name = ""
    user.save(update_fields=["name"])
    problem = _problem()
    solution = _solution_with_blocks(problem=problem, author=user, blocks=[])
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="Y",
    )
    assert user.email not in tex
    assert r"\author{Unknown}" in tex


def test_build_solution_tex_wraps_problem_statement_in_mdpurplebox():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("Note", "After problem.", "remark")],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="Z",
        problem_statement_latex=r"Let $ABC$ be a triangle. Prove $a+b>c$.",
    )
    maketitle_at = tex.index(r"\maketitle")
    problem_box = tex.index(r"\begin{mdframed}[style=mdpurplebox,frametitle={Problem Statement}]")
    block_at = tex.index("After problem.")
    assert maketitle_at < problem_box < block_at
    assert r"\end{mdframed}" in tex
    assert r"Let $ABC$ be a triangle. Prove $a+b>c$." in tex


def test_build_solution_tex_splits_claim_title_from_claim_body():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            ("1 is solitary.", "This is trivial.", "claim"),
            ("Induction step", "Assume the result for $n$.", "proof"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\begin{claim}" in tex
    assert r"\end{claim}" in tex
    assert tex.index("1 is solitary.") < tex.index(r"\end{claim}")
    assert tex.index(r"\end{claim}") < tex.index(r"\begin{proof}")
    assert tex.count(r"\begin{proof}") == 2
    assert "This is trivial." in tex
    first_proof_begin = tex.index(r"\begin{proof}")
    first_proof_end = tex.index(r"\end{proof}")
    assert tex[first_proof_begin + len(r"\begin{proof}")] != "["
    assert first_proof_begin < tex.index("This is trivial.") < first_proof_end
    assert tex.index(r"\begin{proof}[Induction step]") > first_proof_end
    assert r"\begin{proof}[Induction step]" in tex
    assert "Assume the result for $n$." in tex
    assert r"\end{proof}" in tex


def test_build_solution_tex_claim_body_only_stays_in_claim_box():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("", "Only the statement text.", "claim")],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\begin{claim}" in tex
    assert tex.index(r"\begin{claim}") < tex.index("Only the statement text.") < tex.index(r"\end{claim}")
    assert "Only the statement text." in tex
    assert r"\begin{proof}" not in tex
    assert r"\end{claim}" in tex


def test_build_solution_tex_uses_single_line_spacing_between_blocks():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            ("Note", "First block.", "remark"),
            ("Second note", "Second block.", "remark"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\addvspace{\baselineskip}" in tex
    assert r"\addvspace{2\baselineskip}" not in tex


def test_build_solution_tex_maps_observation_to_fact_and_preserves_raw_latex_titles():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[(r"$n$ is solitary", "Then $10n$ is solitary.", "observation")],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\begin{fact}" in tex
    assert r"$n$ is solitary" in tex
    assert r"\$n\$ is solitary" not in tex
    assert r"\end{fact}" in tex


def test_build_solution_tex_maps_remark_to_remark_environment():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("Note", "Keep track of leading digits.", "remark")],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\begin{remark}" in tex
    assert "Note" in tex
    assert "Keep track of leading digits." in tex
    assert r"\end{remark}" in tex


def test_build_solution_tex_maps_section_and_part_blocks_to_headings():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            ("Reduction", "We first reduce to the base case.", "section"),
            ("Part A", "Now handle the finite family.", "part"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\section*{Reduction}" in tex
    assert "We first reduce to the base case." in tex
    assert r"\subsection*{Part A}" in tex
    assert "Now handle the finite family." in tex


def test_build_solution_tex_renders_case_and_idea_blocks_as_bold_lead_ins():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            ("Case 1", "Assume the first digit is 2.", "case"),
            ("Idea", "Shift the contradiction to a smaller number.", "idea"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\textbf{Case 1.}" in tex
    assert "Assume the first digit is 2." in tex
    assert r"\textbf{Idea.}" in tex
    assert "Shift the contradiction to a smaller number." in tex
    assert r"\paragraph{Case" not in tex
    assert r"\paragraph{Idea" not in tex


def test_build_solution_tex_renders_computation_and_conclusion_blocks_as_bold_lead_ins():
    user = UserFactory(name="Author Display")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            ("Computation", r"We obtain $a+b=n$.", "computation"),
            ("Therefore", "This contradicts solitude.", "conclusion"),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert r"\textbf{Computation.}" in tex
    assert r"We obtain $a+b=n$." in tex
    assert r"\textbf{Therefore.}" in tex
    assert "This contradicts solitude." in tex


def test_build_solution_tex_emits_plain_text_block_body_as_latex():
    user = UserFactory()
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("Step", "plain % not a comment in editor", "idea")],
    )
    block = solution.blocks.order_by("position").first()
    block.body_format = ProblemSolutionBlock.BodyFormat.PLAIN_TEXT
    block.save(update_fields=["body_format"])
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="X",
    )
    assert "plain % not a comment" in tex


def test_build_solution_tex_plain_block_omits_heading_and_title():
    user = UserFactory()
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("Lead paragraph", "This starts the solution body.", "plain")],
    )
    blocks = list(solution.blocks.order_by("position"))
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=Path(settings.MEDIA_ROOT),
        problem_label="USAMO 2026 P4",
    )
    assert "This starts the solution body." in tex
    assert "Lead paragraph" not in tex
    assert r"\paragraph{" not in tex


def test_latex_log_user_excerpt_finds_error_not_preamble_tail():
    preamble = ("(/usr/share/texlive/texmf-dist/tex/latex/microtype/microtype.sty)\n") * 400
    err = "\n! LaTeX Error: missing \\begin{document}.\nl.44 \\foo"
    data = preamble + err
    excerpt = _latex_log_user_excerpt(data, max_chars=2000)
    assert excerpt.startswith("!")
    assert "LaTeX Error" in excerpt


def test_merge_latex_fail_detail_appends_stderr_when_not_in_log():
    log = "x" * 3000 + "\n! LaTeX Error: bad.\n"
    merged = _merge_latex_fail_detail(
        log_text=log,
        stderr="latexmk: summary failure line\n",
        max_chars=8000,
    )
    assert "LaTeX Error" in merged
    assert "latexmk" in merged


def test_problem_solution_pdf_404_when_solution_not_saved(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    url = reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid])
    response = client.get(url)
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_problem_solution_pdf_returns_attachment_when_compile_succeeds(monkeypatch, client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[("Block", "body", "idea")],
    )

    monkeypatch.setattr(
        "inspinia.solutions.views.compile_solution_to_pdf",
        lambda *args, **kwargs: b"%PDF-1.4\n",
    )
    url = reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]


def test_problem_solution_pdf_compile_error_renders_log_tail(monkeypatch, client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    _solution_with_blocks(problem=problem, author=user, blocks=[("X", "y", "idea")])

    def _boom(*args, **kwargs):
        msg = "failed"
        tail = "! LaTeX Error: intentional"
        raise SolutionPdfCompileError(msg, log_tail=tail)

    monkeypatch.setattr("inspinia.solutions.views.compile_solution_to_pdf", _boom)
    url = reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid])
    response = client.get(url)
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert b"! LaTeX Error: intentional" in response.content


def test_problem_solution_pdf_tool_missing_returns_503(monkeypatch, client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    _solution_with_blocks(problem=problem, author=user, blocks=[("X", "y", "idea")])

    def _boom(*args, **kwargs):
        msg = "latexmk not found"
        raise SolutionPdfToolError(msg)

    monkeypatch.setattr("inspinia.solutions.views.compile_solution_to_pdf", _boom)
    url = reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid])
    response = client.get(url)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_admin_problem_solution_pdf_requires_login(client):
    sol = _solution_with_blocks(problem=_problem(), author=UserFactory(), blocks=[("X", "y", "idea")])
    url = reverse("solutions:admin_problem_solution_pdf", args=[sol.pk])
    response = client.get(url)
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_admin_problem_solution_pdf_forbidden_for_non_admin(client):
    user = UserFactory()
    sol = _solution_with_blocks(problem=_problem(), author=user, blocks=[("X", "y", "idea")])
    client.force_login(user)
    url = reverse("solutions:admin_problem_solution_pdf", args=[sol.pk])
    assert client.get(url).status_code == HTTPStatus.FORBIDDEN


def test_admin_problem_solution_pdf_returns_attachment_for_admin(monkeypatch, client):
    author = UserFactory()
    admin = UserFactory(role=User.Role.ADMIN)
    problem = _problem()
    sol = _solution_with_blocks(problem=problem, author=author, blocks=[("Block", "body", "idea")])

    monkeypatch.setattr(
        "inspinia.solutions.views.compile_solution_to_pdf",
        lambda *args, **kwargs: b"%PDF-1.4\n",
    )
    client.force_login(admin)
    url = reverse("solutions:admin_problem_solution_pdf", args=[sol.pk])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]


def test_problem_solution_edit_stacks_statement_editor_and_notes_in_order(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Linked statement preview text",
    )

    response = client.get(reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Problem metadata" in response_html
    assert "Problem UUID" in response_html
    assert "2026 · P1" in response_html
    assert "Algebra" in response_html
    assert ">5<" in response_html
    assert "Linked statement preview text" in response_html
    assert response_html.index("Problem metadata") < response_html.index("Linked statement")
    assert response_html.index("Linked statement") < response_html.index("Live preview")
    assert response_html.index("Live preview") < response_html.index("Editor notes")
    assert "preview the rendered LaTeX alongside the editor." in response_html
    assert 'class="col-xl-4"' not in response_html
    assert "solution-statement-panel" in response_html
    assert 'textbullet: "\\\\bullet"' in response_html


def test_problem_solution_edit_exposes_plain_block_type_for_live_preview_branch(client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()

    response = client.get(reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    plain_block_type = SolutionBlockType.objects.get(slug="plain")
    assert f'plainBlockTypeId: "{plain_block_type.id}"' in response_html
    assert "function isPlainBlockType(node)" in response_html
