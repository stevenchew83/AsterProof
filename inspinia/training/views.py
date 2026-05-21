from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from inspinia.training.forms import LevelThresholdFormSet
from inspinia.training.forms import MaterialForm
from inspinia.training.forms import ProblemForm
from inspinia.training.forms import ReviewForm
from inspinia.training.forms import SubmissionForm
from inspinia.training.forms import SubtopicForm
from inspinia.training.forms import TopicForm
from inspinia.training.markdown import render_markdown
from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import SubmissionAttachment
from inspinia.training.models import SubmissionComment
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.training.services import complete_material
from inspinia.training.services import get_next_level
from inspinia.training.services import get_subtopic_progress
from inspinia.training.services import get_topic_progress
from inspinia.training.services import get_user_current_level
from inspinia.training.services import get_user_total_points
from inspinia.training.services import has_accepted_submission
from inspinia.training.services import has_completed_material
from inspinia.training.services import review_submission
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role

FULL_PROGRESS_PERCENTAGE = 100


def _require_trainer_or_admin(request) -> None:
    if not user_has_trainer_or_admin_role(request.user):
        raise PermissionDenied


def _require_admin(request) -> None:
    if not user_has_admin_role(request.user):
        raise PermissionDenied


def _can_view_unpublished(user) -> bool:
    return user_has_trainer_or_admin_role(user)


def _topic_queryset_for_user(user):
    queryset = Topic.objects.prefetch_related("subtopics").order_by("order", "title", "id")
    if _can_view_unpublished(user):
        return queryset
    return queryset.filter(is_published=True)


def _subtopic_queryset_for_user(user):
    queryset = Subtopic.objects.select_related("topic").order_by("topic__order", "order", "title", "id")
    if _can_view_unpublished(user):
        return queryset
    return queryset.filter(is_published=True, topic__is_published=True)


def _material_queryset_for_user(user):
    queryset = Material.objects.select_related("subtopic", "subtopic__topic")
    if _can_view_unpublished(user):
        return queryset
    return queryset.filter(is_published=True, subtopic__is_published=True, subtopic__topic__is_published=True)


def _problem_queryset_for_user(user):
    queryset = Problem.objects.select_related("subtopic", "subtopic__topic")
    if _can_view_unpublished(user):
        return queryset
    return queryset.filter(is_published=True, subtopic__is_published=True, subtopic__topic__is_published=True)


def _status_badge_class(status: str) -> str:
    return {
        Submission.Status.ACCEPTED: "text-bg-success",
        Submission.Status.PARTIALLY_ACCEPTED: "text-bg-success",
        Submission.Status.NEEDS_REVISION: "text-bg-warning",
        Submission.Status.REJECTED: "text-bg-danger",
        Submission.Status.SUBMITTED: "text-bg-info",
        Submission.Status.UNDER_REVIEW: "text-bg-primary",
    }.get(status, "text-bg-secondary")


def _difficulty_badge_class(difficulty: str) -> str:
    return {
        Problem.Difficulty.INTRODUCTORY: "bg-success-subtle text-success border border-success-subtle",
        Problem.Difficulty.INTERMEDIATE: "bg-info-subtle text-info border border-info-subtle",
        Problem.Difficulty.ADVANCED: "bg-warning-subtle text-warning border border-warning-subtle",
        Problem.Difficulty.OLYMPIAD: "bg-danger-subtle text-danger border border-danger-subtle",
    }.get(difficulty, "bg-light text-dark border")


def _level_progress(total_points: int, current_level: LevelThreshold, next_level: LevelThreshold | None) -> dict:
    if next_level is None:
        return {"percentage": 100, "remaining": 0}
    span = max(next_level.minimum_points - current_level.minimum_points, 1)
    earned_in_level = max(total_points - current_level.minimum_points, 0)
    return {
        "percentage": min(100, round((earned_in_level / span) * 100)),
        "remaining": max(next_level.minimum_points - total_points, 0),
    }


