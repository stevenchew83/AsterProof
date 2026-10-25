from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models import Sum
from django.utils import timezone

from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import PointLedger
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import SubmissionComment
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.users.roles import user_has_trainer_or_admin_role


@dataclass(frozen=True)
class ProgressSummary:
    completed_materials: int
    total_materials: int
    accepted_problems: int
    total_problems: int
    earned_points: int
    available_points: int
    completion_percentage: int


def _user_id(user_or_id) -> int:
    if isinstance(user_or_id, int):
        return user_or_id
    return int(user_or_id.pk)


def get_user_total_points(user_or_id) -> int:
    total = PointLedger.objects.filter(user_id=_user_id(user_or_id)).aggregate(total=Sum("points"))["total"]
    return int(total or 0)


def get_user_current_level(user_or_id, *, total_points: int | None = None) -> LevelThreshold:
    total = get_user_total_points(user_or_id) if total_points is None else total_points
    threshold = LevelThreshold.objects.filter(minimum_points__lte=total).order_by("-minimum_points").first()
    if threshold is not None:
        return threshold
    return LevelThreshold(level_number=1, name="Euclid Initiate", minimum_points=0)


def get_next_level(user_or_id, *, total_points: int | None = None) -> LevelThreshold | None:
    total = get_user_total_points(user_or_id) if total_points is None else total_points
    return LevelThreshold.objects.filter(minimum_points__gt=total).order_by("minimum_points").first()


def has_completed_material(user_or_id, material_or_id) -> bool:
    material_id = material_or_id if isinstance(material_or_id, int) else material_or_id.pk
    return MaterialCompletion.objects.filter(user_id=_user_id(user_or_id), material_id=material_id).exists()


def has_accepted_submission(user_or_id, problem_or_id) -> bool:
    problem_id = problem_or_id if isinstance(problem_or_id, int) else problem_or_id.pk
    return Submission.objects.filter(
        user_id=_user_id(user_or_id),
        problem_id=problem_id,
        status__in=[Submission.Status.ACCEPTED, Submission.Status.PARTIALLY_ACCEPTED],
    ).exists()


@transaction.atomic
def complete_material(*, user, material: Material) -> MaterialCompletion:
    completion, created = MaterialCompletion.objects.get_or_create(
        user=user,
        material=material,
        defaults={"points_awarded": material.completion_points},
    )
    if not created and completion.points_awarded != material.completion_points:
        # Preserve the original award amount; the ledger is historical.
        return completion

    PointLedger.objects.get_or_create(
        source_type=PointLedger.SourceType.MATERIAL_COMPLETION,
        source_id=str(completion.id),
        defaults={
            "user": user,
            "points": completion.points_awarded,
            "reason": f"Completed material: {material.title}",
            "created_by": user,
        },
    )
    return completion


def _review_points_for_status(*, submission: Submission, status: str, awarded_points: int) -> int:
    if status == Submission.Status.ACCEPTED:
        return submission.problem.max_points
    if status == Submission.Status.PARTIALLY_ACCEPTED:
        if awarded_points < 0 or awarded_points > submission.problem.max_points:
            msg = f"Awarded points must be between 0 and {submission.problem.max_points}."
            raise ValidationError(msg)
        return awarded_points
    return 0


@transaction.atomic
def review_submission(
    *,
    submission: Submission,
    reviewer,
    status: str,
    awarded_points: int = 0,
    comment_body: str = "",
) -> Submission:
    if not user_has_trainer_or_admin_role(reviewer):
        raise PermissionDenied
    if status not in Submission.Status.values:
        msg = "Invalid submission status."
        raise ValidationError(msg)

    submission = Submission.objects.select_for_update().select_related("problem", "user").get(pk=submission.pk)
    points = _review_points_for_status(submission=submission, status=status, awarded_points=awarded_points)
    submission.status = status
    submission.awarded_points = points
    submission.reviewed_by = reviewer
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "awarded_points", "reviewed_by", "reviewed_at", "updated_at"])

    body = (comment_body or "").strip()
    if body:
        SubmissionComment.objects.create(submission=submission, author=reviewer, body_markdown=body)

    if points > 0:
        PointLedger.objects.update_or_create(
            source_type=PointLedger.SourceType.PROBLEM_SUBMISSION,
            source_id=str(submission.id),
            defaults={
                "user": submission.user,
                "points": points,
                "reason": f"Reviewed solution: {submission.problem.title}",
                "created_by": reviewer,
            },
        )
    else:
        PointLedger.objects.filter(
            source_type=PointLedger.SourceType.PROBLEM_SUBMISSION,
            source_id=str(submission.id),
        ).delete()
    return submission


