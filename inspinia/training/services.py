from __future__ import annotations

import uuid

from django.db import transaction

from inspinia.pages.models import ProblemSolveRecord
from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingMaterialProblem
from inspinia.training.models import TrainingMaterialSubtopic
from inspinia.training.models import TrainingSubtopic


class TrainingMaterialServiceError(ValueError):
    """Raised when a training material update cannot be applied."""


def set_training_material_status(material: TrainingMaterial, status: str, *, actor) -> TrainingMaterial:
    if status not in TrainingMaterial.Status.values:
        msg = "Choose draft, published, or archived status."
        raise TrainingMaterialServiceError(msg)

    if status == TrainingMaterial.Status.PUBLISHED:
        material.publish()
    else:
        material.status = status
    material.updated_by = actor
    material.save(update_fields=["status", "published_at", "updated_by", "updated_at"])
    return material


def save_material_subtopics(material: TrainingMaterial, subtopic_uuids: list[str]) -> list[TrainingMaterialSubtopic]:
    normalized_subtopic_uuids = _normalize_uuid_order(subtopic_uuids, error_message="Choose active subtopics.")
    if len(normalized_subtopic_uuids) != len(set(normalized_subtopic_uuids)):
        msg = "A subtopic appears more than once."
        raise TrainingMaterialServiceError(msg)

    subtopics_by_uuid = TrainingSubtopic.objects.in_bulk(normalized_subtopic_uuids, field_name="subtopic_uuid")
    if set(subtopics_by_uuid) != set(normalized_subtopic_uuids) or any(
        not subtopic.is_active for subtopic in subtopics_by_uuid.values()
    ):
        msg = "Choose active subtopics."
        raise TrainingMaterialServiceError(msg)

    with transaction.atomic():
        locked_material = TrainingMaterial.objects.select_for_update().get(pk=material.pk)
        locked_material.material_subtopics.all().delete()
        return [
            TrainingMaterialSubtopic.objects.create(
                material=locked_material,
                subtopic=subtopics_by_uuid[subtopic_uuid],
            )
            for subtopic_uuid in normalized_subtopic_uuids
        ]


def replace_training_material_problems(
    material: TrainingMaterial,
    problem_uuids: list[str],
    *,
    notes: list[str] | None = None,
) -> list[TrainingMaterialProblem]:
    normalized_problem_uuids = _normalize_uuid_order(
        problem_uuids,
        error_message="Submitted problem sequence is invalid.",
    )
    if len(normalized_problem_uuids) != len(set(normalized_problem_uuids)):
        msg = "A problem appears more than once in this sequence."
        raise TrainingMaterialServiceError(msg)
    normalized_notes = (
        _normalize_notes(notes, expected_count=len(normalized_problem_uuids))
        if notes is not None
        else None
    )

    problems_by_uuid = ProblemSolveRecord.objects.in_bulk(normalized_problem_uuids, field_name="problem_uuid")
    if set(problems_by_uuid) != set(normalized_problem_uuids) or any(
        not problem.is_active for problem in problems_by_uuid.values()
    ):
        msg = "Select active contest problems only."
        raise TrainingMaterialServiceError(msg)

    with transaction.atomic():
        locked_material = TrainingMaterial.objects.select_for_update().get(pk=material.pk)
        existing_items = list(
            TrainingMaterialProblem.objects.select_for_update()
            .filter(material=locked_material)
            .order_by("position", "id"),
        )
        for item in existing_items:
            item.delete()
        return [
            TrainingMaterialProblem.objects.create(
                material=locked_material,
                problem=problems_by_uuid[problem_uuid],
                position=index,
                note=normalized_notes[index - 1] if normalized_notes is not None else "",
            )
            for index, problem_uuid in enumerate(normalized_problem_uuids, start=1)
        ]


def _normalize_uuid_order(raw_uuids: list[str], *, error_message: str) -> list[uuid.UUID]:
    normalized_uuids: list[uuid.UUID] = []
    for raw_uuid in raw_uuids:
        raw_value = str(raw_uuid or "").strip()
        if not raw_value:
            continue
        try:
            normalized_uuids.append(uuid.UUID(raw_value))
        except ValueError as exc:
            raise TrainingMaterialServiceError(error_message) from exc
    return normalized_uuids


def _normalize_notes(notes: list[str], *, expected_count: int) -> list[str]:
    normalized_notes = [(note or "").strip() for note in notes[:expected_count]]
    if len(normalized_notes) < expected_count:
        normalized_notes.extend([""] * (expected_count - len(normalized_notes)))
    return normalized_notes
