from __future__ import annotations

import csv
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.db.models import F
from django.http import HttpResponse
from django.urls import reverse

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.models import TOPIC_TAG_LAYER_FIELDS
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.technique_progress_catalog import technique_progress_catalog_status_context
from inspinia.pages.topic_labels import display_topic_label
from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role

if TYPE_CHECKING:
    from collections.abc import Mapping

NEXT_GAP_LIMIT = 6
GAP_PAGE_SIZE = 50
GAP_CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
GAP_CSV_FIELDNAMES = [
    "Area",
    "Canonical Subtopic",
    "Type",
    "Topic",
    "Completed",
    "Remaining",
    "Coverage",
    "Practice URL",
]
GAP_KIND_SUBTOPICS = "subtopics"
GAP_KIND_TECHNIQUES = "techniques"
GAP_KIND_OBJECTS = "objects"
GAP_KIND_METHODS = "methods"
GAP_KIND_LEMMAS = "lemmas"
GAP_KIND_PROOF_ROLES = "proof_roles"
GAP_KIND_ALL = "all"
GAP_KIND_CHOICES = {
    GAP_KIND_SUBTOPICS,
    GAP_KIND_TECHNIQUES,
    GAP_KIND_OBJECTS,
    GAP_KIND_METHODS,
    GAP_KIND_LEMMAS,
    GAP_KIND_PROOF_ROLES,
    GAP_KIND_ALL,
}
GAP_KIND_BY_TYPE_LABEL = {
    "Lemma/Theorem": GAP_KIND_LEMMAS,
    "Method": GAP_KIND_METHODS,
    "Object": GAP_KIND_OBJECTS,
    "Proof role": GAP_KIND_PROOF_ROLES,
    "Subtopic": GAP_KIND_SUBTOPICS,
    "Technique": GAP_KIND_TECHNIQUES,
}
GAP_DATATABLE_DEFAULT_SORT_FIELD = "completion_percent"
GAP_DATATABLE_SORT_FIELDS = {
    "canonical_subtopic",
    "canonical_subtopic_label",
    "completion_percent",
    "label",
    "main_topic_label",
    "remaining",
    "solved_total_label",
    "type",
}
MAIN_TOPIC_ORDER = ["Algebra", "Number Theory", "Geometry", "Combinatorics"]
OTHER_TOPIC_LABEL = "Other"
SUBTOPIC_ALWAYS_SUPPRESSED_NORMALIZATION_STATUSES = {"corrupt", "invalid", "metadata"}
SUBTOPIC_EMPTY_CANONICAL_SUPPRESSED_NORMALIZATION_STATUSES = {"lemma", "method", "needs_review"}
TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES = {"corrupt", "invalid", "metadata"}
FACT_LAYER_METADATA_FIELDS = {
    TechniqueProgressFact.Layer.OBJECT: "object_tags",
    TechniqueProgressFact.Layer.METHOD: "technique_tags",
    TechniqueProgressFact.Layer.LEMMA: "lemma_theorem_tags",
    TechniqueProgressFact.Layer.PROOF_ROLE: "proof_roles",
}
MAIN_TOPIC_SLUGS = {
    "algebra": "Algebra",
    "number-theory": "Number Theory",
    "geometry": "Geometry",
    "combinatorics": "Combinatorics",
    "other": OTHER_TOPIC_LABEL,
}
GAP_TOPIC_ALL = "all"
GAP_TOPIC_SLUGS = {
    GAP_TOPIC_ALL: "All",
    "algebra": "Algebra",
    "number-theory": "Number Theory",
    "geometry": "Geometry",
    "combinatorics": "Combinatorics",
}


def _layers_for_gap_kind(gap_kind: str) -> set[str]:
    layer_sets = {
        GAP_KIND_TECHNIQUES: {TechniqueProgressFact.Layer.TECHNIQUE},
        GAP_KIND_OBJECTS: {TechniqueProgressFact.Layer.OBJECT},
        GAP_KIND_METHODS: {TechniqueProgressFact.Layer.METHOD},
        GAP_KIND_LEMMAS: {TechniqueProgressFact.Layer.LEMMA},
        GAP_KIND_PROOF_ROLES: {TechniqueProgressFact.Layer.PROOF_ROLE},
        GAP_KIND_ALL: {
            TechniqueProgressFact.Layer.SUBTOPIC,
            TechniqueProgressFact.Layer.TECHNIQUE,
        },
    }
    return layer_sets.get(gap_kind, {TechniqueProgressFact.Layer.SUBTOPIC})


