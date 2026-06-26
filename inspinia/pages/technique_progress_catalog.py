from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count
from django.utils import timezone

from inspinia.pages.models import TOPIC_TAG_LAYER_FIELDS
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressCatalogState
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label

if TYPE_CHECKING:
    from collections.abc import Iterable

MAIN_TOPIC_ORDER = ["Algebra", "Number Theory", "Geometry", "Combinatorics"]
OTHER_TOPIC_LABEL = "Other"
SUBTOPIC_ALWAYS_SUPPRESSED_NORMALIZATION_STATUSES = {"corrupt", "invalid", "metadata"}
SUBTOPIC_EMPTY_CANONICAL_SUPPRESSED_NORMALIZATION_STATUSES = {"lemma", "method", "needs_review"}
TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES = {"corrupt", "invalid", "metadata"}
LAYER_TAG_FIELDS = {
    TechniqueProgressFact.Layer.OBJECT: "object_tags",
    TechniqueProgressFact.Layer.METHOD: "technique_tags",
    TechniqueProgressFact.Layer.LEMMA: "lemma_theorem_tags",
    TechniqueProgressFact.Layer.PROOF_ROLE: "proof_roles",
}


def rebuild_technique_progress_catalog(
    *,
    statement_ids: Iterable[int] | None = None,
    problem_ids: Iterable[int] | None = None,
) -> int:
    """Refresh all facts, or the union of targeted statements and linked problems."""
    requested_statement_ids = _clean_int_set(statement_ids)
    requested_problem_ids = _clean_int_set(problem_ids)
    is_full_refresh = not requested_statement_ids and not requested_problem_ids

    try:
        if is_full_refresh:
            TechniqueProgressFact.objects.all().delete()
            target_statement_ids = list(
                ContestProblemStatement.objects.filter(is_active=True)
                .order_by("id")
                .values_list("id", flat=True),
            )
        else:
            linked_statement_ids = set()
            if requested_problem_ids:
                linked_statement_ids = set(
                    ContestProblemStatement.objects.filter(linked_problem_id__in=requested_problem_ids)
                    .order_by("id")
                    .values_list("id", flat=True),
                )
            target_statement_ids = sorted(requested_statement_ids | linked_statement_ids)

        refreshed_count = 0
        for statement_id in target_statement_ids:
            refreshed_count += sync_technique_progress_facts_for_statement(statement_id)

        _mark_catalog_refreshed(full_refresh=is_full_refresh)
    except Exception as exc:
        _mark_catalog_error(str(exc))
        raise

    return refreshed_count


def sync_technique_progress_facts_for_statement(statement_id: int) -> int:
    statement = (
        ContestProblemStatement.objects.select_related("linked_problem")
        .only(
            "id",
            "linked_problem_id",
            "topic",
            "linked_problem__id",
            "linked_problem__topic",
            "is_active",
        )
        .filter(pk=statement_id)
        .first()
    )
    TechniqueProgressFact.objects.filter(statement_id=statement_id).delete()
    if statement is None or not statement.is_active:
        return 0

    facts = _facts_for_statement(statement)
    if not facts:
        return 0

    TechniqueProgressFact.objects.bulk_create(facts)
    return len(facts)


def queue_technique_progress_catalog_refresh(
    *,
    statement_ids: Iterable[int] | None = None,
    problem_ids: Iterable[int] | None = None,
) -> None:
    requested_statement_ids = tuple(sorted(_clean_int_set(statement_ids)))
    requested_problem_ids = tuple(sorted(_clean_int_set(problem_ids)))
    if not requested_statement_ids and not requested_problem_ids:
        return

    _mark_catalog_stale()


def request_technique_progress_catalog_rebuild() -> None:
    _mark_catalog_stale()


def technique_progress_catalog_needs_rebuild() -> bool:
    state = TechniqueProgressCatalogState.objects.filter(singleton_key=1).first()
    if state is None:
        return True
    return state.last_refreshed_at is None or state.needs_rebuild or bool(state.last_error)


def technique_progress_catalog_status_context() -> dict[str, object]:
    state = _catalog_state()
    return {
        "technique_progress_catalog_fact_count": state.fact_count,
        "technique_progress_catalog_is_current": (
            state.last_refreshed_at is not None
            and not state.needs_rebuild
            and not state.last_error
        ),
        "technique_progress_catalog_last_error": state.last_error,
        "technique_progress_catalog_last_refreshed_at": state.last_refreshed_at,
        "technique_progress_catalog_needs_rebuild": state.needs_rebuild,
    }


