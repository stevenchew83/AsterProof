"""Resolve caption context from the same authoritative source tag for counts and practice."""

import json
from collections import defaultdict
from itertools import islice

from django.db import connection
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q

from inspinia.pages.concept_alias_policy import CONTEXT_BINDINGS
from inspinia.pages.concept_alias_policy import ROLE_FIELDS
from inspinia.pages.concept_alias_policy import SUBJECT_CODES
from inspinia.pages.concept_alias_policy import caption_key
from inspinia.pages.concept_alias_policy import resolve_binding
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique

BY_MEMBER = defaultdict(list)
for _binding in CONTEXT_BINDINGS:
    BY_MEMBER[(_binding["kind"], caption_key(_binding["caption"]))].append(_binding)
SOURCE_FIELDS = (
    "technique", "canonical_subtopic", "main_topic", "domains", "normalization_status",
    "object_tags", "technique_tags", "lemma_theorem_tags", "proof_roles",
)


def _collect(target: dict, tag: dict, fallback: str) -> None:
    if caption_key(tag["normalization_status"]) in {"invalid", "corrupt", "metadata"}:
        return
    for (kind, label), bindings in BY_MEMBER.items():
        values = tag[ROLE_FIELDS[kind]]
        values = values if isinstance(values, list) else [values]
        if label not in {caption_key(value) for value in values}:
            continue
        for binding in bindings:
            decision = resolve_binding(binding, source=tag, fallback_topic=fallback)
            for cid in decision.concept_ids:
                target[(kind, label, binding["subject"])].add((cid, tag["canonical_subtopic"]))


def _source_contexts(targets: dict) -> dict:
    by_statement = defaultdict(lambda: defaultdict(set))
    has_statement_tags = set()
    seen = set()
    statement_tags = StatementTopicTechnique.objects.filter(statement_id__in=targets).order_by("technique", "id")
    for tag in statement_tags.values(
        "statement_id", "statement__topic", "statement__linked_problem__topic", *SOURCE_FIELDS,
    ).iterator(chunk_size=1000):
        sid = tag["statement_id"]
        has_statement_tags.add(sid)
        pair = (sid, str(tag["technique"]).casefold())
        if pair not in seen:
            seen.add(pair)
            _collect(by_statement[sid], tag, tag["statement__topic"] or tag["statement__linked_problem__topic"])
    fallback = defaultdict(list)
    for sid, problem_id in targets.items():
        if sid not in has_statement_tags and problem_id is not None:
            fallback[problem_id].append(sid)
    if fallback:
        topics = {
            row["id"]: row["topic"] or row["linked_problem__topic"]
            for row in ContestProblemStatement.objects.filter(
                id__in=[sid for ids in fallback.values() for sid in ids],
            ).values("id", "topic", "linked_problem__topic")
        }
        seen.clear()
        for tag in ProblemTopicTechnique.objects.filter(record_id__in=fallback).order_by("technique", "id").values(
            "record_id", *SOURCE_FIELDS,
        ).iterator(chunk_size=1000):
            pair = (tag["record_id"], str(tag["technique"]).casefold())
            if pair in seen:
                continue
            seen.add(pair)
            for sid in fallback[tag["record_id"]]:
                _collect(by_statement[sid], tag, topics[sid])
    return by_statement


def annotate_alias_context(facts: list[dict], *, canonical_subtopic: str = "") -> list[dict]:
    targets = {
        fact["statement_id"]: fact.get("linked_problem_id")
        for fact in facts if (fact["layer"], caption_key(fact["label"])) in BY_MEMBER
    }
    if not targets:
        return facts
    sources = _source_contexts(targets)
    for fact in facts:
        if fact["statement_id"] not in targets:
            continue
        member = (fact["layer"], caption_key(fact["label"]))
        by_subject = {}
        families = defaultdict(set)
        for binding in BY_MEMBER.get(member, ()):
            matches = sources[fact["statement_id"]].get((*member, binding["subject"]), ())
            if canonical_subtopic:
                matches = [
                    (cid, family) for cid, family in matches
                    if caption_key(family) == caption_key(canonical_subtopic)
                ]
            by_subject[binding["subject"]] = tuple(sorted({cid for cid, _family in matches}))
            for cid, family in matches:
                families[cid].add(family)
        fact["_alias_context_ids"] = by_subject
        fact["_alias_context_families"] = dict(families)
    return facts


def iter_alias_context(facts):
    source = iter(facts)
    while batch := list(islice(source, 1000)):
        yield from annotate_alias_context(batch)


def _member(field: str, caption: str) -> Q:
    literal = json.dumps(caption, ensure_ascii=connection.vendor != "postgresql")
    return Q(**{f"{field}__icontains": literal})


def _topic(field: str, subject: str) -> Q:
    query = Q(pk__in=[])
    for code in SUBJECT_CODES[subject]:
        query |= Q(**{f"{field}__iexact": code})
    return query


def _explicit_scope(subject: str) -> Q:
    query = _topic("main_topic", subject)
    for code in SUBJECT_CODES[subject]:
        query |= _member("domains", code)
    return query


def _source_match(binding: dict, rule: dict) -> Q:
    query = Q(technique__iexact=rule["technique"], canonical_subtopic__iexact=rule["family"])
    for status in ("invalid", "corrupt", "metadata"):
        query &= ~Q(normalization_status__iexact=status)
    field = ROLE_FIELDS[binding["kind"]]
    query &= _member(field, binding["caption"]) if field.endswith("_tags") or field == "proof_roles" else Q(
        **{f"{field}__iexact": binding["caption"]},
    )
    for field, required in rule.get("requires", {}).items():
        for caption in required:
            query &= _member(field, caption) if field.endswith("_tags") or field == "proof_roles" else Q(
                **{f"{field}__iexact": caption},
            )
    return query


def contextual_fact_filter(concept_id: str) -> Q:
    """Correlate source rows exactly; a neighboring tag cannot supply evidence."""
    result = Q(pk__in=[])
    any_statement = StatementTopicTechnique.objects.filter(statement_id=OuterRef("statement_id"))
    for binding in CONTEXT_BINDINGS:
        rules = [r for r in binding["context_rules"] if r["concept_id"] == concept_id]
        if not rules:
            continue
        subject = binding["subject"]
        source = Q(pk__in=[])
        for rule in rules:
            source |= _source_match(binding, rule)
        for other in binding["context_rules"]:
            if other["concept_id"] != concept_id:
                source &= ~_source_match(binding, other)
        fallback = _topic("statement__topic", subject) | (
            Q(statement__topic="") & _topic("statement__linked_problem__topic", subject)
        )
        explicit = _explicit_scope(subject)
        statement_tags = StatementTopicTechnique.objects.filter(
            source & (explicit | (Q(main_topic="", domains=[]) & fallback)),
            statement_id=OuterRef("statement_id"),
        )
        problem_tags = ProblemTopicTechnique.objects.filter(
            source & explicit, record_id=OuterRef("linked_problem_id"),
        )
        blank_problem_tags = ProblemTopicTechnique.objects.filter(
            source, main_topic="", domains=[], record_id=OuterRef("linked_problem_id"),
        )
        problem_match = Q(Exists(problem_tags)) | (fallback & Q(Exists(blank_problem_tags)))
        layer = "subtopic" if binding["kind"] == "canonical_subtopic" else binding["kind"]
        result |= Q(layer=layer, label__iexact=binding["caption"]) & (
            Q(Exists(statement_tags)) | (~Q(Exists(any_statement)) & problem_match)
        )
    return result