def _topic_rows_for_user(user) -> list[dict]:
    rows = []
    for topic in _topic_queryset_for_user(user):
        subtopics = topic.subtopics.all()
        visible_subtopics = [
            subtopic
            for subtopic in subtopics
            if _can_view_unpublished(user) or (topic.is_published and subtopic.is_published)
        ]
        progress = get_topic_progress(user, topic)
        available_points = progress.available_points
        rows.append(
            {
                "available_points": available_points,
                "description": topic.description,
                "is_published": topic.is_published,
                "progress": progress,
                "subtopic_count": len(visible_subtopics),
                "title": topic.title,
                "url": reverse("training:topic_detail", args=[topic.slug]),
            },
        )
    return rows


def _recommended_subtopic(user) -> Subtopic | None:
    for subtopic in _subtopic_queryset_for_user(user):
        if get_subtopic_progress(user, subtopic).completion_percentage < FULL_PROGRESS_PERCENTAGE:
            return subtopic
    return None


@login_required
def dashboard_view(request):
    total_points = get_user_total_points(request.user)
    current_level = get_user_current_level(request.user)
    next_level = get_next_level(request.user)
    submissions = (
        Submission.objects.filter(user=request.user)
        .select_related("problem", "problem__subtopic", "problem__subtopic__topic")
        .order_by("-updated_at", "-id")
    )
    recent_comments = (
        SubmissionComment.objects.filter(submission__user=request.user)
        .select_related("author", "submission", "submission__problem")
        .order_by("-created_at", "-id")[:5]
    )
    recommendation = _recommended_subtopic(request.user)
    return render(
        request,
        "training/dashboard.html",
        {
            "current_level": current_level,
            "level_progress": _level_progress(total_points, current_level, next_level),
            "next_level": next_level,
            "pending_submissions": submissions.exclude(
                status__in=[
                    Submission.Status.ACCEPTED,
                    Submission.Status.PARTIALLY_ACCEPTED,
                    Submission.Status.REJECTED,
                ],
            )[:6],
            "recent_comments": recent_comments,
            "recommended_subtopic": recommendation,
            "recommended_subtopic_url": (
                reverse("training:subtopic_detail", args=[recommendation.topic.slug, recommendation.slug])
                if recommendation is not None
                else ""
            ),
            "topic_rows": _topic_rows_for_user(request.user),
            "total_points": total_points,
        },
    )


@login_required
def roadmap_view(request):
    return render(request, "training/roadmap.html", {"topic_rows": _topic_rows_for_user(request.user)})


@login_required
def my_submissions_view(request):
    submissions = (
        Submission.objects.filter(user=request.user)
        .select_related("problem", "problem__subtopic", "problem__subtopic__topic")
        .order_by("-updated_at", "-id")
    )
    return render(request, "training/my_submissions.html", {"submissions": submissions})


@login_required
def topic_detail_view(request, topic_slug: str):
    topic = get_object_or_404(_topic_queryset_for_user(request.user), slug=topic_slug)
    subtopic_rows = []
    for subtopic in _subtopic_queryset_for_user(request.user).filter(topic=topic):
        progress = get_subtopic_progress(request.user, subtopic)
        subtopic_rows.append(
            {
                "material_count": Material.objects.filter(subtopic=subtopic, is_published=True).count(),
                "problem_count": Problem.objects.filter(subtopic=subtopic, is_published=True).count(),
                "progress": progress,
                "subtopic": subtopic,
                "url": reverse("training:subtopic_detail", args=[topic.slug, subtopic.slug]),
            },
        )
    return render(
        request,
        "training/topic_detail.html",
        {
            "subtopic_rows": subtopic_rows,
            "topic": topic,
            "topic_progress": get_topic_progress(request.user, topic),
        },
    )