def _facts_for_statement(statement: ContestProblemStatement) -> list[TechniqueProgressFact]:
    tag_rows = _effective_tag_rows(statement)
    if not tag_rows:
        return []

    fallback_topic = display_topic_label(effective_topic(statement)) if effective_topic(statement) else ""
    buckets: dict[tuple[str, str], dict[str, object]] = {}
    for tag in tag_rows:
        technique = str(tag.get("technique") or "").strip()
        if not technique:
            continue

        canonical_subtopic = str(tag.get("canonical_subtopic") or "").strip()
        main_topic = str(tag.get("main_topic") or "").strip()
        topic_labels = _topic_labels_for_domains(
            list(tag.get("domains") or []),
            fallback_topic=fallback_topic,
            main_topic=main_topic,
        )
        display_main_topic = (
            display_topic_label(main_topic)
            if main_topic
            else (topic_labels[0] if topic_labels else fallback_topic)
        )
        main_topic_label = _main_topic_bucket_label(display_main_topic)
        search_terms = {
            technique,
            canonical_subtopic,
            main_topic_label,
            *topic_labels,
        }
        canonical_subtopics = [canonical_subtopic] if canonical_subtopic else []
        main_topics = _dedupe_preserve_order([main_topic_label, *topic_labels])

        _add_fact_bucket(
            buckets,
            layer=TechniqueProgressFact.Layer.MAIN_TOPIC,
            label=main_topic_label,
            canonical_subtopics=canonical_subtopics,
            main_topics=main_topics,
            search_terms=search_terms,
        )

        normalization_status = str(tag.get("normalization_status") or "").strip().casefold()
        if normalization_status not in TECHNIQUE_SUPPRESSED_NORMALIZATION_STATUSES:
            _add_fact_bucket(
                buckets,
                layer=TechniqueProgressFact.Layer.TECHNIQUE,
                label=technique,
                canonical_subtopics=canonical_subtopics,
                main_topics=main_topics,
                search_terms=search_terms,
            )
            for layer, tag_field in LAYER_TAG_FIELDS.items():
                for raw_label in tag.get(tag_field, []) or []:
                    layer_label = str(raw_label or "").strip()
                    if not layer_label:
                        continue
                    _add_fact_bucket(
                        buckets,
                        layer=layer,
                        label=layer_label,
                        canonical_subtopics=canonical_subtopics,
                        main_topics=main_topics,
                        search_terms={*search_terms, layer_label},
                    )

        if _include_subtopic_fact(
            normalization_status=normalization_status,
            canonical_subtopic=canonical_subtopic,
        ):
            _add_fact_bucket(
                buckets,
                layer=TechniqueProgressFact.Layer.SUBTOPIC,
                label=canonical_subtopic,
                canonical_subtopics=canonical_subtopics,
                main_topics=main_topics,
                search_terms=search_terms,
            )

    return [
        _fact_from_bucket(statement=statement, bucket=bucket)
        for bucket in buckets.values()
    ]


def _effective_tag_rows(statement: ContestProblemStatement) -> list[dict[str, object]]:
    statement_tags = _statement_tag_rows(statement.id)
    if statement_tags:
        return statement_tags
    if statement.linked_problem_id is None:
        return []
    return _problem_tag_rows(statement.linked_problem_id)


def _statement_tag_rows(statement_id: int) -> list[dict[str, object]]:
    rows = []
    seen: set[str] = set()
    for tag_row in (
        StatementTopicTechnique.objects.filter(statement_id=statement_id)
        .values(
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "normalization_status",
            *TOPIC_TAG_LAYER_FIELDS,
        )
        .order_by("technique", "id")
    ):
        technique_key = str(tag_row["technique"] or "").casefold()
        if technique_key in seen:
            continue
        seen.add(technique_key)
        rows.append(tag_row)
    return rows


def _problem_tag_rows(record_id: int) -> list[dict[str, object]]:
    rows = []
    seen: set[str] = set()
    for tag_row in (
        ProblemTopicTechnique.objects.filter(record_id=record_id)
        .values(
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "normalization_status",
            *TOPIC_TAG_LAYER_FIELDS,
        )
        .order_by("technique", "id")
    ):
        technique_key = str(tag_row["technique"] or "").casefold()
        if technique_key in seen:
            continue
        seen.add(technique_key)
        rows.append(tag_row)
    return rows


