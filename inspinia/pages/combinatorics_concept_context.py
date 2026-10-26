"""Resolve reviewed polysemous labels from their original tag, never co-occurrence."""

import json
from collections import defaultdict
from itertools import islice

from django.db import connection
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.technique_concepts import COMBINATORICS_CONCEPTS

TAG_LAYER_FIELDS = {"object": "object_tags", "method": "technique_tags", "lemma": "lemma_theorem_tags"}
COMB_CODES = {"c", "comb", "combinatorics"}
SUPPRESSED = {"invalid", "corrupt", "metadata"}
RULES = [
    {**rule, "concept_id": cid}
    for cid, definition in COMBINATORICS_CONCEPTS.items()
    for rule in definition["contextual_aliases"]
]
CONTEXT_MEMBERS = {(rule["kind"], rule["label"].casefold()) for rule in RULES}
RULES_BY_SOURCE = defaultdict(list)
for _rule in RULES:
    RULES_BY_SOURCE[(_rule["technique"].casefold(), _rule["family"].casefold())].append(_rule)


def _is_comb_tag(tag: dict, fallback: str) -> bool:
    topics = [tag["main_topic"], *(tag["domains"] or [])]
    topics = [str(value).strip().casefold() for value in topics if value]
    return bool(COMB_CODES.intersection(topics or [str(fallback).strip().casefold()]))


def _collect_tag_contexts(target: dict, tag: dict, *, fallback: str) -> None:
    if str(tag["normalization_status"]).casefold() in SUPPRESSED or not _is_comb_tag(tag, fallback):
        return
    rules = RULES_BY_SOURCE.get(
        (tag["technique"].strip().casefold(), tag["canonical_subtopic"].strip().casefold()),
        (),
    )
    for rule in rules:
        values = [tag["technique"]] if rule["kind"] == "technique" else tag[TAG_LAYER_FIELDS[rule["kind"]]]
        if rule["label"].casefold() in {str(value).strip().casefold() for value in values or []}:
            target[(rule["kind"], rule["label"].casefold())].add((rule["concept_id"], tag["canonical_subtopic"]))


def _source_contexts(targets: dict) -> dict:
    fields = (
        "technique",
        "canonical_subtopic",
        "main_topic",
        "domains",
        "normalization_status",
        *TAG_LAYER_FIELDS.values(),
    )
    by_statement = defaultdict(lambda: defaultdict(set))
    has_statement_tags = set()
    seen = set()
    for tag in (
        StatementTopicTechnique.objects.filter(statement_id__in=targets)
        .order_by("technique", "id")
        .values(
            "statement_id",
            "statement__topic",
            "statement__linked_problem__topic",
            *fields,
        )
        .iterator(chunk_size=1000)
    ):
        sid = tag["statement_id"]
        has_statement_tags.add(sid)
        pair = (sid, tag["technique"].casefold())
        if pair not in seen:
            seen.add(pair)
            _collect_tag_contexts(
                by_statement[sid],
                tag,
                fallback=tag["statement__topic"] or tag["statement__linked_problem__topic"],
            )
    fallback_statements = defaultdict(list)
    for sid, problem_id in targets.items():
        if sid not in has_statement_tags and problem_id is not None:
            fallback_statements[problem_id].append(sid)
    if fallback_statements:
        fallback_topics = {
            row["pk"]: row["topic"] or row["linked_problem__topic"]
            for row in ContestProblemStatement.objects.filter(
                pk__in=[sid for ids in fallback_statements.values() for sid in ids],
            ).values("pk", "topic", "linked_problem__topic")
        }
        seen.clear()
        for tag in (
            ProblemTopicTechnique.objects.filter(record_id__in=fallback_statements)
            .order_by("technique", "id")
            .values(
                "record_id",
                *fields,
            )
            .iterator(chunk_size=1000)
        ):
            pair = (tag["record_id"], tag["technique"].casefold())
            if pair in seen:
                continue
            seen.add(pair)
            for sid in fallback_statements[tag["record_id"]]:
                _collect_tag_contexts(by_statement[sid], tag, fallback=fallback_topics[sid])
    return by_statement


