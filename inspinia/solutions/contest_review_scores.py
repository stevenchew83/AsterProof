"""Read published, current AI scores for one learner's contest statements."""

import hashlib
import json
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help_access import active_assistance_restrictions
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import SCORE_MAX
from inspinia.solutions.admin_reviews import approved_user
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.document_source import legacy_source
from inspinia.solutions.document_source import solution_source
from inspinia.solutions.image_access import image_paths
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock


def _published_reviews(subject, problem_ids, statement_ids):
    return (
        AdminSolutionReview.objects.filter(
            solver=subject,
            target__solution__author=subject,
            target__solution__problem_id__in=problem_ids,
            target__statement_id_value__in=statement_ids,
            status=AdminSolutionReview.Status.COMPLETED,
            published_at__isnull=False,
            score__range=(0, SCORE_MAX),
        )
        .filter(Q(self_request__isnull=True) | Q(self_request__user=subject))
        .order_by("-published_at", "-pk")
        .values(
            "target__solution_id", "target__key", "target__statement_id_value",
            "target__solution_version", "target__solution_updated_at",
            "self_request__pk", "problem_label", "score", "published_at", "pk",
        )
    )


def _solutions(subject, solution_ids):
    active_statement = ContestProblemStatement.objects.filter(
        linked_problem_id=OuterRef("problem_id"), is_active=True,
    ).order_by("-updated_at", "-pk")
    restrictions = active_assistance_restrictions(subject).filter(
        Q(problem_uuid__isnull=True)
        | Q(problem_uuid=OuterRef("problem__problem_uuid"))
        | Q(studyhelprestriction__statement_uuid=OuterRef("review_statement_uuid")),
    )
    return (
        ProblemSolution.objects.filter(pk__in=solution_ids, author=subject)
        .select_related("problem", "current_revision")
        .only(
            "problem_id", "problem__problem_uuid", "problem__contest_year_problem",
            "problem__contest", "problem__year", "problem__problem",
            "current_revision_id", "current_revision__solution_id", "current_revision__body_source",
            "title", "summary", "edit_version", "updated_at",
        )
        .annotate(
            review_statement_id=Subquery(active_statement.values("pk")[:1]),
            review_statement_source=Subquery(active_statement.values("statement_latex")[:1]),
            review_statement_uuid=Subquery(active_statement.values("statement_uuid")[:1]),
        )
        .annotate(self_review_restricted=Exists(restrictions))
        .order_by()
    )


def _legacy_blocks(solutions):
    legacy_ids = [solution.pk for solution in solutions if solution.current_revision_id is None]
    by_solution = defaultdict(list)
    for block in (
        ProblemSolutionBlock.objects.filter(solution_id__in=legacy_ids)
        .select_related("block_type")
        .order_by("position", "id")
    ):
        by_solution[block.solution_id].append(block)
    return by_solution


def _target_key(solution, blocks):
    # Match forum.current_target_data using rows already loaded in bulk. The
    # canonical reader is frozen by the deployment compatibility checks.
    source = solution_source(solution) if solution.current_revision_id else legacy_source(blocks)
    payload = {
        "version": 1,
        "title": solution.title,
        "summary": solution.summary,
        "document": {"source": source, "format": "latex"},
        "revision_id": str(solution.current_revision_id or ""),
        "edit_version": solution.edit_version,
        "saved_at": solution.updated_at.isoformat(),
        "statement": {"source": solution.review_statement_source, "id": solution.review_statement_id},
        "image_paths": image_paths(source),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _review_summary(solution, reviews, blocks):
    has_visible_review = False
    key = None
    label = problem_label(solution)
    for review in reviews:
        if review["target__statement_id_value"] != solution.review_statement_id:
            continue
        if review["self_request__pk"] is not None and solution.self_review_restricted:
            continue
        has_visible_review = True
        if (
            review["problem_label"] != label
            or review["target__solution_version"] != solution.edit_version
            or review["target__solution_updated_at"] != solution.updated_at
        ):
            continue
        if key is None:
            try:
                key = _target_key(solution, blocks)
            except ValidationError:
                # An invalid current revision must never make an old score current.
                break
        if review["target__key"] == key:
            return {
                "score": review["score"], "state": "scored", "solution_title": solution.display_title,
                "publication_order": (review["published_at"], review["pk"]),
            }
    return {"score": None, "state": "earlier"} if has_visible_review else None


def published_contest_scores(subject, statements):
    """Map canonical statement IDs to a score or earlier-version state."""
    if not approved_user(subject):
        return {}
    linked_statements = {
        row["id"]: (row["linked_problem_id"], row["problem_uuid"], row["statement_uuid"])
        for row in statements
        if row["linked_problem_id"] is not None
    }
    problem_ids = {identity[0] for identity in linked_statements.values()}
    reviews = defaultdict(list)
    for review in _published_reviews(subject, problem_ids, linked_statements):
        reviews[review["target__solution_id"]].append(review)
    if not reviews:
        return {}

    solutions = [
        solution for solution in _solutions(subject, reviews)
        if linked_statements.get(solution.review_statement_id) == (
            solution.problem_id, solution.problem.problem_uuid, solution.review_statement_uuid,
        )
    ]
    blocks = _legacy_blocks(solutions)
    scores = {}
    publication_orders = {}
    for solution in solutions:
        summary = _review_summary(solution, reviews[solution.pk], blocks[solution.pk])
        if summary is None:
            continue
        statement_id = solution.review_statement_id
        order = summary.pop("publication_order", None)
        if order is None:
            scores.setdefault(statement_id, summary)
        elif statement_id not in publication_orders or order > publication_orders[statement_id]:
            publication_orders[statement_id] = order
            scores[statement_id] = summary
    return scores