def _add_fact_bucket(  # noqa: PLR0913
    buckets: dict[tuple[str, str], dict[str, object]],
    *,
    layer: str,
    label: str,
    canonical_subtopics: list[str],
    main_topics: list[str],
    search_terms: set[str],
) -> None:
    clean_label = str(label or "").strip()
    if not clean_label:
        return

    label_key = clean_label.casefold()
    bucket = buckets.setdefault(
        (layer, label_key),
        {
            "canonical_subtopics": set(),
            "label": clean_label,
            "label_key": label_key,
            "layer": layer,
            "main_topics": set(),
            "search_terms": set(),
        },
    )
    bucket["canonical_subtopics"].update(value for value in canonical_subtopics if value)
    bucket["main_topics"].update(value for value in main_topics if value)
    bucket["search_terms"].update(value for value in search_terms if value)


def _fact_from_bucket(
    *,
    statement: ContestProblemStatement,
    bucket: dict[str, object],
) -> TechniqueProgressFact:
    layer = str(bucket["layer"])
    label = str(bucket["label"])
    canonical_subtopic_labels = sorted(bucket["canonical_subtopics"])
    main_topic_labels = sorted(
        bucket["main_topics"],
        key=lambda value: (
            MAIN_TOPIC_ORDER.index(value) if value in MAIN_TOPIC_ORDER else len(MAIN_TOPIC_ORDER),
            value.casefold(),
        ),
    )
    canonical_subtopic = label if layer == TechniqueProgressFact.Layer.SUBTOPIC else ""
    if not canonical_subtopic and len(canonical_subtopic_labels) == 1:
        canonical_subtopic = canonical_subtopic_labels[0]
    main_topic = label if layer == TechniqueProgressFact.Layer.MAIN_TOPIC else ""
    if not main_topic and len(main_topic_labels) == 1:
        main_topic = main_topic_labels[0]
    search_text = " ".join(sorted(bucket["search_terms"], key=str.casefold))

    return TechniqueProgressFact(
        statement=statement,
        linked_problem_id=statement.linked_problem_id,
        layer=layer,
        label=label,
        label_key=str(bucket["label_key"]),
        canonical_subtopic=canonical_subtopic,
        canonical_subtopic_labels=canonical_subtopic_labels,
        main_topic=main_topic,
        main_topic_labels=main_topic_labels,
        search_text=search_text,
    )


def _include_subtopic_fact(
    *,
    normalization_status: str,
    canonical_subtopic: str,
) -> bool:
    if normalization_status in SUBTOPIC_ALWAYS_SUPPRESSED_NORMALIZATION_STATUSES:
        return False
    if normalization_status in SUBTOPIC_EMPTY_CANONICAL_SUPPRESSED_NORMALIZATION_STATUSES and not canonical_subtopic:
        return False
    return bool(canonical_subtopic)


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


def _main_topic_bucket_label(label: str) -> str:
    return label if label in MAIN_TOPIC_ORDER else OTHER_TOPIC_LABEL


def _clean_int_set(values: Iterable[int] | None) -> set[int]:
    return {int(value) for value in values or [] if value is not None}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped_values = []
    seen_values: set[str] = set()
    for value in values:
        clean_value = str(value or "").strip()
        if not clean_value:
            continue
        seen_key = clean_value.casefold()
        if seen_key in seen_values:
            continue
        seen_values.add(seen_key)
        deduped_values.append(clean_value)
    return deduped_values


def _catalog_state() -> TechniqueProgressCatalogState:
    state, _ = TechniqueProgressCatalogState.objects.get_or_create(singleton_key=1)
    return state


def _mark_catalog_stale() -> None:
    state = _catalog_state()
    update_fields = {"updated_at"}
    if not state.needs_rebuild:
        state.needs_rebuild = True
        update_fields.add("needs_rebuild")
    if state.last_error:
        state.last_error = ""
        update_fields.add("last_error")
    if len(update_fields) == 1:
        return
    state.save(update_fields=update_fields)


def _mark_catalog_refreshed(*, full_refresh: bool) -> None:
    state = _catalog_state()
    state.last_refreshed_at = timezone.now()
    if full_refresh:
        state.needs_rebuild = False
    state.fact_count = TechniqueProgressFact.objects.aggregate(total=Count("id"))["total"] or 0
    state.last_error = ""
    state.save(
        update_fields={
            "fact_count",
            "last_error",
            "last_refreshed_at",
            "needs_rebuild",
            "updated_at",
        },
    )


def _mark_catalog_error(message: str) -> None:
    state = _catalog_state()
    state.needs_rebuild = True
    state.last_error = message
    state.save(update_fields={"last_error", "needs_rebuild", "updated_at"})