def _progress_fact_rows(
    *,
    user: User,
    layers: set[str],
    include_layer_metadata: bool = False,
) -> list[dict[str, object]]:
    fact_rows = list(
        TechniqueProgressFact.objects.filter(layer__in=layers)
        .values(
            "canonical_subtopic",
            "canonical_subtopic_labels",
            "label",
            "layer",
            "linked_problem_id",
            "main_topic",
            "main_topic_labels",
            "search_text",
            "statement_id",
        )
        .order_by("layer", "label", "statement_id", "id"),
    )
    if not fact_rows:
        return []

    statement_problem_ids = {
        int(row["statement_id"]): row["linked_problem_id"]
        for row in fact_rows
    }
    statement_ids = sorted(statement_problem_ids)
    metadata_source_rows = [
        row
        for row in fact_rows
        if row["layer"] in FACT_LAYER_METADATA_FIELDS
    ]
    if include_layer_metadata:
        metadata_source_rows = list(
            TechniqueProgressFact.objects.filter(
                statement_id__in=statement_ids,
                layer__in=FACT_LAYER_METADATA_FIELDS,
            )
            .values("label", "layer", "statement_id")
            .order_by("layer", "label", "statement_id", "id"),
        )
    layer_metadata_by_statement_id: dict[int, dict[str, set[str]]] = {
        statement_id: {field_name: set() for field_name in TOPIC_TAG_LAYER_FIELDS}
        for statement_id in statement_ids
    }
    for metadata_row in metadata_source_rows:
        field_name = FACT_LAYER_METADATA_FIELDS.get(str(metadata_row["layer"]))
        if not field_name:
            continue
        label = str(metadata_row.get("label") or "").strip()
        if not label:
            continue
        statement_metadata = layer_metadata_by_statement_id.setdefault(
            int(metadata_row["statement_id"]),
            {field_name: set() for field_name in TOPIC_TAG_LAYER_FIELDS},
        )
        statement_metadata.setdefault(field_name, set()).add(label)

    completion_by_statement_id = _completion_by_catalog_statement_id(
        statement_problem_ids=statement_problem_ids,
        user=user,
    )

    rows = []
    for fact in fact_rows:
        statement_id = int(fact["statement_id"])
        completion = completion_by_statement_id.get(statement_id)
        is_solved = completion is not None and is_completion_status_solved(completion.status)
        layer = str(fact["layer"])
        label = str(fact["label"] or "")
        main_topic_labels = list(fact.get("main_topic_labels") or [])
        canonical_subtopic = str(fact.get("canonical_subtopic") or "")
        layer_metadata = layer_metadata_by_statement_id.get(
            statement_id,
            {field_name: set() for field_name in TOPIC_TAG_LAYER_FIELDS},
        )
        rows.append(
            {
                "canonical_subtopic": canonical_subtopic,
                "canonical_subtopic_labels": list(fact.get("canonical_subtopic_labels") or []),
                "domain_topic_labels": main_topic_labels,
                "is_solved": is_solved,
                "label": label,
                "layer": layer,
                "main_topic": str(fact.get("main_topic") or (main_topic_labels[0] if main_topic_labels else "")),
                "main_topic_labels": main_topic_labels,
                "object_tags": sorted(layer_metadata.get("object_tags", set()), key=str.casefold),
                "lemma_theorem_tags": sorted(layer_metadata.get("lemma_theorem_tags", set()), key=str.casefold),
                "proof_roles": sorted(layer_metadata.get("proof_roles", set()), key=str.casefold),
                "search_text": str(fact.get("search_text") or ""),
                "statement_id": statement_id,
                "subtopic": label if layer == TechniqueProgressFact.Layer.SUBTOPIC else canonical_subtopic,
                "technique": label if layer == TechniqueProgressFact.Layer.TECHNIQUE else "",
                "technique_tags": sorted(layer_metadata.get("technique_tags", set()), key=str.casefold),
            },
        )
    return rows


def _completion_by_catalog_statement_id(
    *,
    statement_problem_ids: dict[int, int | None],
    user: User,
) -> dict[int, UserProblemCompletion]:
    statement_ids = sorted(statement_problem_ids)
    completion_by_statement_id = {
        completion.statement_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.statement_id is not None
    }
    linked_problem_ids = sorted(
        {
            problem_id
            for problem_id in statement_problem_ids.values()
            if problem_id is not None
        },
    )
    if not linked_problem_ids:
        return completion_by_statement_id

    legacy_completion_by_problem_id = {
        completion.problem_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            problem_id__in=linked_problem_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.problem_id is not None
    }
    for statement_id, problem_id in statement_problem_ids.items():
        if statement_id in completion_by_statement_id:
            continue
        if problem_id in legacy_completion_by_problem_id:
            completion_by_statement_id[statement_id] = legacy_completion_by_problem_id[problem_id]
    return completion_by_statement_id


def _rows_for_layer(rows: list[dict[str, object]], layer: str) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row.get("layer") == layer
    ]


def technique_progress_user_options() -> list[dict[str, str]]:
    options = []
    for user in User.objects.filter(is_active=True).order_by("name", "email", "id"):
        user_label = user.name or user.email
        options.append(
            {
                "label": user_label if user_label == user.email else f"{user_label} ({user.email})",
                "value": str(user.pk),
            },
        )
    return options


def resolve_technique_progress_user(
    *,
    request_user: User,
    raw_user_id: str,
) -> tuple[User, bool]:
    can_select_user = user_has_admin_role(request_user)
    if not can_select_user:
        return request_user, False

    selected_user = None
    if raw_user_id:
        try:
            selected_user_id = int(raw_user_id)
        except (TypeError, ValueError):
            selected_user_id = None
        if selected_user_id is not None:
            selected_user = User.objects.filter(pk=selected_user_id, is_active=True).first()
    return selected_user or request_user, True


def build_technique_progress_context(
    *,
    request_user: User,
    raw_user_id: str = "",
) -> dict[str, object]:
    payload = _build_progress_payload(
        request_user=request_user,
        raw_user_id=raw_user_id,
        required_layers={
            TechniqueProgressFact.Layer.MAIN_TOPIC,
            TechniqueProgressFact.Layer.SUBTOPIC,
            TechniqueProgressFact.Layer.TECHNIQUE,
        },
    )
    return {
        **payload["base_context"],
        "technique_progress_main_topic_rows": payload["main_topic_rows"],
        "technique_progress_next_gaps": payload["next_gaps"],
        "technique_progress_stats": payload["stats"],
        "technique_progress_subtopic_rows": payload["subtopic_rows"],
        "technique_progress_technique_rows": payload["technique_rows"],
    }


