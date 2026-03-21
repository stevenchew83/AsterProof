import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

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


def _problem(*, year: int = 2026, contest: str = "IMO", problem: str = "P1") -> ProblemSolveRecord:
    return ProblemSolveRecord.objects.create(
        year=year,
        topic="ALG",
        mohs=5,
        contest=contest,
        problem=problem,
        contest_year_problem=f"{contest} {year} {problem}",
    )


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