@login_required
def subtopic_detail_view(request, topic_slug: str, subtopic_slug: str):
    subtopic = get_object_or_404(
        _subtopic_queryset_for_user(request.user),
        topic__slug=topic_slug,
        slug=subtopic_slug,
    )
    materials = [
        {
            "completed": has_completed_material(request.user, material),
            "material": material,
            "url": reverse("training:material_detail", args=[material.slug]),
        }
        for material in _material_queryset_for_user(request.user).filter(subtopic=subtopic).order_by("order", "title")
    ]
    problems = [
        {
            "accepted": has_accepted_submission(request.user, problem),
            "badge_class": _difficulty_badge_class(problem.difficulty),
            "problem": problem,
            "url": reverse("training:problem_detail", args=[problem.slug]),
        }
        for problem in _problem_queryset_for_user(request.user).filter(subtopic=subtopic).order_by("order", "title")
    ]
    return render(
        request,
        "training/subtopic_detail.html",
        {
            "materials": materials,
            "problems": problems,
            "progress": get_subtopic_progress(request.user, subtopic),
            "subtopic": subtopic,
            "topic": subtopic.topic,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def material_detail_view(request, material_slug: str):
    material = get_object_or_404(_material_queryset_for_user(request.user), slug=material_slug)
    if request.method == "POST":
        complete_material(user=request.user, material=material)
        messages.success(request, "Material marked complete.")
        return redirect("training:material_detail", material.slug)
    completed = has_completed_material(request.user, material)
    return render(
        request,
        "training/material_detail.html",
        {
            "completed": completed,
            "material": material,
            "rendered_content": render_markdown(material.content_markdown),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def problem_detail_view(request, problem_slug: str):
    problem = get_object_or_404(_problem_queryset_for_user(request.user), slug=problem_slug)
    submissions = list(
        Submission.objects.filter(user=request.user, problem=problem)
        .prefetch_related("comments", "comments__author", "attachments")
        .order_by("-created_at", "-id"),
    )
    accepted_submission = next((submission for submission in submissions if submission.is_accepted_for_progress), None)
    latest_submission = submissions[0] if submissions else None
    editable_submission = None if accepted_submission is not None else latest_submission

    if request.method == "POST":
        if accepted_submission is not None:
            messages.error(request, "Accepted solutions cannot be edited from this page.")
            return redirect("training:problem_detail", problem.slug)
        form = SubmissionForm(request.POST, instance=editable_submission)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.user = request.user
            submission.problem = problem
            submission.status = Submission.Status.SUBMITTED
            submission.awarded_points = 0
            submission.save()
            upload = request.FILES.get("attachment")
            if upload is not None:
                SubmissionAttachment.objects.create(
                    submission=submission,
                    file=upload,
                    original_name=upload.name,
                )
            messages.success(request, "Solution submitted for trainer review.")
            return redirect("training:problem_detail", problem.slug)
    else:
        form = SubmissionForm(instance=editable_submission)

    return render(
        request,
        "training/problem_detail.html",
        {
            "accepted_submission": accepted_submission,
            "can_view_official_solution": _can_view_unpublished(request.user) or accepted_submission is not None,
            "difficulty_badge_class": _difficulty_badge_class(problem.difficulty),
            "form": form,
            "problem": problem,
            "rendered_official_solution": render_markdown(problem.official_solution_markdown),
            "rendered_statement": render_markdown(problem.statement_markdown),
            "status_badge_class": _status_badge_class,
            "submissions": submissions,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def submission_detail_view(request, submission_id: int):
    submission = get_object_or_404(
        Submission.objects.select_related("user", "problem", "problem__subtopic", "problem__subtopic__topic"),
        pk=submission_id,
    )
    reviewer_view = user_has_trainer_or_admin_role(request.user)
    if submission.user_id != request.user.id and not reviewer_view:
        raise PermissionDenied

    if request.method == "POST":
        if not reviewer_view:
            raise PermissionDenied
        form = ReviewForm(request.POST, problem=submission.problem)
        if form.is_valid():
            review_submission(
                submission=submission,
                reviewer=request.user,
                status=form.cleaned_data["status"],
                awarded_points=form.cleaned_data["awarded_points"],
                comment_body=form.cleaned_data["comment_body"],
            )
            messages.success(request, "Submission review saved.")
            return redirect("training:submission_detail", submission.id)
    else:
        form = ReviewForm(
            initial={"status": submission.status, "awarded_points": submission.awarded_points},
            problem=submission.problem,
        )

    comments = [
        {
            "comment": comment,
            "rendered_body": render_markdown(comment.body_markdown),
        }
        for comment in submission.comments.select_related("author")
    ]
    return render(
        request,
        "training/submission_detail.html",
        {
            "comments": comments,
            "form": form,
            "rendered_solution": render_markdown(submission.solution_markdown),
            "reviewer_view": reviewer_view,
            "status_badge_class": _status_badge_class(submission.status),
            "submission": submission,
        },
    )


@login_required
def trainer_dashboard_view(request):
    _require_trainer_or_admin(request)
    pending_statuses = [Submission.Status.SUBMITTED, Submission.Status.UNDER_REVIEW, Submission.Status.NEEDS_REVISION]
    pending_submissions = (
        Submission.objects.filter(status__in=pending_statuses)
        .select_related("user", "problem", "problem__subtopic", "problem__subtopic__topic")
        .order_by("-updated_at", "-id")[:10]
    )
    return render(
        request,
        "training/trainer/dashboard.html",
        {
            "material_total": Material.objects.count(),
            "pending_submissions": pending_submissions,
            "pending_total": Submission.objects.filter(status__in=pending_statuses).count(),
            "problem_total": Problem.objects.count(),
            "recent_completions": MaterialCompletion.objects.select_related("user", "material").order_by(
                "-completed_at",
                "-id",
            )[:8],
            "topic_total": Topic.objects.count(),
        },
    )


def _redirect_with_edit(route_name: str, item_id: int | None = None, *, param_name: str = "edit"):
    url = reverse(route_name)
    if item_id is not None:
        url = f"{url}?{urlencode({param_name: item_id})}"
    return redirect(url)


def _selected_training_topic(topics: list[Topic], topic: Topic | None, subtopic: Subtopic | None) -> Topic | None:
    if topic is not None:
        return topic
    if subtopic is not None:
        return subtopic.topic
    return topics[0] if topics else None


def _topic_workspace_stats(topics: list[Topic], subtopics: list[Subtopic]) -> dict[str, int]:
    published_topic_count = sum(1 for topic in topics if topic.is_published)
    published_subtopic_count = sum(
        1
        for subtopic in subtopics
        if subtopic.is_published and subtopic.topic.is_published
    )
    return {
        "topic_total": len(topics),
        "subtopic_total": len(subtopics),
        "published_total": published_topic_count + published_subtopic_count,
        "draft_total": (len(topics) - published_topic_count) + (len(subtopics) - published_subtopic_count),
    }


@login_required
@require_http_methods(["GET", "POST"])
def trainer_topics_view(request):
    _require_trainer_or_admin(request)
    topic_instance = None
    subtopic_instance = None
    active_form_kind = "topic"
    if request.GET.get("edit_topic"):
        topic_instance = get_object_or_404(Topic, pk=request.GET["edit_topic"])
        active_form_kind = "topic"
    if request.GET.get("edit_subtopic"):
        subtopic_instance = get_object_or_404(Subtopic, pk=request.GET["edit_subtopic"])
        active_form_kind = "subtopic"

    topic_form = TopicForm(instance=topic_instance)
    subtopic_form = SubtopicForm(instance=subtopic_instance)

    if request.method == "POST":
        form_kind = request.POST.get("form_kind")
        if form_kind == "topic":
            instance = Topic.objects.filter(pk=request.POST.get("item_id")).first()
            topic_form = TopicForm(request.POST, instance=instance)
            active_form_kind = "topic"
            if topic_form.is_valid():
                saved = topic_form.save()
                messages.success(request, "Topic saved.")
                return _redirect_with_edit("training:trainer_topics", saved.id, param_name="edit_topic")
        elif form_kind == "subtopic":
            instance = Subtopic.objects.filter(pk=request.POST.get("item_id")).first()
            subtopic_form = SubtopicForm(request.POST, instance=instance)
            active_form_kind = "subtopic"
            if subtopic_form.is_valid():
                subtopic_form.save()
                messages.success(request, "Subtopic saved.")
                return redirect("training:trainer_topics")

    topics = list(Topic.objects.prefetch_related("subtopics"))
    subtopics = list(Subtopic.objects.select_related("topic"))

    return render(
        request,
        "training/trainer/topics.html",
        {
            "active_form_kind": active_form_kind,
            "selected_topic": _selected_training_topic(topics, topic_instance, subtopic_instance),
            "subtopic_form": subtopic_form,
            "subtopics": subtopics,
            "topic_form": topic_form,
            "topic_workspace_stats": _topic_workspace_stats(topics, subtopics),
            "topics": topics,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def trainer_materials_view(request):
    _require_trainer_or_admin(request)
    instance = Material.objects.filter(pk=request.GET.get("edit")).first()
    if request.method == "POST":
        instance = Material.objects.filter(pk=request.POST.get("item_id")).first()
        form = MaterialForm(request.POST, instance=instance)
        if form.is_valid():
            material = form.save(commit=False)
            if material.created_by_id is None:
                material.created_by = request.user
            material.save()
            messages.success(request, "Material saved.")
            return _redirect_with_edit("training:trainer_materials", material.id)
    else:
        form = MaterialForm(instance=instance)

    return render(
        request,
        "training/trainer/materials.html",
        {
            "form": form,
            "materials": Material.objects.select_related("subtopic", "subtopic__topic"),
            "rendered_material_preview": render_markdown(instance.content_markdown) if instance is not None else "",
            "selected_material": instance,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def trainer_problems_view(request):
    _require_trainer_or_admin(request)
    instance = Problem.objects.filter(pk=request.GET.get("edit")).first()
    if request.method == "POST":
        instance = Problem.objects.filter(pk=request.POST.get("item_id")).first()
        form = ProblemForm(request.POST, instance=instance)
        if form.is_valid():
            problem = form.save(commit=False)
            if problem.created_by_id is None:
                problem.created_by = request.user
            problem.save()
            messages.success(request, "Problem saved.")
            return _redirect_with_edit("training:trainer_problems", problem.id)
    else:
        form = ProblemForm(instance=instance)

    return render(
        request,
        "training/trainer/problems.html",
        {
            "form": form,
            "problems": Problem.objects.select_related("subtopic", "subtopic__topic"),
            "rendered_official_solution_preview": (
                render_markdown(instance.official_solution_markdown) if instance is not None else ""
            ),
            "rendered_statement_preview": render_markdown(instance.statement_markdown) if instance is not None else "",
            "selected_problem": instance,
        },
    )


@login_required
def trainer_submissions_view(request):
    _require_trainer_or_admin(request)
    submissions = Submission.objects.select_related("user", "problem", "problem__subtopic", "problem__subtopic__topic")
    status_filter = request.GET.get("status", "")
    topic_filter = request.GET.get("topic", "")
    query = request.GET.get("q", "").strip()
    if status_filter in Submission.Status.values:
        submissions = submissions.filter(status=status_filter)
    if topic_filter.isdigit():
        submissions = submissions.filter(problem__subtopic__topic_id=int(topic_filter))
    if query:
        submissions = submissions.filter(
            Q(user__email__icontains=query) | Q(user__name__icontains=query) | Q(problem__title__icontains=query),
        )
    return render(
        request,
        "training/trainer/submissions.html",
        {
            "status_badge_class": _status_badge_class,
            "status_choices": Submission.Status.choices,
            "status_filter": status_filter,
            "submissions": submissions.order_by("-updated_at", "-id")[:100],
            "topic_filter": topic_filter,
            "topic_options": [
                {
                    "is_selected": str(topic.id) == topic_filter,
                    "topic": topic,
                }
                for topic in Topic.objects.annotate(submission_count=Count("subtopics__problems__submissions"))
            ],
            "query": query,
        },
    )


@login_required
def admin_users_view(request):
    _require_admin(request)
    return redirect("users:manage_roles")


@login_required
@require_http_methods(["GET", "POST"])
def admin_levels_view(request):
    _require_admin(request)
    queryset = LevelThreshold.objects.order_by("level_number")
    if request.method == "POST":
        formset = LevelThresholdFormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Level thresholds saved.")
            return redirect("training:admin_levels")
    else:
        formset = LevelThresholdFormSet(queryset=queryset)
    return render(request, "training/admin/levels.html", {"formset": formset})


def permission_denied_response(request):
    return render(request, "403.html", status=HTTPStatus.FORBIDDEN)
