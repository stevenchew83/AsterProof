"""Read-only AI review summaries for admin inventories."""

from collections import defaultdict
from contextlib import closing
from itertools import batched

from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import prefetch_related_objects
from django.urls import reverse

from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.forum import current_target_data
from inspinia.solutions.models import ProblemSolution

DRAFT_READY = "draft_ready"
Status = AdminSolutionReview.Status
REVIEW_SUMMARY_FIELDS = (
    "target__solution_id", "target__solution_version", "target__solution_updated_at", "target__key",
    "problem_label", "status", "score", "published_at",
)


def _current_reviews(solution, reviews):
    label = problem_label(solution)
    candidates = [
        row for row in reviews
        if row["problem_label"] == label
        and row["target__solution_version"] == solution.edit_version
        and row["target__solution_updated_at"] == solution.updated_at
    ]
    if not candidates:
        return []
    key = current_target_data(solution)["key"]
    return [row for row in candidates if row["target__key"] == key]


def _review_summary(current):
    if not current:
        return {"label": "Earlier version"}
    published = max(
        (row for row in current if row["published_at"] is not None),
        key=lambda row: (row["published_at"], row["pk"]), default=None,
    )
    if published is not None:
        return {"label": "Published", "score": published["score"], "solution_id": published["target__solution_id"]}
    drafts = [row for row in current if row["status"] == Status.COMPLETED]
    if drafts:
        return {
            "state": DRAFT_READY,
            "label": f"{len(drafts)} drafts ready" if len(drafts) > 1 else "Draft ready",
            "score": drafts[0]["score"] if len(drafts) == 1 else None,
            "solution_id": drafts[0]["target__solution_id"],
        }
    statuses = {row["status"] for row in current}
    status = next(
        (state for state in (Status.RUNNING, Status.QUEUED) if state in statuses),
        Status(current[0]["status"]),
    )
    review = next(row for row in current if row["status"] == status)
    return {
        "label": "Failed" if status == Status.FAILED else status.label,
        "solution_id": review["target__solution_id"],
    }


def latest_solution_review_summaries(solutions):
    """Show the newest attempt for the exact proof and statement on each loaded row."""
    if not solutions:
        return {}

    reviews = AdminSolutionReview.objects.filter(
        target__solution_id__in=[solution.pk for solution in solutions],
        solver_id=F("target__solution__author_id"),
    ).order_by("-created_at", "-pk").values(*REVIEW_SUMMARY_FIELDS)
    by_solution = defaultdict(list)
    for review in reviews:
        by_solution[review["target__solution_id"]].append(review)

    reviewed = [solution for solution in solutions if solution.pk in by_solution]
    prefetch_related_objects(reviewed, "current_revision")
    summaries = {}
    for solution in reviewed:
        current = _current_reviews(solution, by_solution[solution.pk])
        label, score = "Earlier version", None
        if current:
            latest = current[0]
            status = Status(latest["status"])
            label = "Failed" if status == Status.FAILED else status.label
            if latest["published_at"] is not None:
                label = "Published"
            score = latest["score"]
        summaries[solution.pk] = {
            "label": label,
            "score": score,
            "url": reverse("solutions:solution_detail", args=[solution.pk]) + "#ai-review",
        }
    return summaries


def completion_review_summaries(completions, *, draft_ready_only=False):
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
        "created_at",
        "pk",
        *REVIEW_SUMMARY_FIELDS,
    )
    by_solution = defaultdict(list)
    for review in reviews:
        if (review["solver_id"], review["target__solution__problem_id"]) in completion_ids:
            by_solution[review["target__solution_id"]].append(review)

    current_by_problem = defaultdict(list)
    solutions = ProblemSolution.objects.filter(pk__in=by_solution).select_related("problem", "current_revision")
    for solution in solutions:
        current = _current_reviews(solution, by_solution[solution.pk])
        if draft_ready_only:
            has_published = any(row["published_at"] for row in current)
            current = [row for row in current if not has_published and row["status"] == Status.COMPLETED]
        current_by_problem[solution.author_id, solution.problem_id].extend(current)
    summaries = {}
    for key, current in current_by_problem.items():
        current.sort(key=lambda row: (row["created_at"], row["pk"]), reverse=True)
        summary = _review_summary(current)
        for completion_id in completion_ids[key]:
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
            batch_summaries = completion_review_summaries(batch, draft_ready_only=True)
            for completion in batch:
                summary = batch_summaries.get(completion.pk, {})
                if summary.get("state") == DRAFT_READY:
                    matches.append(completion)
                    summaries[completion.pk] = summary
                    if len(matches) == limit:
                        return matches, summaries
    return matches, summaries
