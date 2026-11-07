"""Read-only AI review summaries for the admin completion inventory."""

from collections import defaultdict
from contextlib import closing
from itertools import batched

from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import Subquery
from django.db.models import prefetch_related_objects

from inspinia.pages.models import ContestProblemStatement
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.document_source import legacy_source
from inspinia.solutions.document_source import solution_source
from inspinia.solutions.forum import active_statement_queryset
from inspinia.solutions.forum import saved_target_data
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock

DRAFT_READY = "draft_ready"
Status = AdminSolutionReview.Status


def _review_summary(reviews, key, label):
    current = [row for row in reviews if row["target__key"] == key and row["problem_label"] == label]
    if not current:
        return {"label": "Earlier version"}
    published = next((row for row in current if row["published_at"] is not None), None)
    if published is not None:
        return {"label": "Published", "score": published["score"]}
    drafts = [row for row in current if row["status"] == Status.COMPLETED]
    if drafts:
        return {
            "state": DRAFT_READY,
            "label": f"{len(drafts)} drafts ready" if len(drafts) > 1 else "Draft ready",
            "score": drafts[0]["score"] if len(drafts) == 1 else None,
        }
    statuses = {row["status"] for row in current}
    status = next(
        (state for state in (Status.RUNNING, Status.QUEUED) if state in statuses),
        Status(current[0]["status"]),
    )
    return {"label": "Failed" if status == Status.FAILED else status.label}


def _current_review_targets(solution_ids):
    active_statement = active_statement_queryset(OuterRef("problem_id"))
    solutions = list(
        ProblemSolution.objects.filter(pk__in=solution_ids)
        .select_related("problem", "current_revision")
        .annotate(review_statement_id=Subquery(active_statement.values("pk")[:1])),
    )
    statements = ContestProblemStatement.objects.only("statement_latex").in_bulk(
        {solution.review_statement_id for solution in solutions if solution.review_statement_id is not None},
    )
    prefetch_related_objects(
        [solution for solution in solutions if not solution.current_revision_id],
        Prefetch(
            "blocks",
            queryset=ProblemSolutionBlock.objects.select_related("block_type").order_by("position", "id"),
            to_attr="review_blocks",
        ),
    )
    for solution in solutions:
        source = solution_source(solution) if solution.current_revision_id else legacy_source(solution.review_blocks)
        target = saved_target_data(solution, statements.get(solution.review_statement_id), source)
        yield solution, target["key"]


def completion_review_summaries(completions):
    completion_ids = defaultdict(list)
    for completion in completions:
        if completion.effective_problem_id is not None:
            completion_ids[completion.user_id, completion.effective_problem_id].append(completion.pk)
    if not completion_ids:
        return {}

    reviews = AdminSolutionReview.objects.filter(
        solver_id__in={user_id for user_id, _ in completion_ids},
        target__solution__problem_id__in={problem_id for _, problem_id in completion_ids},
        target__solution__author_id=F("solver_id"),
    ).values(
        "solver_id",
        "target__solution__problem_id",
        "target__solution_id",
        "target__key",
        "problem_label",
        "status",
        "score",
        "published_at",
    )
    by_solution = defaultdict(list)
    for review in reviews:
        if (review["solver_id"], review["target__solution__problem_id"]) in completion_ids:
            by_solution[review["target__solution_id"]].append(review)

    summaries = {}
    for solution, target_key in _current_review_targets(by_solution):
        summary = _review_summary(by_solution[solution.pk], target_key, problem_label(solution))
        for completion_id in completion_ids[solution.author_id, solution.problem_id]:
            summaries[completion_id] = summary
    return summaries


def draft_ready_completions(queryset, limit):
    """Narrow candidates in SQL, then match the exact review target before counting a row."""
    published = AdminSolutionReview.objects.filter(
        target_id=OuterRef("target_id"),
        problem_label=OuterRef("problem_label"),
        solver_id=OuterRef("solver_id"),
        published_at__isnull=False,
    )
    drafts = AdminSolutionReview.objects.filter(
        solver_id=OuterRef("user_id"),
        target__solution__author_id=F("solver_id"),
        target__solution__problem_id=OuterRef("effective_problem_id"),
        target__solution_version=F("target__solution__edit_version"),
        target__solution_updated_at=F("target__solution__updated_at"),
        status=Status.COMPLETED,
        published_at__isnull=True,
    ).filter(~Exists(published))
    matches, summaries = [], {}
    with closing(queryset.filter(Exists(drafts)).iterator(chunk_size=limit)) as candidates:
        for batch in batched(candidates, limit):
            batch_summaries = completion_review_summaries(batch)
            for completion in batch:
                summary = batch_summaries.get(completion.pk, {})
                if summary.get("state") == DRAFT_READY:
                    matches.append(completion)
                    summaries[completion.pk] = summary
                    if len(matches) == limit:
                        return matches, summaries
    return matches, summaries
