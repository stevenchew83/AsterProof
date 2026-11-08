import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.study_help_models import StudyHelpRestriction
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.contest_review_scores import published_contest_scores
from inspinia.solutions.document_source import source_digest
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBlockType
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _proof(author, number, *, day="Day 1"):
    code = f"P{number}"
    problem = ProblemSolveRecord.objects.create(contest="IMO", year=2026, problem=code)
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name="IMO", contest_year=2026, problem_code=code,
        problem_number=number, day_label=day, statement_latex="Prove that a square is nonnegative.",
    )
    solution = ProblemSolution.objects.create(
        problem=problem, author=author, status=ProblemSolution.Status.SUBMITTED, title="Nonnegative squares",
    )
    solution.blocks.create(position=1, body_source="A square is nonnegative.")
    return statement, solution


def _review(solution, score, *, published=True, solver=None, self_requester=None):
    data = forum.current_target_data(solution)
    target = forum._target(solution, {"target_key": data["key"]})  # noqa: SLF001
    review = AdminSolutionReview.objects.create(
        target=target,
        solver=solver or solution.author,
        problem_label=problem_label(solution),
        status=AdminSolutionReview.Status.COMPLETED,
        score=score,
        published_at=timezone.now() if published else None,
        batch_id=uuid.uuid4(),
        key_version=uuid.uuid4(),
        model="gpt-6.1-sol",
        output_limit=1000,
        feedback="Only the score is projected.",
    )
    if self_requester is not None:
        SelfSolutionReviewUsage.objects.create(
            user=self_requester, review=review, problem_uuid=solution.problem.problem_uuid, batch_id=review.batch_id,
        )
    return review


def _scored(score, title="Nonnegative squares"):
    return {"score": score, "state": "scored", "solution_title": title}


def _rows(*statements):
    return [
        {
            "id": row.pk,
            "linked_problem_id": row.linked_problem_id,
            "problem_uuid": row.problem_uuid,
            "statement_uuid": row.statement_uuid,
            "contest_year": row.contest_year,
            "problem_code": row.problem_code,
            "day_label": row.day_label,
        }
        for row in statements
    ]


def test_scores_are_scoped_to_learner_and_exact_statement_even_without_a_completion():
    subject, other = UserFactory(), UserFactory()
    first, own_solution = _proof(subject, 1)
    other_day, other_solution = _proof(other, 1, day="Day 2")
    wrong_solver, wrong_solver_solution = _proof(subject, 2)
    wrong_requester, wrong_requester_solution = _proof(subject, 3)
    only_draft, draft_solution = _proof(subject, 4)
    _review(own_solution, 0)
    _review(own_solution, 7, published=False)
    _review(other_solution, 6)
    _review(wrong_solver_solution, 5, solver=other)
    _review(wrong_requester_solution, 4, self_requester=other)
    _review(draft_solution, 7, published=False)

    statements = _rows(first, other_day, wrong_solver, wrong_requester, only_draft)
    assert published_contest_scores(subject, statements) == {first.pk: _scored(0)}
    assert published_contest_scores(other, statements) == {other_day.pk: _scored(6)}


@pytest.mark.parametrize("changed", ["statement", "legacy_block", "revision"])
def test_prior_publication_only_marks_earlier_after_the_proof_or_statement_changes(changed):
    subject = UserFactory()
    statement, solution = _proof(subject, 1)
    if changed == "revision":
        _save_revision(solution, 1)
    _review(solution, 7)

    if changed == "statement":
        ContestProblemStatement.objects.filter(pk=statement.pk).update(statement_latex="Find all equality cases.")
    elif changed == "legacy_block":
        solution.blocks.update(body_source="The proof changed without a solution timestamp update.")
    else:
        _save_revision(solution, 2)
    assert published_contest_scores(subject, _rows(statement)) == {statement.pk: {"score": None, "state": "earlier"}}

    _review(solution, 3)
    assert published_contest_scores(subject, _rows(statement)) == {statement.pk: _scored(3)}


def _save_revision(solution, sequence):
    path = "solution_body_images/" + "a" * 32 + ".png"
    source = rf"Égalité case {sequence}. \includegraphics{{{path}}}"
    solution.current_revision = solution.revisions.create(
        sequence=sequence, body_source=source, source_digest=source_digest(source),
    )
    solution.save(update_fields=["current_revision"])


