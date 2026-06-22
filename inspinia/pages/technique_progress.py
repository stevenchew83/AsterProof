from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.core.cache import cache
from django.db import connection
from django.db.models import Count
from django.db.models import F
from django.db.models import Max
from django.db.models import Q
from django.db.models import QuerySet
from django.http import HttpResponse
from django.urls import reverse

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.models import TOPIC_TAG_LAYER_FIELDS
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressCatalogState
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.technique_progress_catalog import technique_progress_catalog_status_context
from inspinia.pages.topic_labels import display_topic_label
from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping

NEXT_GAP_LIMIT = 6
SUBTOPIC_LAYER_PREVIEW_LIMIT = 3
GAP_PAGE_SIZE = 50
GAP_CACHE_TIMEOUT_SECONDS = 15 * 60
GAP_CACHE_VERSION = "v1"
GAP_CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
GAP_CSV_FIELDNAMES = [
    "Area",
    "Canonical Subtopic",
    "Type",
    "Topic",
    "Completed",
    "Avg MOHS",
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
GAP_DATATABLE_DEFAULT_SORT_FIELD = "remaining"
GAP_DATATABLE_SORT_FIELDS = {
    "canonical_subtopic",
    "canonical_subtopic_label",
    "average_solved_mohs",
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
LAYER_GAP_KIND_CONFIG = {
    GAP_KIND_OBJECTS: {
        "fact_layer": TechniqueProgressFact.Layer.OBJECT,
        "label": "Object tags",
        "layer_key": "object_tags",
        "noun": "object gaps",
        "type": "Object",
    },
    GAP_KIND_METHODS: {
        "fact_layer": TechniqueProgressFact.Layer.METHOD,
        "label": "Technique tags",
        "layer_key": "technique_tags",
        "noun": "technique-tag gaps",
        "type": "Technique",
    },
    GAP_KIND_LEMMAS: {
        "fact_layer": TechniqueProgressFact.Layer.LEMMA,
        "label": "Lemma/Theorem tags",
        "layer_key": "lemma_theorem_tags",
        "noun": "lemma/theorem gaps",
        "type": "Lemma/Theorem",
    },
    GAP_KIND_PROOF_ROLES: {
        "fact_layer": TechniqueProgressFact.Layer.PROOF_ROLE,
        "label": "Proof roles",
        "layer_key": "proof_roles",
        "noun": "proof-role gaps",
        "type": "Proof role",
    },
}
LAYER_GAP_KINDS = tuple(LAYER_GAP_KIND_CONFIG)


def _filter_progress_fact_queryset(
    queryset: QuerySet[TechniqueProgressFact],
    *,
    gap_topic: str,
    gap_canonical_subtopic: str,
) -> QuerySet[TechniqueProgressFact]:
    if gap_topic != GAP_TOPIC_ALL:
        topic_label = GAP_TOPIC_SLUGS[gap_topic]
        queryset = queryset.filter(Q(main_topic=topic_label) | Q(main_topic_labels__contains=[topic_label]))
    if gap_canonical_subtopic:
        queryset = queryset.filter(
            Q(canonical_subtopic__iexact=gap_canonical_subtopic)
            | Q(canonical_subtopic_labels__contains=[gap_canonical_subtopic]),
        )
    return queryset


def _filter_fact_rows_by_topic(
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
        if _fact_row_has_topic(row, topic_label=topic_label)
    ]


def _fact_row_has_topic(row: dict[str, object], *, topic_label: str) -> bool:
    if str(row.get("main_topic") or "") == topic_label:
        return True
    return topic_label in [str(label) for label in row.get("main_topic_labels", []) or []]


def _filter_fact_rows_by_canonical_subtopic(
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
        if _fact_row_has_canonical_subtopic(
            row,
            normalized_canonical_subtopic=normalized_canonical_subtopic,
        )
    ]


def _fact_row_has_canonical_subtopic(
    row: dict[str, object],
    *,
    normalized_canonical_subtopic: str,
) -> bool:
    if str(row.get("canonical_subtopic") or "").casefold() == normalized_canonical_subtopic:
        return True
    return normalized_canonical_subtopic in {
        str(label).casefold()
        for label in row.get("canonical_subtopic_labels", []) or []
    }


def _layers_for_gap_kind(gap_kind: str) -> set[str]:
    layer_sets = {
        GAP_KIND_TECHNIQUES: {TechniqueProgressFact.Layer.TECHNIQUE},
        GAP_KIND_OBJECTS: {str(LAYER_GAP_KIND_CONFIG[GAP_KIND_OBJECTS]["fact_layer"])},
        GAP_KIND_METHODS: {str(LAYER_GAP_KIND_CONFIG[GAP_KIND_METHODS]["fact_layer"])},
        GAP_KIND_LEMMAS: {str(LAYER_GAP_KIND_CONFIG[GAP_KIND_LEMMAS]["fact_layer"])},
        GAP_KIND_PROOF_ROLES: {str(LAYER_GAP_KIND_CONFIG[GAP_KIND_PROOF_ROLES]["fact_layer"])},
        GAP_KIND_ALL: {
            str(LAYER_GAP_KIND_CONFIG[layer_kind]["fact_layer"])
            for layer_kind in LAYER_GAP_KINDS
        },
    }
    return layer_sets.get(gap_kind, {TechniqueProgressFact.Layer.SUBTOPIC})


def _progress_fact_rows(
    *,
    user: User,
    layers: set[str],
    include_layer_metadata: bool = False,
    gap_topic: str = GAP_TOPIC_ALL,
    gap_canonical_subtopic: str = "",
) -> list[dict[str, object]]:
    fact_queryset = TechniqueProgressFact.objects.filter(layer__in=layers)
    if connection.vendor == "postgresql":
        fact_queryset = _filter_progress_fact_queryset(
            fact_queryset,
            gap_topic=gap_topic,
            gap_canonical_subtopic=gap_canonical_subtopic,
        )
    fact_rows = list(
        fact_queryset
        .values(
            "canonical_subtopic",
            "canonical_subtopic_labels",
            "label",
            "layer",
            "linked_problem_id",
            "linked_problem__mohs",
            "main_topic",
            "main_topic_labels",
            "search_text",
            "statement_id",
            "statement__mohs",
        )
        .order_by("layer", "label", "statement_id", "id"),
    )
    fact_rows = _filter_fact_rows_by_topic(fact_rows, gap_topic=gap_topic)
    fact_rows = _filter_fact_rows_by_canonical_subtopic(
        fact_rows,
        gap_canonical_subtopic=gap_canonical_subtopic,
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
        completion_status = completion_by_statement_id.get(statement_id)
        is_solved = completion_status is not None and is_completion_status_solved(completion_status)
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
                "mohs": _fact_effective_mohs(fact),
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


def _fact_effective_mohs(fact: dict[str, object]) -> int | None:
    for value in [fact.get("statement__mohs"), fact.get("linked_problem__mohs")]:
        if value is not None:
            return int(value)
    return None


def _completion_by_catalog_statement_id(
    *,
    statement_problem_ids: dict[int, int | None],
    user: User,
) -> dict[int, str]:
    statement_ids = sorted(statement_problem_ids)
    completion_by_statement_id = {
        int(row["statement_id"]): str(row["status"])
        for row in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        )
        .order_by()
        .values("statement_id", "problem_id", "status")
        if row["statement_id"] is not None
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
        int(row["problem_id"]): str(row["status"])
        for row in UserProblemCompletion.objects.filter(
            user=user,
            problem_id__in=linked_problem_ids,
        )
        .order_by()
        .values("statement_id", "problem_id", "status")
        if row["problem_id"] is not None
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
    (
        selected_user,
        can_select_user,
        gap_kind,
        gap_topic,
        gap_min_total,
        gap_canonical_subtopic,
    ) = _resolve_gap_request(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_kind=raw_kind,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
    )
    base_context = _base_context(
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    is_drilldown = bool(gap_canonical_subtopic)
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
        "technique_progress_gap_rows_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_min_total=gap_min_total,
            gap_canonical_subtopic=gap_canonical_subtopic,
            extra_query={"format": "datatable"},
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
        "technique_progress_gap_first_column_label": _gap_first_column_label(
            gap_kind,
            is_drilldown=is_drilldown,
        ),
        "technique_progress_gap_is_drilldown": is_drilldown,
        "technique_progress_gap_min_total": gap_min_total,
        "technique_progress_gap_min_total_reset_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_canonical_subtopic=gap_canonical_subtopic,
        ),
        "technique_progress_gap_result_summary": _gap_loading_summary(gap_kind=gap_kind),
        "technique_progress_gap_show_canonical_subtopic_column": (
            gap_kind in {GAP_KIND_TECHNIQUES, GAP_KIND_ALL} and not is_drilldown
        ),
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
    _gap_kind, gap_rows = _gap_rows_for_request(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_kind=raw_kind,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
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
    gap_kind, gap_rows = _gap_rows_for_request(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_kind=raw_kind,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
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


def _resolve_gap_request(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str,
    raw_kind: str,
    raw_topic: str,
    raw_min_total: str,
    raw_canonical_subtopic: str,
) -> tuple[User, bool, str, str, int, str]:
    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    return (
        selected_user,
        can_select_user,
        _gap_kind(raw_kind),
        _gap_topic(raw_topic),
        _gap_min_total(raw_min_total),
        _gap_canonical_subtopic(raw_canonical_subtopic),
    )


def _gap_rows_for_request(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str,
    raw_kind: str,
    raw_topic: str,
    raw_min_total: str,
    raw_canonical_subtopic: str,
) -> tuple[str, list[dict[str, object]]]:
    (
        selected_user,
        can_select_user,
        gap_kind,
        gap_topic,
        gap_min_total,
        gap_canonical_subtopic,
    ) = _resolve_gap_request(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_kind=raw_kind,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
    )
    return (
        gap_kind,
        _cached_filtered_gap_rows(
            request_user=request_user,
            raw_user_id=raw_user_id,
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_min_total=gap_min_total,
            gap_canonical_subtopic=gap_canonical_subtopic,
        ),
    )


def _cached_filtered_gap_rows(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int,
    gap_canonical_subtopic: str,
) -> list[dict[str, object]]:
    cache_key = _gap_rows_cache_key(
        selected_user=selected_user,
        can_select_user=can_select_user,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    cached_rows = cache.get(cache_key)
    if cached_rows is not None:
        return cached_rows

    payload = _build_progress_payload(
        request_user=request_user,
        raw_user_id=raw_user_id,
        required_layers=_layers_for_gap_kind(gap_kind),
        include_user_options=False,
        gap_topic=gap_topic,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
    cache.set(cache_key, gap_rows, GAP_CACHE_TIMEOUT_SECONDS)
    return gap_rows


def _gap_rows_cache_key(  # noqa: PLR0913
    *,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int,
    gap_canonical_subtopic: str,
) -> str:
    key_payload = "|".join(
        [
            GAP_CACHE_VERSION,
            f"user={selected_user.pk}",
            f"can_select_user={int(can_select_user)}",
            f"kind={gap_kind}",
            f"topic={gap_topic}",
            f"canonical_subtopic={gap_canonical_subtopic}",
            f"min_total={gap_min_total}",
            f"catalog={_catalog_cache_marker()}",
            f"completion={_completion_cache_marker(selected_user)}",
        ],
    )
    digest = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()
    return f"technique-gaps:{GAP_CACHE_VERSION}:{digest}"


def _catalog_cache_marker() -> str:
    catalog_state = (
        TechniqueProgressCatalogState.objects.only("updated_at", "fact_count", "needs_rebuild")
        .filter(singleton_key=1)
        .first()
    )
    if catalog_state is None:
        return "missing"
    updated_at = catalog_state.updated_at.isoformat() if catalog_state.updated_at else ""
    return f"{updated_at}:{catalog_state.fact_count}:{int(catalog_state.needs_rebuild)}"


def _completion_cache_marker(user: User) -> str:
    marker = UserProblemCompletion.objects.filter(user=user).aggregate(
        completion_count=Count("id"),
        latest_updated_at=Max("updated_at"),
    )
    latest_updated_at = marker["latest_updated_at"]
    latest_marker = latest_updated_at.isoformat() if latest_updated_at else ""
    return f"{marker['completion_count'] or 0}:{latest_marker}"


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
    topic_subtopic_rows = _rows_with_layer_practice_urls(
        topic_subtopic_rows,
        layer_kind=GAP_KIND_SUBTOPICS,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    topic_layer_rows = _all_layer_progress_rows(
        topic_tagged_rows,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    topic_subtopic_rows = _subtopic_rows_with_layer_previews(
        topic_subtopic_rows,
        layer_rows=topic_layer_rows,
        selected_user=selected_user,
        can_select_user=can_select_user,
        topic_slug=topic_slug,
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


def _build_progress_payload(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str,
    required_layers: set[str],
    include_user_options: bool = True,
    gap_topic: str = GAP_TOPIC_ALL,
    gap_canonical_subtopic: str = "",
) -> dict[str, object]:
    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _progress_fact_rows(
        user=selected_user,
        layers=required_layers,
        gap_topic=gap_topic,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )
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
    technique_rows = _rows_with_layer_practice_urls(
        technique_rows,
        layer_kind=GAP_KIND_TECHNIQUES,
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
    subtopic_rows = _rows_with_layer_practice_urls(
        subtopic_rows,
        layer_kind=GAP_KIND_SUBTOPICS,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    layer_rows_by_kind = {
        layer_kind: _fact_layer_progress_rows(
            rows_by_layer=rows_by_layer,
            layer_kind=layer_kind,
            selected_user=selected_user,
            can_select_user=can_select_user,
        )
        for layer_kind in LAYER_GAP_KINDS
    }
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
            include_user_options=include_user_options,
        ),
        "gap_rows": gap_rows,
        "lemma_rows": layer_rows_by_kind[GAP_KIND_LEMMAS],
        "main_topic_rows": _main_topic_rows(
            rows_by_layer.get(TechniqueProgressFact.Layer.MAIN_TOPIC, []),
            subtopic_rows=subtopic_rows,
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "next_gaps": next_gaps,
        "method_rows": layer_rows_by_kind[GAP_KIND_METHODS],
        "object_rows": layer_rows_by_kind[GAP_KIND_OBJECTS],
        "proof_role_rows": layer_rows_by_kind[GAP_KIND_PROOF_ROLES],
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


def _fact_layer_progress_rows(
    *,
    rows_by_layer: dict[str, list[dict[str, object]]],
    layer_kind: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    layer_config = LAYER_GAP_KIND_CONFIG[layer_kind]
    rows = _aggregate_progress_rows(
        rows_by_layer.get(str(layer_config["fact_layer"]), []),
        label_key="label",
        type_label=str(layer_config["type"]),
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    return _rows_with_layer_practice_urls(
        rows,
        layer_kind=layer_kind,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )


def _layer_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    layer_kind: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    layer_config = LAYER_GAP_KIND_CONFIG[layer_kind]
    layer_rows: list[dict[str, object]] = []
    for row in tagged_rows:
        status = str(row.get("normalization_status") or "").casefold()
        if status in TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES:
            continue
        for layer_label in row.get(str(layer_config["layer_key"]), []) or []:
            label = str(layer_label or "").strip()
            if not label:
                continue
            layer_rows.append({**row, "layer_label": label})
    rows = _aggregate_progress_rows(
        layer_rows,
        label_key="layer_label",
        type_label=str(layer_config["type"]),
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    return _rows_with_layer_practice_urls(
        rows,
        layer_kind=layer_kind,
        selected_user=selected_user,
        can_select_user=can_select_user,
    )


def _rows_with_layer_practice_urls(
    rows: list[dict[str, object]],
    *,
    layer_kind: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    return [
        {
            **row,
            "layer_kind": layer_kind,
            "practice_url": _practice_url(
                "",
                selected_user=selected_user,
                can_select_user=can_select_user,
                layer_kind=layer_kind,
                layer_tag=str(row["label"]),
            ),
        }
        for row in rows
    ]


def _all_layer_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for layer_kind in LAYER_GAP_KINDS:
        rows.extend(
            _layer_progress_rows(
                tagged_rows,
                layer_kind=layer_kind,
                selected_user=selected_user,
                can_select_user=can_select_user,
            ),
        )
    return _sort_gap_rows_by_priority(rows)


def _base_context(
    *,
    selected_user: User,
    can_select_user: bool,
    has_completed: bool = False,
    has_tagged_statements: bool = False,
    include_user_options: bool = True,
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
        "technique_progress_user_options": (
            technique_progress_user_options() if can_select_user and include_user_options else []
        ),
    }


def _subtopic_rows_with_layer_previews(
    subtopic_rows: list[dict[str, object]],
    *,
    layer_rows: list[dict[str, object]],
    selected_user: User,
    can_select_user: bool,
    topic_slug: str,
) -> list[dict[str, object]]:
    layer_rows_by_subtopic: dict[str, list[dict[str, object]]] = defaultdict(list)
    for layer_row in layer_rows:
        if not int(layer_row.get("remaining", 0)):
            continue
        for canonical_subtopic in layer_row.get("canonical_subtopic_labels", []) or []:
            label = str(canonical_subtopic or "").strip()
            if label:
                layer_rows_by_subtopic[label].append(layer_row)

    enriched_rows = []
    for row in subtopic_rows:
        canonical_subtopic = str(row.get("canonical_subtopic") or row.get("label") or "").strip()
        preview_rows = _sort_gap_rows_by_priority(layer_rows_by_subtopic.get(canonical_subtopic, []))
        enriched_rows.append(
            {
                **row,
                "drilldown_url": _gap_url(
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                    gap_kind=GAP_KIND_ALL,
                    gap_topic=topic_slug,
                    gap_canonical_subtopic=canonical_subtopic,
                ),
                "layer_gap_preview": [
                    {
                        "label": preview_row["label"],
                        "remaining": int(preview_row["remaining"]),
                        "type": preview_row["type"],
                    }
                    for preview_row in preview_rows[:SUBTOPIC_LAYER_PREVIEW_LIMIT]
                ],
                "layer_gap_preview_overflow": max(
                    len(preview_rows) - SUBTOPIC_LAYER_PREVIEW_LIMIT,
                    0,
                ),
            },
        )
    return enriched_rows


def _sort_gap_rows_by_priority(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("remaining", 0)) == 0,
            -int(row.get("remaining", 0)),
            str(row.get("label", "")).casefold(),
            str(row.get("type", "")).casefold(),
        ),
    )


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
        return [dict(row, type="Technique") for row in method_rows if row["remaining"]]
    if gap_kind == GAP_KIND_LEMMAS:
        return [dict(row, type="Lemma/Theorem") for row in lemma_rows if row["remaining"]]
    if gap_kind == GAP_KIND_PROOF_ROLES:
        return [dict(row, type="Proof role") for row in proof_role_rows if row["remaining"]]
    if gap_kind == GAP_KIND_ALL:
        return _sort_gap_rows_by_priority(
            [
                *[dict(row, type="Object") for row in object_rows if row["remaining"]],
                *[dict(row, type="Technique") for row in method_rows if row["remaining"]],
                *[dict(row, type="Lemma/Theorem") for row in lemma_rows if row["remaining"]],
                *[dict(row, type="Proof role") for row in proof_role_rows if row["remaining"]],
            ],
        )
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
    gap_rows = _filter_gap_rows_by_min_total(gap_rows, gap_min_total=gap_min_total)
    return _gap_rows_with_urls(
        gap_rows,
        selected_user=payload["base_context"]["technique_progress_selected_user"],
        can_select_user=bool(payload["base_context"]["technique_progress_can_select_user"]),
        gap_topic=gap_topic,
        gap_canonical_subtopic=gap_canonical_subtopic,
    )


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
    layer_options = [
        {"label": "All", "value": GAP_KIND_ALL},
        *[
            {"label": str(LAYER_GAP_KIND_CONFIG[layer_kind]["label"]), "value": layer_kind}
            for layer_kind in LAYER_GAP_KINDS
        ],
    ]
    if active_canonical_subtopic:
        options = layer_options
    else:
        options = [
            {"label": "Subtopics", "value": GAP_KIND_SUBTOPICS},
            {"label": "Technique gaps", "value": GAP_KIND_TECHNIQUES},
            *layer_options[1:],
            layer_options[0],
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


def _gap_rows_with_urls(
    rows: list[dict[str, object]],
    *,
    selected_user: User,
    can_select_user: bool,
    gap_topic: str,
    gap_canonical_subtopic: str,
) -> list[dict[str, object]]:
    enriched_rows = []
    for row in rows:
        enriched_row = dict(row)
        if row["type"] == "Subtopic" and row.get("canonical_subtopic"):
            enriched_row["drilldown_url"] = _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=GAP_KIND_ALL,
                gap_topic=gap_topic,
                gap_canonical_subtopic=str(row["canonical_subtopic"]),
            )
        else:
            enriched_row["drilldown_url"] = ""
        layer_kind = str(row.get("layer_kind") or "")
        if layer_kind:
            enriched_row["practice_url"] = _practice_url(
                "",
                selected_user=selected_user,
                can_select_user=can_select_user,
                layer_kind=layer_kind,
                layer_tag=str(row["label"]),
            )
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
        GAP_KIND_OBJECTS: LAYER_GAP_KIND_CONFIG[GAP_KIND_OBJECTS]["noun"],
        GAP_KIND_METHODS: LAYER_GAP_KIND_CONFIG[GAP_KIND_METHODS]["noun"],
        GAP_KIND_LEMMAS: LAYER_GAP_KIND_CONFIG[GAP_KIND_LEMMAS]["noun"],
        GAP_KIND_PROOF_ROLES: LAYER_GAP_KIND_CONFIG[GAP_KIND_PROOF_ROLES]["noun"],
        GAP_KIND_ALL: "layer-tag gaps",
    }[gap_kind]
    if not row_total:
        return f"Showing 0 of 0 {noun}"
    return f"Showing {row_total} {noun}"


def _gap_loading_summary(*, gap_kind: str) -> str:
    noun = {
        GAP_KIND_SUBTOPICS: "subtopic gaps",
        GAP_KIND_TECHNIQUES: "technique gaps",
        GAP_KIND_OBJECTS: "object gaps",
        GAP_KIND_METHODS: "method gaps",
        GAP_KIND_LEMMAS: "lemma/theorem gaps",
        GAP_KIND_PROOF_ROLES: "proof-role gaps",
        GAP_KIND_ALL: "practice gaps",
    }[gap_kind]
    return f"Loading {noun}"


def _gap_title(gap_kind: str) -> str:
    return {
        GAP_KIND_SUBTOPICS: "Subtopic practice gaps",
        GAP_KIND_TECHNIQUES: "Technique practice gaps",
        GAP_KIND_OBJECTS: "Object tag practice gaps",
        GAP_KIND_METHODS: "Technique tag practice gaps",
        GAP_KIND_LEMMAS: "Lemma/theorem practice gaps",
        GAP_KIND_PROOF_ROLES: "Proof-role practice gaps",
        GAP_KIND_ALL: "All practice gaps",
    }[gap_kind]


def _gap_first_column_label(gap_kind: str, *, is_drilldown: bool) -> str:
    if gap_kind == GAP_KIND_ALL:
        return "Gap"
    if is_drilldown and gap_kind in LAYER_GAP_KINDS:
        return "Tag"
    return {
        GAP_KIND_SUBTOPICS: "Canonical subtopic",
        GAP_KIND_TECHNIQUES: "Technique",
        GAP_KIND_OBJECTS: "Object",
        GAP_KIND_METHODS: "Technique tag",
        GAP_KIND_LEMMAS: "Lemma/theorem",
        GAP_KIND_PROOF_ROLES: "Proof role",
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
        row.get("average_solved_mohs", ""),
        row.get("average_solved_mohs_label", ""),
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
    return sorted(
        rows,
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
    if sort_field == "average_solved_mohs":
        value = row.get("average_solved_mohs")
        return float(value) if value is not None else -1
    if sort_field in {"completion_percent", "remaining"}:
        return int(row.get(sort_field, 0))
    return str(row.get(sort_field, "")).casefold()


def _gap_datatable_row(row: dict[str, object]) -> dict[str, object]:
    solved = int(row["solved"])
    total = int(row["total"])
    return {
        "average_solved_mohs": row.get("average_solved_mohs"),
        "average_solved_mohs_label": row.get("average_solved_mohs_label", "-"),
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
        "Avg MOHS": row.get("average_solved_mohs_label", "-"),
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
                "solved_mohs_by_statement_id": {},
                "solved_statement_ids": set(),
                "statement_ids": set(),
                "type": type_label,
            },
        )
        bucket["statement_ids"].add(tagged_row["statement_id"])
        if tagged_row["is_solved"]:
            statement_id = tagged_row["statement_id"]
            bucket["solved_statement_ids"].add(statement_id)
            mohs = tagged_row.get("mohs")
            if mohs is not None:
                bucket["solved_mohs_by_statement_id"][statement_id] = int(mohs)
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
        average_solved_mohs = _average_mohs(bucket["solved_mohs_by_statement_id"].values())
        rows.append(
            {
                "average_solved_mohs": average_solved_mohs,
                "average_solved_mohs_label": _average_mohs_label(average_solved_mohs),
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


def _average_mohs(mohs_values: Iterable[int]) -> float | None:
    values = [int(value) for value in mohs_values]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _average_mohs_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _add_progress_row_metadata(
    *,
    bucket: dict[str, object],
    tagged_row: dict[str, object],
) -> None:
    _add_bucket_value(
        bucket=bucket,
        field_name="canonical_subtopics",
        raw_value=tagged_row.get("canonical_subtopic"),
        include_search=True,
    )
    for raw_canonical_subtopic in tagged_row.get("canonical_subtopic_labels", []) or []:
        _add_bucket_value(
            bucket=bucket,
            field_name="canonical_subtopics",
            raw_value=raw_canonical_subtopic,
            include_search=True,
        )

    _add_bucket_search_term(bucket=bucket, raw_value=tagged_row.get("technique"))
    _add_bucket_search_term(bucket=bucket, raw_value=tagged_row.get("search_text"))
    for layer_field in TOPIC_TAG_LAYER_FIELDS:
        for raw_layer_label in tagged_row.get(layer_field, []) or []:
            _add_bucket_value(
                bucket=bucket,
                field_name=layer_field,
                raw_value=raw_layer_label,
                include_search=True,
            )

    for raw_topic_label in [
        *(tagged_row.get("domain_topic_labels", []) or []),
        *(tagged_row.get("main_topic_labels", []) or []),
    ]:
        _add_bucket_value(
            bucket=bucket,
            field_name="main_topics",
            raw_value=raw_topic_label,
        )


def _add_bucket_value(
    *,
    bucket: dict[str, object],
    field_name: str,
    raw_value: object,
    include_search: bool = False,
) -> None:
    value = str(raw_value or "").strip()
    if not value:
        return
    bucket[field_name].add(value)
    if include_search:
        bucket["search_terms"].add(value)


def _add_bucket_search_term(
    *,
    bucket: dict[str, object],
    raw_value: object,
) -> None:
    value = str(raw_value or "").strip()
    if value:
        bucket["search_terms"].add(value)


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
    selected_user: User,
    can_select_user: bool,
    layer_kind: str = "",
    layer_tag: str = "",
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["target_user_id"] = str(selected_user.pk)
    if layer_kind and layer_tag:
        query["layer_kind"] = layer_kind
        query["layer_tag"] = layer_tag
    elif label:
        query["subtopics"] = label
    return f"{reverse('pages:completion_quick_update')}?{urlencode(query)}"


def _percent(numerator: int, denominator: int) -> int:
    if not denominator:
        return 0
    return round((numerator / denominator) * 100)
