"""AI review summaries and row actions for admin inventories."""

import uuid
from collections import defaultdict
from contextlib import closing
from itertools import batched

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import prefetch_related_objects
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.solutions import admin_reviews
from inspinia.solutions.admin_review_models import MODEL_CHOICES
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.forum import ForumError
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


def solution_inventory_review_states(solutions):
    """Build the display and action state for the current proof and statement."""
    if not solutions:
        return {}

    reviews = AdminSolutionReview.objects.filter(
        target__solution_id__in=[solution.pk for solution in solutions],
        solver_id=F("target__solution__author_id"),
    ).order_by("-created_at", "-pk").values("pk", "model", "taken_down_at", *REVIEW_SUMMARY_FIELDS)
    by_solution = defaultdict(list)
    for review in reviews:
        by_solution[review["target__solution_id"]].append(review)

    reviewed = [solution for solution in solutions if solution.pk in by_solution]
    prefetch_related_objects(reviewed, "current_revision")
    return {
        solution.pk: _solution_inventory_review_state(solution, by_solution.get(solution.pk, ()))
        for solution in solutions
    }


def _solution_inventory_review_state(solution, reviews):
    current = _current_reviews(solution, reviews)
    published = next((row for row in current if row["published_at"] is not None), None)
    active = not published and any(row["status"] in admin_reviews.LIVE_STATES for row in current)
    draft = None
    if not (published or active):
        draft = next((row for row in current if row["status"] == Status.COMPLETED), None)
    displayed = published or draft or (current[0] if current else None)
    label, score = "Earlier version", None
    if displayed:
        status = Status(displayed["status"])
        label = "Failed" if status == Status.FAILED else status.label
        if published:
            label = "Published"
        score = displayed["score"]

    reviewable = solution.status in admin_reviews.REVIEWABLE_STATES
    can_start = settings.ADMIN_SOLUTION_REVIEW_ENABLED and reviewable and not current
    can_publish = draft is not None and reviewable
    action = None
    if can_start or active or can_publish:
        action = {
            "url": reverse("pages:user_solution_record_review", args=[solution.pk]),
            "can_start": can_start,
            "active": active,
        }
        if can_publish:
            taken_down = draft["taken_down_at"]
            action["publish"] = {
                "id": str(draft["pk"]),
                "model": admin_reviews.MODEL_LABELS.get(draft["model"], draft["model"]),
                "last_taken_down": taken_down.isoformat() if taken_down else "",
            }
    return {
        "ai_review": {
            "label": label,
            "score": score,
            "url": reverse("solutions:solution_detail", args=[solution.pk]) + "#ai-review",
        } if reviews else None,
        "review_action": action,
    }


def _queue_inventory_review(request, solution):
    if request.POST.get("include_solution_images") != "1":
        message = "Confirm what will be sent to OpenAI before requesting a review."
        raise ForumError(message)

    config = admin_reviews.review_settings()
    model = next((model for model, _ in MODEL_CHOICES if config and model in config.models_enabled), "")
    data = request.POST.copy()
    data.update({
        "target_key": current_target_data(solution)["key"],
        "problem_label": problem_label(solution),
        "settings_version": str(config.version) if config else "",
        "batch_id": str(uuid.uuid4()),
    })
    data.setlist("models", [model] if model else [])
    return admin_reviews.enqueue(request.user, solution.pk, data, only_unreviewed=True)


def _publish_inventory_review(request, solution):
    try:
        review_id = uuid.UUID(request.POST.get("review_id", ""))
    except ValueError as exc:
        message = "Choose a valid AI review to publish."
        raise ForumError(message) from exc

    admin_reviews.publish(
        request.user, solution.pk, review_id, last_taken_down=request.POST.get("last_taken_down", ""),
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def user_solution_record_review_view(request, solution_pk):
    admin_reviews.require_admin(request.user)
    solution = get_object_or_404(ProblemSolution.objects.select_related("problem", "current_revision"), pk=solution_pk)
    status = 200
    error = ""
    if request.method == "POST":
        action = request.POST.get("action", "start")
        try:
            if action == "publish":
                _publish_inventory_review(request, solution)
            elif action == "start":
                if _queue_inventory_review(request, solution):
                    status = 202
            else:
                error, status = "Choose a valid AI review action.", 422
        except ForumError as exc:
            error, status = str(exc), exc.status
        solution.refresh_from_db()

    state = solution_inventory_review_states([solution])[solution.pk]
    return JsonResponse({**state, "error": error}, status=status)


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