def build_technique_progress_gaps_context(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
) -> dict[str, object]:
    gap_kind = _gap_kind(raw_kind)
    payload = _build_progress_payload(
        request_user=request_user,
        raw_user_id=raw_user_id,
        required_layers=_layers_for_gap_kind(gap_kind),
    )
    base_context = payload["base_context"]
    selected_user = base_context["technique_progress_selected_user"]
    can_select_user = bool(base_context["technique_progress_can_select_user"])
    gap_topic = _gap_topic(raw_topic)
    gap_min_total = _gap_min_total(raw_min_total)
    gap_canonical_subtopic = _gap_canonical_subtopic(raw_canonical_subtopic)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    gap_rows = _gap_rows_with_drilldown_urls(
        gap_rows,
        selected_user=selected_user,
        can_select_user=can_select_user,
        gap_topic=gap_topic,
    )
    return {
        **base_context,
        "technique_progress_gap_canonical_subtopic": gap_canonical_subtopic,
        "technique_progress_gap_canonical_subtopic_reset_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_min_total=gap_min_total,
        ),
        "technique_progress_gap_export_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_min_total=gap_min_total,
            gap_canonical_subtopic=gap_canonical_subtopic,
            extra_query={"export": "csv"},
        ),
        "technique_progress_gap_kind": gap_kind,
        "technique_progress_gap_kind_options": _gap_kind_options(
            selected_user=selected_user,
            can_select_user=can_select_user,
            active_kind=gap_kind,
            active_topic=gap_topic,
            active_min_total=gap_min_total,
            active_canonical_subtopic=gap_canonical_subtopic,
        ),
        "technique_progress_gap_first_column_label": _gap_first_column_label(gap_kind),
        "technique_progress_gap_min_total": gap_min_total,
        "technique_progress_gap_min_total_reset_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_canonical_subtopic=gap_canonical_subtopic,
        ),
        "technique_progress_gap_result_summary": _gap_result_summary(
            gap_rows,
            gap_kind=gap_kind,
        ),
        "technique_progress_gap_rows": gap_rows,
        "technique_progress_gap_show_canonical_subtopic_column": gap_kind in {GAP_KIND_TECHNIQUES, GAP_KIND_ALL},
        "technique_progress_gap_show_type_column": gap_kind == GAP_KIND_ALL,
        "technique_progress_gap_title": _gap_title(gap_kind),
        "technique_progress_gap_topic": gap_topic,
        "technique_progress_gap_topic_tabs": _gap_topic_tabs(
            selected_user=selected_user,
            can_select_user=can_select_user,
            active_kind=gap_kind,
            active_topic=gap_topic,
            active_min_total=gap_min_total,
            active_canonical_subtopic=gap_canonical_subtopic,
        ),
        "technique_progress_stats": payload["stats"],
    }


