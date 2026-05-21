from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from inspinia.training.forms import TrainingMaterialForm
from inspinia.training.forms import TrainingSubtopicForm
from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingSubtopic
from inspinia.training.models import TrainingTopic
from inspinia.training.rendering import render_training_markdown
from inspinia.training.selectors import curator_material_rows
from inspinia.training.selectors import curator_materials_queryset
from inspinia.training.selectors import material_card_rows
from inspinia.training.selectors import material_problem_rows
from inspinia.training.selectors import published_materials_queryset
from inspinia.training.selectors import subtopic_manage_rows
from inspinia.training.selectors import topic_rows
from inspinia.training.services import TrainingMaterialServiceError
from inspinia.training.services import replace_training_material_problems
from inspinia.training.services import save_material_subtopics
from inspinia.training.services import set_training_material_status
from inspinia.users.roles import user_can_curate_training


@login_required
def index_view(request):
    recent_materials = list(published_materials_queryset()[:12])
    return render(
        request,
        "training/index.html",
        {
            "material_rows": material_card_rows(recent_materials),
            "topic_rows": topic_rows(),
        },
    )


@login_required
def topic_detail_view(request, topic_slug: str):
    topic = get_object_or_404(TrainingTopic, slug=topic_slug, is_active=True)
    materials = published_materials_queryset().filter(subtopics__topic=topic).distinct()
    subtopic_rows = [
        {
            "description": subtopic.description,
            "detail_url": reverse("training:subtopic_detail", args=[topic.slug, subtopic.slug]),
            "material_total": published_materials_queryset().filter(subtopics=subtopic).count(),
            "title": subtopic.title,
        }
        for subtopic in topic.subtopics.filter(is_active=True).order_by("sort_order", "title")
    ]
    return render(
        request,
        "training/topic-detail.html",
        {
            "material_rows": material_card_rows(materials),
            "subtopic_rows": subtopic_rows,
            "topic": topic,
        },
    )


@login_required
def subtopic_detail_view(request, topic_slug: str, subtopic_slug: str):
    topic = get_object_or_404(TrainingTopic, slug=topic_slug, is_active=True)
    subtopic = get_object_or_404(TrainingSubtopic, topic=topic, slug=subtopic_slug, is_active=True)
    materials = published_materials_queryset().filter(subtopics=subtopic).distinct()
    return render(
        request,
        "training/subtopic-detail.html",
        {
            "material_rows": material_card_rows(materials),
            "subtopic": subtopic,
            "topic": topic,
        },
    )


@login_required
def material_detail_view(request, material_uuid, slug: str):
    material = get_object_or_404(
        published_materials_queryset(),
        material_uuid=material_uuid,
        slug=slug,
    )
    return render(
        request,
        "training/material-detail.html",
        {
            "material": material,
            "problem_rows": material_problem_rows(material),
            "rendered_body": render_training_markdown(material.body_source),
        },
    )


@login_required
def manage_view(request):
    _require_training_curator(request)
    materials = list(curator_materials_queryset())
    archived_total = sum(1 for material in materials if material.status == TrainingMaterial.Status.ARCHIVED)
    published_total = sum(1 for material in materials if material.status == TrainingMaterial.Status.PUBLISHED)
    return render(
        request,
        "training/manage.html",
        {
            "material_rows": curator_material_rows(materials),
            "stats": {
                "archived_total": archived_total,
                "draft_total": sum(1 for material in materials if material.status == TrainingMaterial.Status.DRAFT),
                "published_total": published_total,
                "total": len(materials),
            },
        },
    )


@login_required
def create_view(request):
    _require_training_curator(request)
    form = TrainingMaterialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        material = form.save(commit=False)
        material.created_by = request.user
        material.updated_by = request.user
        material.save()
        save_material_subtopics(
            material,
            [str(subtopic.subtopic_uuid) for subtopic in form.cleaned_data["subtopics"]],
        )
        messages.success(request, "Created training material.")
        return redirect("training:update", material.material_uuid)
    return render(
        request,
        "training/material-form.html",
        {
            "form": form,
            "form_title": "Create training material",
            "material": None,
            "problem_rows": [],
        },
    )