@pytest.mark.parametrize("scope", ["problem", "statement", "global"])
def test_scores_preserve_assistance_restrictions_for_published_self_reviews(scope):
    subject, unrelated = UserFactory(), UserFactory()
    statement, self_solution = _proof(subject, 1)
    admin_statement, admin_solution = _proof(subject, 2)
    _review(self_solution, 6, self_requester=subject)
    _review(admin_solution, 7)
    rows = _rows(statement, admin_statement)
    expected = {admin_statement.pk: _scored(7)}
    now = timezone.now()
    old_uuid = uuid.uuid4()
    scope_uuid = {"problem": statement.problem_uuid, "statement": old_uuid, "global": None}[scope]

    # Neither another user's live rule nor the subject's expired rule applies.
    for actor, ends in [(unrelated, now + timedelta(minutes=5)), (subject, now - timedelta(minutes=1))]:
        AssistancePolicy.objects.create(
            actor_id_scope=actor.pk, problem_uuid=statement.problem_uuid, mode="restricted_assessment",
            starts_at=now - timedelta(minutes=2), ends_at=ends,
        )
    assert published_contest_scores(subject, rows) == {
        statement.pk: _scored(6),
        **expected,
    }

    policy = AssistancePolicy.objects.create(
        actor_id_scope=subject.pk, problem_uuid=scope_uuid, mode="restricted_assessment",
        starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=5),
    )
    if scope == "statement":
        StudyHelpRestriction.objects.create(policy=policy, statement_uuid=statement.statement_uuid)
    assert published_contest_scores(subject, rows) == expected


def test_inactive_or_misaligned_statements_never_receive_a_score():
    subject = UserFactory()
    statement, solution = _proof(subject, 1)
    _review(solution, 7)
    row = _rows(statement)[0]
    assert published_contest_scores(subject, [{**row, "problem_uuid": uuid.uuid4()}]) == {}

    ContestProblemStatement.objects.filter(pk=statement.pk).update(is_active=False)
    assert published_contest_scores(subject, [row]) == {}


def test_replacement_statement_does_not_inherit_review_history():
    subject = UserFactory()
    statement, solution = _proof(subject, 1)
    _review(solution, 7)
    ContestProblemStatement.objects.filter(pk=statement.pk).update(
        is_active=False, linked_problem=None, problem_uuid=uuid.uuid4(),
    )
    replacement = ContestProblemStatement.objects.create(
        linked_problem=solution.problem, contest_name=statement.contest_name,
        contest_year=statement.contest_year, problem_code=statement.problem_code,
        problem_number=statement.problem_number, day_label="Day 2",
        statement_latex="Prove that a square is nonnegative.",
    )
    assert published_contest_scores(subject, _rows(replacement)) == {}


def test_newer_publication_for_another_target_cannot_replace_the_current_score():
    subject = UserFactory()
    statement, solution = _proof(subject, 1)
    _review(solution, 5)
    source = solution.blocks.get().body_source
    solution.blocks.update(body_source="An alternate proof.")
    _review(solution, 7)
    solution.blocks.update(body_source=source)

    assert published_contest_scores(subject, _rows(statement)) == {statement.pk: _scored(5)}


def test_target_matching_batches_legacy_sources_and_revisions(django_assert_num_queries):
    subject = UserFactory()
    claim, _created = SolutionBlockType.objects.get_or_create(slug="claim", defaults={"label": "Claim"})
    statements = []
    for number in range(1, 9):
        statement, solution = _proof(subject, number)
        if number % 2:
            solution.blocks.create(
                position=2, block_type=claim, title="A special case", body_source=r"x + y \geq 0",
            )
        else:
            _save_revision(solution, 1)
        # Review fixtures derive their keys directly from the canonical reader.
        _review(solution, 4, self_requester=subject)
        statements.append(statement)

    with django_assert_num_queries(3):
        single = published_contest_scores(subject, _rows(statements[0]))
    assert single == {statements[0].pk: _scored(4)}

    with django_assert_num_queries(3):
        summaries = published_contest_scores(subject, _rows(*statements))
    assert summaries == {row.pk: _scored(4) for row in statements}


def test_contest_progress_uses_latest_current_review_across_solutions():
    subject = UserFactory()
    statement, original = _proof(subject, 1)
    alternate = ProblemSolution.objects.create(
        problem=original.problem, author=subject, additional_draft_key=uuid.uuid4(), title="Coordinate proof",
    )
    _save_revision(alternate, 1)
    _review(original, 7)
    _review(alternate, 3)
    rows = _rows(statement)
    assert published_contest_scores(subject, rows) == {statement.pk: _scored(3, "Coordinate proof")}

    _save_revision(alternate, 2)
    assert published_contest_scores(subject, rows) == {statement.pk: _scored(7)}
    original.blocks.update(body_source="The original was edited too.")
    assert published_contest_scores(subject, rows) == {statement.pk: {"score": None, "state": "earlier"}}