def annotate_combinatorics_context(facts: list[dict]) -> list[dict]:
    """Attach read-only context in batched reads, preserving statement precedence."""
    targets = {
        fact["statement_id"]: fact.get("linked_problem_id")
        for fact in facts
        if (fact["layer"], str(fact["label"]).strip().casefold()) in CONTEXT_MEMBERS
        and "Combinatorics" in {fact.get("main_topic", ""), *(fact.get("main_topic_labels") or [])}
    }
    if not targets:
        return facts
    by_statement = _source_contexts(targets)
    for fact in facts:
        if fact["statement_id"] in targets:
            matches = by_statement[fact["statement_id"]].get(
                (fact["layer"], str(fact["label"]).strip().casefold()),
                (),
            )
            fact["_comb_context_ids"] = tuple(sorted({cid for cid, _family in matches}))
            fact["_comb_context_families"] = {
                cid: {family for matched_id, family in matches if matched_id == cid}
                for cid in fact["_comb_context_ids"]
            }
    return facts


def iter_combinatorics_context(facts):
    """Keep subtopic previews streamed while batching context reads."""
    source = iter(facts)
    while batch := list(islice(source, 1000)):
        yield from annotate_combinatorics_context(batch)


def _json_member(field: str, label: str) -> Q:
    # A complete JSON string literal matches one list member, not a substring
    # of a longer caption. Both backends retain exact punctuation and domains.
    literal = json.dumps(label, ensure_ascii=connection.vendor != "postgresql")
    return Q(**{f"{field}__icontains": literal})


def _comb_topic(prefix: str) -> Q:
    return (
        Q(**{f"{prefix}__iexact": "C"})
        | Q(**{f"{prefix}__iexact": "COMB"})
        | Q(**{f"{prefix}__iexact": "Combinatorics"})
    )


def _explicit_comb_tag_scope() -> Q:
    scope = _comb_topic("main_topic")
    for code in ("C", "COMB", "COMBINATORICS"):
        scope |= _json_member("domains", code)
    return scope


def _comb_tag_scope(parent: str) -> Q:
    scope = _explicit_comb_tag_scope()
    fallback = _comb_topic(f"{parent}__topic")
    if parent == "statement":
        fallback |= Q(statement__topic="") & _comb_topic("statement__linked_problem__topic")
    return scope | (Q(main_topic="", domains=[]) & fallback)


def contextual_fact_filter(concept_id: str) -> Q:
    """Use correlated source-tag existence with the same rules as streamed gaps."""
    rules = COMBINATORICS_CONCEPTS.get(concept_id, {}).get("contextual_aliases", ())
    by_member = defaultdict(list)
    for rule in rules:
        by_member[(rule["kind"], rule["label"])].append(rule)
    query = Q(pk__in=[])
    any_statement_tags = StatementTopicTechnique.objects.filter(statement_id=OuterRef("statement_id"))
    for (kind, label), member_rules in by_member.items():
        source = Q(pk__in=[])
        for rule in member_rules:
            source |= Q(technique__iexact=rule["technique"], canonical_subtopic__iexact=rule["family"])
        source &= ~Q(normalization_status__in=SUPPRESSED)
        source &= Q(technique__iexact=label) if kind == "technique" else _json_member(TAG_LAYER_FIELDS[kind], label)
        statement_tags = StatementTopicTechnique.objects.filter(
            source & _comb_tag_scope("statement"),
            statement_id=OuterRef("statement_id"),
        )
        problem_tags = ProblemTopicTechnique.objects.filter(
            source & _explicit_comb_tag_scope(),
            record_id=OuterRef("linked_problem_id"),
        )
        blank_problem_tags = ProblemTopicTechnique.objects.filter(
            source,
            main_topic="",
            domains=[],
            record_id=OuterRef("linked_problem_id"),
        )
        fallback_topic = _comb_topic("statement__topic") | (
            Q(statement__topic="") & _comb_topic("statement__linked_problem__topic")
        )
        problem_match = Q(Exists(problem_tags)) | (fallback_topic & Q(Exists(blank_problem_tags)))
        query |= Q(layer=kind, label__iexact=label) & (
            Q(Exists(statement_tags)) | (~Q(Exists(any_statement_tags)) & problem_match)
        )
    return query
