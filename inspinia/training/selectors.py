from __future__ import annotations

from django.db.models import Count
from django.db.models import Q
from django.urls import reverse

from inspinia.problemsets.selectors import problem_label
from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingSubtopic
from inspinia.training.models import TrainingTopic


def published_materials_queryset():
    return (
        TrainingMaterial.objects.filter(
            status=TrainingMaterial.Status.PUBLISHED,
            subtopics__is_active=True,
            subtopics__topic__is_active=True,
        )
        .prefetch_related("subtopics__topic", "practice_problems__problem")
        .distinct()
        .order_by("-published_at", "-updated_at", "title")
    )


def curator_materials_queryset():
    return (
        TrainingMaterial.objects.all()
        .select_related("created_by", "updated_by")
        .prefetch_related("subtopics__topic", "practice_problems")
        .order_by("-updated_at", "-id")
    )


def topic_rows() -> list[dict]:
    topics = (
        TrainingTopic.objects.filter(is_active=True)
        .annotate(
            subtopic_total=Count("subtopics", filter=Q(subtopics__is_active=True), distinct=True),
            material_total=Count(
                "subtopics__materials",
                filter=Q(
                    subtopics__is_active=True,
                    subtopics__materials__status=TrainingMaterial.Status.PUBLISHED,
                ),
                distinct=True,
            ),
        )
        .order_by("sort_order", "title")
    )
    return [
        {
            "description": topic.description,
            "detail_url": reverse("training:topic_detail", args=[topic.slug]),
            "material_total": topic.material_total,
            "subtopic_total": topic.subtopic_total,
            "title": topic.title,
        }
        for topic in topics
    ]


def material_card_rows(materials) -> list[dict]:
    rows = []
    for material in materials:
        subtopics = list(material.subtopics.all())
        rows.append(
            {
                "detail_url": reverse("training:material_detail", args=[material.material_uuid, material.slug]),
                "estimated_minutes": material.estimated_minutes,
                "status": material.status,
                "summary": material.summary,
                "subtopic_labels": [subtopic.title for subtopic in subtopics],
                "title": material.title,
            },
        )
    return rows


def curator_material_rows(materials) -> list[dict]:
    return [
        {
            "archive_url": reverse("training:archive", args=[material.material_uuid]),
            "edit_url": reverse("training:update", args=[material.material_uuid]),
            "problem_total": material.practice_problems.count(),
            "publish_url": reverse("training:publish", args=[material.material_uuid]),
            "status": material.status,
            "status_label": material.get_status_display(),
            "subtopic_labels": [subtopic.title for subtopic in material.subtopics.all()],
            "title": material.title,
            "updated_at": material.updated_at,
        }
        for material in materials
    ]


def material_problem_rows(material: TrainingMaterial) -> list[dict]:
    rows = []
    for item in material.practice_problems.select_related("problem").order_by("position", "id"):
        problem = item.problem
        rows.append(
            {
                "label": problem_label(problem),
                "mohs": problem.mohs,
                "note": item.note,
                "position": item.position,
                "problem": problem,
                "problem_uuid": str(problem.problem_uuid),
                "solution_url": reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
                "topic": problem.topic,
            },
        )
    return rows


def subtopic_manage_rows() -> list[dict]:
    subtopics = TrainingSubtopic.objects.select_related("topic").order_by(
        "topic__sort_order",
        "topic__title",
        "sort_order",
        "title",
    )
    return [
        {
            "description": subtopic.description,
            "edit_url": reverse("training:subtopic_update", args=[subtopic.subtopic_uuid]),
            "is_active": subtopic.is_active,
            "is_seeded": subtopic.is_seeded,
            "title": subtopic.title,
            "toggle_url": reverse("training:subtopic_toggle", args=[subtopic.subtopic_uuid]),
            "topic_title": subtopic.topic.title,
        }
        for subtopic in subtopics
    ]
