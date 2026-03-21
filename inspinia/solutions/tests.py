from http import HTTPStatus

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.models import SolutionSourceArtifact
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
        ("solutions:problem_solution_list", {"problem": "P1"}),
        ("solutions:problem_solution_edit", {"problem": "P2"}),
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
    assert "My draft" in response_html
    assert "Other published solution" not in response_html


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
    assert response.context["my_solution_row"]["title"] == "My working draft"
    assert [row["title"] for row in response.context["published_solution_rows"]] == ["Published proof"]
    assert response.context["solution_stats"]["published_total"] == 1
    assert response.context["solution_stats"]["visible_total"] == EXPECTED_VISIBLE_SOLUTION_TOTAL
    response_html = response.content.decode("utf-8")
    assert "My working draft" in response_html
    assert "Published proof" in response_html
    assert "Hidden draft" not in response_html


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