@login_required
def update_view(request, material_uuid):
    _require_training_curator(request)
    material = get_object_or_404(TrainingMaterial, material_uuid=material_uuid)
    form = TrainingMaterialForm(request.POST or None, instance=material)
    if request.method == "POST" and form.is_valid():
        material = form.save(commit=False)
        material.updated_by = request.user
        material.save()
        save_material_subtopics(
            material,
            [str(subtopic.subtopic_uuid) for subtopic in form.cleaned_data["subtopics"]],
        )
        messages.success(request, "Saved training material.")
        return redirect("training:update", material.material_uuid)
    return render(
        request,
        "training/material-form.html",
        {
            "form": form,
            "form_title": "Edit training material",
            "material": material,
            "problem_rows": material_problem_rows(material),
        },
    )


@login_required
@require_POST
def save_problems_view(request, material_uuid):
    _require_training_curator(request)
    material = get_object_or_404(TrainingMaterial, material_uuid=material_uuid)
    try:
        replace_training_material_problems(
            material,
            request.POST.getlist("problem_uuid_order"),
            notes=request.POST.getlist("problem_note"),
        )
    except TrainingMaterialServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Saved practice problem sequence.")
    return redirect("training:update", material.material_uuid)


@login_required
@require_POST
def publish_view(request, material_uuid):
    _require_training_curator(request)
    material = get_object_or_404(TrainingMaterial, material_uuid=material_uuid)
    set_training_material_status(material, TrainingMaterial.Status.PUBLISHED, actor=request.user)
    messages.success(request, "Published training material.")
    return redirect("training:manage")


@login_required
@require_POST
def archive_view(request, material_uuid):
    _require_training_curator(request)
    material = get_object_or_404(TrainingMaterial, material_uuid=material_uuid)
    set_training_material_status(material, TrainingMaterial.Status.ARCHIVED, actor=request.user)
    messages.success(request, "Archived training material.")
    return redirect("training:manage")


@login_required
def subtopic_manage_view(request):
    _require_training_curator(request)
    return render(
        request,
        "training/subtopic-manage.html",
        {
            "subtopic_rows": subtopic_manage_rows(),
        },
    )


@login_required
def subtopic_create_view(request):
    _require_training_curator(request)
    form = TrainingSubtopicForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        subtopic = form.save(commit=False)
        subtopic.is_seeded = False
        subtopic.save()
        messages.success(request, "Created training subtopic.")
        return redirect("training:subtopic_manage")
    return render(
        request,
        "training/subtopic-form.html",
        {
            "form": form,
            "form_title": "Create training subtopic",
        },
    )


@login_required
def subtopic_update_view(request, subtopic_uuid):
    _require_training_curator(request)
    subtopic = get_object_or_404(TrainingSubtopic, subtopic_uuid=subtopic_uuid)
    form = TrainingSubtopicForm(request.POST or None, instance=subtopic)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved training subtopic.")
        return redirect("training:subtopic_manage")
    return render(
        request,
        "training/subtopic-form.html",
        {
            "form": form,
            "form_title": "Edit training subtopic",
            "subtopic": subtopic,
        },
    )


@login_required
@require_POST
def subtopic_toggle_view(request, subtopic_uuid):
    _require_training_curator(request)
    subtopic = get_object_or_404(TrainingSubtopic, subtopic_uuid=subtopic_uuid)
    if subtopic.is_seeded:
        raise PermissionDenied
    subtopic.is_active = not subtopic.is_active
    subtopic.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Updated training subtopic.")
    return redirect("training:subtopic_manage")


def _require_training_curator(request) -> None:
    if not user_can_curate_training(request.user):
        raise PermissionDenied