def build_technique_progress_gaps_csv_response(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
) -> HttpResponse:
    gap_kind = _gap_kind(raw_kind)
    payload = _build_progress_payload(
        request_user=request_user,
        raw_user_id=raw_user_id,
        required_layers=_layers_for_gap_kind(gap_kind),
    )
    gap_min_total = _gap_min_total(raw_min_total)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=_gap_topic(raw_topic),
        gap_min_total=gap_min_total,
        gap_canonical_subtopic=_gap_canonical_subtopic(raw_canonical_subtopic),
    )
    response = HttpResponse(content_type=GAP_CSV_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="technique-progress-gaps.csv"'
    writer = csv.DictWriter(response, fieldnames=GAP_CSV_FIELDNAMES)
    writer.writeheader()
    writer.writerows(_gap_csv_row(row) for row in gap_rows)
    return response


def build_technique_progress_gaps_datatable_payload(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
    params: Mapping[str, str] | None = None,
) -> dict[str, object]:
    params = params or {}
    gap_kind = _gap_kind(raw_kind)
    payload = _build_progress_payload(
        request_user=request_user,
        raw_user_id=raw_user_id,
        required_layers=_layers_for_gap_kind(gap_kind),
    )
    gap_topic = _gap_topic(raw_topic)
    gap_min_total = _gap_min_total(raw_min_total)
    gap_canonical_subtopic = _gap_canonical_subtopic(raw_canonical_subtopic)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    gap_rows = _gap_rows_with_drilldown_urls(
        gap_rows,
        selected_user=payload["base_context"]["technique_progress_selected_user"],
        can_select_user=bool(payload["base_context"]["technique_progress_can_select_user"]),
        gap_topic=gap_topic,
    )

    draw = _datatable_int(params.get("draw"), default=0)
    start = _datatable_int(params.get("start"), default=0)
    requested_length = _datatable_int(params.get("length"), default=GAP_PAGE_SIZE)
    page_length = min(max(requested_length, 1), GAP_PAGE_SIZE)

    records_total = len(gap_rows)
    searched_rows = _search_gap_rows(gap_rows, raw_search=params.get("search[value]", ""))
    sorted_rows = _sort_gap_rows_for_datatable(
        searched_rows,
        params=params,
        gap_kind=gap_kind,
    )
    page_rows = sorted_rows[start : start + page_length]

    return {
        "draw": draw,
        "recordsTotal": records_total,
        "recordsFiltered": len(searched_rows),
        "data": [_gap_datatable_row(row) for row in page_rows],
    }


def build_technique_progress_topic_context(
    *,
    request_user: User,
    raw_user_id: str = "",
    topic_slug: str,
) -> dict[str, object]:
    topic_label = MAIN_TOPIC_SLUGS.get(topic_slug)
    if topic_label is None:
        raise ValueError(topic_slug)

    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _progress_fact_rows(
        user=selected_user,
        layers={
            TechniqueProgressFact.Layer.MAIN_TOPIC,
            TechniqueProgressFact.Layer.SUBTOPIC,
        },
        include_layer_metadata=True,
    )
    main_topic_fact_rows = _rows_for_layer(tagged_rows, TechniqueProgressFact.Layer.MAIN_TOPIC)
    subtopic_fact_rows = _rows_for_layer(tagged_rows, TechniqueProgressFact.Layer.SUBTOPIC)
    topic_tagged_rows = [
        row
        for row in main_topic_fact_rows
        if row["label"] == topic_label
    ]
    topic_subtopic_fact_rows = [
        row
        for row in subtopic_fact_rows
        if topic_label in row.get("main_topic_labels", [])
    ]
    topic_subtopic_rows = _aggregate_progress_rows(
        topic_subtopic_fact_rows,
        label_key="label",
        type_label="Subtopic",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    summary = _summary_from_tagged_rows(topic_tagged_rows)
    summary["incomplete_subtopic_total"] = sum(1 for row in topic_subtopic_rows if row["remaining"])
    summary["subtopic_total"] = len(topic_subtopic_rows)
    return {
        **_base_context(
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_dashboard_url": _page_url(
            "pages:technique_dashboard",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_topic_label": topic_label,
        "technique_progress_topic_slug": topic_slug,
        "technique_progress_topic_subtopic_rows": topic_subtopic_rows,
        "technique_progress_topic_summary": summary,
    }


def _build_progress_payload(
    *,
    request_user: User,
    raw_user_id: str,
    required_layers: set[str],
) -> dict[str, object]:
    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _progress_fact_rows(user=selected_user, layers=required_layers)
    rows_by_layer = {
        layer: _rows_for_layer(tagged_rows, layer)
        for layer in required_layers
    }
    technique_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.TECHNIQUE, []),
        label_key="label",
        type_label="Technique",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    subtopic_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.SUBTOPIC, []),
        label_key="label",
        type_label="Subtopic",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    object_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.OBJECT, []),
        label_key="label",
        type_label="Object",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    method_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.METHOD, []),
        label_key="label",
        type_label="Method",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    lemma_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.LEMMA, []),
        label_key="label",
        type_label="Lemma/Theorem",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    proof_role_rows = _aggregate_progress_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.PROOF_ROLE, []),
        label_key="label",
        type_label="Proof role",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    summary = _summary_from_tagged_rows(
        rows_by_layer.get(TechniqueProgressFact.Layer.MAIN_TOPIC, tagged_rows),
    )
    stats = {
        "completion_percent": summary["completion_percent"],
        "completed_statement_total": summary["solved"],
        "incomplete_subtopic_total": sum(1 for row in subtopic_rows if row["remaining"]),
        "incomplete_technique_total": sum(1 for row in technique_rows if row["remaining"]),
        "subtopic_total": len(subtopic_rows),
        "tagged_statement_total": summary["total"],
        "technique_total": len(technique_rows),
    }
    gap_rows = _gap_rows(subtopic_rows=subtopic_rows, technique_rows=technique_rows)
    next_gaps = _next_gap_rows(subtopic_rows=subtopic_rows, technique_rows=technique_rows)
    return {
        "base_context": _base_context(
            selected_user=selected_user,
            can_select_user=can_select_user,
            has_completed=bool(summary["solved"]),
            has_tagged_statements=bool(summary["total"]),
        ),
        "gap_rows": gap_rows,
        "lemma_rows": lemma_rows,
        "main_topic_rows": _main_topic_rows(
            rows_by_layer.get(TechniqueProgressFact.Layer.MAIN_TOPIC, []),
            subtopic_rows=subtopic_rows,
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "next_gaps": next_gaps,
        "method_rows": method_rows,
        "object_rows": object_rows,
        "proof_role_rows": proof_role_rows,
        "stats": stats,
        "subtopic_rows": subtopic_rows,
        "technique_rows": technique_rows,
    }


def _subtopic_progress_rows(tagged_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for row in tagged_rows:
        status = str(row.get("normalization_status") or "").casefold()
        canonical_subtopic = str(row.get("canonical_subtopic") or "").strip()
        if status in SUBTOPIC_ALWAYS_SUPPRESSED_NORMALIZATION_STATUSES:
            continue
        if status in SUBTOPIC_EMPTY_CANONICAL_SUPPRESSED_NORMALIZATION_STATUSES and not canonical_subtopic:
            continue
        rows.append(row)
    return rows


def _technique_progress_rows(tagged_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for row in tagged_rows:
        status = str(row.get("normalization_status") or "").casefold()
        if status in TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES:
            continue
        rows.append(row)
    return rows


def _layer_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    layer_key: str,
    type_label: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    layer_rows: list[dict[str, object]] = []
    for row in tagged_rows:
        status = str(row.get("normalization_status") or "").casefold()
        if status in TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES:
            continue
        for layer_label in row.get(layer_key, []) or []:
            label = str(layer_label or "").strip()
            if not label:
                continue
            layer_rows.append({**row, "layer_label": label})
    return _aggregate_progress_rows(
        layer_rows,
        label_key="layer_label",
        type_label=type_label,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )


def _base_context(
    *,
    selected_user: User,
    can_select_user: bool,
    has_completed: bool = False,
    has_tagged_statements: bool = False,
) -> dict[str, object]:
    return {
        **technique_progress_catalog_status_context(),
        "technique_progress_all_gaps_url": _page_url(
            "pages:technique_progress_gaps",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_can_select_user": can_select_user,
        "technique_progress_dashboard_url": _page_url(
            "pages:technique_dashboard",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_filters": {
            "user": str(selected_user.pk) if can_select_user else "",
        },
        "technique_progress_has_completed": has_completed,
        "technique_progress_has_tagged_statements": has_tagged_statements,
        "technique_progress_quick_update_url": reverse("pages:completion_quick_update"),
        "technique_progress_selected_user": selected_user,
        "technique_progress_user_options": technique_progress_user_options() if can_select_user else [],
    }


def _gap_rows(
    *,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        [
            *[dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]],
            *[dict(row, type="Technique") for row in technique_rows if row["remaining"]],
        ],
        key=lambda row: (-int(row["remaining"]), str(row["label"]).casefold(), str(row["type"]).casefold()),
    )


def _next_gap_rows(
    *,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        [
            *[dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]],
            *[dict(row, type="Technique") for row in technique_rows if row["remaining"]],
        ],
        key=lambda row: (
            -int(row["remaining"]),
            0 if row["type"] == "Subtopic" else 1,
            str(row["label"]).casefold(),
        ),
    )[:NEXT_GAP_LIMIT]


def _gap_kind(raw_kind: str) -> str:
    normalized_kind = (raw_kind or "").strip().casefold()
    return normalized_kind if normalized_kind in GAP_KIND_CHOICES else GAP_KIND_SUBTOPICS


def _gap_topic(raw_topic: str) -> str:
    normalized_topic = (raw_topic or "").strip().casefold()
    return normalized_topic if normalized_topic in GAP_TOPIC_SLUGS else GAP_TOPIC_ALL


def _gap_min_total(raw_min_total: str) -> int:
    return _datatable_int(raw_min_total, default=0)


def _gap_canonical_subtopic(raw_canonical_subtopic: str) -> str:
    return str(raw_canonical_subtopic or "").strip()


def _rows_for_gap_kind(  # noqa: PLR0911, PLR0913
    *,
    gap_kind: str,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
    object_rows: list[dict[str, object]],
    method_rows: list[dict[str, object]],
    lemma_rows: list[dict[str, object]],
    proof_role_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    visible_subtopic_rows = [dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]]
    visible_technique_rows = [dict(row, type="Technique") for row in technique_rows if row["remaining"]]
    if gap_kind == GAP_KIND_TECHNIQUES:
        return visible_technique_rows
    if gap_kind == GAP_KIND_OBJECTS:
        return [dict(row, type="Object") for row in object_rows if row["remaining"]]
    if gap_kind == GAP_KIND_METHODS:
        return [dict(row, type="Method") for row in method_rows if row["remaining"]]
    if gap_kind == GAP_KIND_LEMMAS:
        return [dict(row, type="Lemma/Theorem") for row in lemma_rows if row["remaining"]]
    if gap_kind == GAP_KIND_PROOF_ROLES:
        return [dict(row, type="Proof role") for row in proof_role_rows if row["remaining"]]
    if gap_kind == GAP_KIND_ALL:
        subtopic_labels = {str(row["label"]).casefold() for row in visible_subtopic_rows}
        non_duplicate_technique_rows = [
            row
            for row in visible_technique_rows
            if str(row["label"]).casefold() not in subtopic_labels
        ]
        return [*visible_subtopic_rows, *non_duplicate_technique_rows]
    return visible_subtopic_rows


def _filter_gap_rows_by_topic(
    rows: list[dict[str, object]],
    *,
    gap_topic: str,
) -> list[dict[str, object]]:
    if gap_topic == GAP_TOPIC_ALL:
        return rows
    topic_label = GAP_TOPIC_SLUGS[gap_topic]
    return [
        row
        for row in rows
        if topic_label in row.get("main_topic_labels", [])
    ]


def _filter_gap_rows_by_canonical_subtopic(
    rows: list[dict[str, object]],
    *,
    gap_canonical_subtopic: str,
) -> list[dict[str, object]]:
    if not gap_canonical_subtopic:
        return rows
    normalized_canonical_subtopic = gap_canonical_subtopic.casefold()
    return [
        row
        for row in rows
        if normalized_canonical_subtopic
        in {str(label).casefold() for label in row.get("canonical_subtopic_labels", [])}
    ]


def _filtered_gap_rows(
    *,
    payload: dict[str, object],
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int,
    gap_canonical_subtopic: str,
) -> list[dict[str, object]]:
    gap_rows = _rows_for_gap_kind(
        gap_kind=gap_kind,
        subtopic_rows=payload["subtopic_rows"],
        technique_rows=payload["technique_rows"],
        object_rows=payload["object_rows"],
        method_rows=payload["method_rows"],
        lemma_rows=payload["lemma_rows"],
        proof_role_rows=payload["proof_role_rows"],
    )
    gap_rows = _filter_gap_rows_by_topic(gap_rows, gap_topic=gap_topic)
    gap_rows = _filter_gap_rows_by_canonical_subtopic(
        gap_rows,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    return _filter_gap_rows_by_min_total(gap_rows, gap_min_total=gap_min_total)


def _filter_gap_rows_by_min_total(
    rows: list[dict[str, object]],
    *,
    gap_min_total: int,
) -> list[dict[str, object]]:
    if gap_min_total <= 0:
        return rows
    return [
        row
        for row in rows
        if int(row.get("total", 0)) >= gap_min_total
    ]


def _gap_kind_options(  # noqa: PLR0913
    *,
    selected_user: User,
    can_select_user: bool,
    active_kind: str,
    active_topic: str,
    active_min_total: int,
    active_canonical_subtopic: str,
) -> list[dict[str, object]]:
    options = [
        {"label": "Subtopics", "value": GAP_KIND_SUBTOPICS},
        {"label": "Technique gaps", "value": GAP_KIND_TECHNIQUES},
        {"label": "Object gaps", "value": GAP_KIND_OBJECTS},
        {"label": "Method gaps", "value": GAP_KIND_METHODS},
        {"label": "Lemma/theorem gaps", "value": GAP_KIND_LEMMAS},
        {"label": "Proof-role gaps", "value": GAP_KIND_PROOF_ROLES},
        {"label": "All", "value": GAP_KIND_ALL},
    ]
    return [
        {
            **option,
            "is_active": option["value"] == active_kind,
            "url": _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=str(option["value"]),
                gap_topic=active_topic,
                gap_min_total=active_min_total,
                gap_canonical_subtopic=active_canonical_subtopic,
            ),
        }
        for option in options
    ]


def _gap_topic_tabs(  # noqa: PLR0913
    *,
    selected_user: User,
    can_select_user: bool,
    active_kind: str,
    active_topic: str,
    active_min_total: int,
    active_canonical_subtopic: str,
) -> list[dict[str, object]]:
    return [
        {
            "is_active": topic_slug == active_topic,
            "label": topic_label,
            "url": _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=active_kind,
                gap_topic=topic_slug,
                gap_min_total=active_min_total,
                gap_canonical_subtopic=active_canonical_subtopic,
            ),
            "value": topic_slug,
        }
        for topic_slug, topic_label in GAP_TOPIC_SLUGS.items()
    ]


def _gap_url(  # noqa: PLR0913
    *,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int = 0,
    gap_canonical_subtopic: str = "",
    extra_query: dict[str, str] | None = None,
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["user"] = str(selected_user.pk)
    query["kind"] = gap_kind
    query["topic"] = gap_topic
    if gap_min_total > 0:
        query["min_total"] = str(gap_min_total)
    if gap_canonical_subtopic:
        query["canonical_subtopic"] = gap_canonical_subtopic
    if extra_query:
        query.update(extra_query)
    return f"{reverse('pages:technique_progress_gaps')}?{urlencode(query)}"


def _gap_rows_with_drilldown_urls(
    rows: list[dict[str, object]],
    *,
    selected_user: User,
    can_select_user: bool,
    gap_topic: str,
) -> list[dict[str, object]]:
    enriched_rows = []
    for row in rows:
        enriched_row = dict(row)
        if row["type"] == "Subtopic" and row.get("canonical_subtopic"):
            enriched_row["drilldown_url"] = _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=GAP_KIND_TECHNIQUES,
                gap_topic=gap_topic,
                gap_canonical_subtopic=str(row["canonical_subtopic"]),
            )
        else:
            enriched_row["drilldown_url"] = ""
        enriched_rows.append(enriched_row)
    return enriched_rows


def _gap_pagination_suffix(
    *,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int = 0,
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["user"] = str(selected_user.pk)
    query["kind"] = gap_kind
    query["topic"] = gap_topic
    if gap_min_total > 0:
        query["min_total"] = str(gap_min_total)
    query_string = urlencode(query)
    return f"&{query_string}" if query_string else ""


def _gap_result_summary(rows: list[dict[str, object]], *, gap_kind: str) -> str:
    row_total = len(rows)
    noun = {
        GAP_KIND_SUBTOPICS: "subtopic gaps",
        GAP_KIND_TECHNIQUES: "technique gaps",
        GAP_KIND_OBJECTS: "object gaps",
        GAP_KIND_METHODS: "method gaps",
        GAP_KIND_LEMMAS: "lemma/theorem gaps",
        GAP_KIND_PROOF_ROLES: "proof-role gaps",
        GAP_KIND_ALL: "practice gaps",
    }[gap_kind]
    if not row_total:
        return f"Showing 0 of 0 {noun}"
    return f"Showing {row_total} {noun}"


def _gap_title(gap_kind: str) -> str:
    return {
        GAP_KIND_SUBTOPICS: "Subtopic practice gaps",
        GAP_KIND_TECHNIQUES: "Technique practice gaps",
        GAP_KIND_OBJECTS: "Object practice gaps",
        GAP_KIND_METHODS: "Method practice gaps",
        GAP_KIND_LEMMAS: "Lemma/theorem practice gaps",
        GAP_KIND_PROOF_ROLES: "Proof-role practice gaps",
        GAP_KIND_ALL: "All practice gaps",
    }[gap_kind]


def _gap_first_column_label(gap_kind: str) -> str:
    return {
        GAP_KIND_SUBTOPICS: "Canonical subtopic",
        GAP_KIND_TECHNIQUES: "Technique",
        GAP_KIND_OBJECTS: "Object",
        GAP_KIND_METHODS: "Method",
        GAP_KIND_LEMMAS: "Lemma/theorem",
        GAP_KIND_PROOF_ROLES: "Proof role",
        GAP_KIND_ALL: "Area",
    }[gap_kind]


def _datatable_int(raw_value: str | None, *, default: int = 0) -> int:
    try:
        value = int(raw_value or "")
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _search_gap_rows(
    rows: list[dict[str, object]],
    *,
    raw_search: str | None,
) -> list[dict[str, object]]:
    search_term = str(raw_search or "").strip().casefold()
    if not search_term:
        return rows
    return [
        row
        for row in rows
        if search_term in _gap_search_haystack(row)
    ]


def _gap_search_haystack(row: dict[str, object]) -> str:
    values = [
        row.get("canonical_subtopic", ""),
        row.get("canonical_subtopic_label", ""),
        row.get("label", ""),
        row.get("search_text", ""),
        row.get("type", ""),
        row.get("main_topic_label", ""),
        row.get("solved", ""),
        row.get("total", ""),
        row.get("remaining", ""),
        row.get("completion_percent", ""),
        f"{row.get('solved', '')} of {row.get('total', '')}",
    ]
    return " ".join(str(value) for value in values).casefold()


def _sort_gap_rows_for_datatable(
    rows: list[dict[str, object]],
    *,
    params: Mapping[str, str],
    gap_kind: str,
) -> list[dict[str, object]]:
    sort_field = _gap_datatable_sort_field(params, gap_kind=gap_kind)
    sort_direction = str(params.get("order[0][dir]") or "desc").casefold()
    sort_descending = sort_direction != "asc"
    sorted_rows = sorted(rows, key=lambda row: str(row.get("label", "")).casefold())
    return sorted(
        sorted_rows,
        key=lambda row: _gap_datatable_sort_value(row, sort_field),
        reverse=sort_descending,
    )


def _gap_datatable_sort_field(params: Mapping[str, str], *, gap_kind: str) -> str:
    default_column_index = 5 if gap_kind == GAP_KIND_ALL else 4
    column_index = _datatable_int(
        params.get("order[0][column]"),
        default=default_column_index,
    )
    requested_field = str(
        params.get(f"columns[{column_index}][data]")
        or params.get(f"columns[{column_index}][name]")
        or "",
    )
    if requested_field in GAP_DATATABLE_SORT_FIELDS:
        return requested_field
    return GAP_DATATABLE_DEFAULT_SORT_FIELD


def _gap_datatable_sort_value(row: dict[str, object], sort_field: str) -> object:
    if sort_field == "solved_total_label":
        return int(row.get("solved", 0))
    if sort_field in {"completion_percent", "remaining"}:
        return int(row.get(sort_field, 0))
    return str(row.get(sort_field, "")).casefold()


def _gap_datatable_row(row: dict[str, object]) -> dict[str, object]:
    solved = int(row["solved"])
    total = int(row["total"])
    return {
        "canonical_subtopic": row.get("canonical_subtopic", ""),
        "canonical_subtopic_label": row.get("canonical_subtopic_label", ""),
        "completion_percent": int(row["completion_percent"]),
        "coverage_label": f"{row['completion_percent']}%",
        "drilldown_url": row.get("drilldown_url", ""),
        "label": row["label"],
        "main_topic_label": row["main_topic_label"] or "-",
        "practice_url": row["practice_url"],
        "remaining": int(row["remaining"]),
        "solved": solved,
        "solved_total_label": f"{solved} of {total}",
        "total": total,
        "type": row["type"],
    }


def _gap_csv_row(row: dict[str, object]) -> dict[str, object]:
    solved = int(row["solved"])
    total = int(row["total"])
    return {
        "Area": row["label"],
        "Canonical Subtopic": row.get("canonical_subtopic_label", ""),
        "Type": row["type"],
        "Topic": row["main_topic_label"] or "-",
        "Completed": f"{solved} of {total}",
        "Remaining": int(row["remaining"]),
        "Coverage": f"{row['completion_percent']}%",
        "Practice URL": row["practice_url"],
    }


def _tagged_statement_rows(*, user: User) -> list[dict[str, object]]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .only(
            "id",
            "linked_problem_id",
            "topic",
            "contest_year",
            "contest_name",
            "problem_number",
            "problem_code",
            "linked_problem__id",
            "linked_problem__topic",
        )
        .order_by("-contest_year", "contest_name", "problem_number", "problem_code", "id"),
    )
    if not statements:
        return []

    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    statement_tags = _statement_tags_by_statement_id(statement_ids)
    linked_tags = _problem_tags_by_record_id(linked_problem_ids)
    completion_by_statement_id = _completion_by_statement_id(
        statements=statements,
        user=user,
    )

    rows = []
    seen_statement_labels: set[tuple[int, str]] = set()
    for statement in statements:
        tags = statement_tags.get(statement.id) or linked_tags.get(statement.linked_problem_id, [])
        if not tags:
            continue
        completion = completion_by_statement_id.get(statement.id)
        is_solved = completion is not None and is_completion_status_solved(completion.status)
        fallback_topic = display_topic_label(effective_topic(statement)) if effective_topic(statement) else ""
        for tag in tags:
            technique = str(tag["technique"] or "").strip()
            if not technique:
                continue
            canonical_subtopic = str(tag.get("canonical_subtopic") or "").strip()
            dedupe_key = (statement.id, technique.casefold())
            if dedupe_key in seen_statement_labels:
                continue
            seen_statement_labels.add(dedupe_key)
            main_topic = str(tag.get("main_topic") or "").strip()
            topic_labels = _topic_labels_for_domains(
                tag.get("domains") or [],
                fallback_topic=fallback_topic,
                main_topic=main_topic,
            )
            display_main_topic = (
                display_topic_label(main_topic)
                if main_topic
                else (topic_labels[0] if topic_labels else fallback_topic)
            )
            rows.append(
                {
                    "is_solved": is_solved,
                    "canonical_subtopic": canonical_subtopic,
                    "domain_topic_labels": topic_labels,
                    "domains": list(tag.get("domains") or []),
                    "main_topic": display_main_topic,
                    "normalization_status": str(tag.get("normalization_status") or "").strip(),
                    "object_tags": list(tag.get("object_tags") or []),
                    "technique_tags": list(tag.get("technique_tags") or []),
                    "lemma_theorem_tags": list(tag.get("lemma_theorem_tags") or []),
                    "proof_roles": list(tag.get("proof_roles") or []),
                    "statement_id": statement.id,
                    "subtopic": canonical_subtopic,
                    "technique": technique,
                },
            )
    return rows


def _statement_tags_by_statement_id(statement_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_statement_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    for tag_row in (
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values(
            "statement_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "normalization_status",
            *TOPIC_TAG_LAYER_FIELDS,
        )
        .order_by("technique", "statement_id", "id")
    ):
        statement_id = int(tag_row["statement_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (statement_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_statement_id[statement_id].append(tag_row)
    return tags_by_statement_id


def _problem_tags_by_record_id(record_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_record_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    if not record_ids:
        return tags_by_record_id
    for tag_row in (
        ProblemTopicTechnique.objects.filter(record_id__in=record_ids)
        .values(
            "record_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "normalization_status",
            *TOPIC_TAG_LAYER_FIELDS,
        )
        .order_by("technique", "record_id", "id")
    ):
        record_id = int(tag_row["record_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (record_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_record_id[record_id].append(tag_row)
    return tags_by_record_id


def _completion_by_statement_id(
    *,
    statements: list[ContestProblemStatement],
    user: User,
) -> dict[int, UserProblemCompletion]:
    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    completion_by_statement_id = {
        completion.statement_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.statement_id is not None
    }
    if not linked_problem_ids:
        return completion_by_statement_id

    legacy_completion_by_problem_id = {
        completion.problem_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            problem_id__in=linked_problem_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.problem_id is not None
    }
    for statement in statements:
        if statement.id in completion_by_statement_id:
            continue
        if statement.linked_problem_id in legacy_completion_by_problem_id:
            completion_by_statement_id[statement.id] = legacy_completion_by_problem_id[statement.linked_problem_id]
    return completion_by_statement_id


def _aggregate_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    label_key: str,
    type_label: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for tagged_row in tagged_rows:
        label = str(tagged_row[label_key] or "").strip()
        if not label:
            continue
        bucket = buckets.setdefault(
            label,
            {
                "canonical_subtopics": set(),
                "label": label,
                "main_topics": set(),
                "object_tags": set(),
                "technique_tags": set(),
                "lemma_theorem_tags": set(),
                "proof_roles": set(),
                "search_terms": set(),
                "solved_statement_ids": set(),
                "statement_ids": set(),
                "type": type_label,
            },
        )
        bucket["statement_ids"].add(tagged_row["statement_id"])
        if tagged_row["is_solved"]:
            bucket["solved_statement_ids"].add(tagged_row["statement_id"])
        _add_progress_row_metadata(bucket=bucket, tagged_row=tagged_row)

    rows = []
    for bucket in buckets.values():
        statement_ids = bucket["statement_ids"]
        solved_statement_ids = bucket["solved_statement_ids"]
        total = len(statement_ids)
        solved = len(solved_statement_ids)
        remaining = total - solved
        label = str(bucket["label"])
        main_topics = sorted(bucket["main_topics"])
        canonical_subtopics = sorted(bucket["canonical_subtopics"])
        canonical_subtopic, canonical_subtopic_label = _canonical_subtopic_display_values(
            type_label=type_label,
            label=label,
            canonical_subtopics=canonical_subtopics,
        )
        rows.append(
            {
                "canonical_subtopic": canonical_subtopic,
                "canonical_subtopic_label": canonical_subtopic_label,
                "canonical_subtopic_labels": canonical_subtopics,
                "completion_percent": _percent(solved, total),
                "label": label,
                "main_topic_labels": main_topics,
                "main_topic_label": ", ".join(main_topics),
                "object_tags": sorted(bucket["object_tags"], key=str.casefold),
                "practice_url": _practice_url(
                    label,
                    layer_kind=GAP_KIND_BY_TYPE_LABEL.get(type_label, GAP_KIND_TECHNIQUES),
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                ),
                "lemma_theorem_tags": sorted(bucket["lemma_theorem_tags"], key=str.casefold),
                "remaining": remaining,
                "search_text": " ".join(sorted(bucket["search_terms"])),
                "solved": solved,
                "proof_roles": sorted(bucket["proof_roles"], key=str.casefold),
                "technique_tags": sorted(bucket["technique_tags"], key=str.casefold),
                "total": total,
                "type": bucket["type"],
            },
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["remaining"]) == 0,
            -int(row["remaining"]),
            str(row["label"]).casefold(),
        ),
    )


def _add_progress_row_metadata(
    *,
    bucket: dict[str, object],
    tagged_row: dict[str, object],
) -> None:
    canonical_subtopic = str(tagged_row.get("canonical_subtopic") or "").strip()
    if canonical_subtopic:
        bucket["canonical_subtopics"].add(canonical_subtopic)
        bucket["search_terms"].add(canonical_subtopic)
    for raw_canonical_subtopic in tagged_row.get("canonical_subtopic_labels", []) or []:
        canonical_subtopic_label = str(raw_canonical_subtopic or "").strip()
        if canonical_subtopic_label:
            bucket["canonical_subtopics"].add(canonical_subtopic_label)
            bucket["search_terms"].add(canonical_subtopic_label)

    technique = str(tagged_row.get("technique") or "").strip()
    if technique:
        bucket["search_terms"].add(technique)
    search_text = str(tagged_row.get("search_text") or "").strip()
    if search_text:
        bucket["search_terms"].add(search_text)
    for layer_field in TOPIC_TAG_LAYER_FIELDS:
        for raw_layer_label in tagged_row.get(layer_field, []) or []:
            layer_label = str(raw_layer_label or "").strip()
            if layer_label:
                bucket[layer_field].add(layer_label)
                bucket["search_terms"].add(layer_label)

    for raw_topic_label in [
        *(tagged_row.get("domain_topic_labels", []) or []),
        *(tagged_row.get("main_topic_labels", []) or []),
    ]:
        topic_label = str(raw_topic_label or "").strip()
        if topic_label:
            bucket["main_topics"].add(topic_label)


def _canonical_subtopic_display_values(
    *,
    type_label: str,
    label: str,
    canonical_subtopics: list[str],
) -> tuple[str, str]:
    if type_label == "Subtopic":
        return label, label
    if len(canonical_subtopics) == 1:
        return canonical_subtopics[0], canonical_subtopics[0]
    return "", ", ".join(canonical_subtopics)


def _main_topic_rows(
    tagged_rows: list[dict[str, object]],
    *,
    subtopic_rows: list[dict[str, object]],
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    topics_with_data = {str(row.get("label") or "") for row in tagged_rows}
    topic_labels = [
        *MAIN_TOPIC_ORDER,
        *sorted(topics_with_data - set(MAIN_TOPIC_ORDER) - {OTHER_TOPIC_LABEL}),
    ]
    if OTHER_TOPIC_LABEL in topics_with_data:
        topic_labels.append(OTHER_TOPIC_LABEL)

    rows = []
    for topic_label in topic_labels:
        topic_rows = [
            row
            for row in tagged_rows
            if row.get("label") == topic_label
        ]
        summary = _summary_from_tagged_rows(topic_rows)
        topic_subtopic_rows = [
            row
            for row in subtopic_rows
            if topic_label in row.get("main_topic_labels", [])
        ]
        rows.append(
            {
                "completion_percent": summary["completion_percent"],
                "incomplete_subtopic_total": sum(1 for row in topic_subtopic_rows if row["remaining"]),
                "label": topic_label,
                "remaining": summary["remaining"],
                "slug": _topic_slug(topic_label),
                "solved": summary["solved"],
                "subtopic_total": len(topic_subtopic_rows),
                "topic_detail_url": _page_url(
                    "pages:technique_progress_topic_detail",
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                    kwargs={"topic_slug": _topic_slug(topic_label)},
                ),
                "total": summary["total"],
            },
        )
    return rows


def _summary_from_tagged_rows(tagged_rows: list[dict[str, object]]) -> dict[str, int]:
    statement_ids = {row["statement_id"] for row in tagged_rows}
    solved_statement_ids = {
        row["statement_id"]
        for row in tagged_rows
        if row["is_solved"]
    }
    total = len(statement_ids)
    solved = len(solved_statement_ids)
    remaining = total - solved
    return {
        "completion_percent": _percent(solved, total),
        "remaining": remaining,
        "solved": solved,
        "total": total,
    }


def _main_topic_label(row: dict[str, object]) -> str:
    label = str(row.get("main_topic") or "").strip()
    return label if label in MAIN_TOPIC_ORDER else OTHER_TOPIC_LABEL


def _topic_labels_for_domains(
    domains: list[str],
    *,
    fallback_topic: str,
    main_topic: str,
) -> list[str]:
    labels: list[str] = []
    for domain in domains or []:
        label = display_topic_label(str(domain or "").strip())
        if label and label not in labels:
            labels.append(label)
    if main_topic:
        main_topic_label = display_topic_label(main_topic)
        if main_topic_label and main_topic_label not in labels:
            labels.insert(0, main_topic_label)
    if not labels and fallback_topic:
        labels.append(fallback_topic)
    return labels


def _topic_slug(label: str) -> str:
    return label.casefold().replace(" ", "-")


def _page_url(
    route_name: str,
    *,
    selected_user: User,
    can_select_user: bool,
    kwargs: dict[str, str] | None = None,
) -> str:
    base_url = reverse(route_name, kwargs=kwargs)
    if not can_select_user:
        return base_url
    return f"{base_url}?{urlencode({'user': str(selected_user.pk)})}"


def _practice_url(
    label: str,
    *,
    layer_kind: str,
    selected_user: User,
    can_select_user: bool,
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["target_user_id"] = str(selected_user.pk)
    query["layer_kind"] = layer_kind
    query["layer_tag"] = label
    return f"{reverse('pages:completion_quick_update')}?{urlencode(query)}"


def _percent(numerator: int, denominator: int) -> int:
    if not denominator:
        return 0
    return round((numerator / denominator) * 100)