def get_subtopic_progress_map(user, subtopic_ids: list[int]) -> dict[int, ProgressSummary]:
    """Load published-content progress in four grouped queries, regardless of roadmap size."""
    if not subtopic_ids:
        return {}

    material_totals = {
        row["subtopic_id"]: row
        for row in Material.objects.filter(subtopic_id__in=subtopic_ids, is_published=True)
        .order_by()
        .values("subtopic_id")
        .annotate(total=Count("id"), points=Sum("completion_points"))
    }
    problem_totals = {
        row["subtopic_id"]: row
        for row in Problem.objects.filter(subtopic_id__in=subtopic_ids, is_published=True)
        .order_by()
        .values("subtopic_id")
        .annotate(total=Count("id"), points=Sum("max_points"))
    }
    material_completions = {
        row["material__subtopic_id"]: row
        for row in MaterialCompletion.objects.filter(
            user=user,
            material__subtopic_id__in=subtopic_ids,
            material__is_published=True,
        )
        .order_by()
        .values("material__subtopic_id")
        .annotate(total=Count("id"), points=Sum("points_awarded"))
    }
    problem_completions = {
        row["problem__subtopic_id"]: row
        for row in Submission.objects.filter(
            user=user,
            problem__subtopic_id__in=subtopic_ids,
            problem__is_published=True,
            status__in=[Submission.Status.ACCEPTED, Submission.Status.PARTIALLY_ACCEPTED],
        )
        .order_by()
        .values("problem__subtopic_id")
        .annotate(
            total=Count("problem_id", distinct=True),
            points=Sum("awarded_points"),
        )
    }
    summaries = {}
    for subtopic_id in subtopic_ids:
        materials = material_totals.get(subtopic_id, {})
        problems = problem_totals.get(subtopic_id, {})
        completed_materials = material_completions.get(subtopic_id, {})
        accepted_problems = problem_completions.get(subtopic_id, {})
        total_items = materials.get("total", 0) + problems.get("total", 0)
        completed_items = completed_materials.get("total", 0) + accepted_problems.get("total", 0)
        summaries[subtopic_id] = ProgressSummary(
            completed_materials=completed_materials.get("total", 0),
            total_materials=materials.get("total", 0),
            accepted_problems=accepted_problems.get("total", 0),
            total_problems=problems.get("total", 0),
            earned_points=int((completed_materials.get("points") or 0) + (accepted_problems.get("points") or 0)),
            available_points=int((materials.get("points") or 0) + (problems.get("points") or 0)),
            completion_percentage=round((completed_items / total_items) * 100) if total_items else 0,
        )
    return summaries


def combine_progress_summaries(summaries) -> ProgressSummary:
    summaries = list(summaries)
    completed_materials = sum(summary.completed_materials for summary in summaries)
    accepted_problems = sum(summary.accepted_problems for summary in summaries)
    total_materials = sum(summary.total_materials for summary in summaries)
    total_problems = sum(summary.total_problems for summary in summaries)
    total_items = total_materials + total_problems
    completed_items = completed_materials + accepted_problems
    return ProgressSummary(
        completed_materials=completed_materials,
        total_materials=total_materials,
        accepted_problems=accepted_problems,
        total_problems=total_problems,
        earned_points=sum(summary.earned_points for summary in summaries),
        available_points=sum(summary.available_points for summary in summaries),
        completion_percentage=round((completed_items / total_items) * 100) if total_items else 0,
    )


def get_subtopic_progress(user, subtopic: Subtopic) -> ProgressSummary:
    return get_subtopic_progress_map(user, [subtopic.id])[subtopic.id]


def get_topic_progress(user, topic: Topic) -> ProgressSummary:
    subtopic_ids = list(topic.subtopics.filter(is_published=True).values_list("id", flat=True))
    return combine_progress_summaries(get_subtopic_progress_map(user, subtopic_ids).values())
