"""Read-only library coverage from authoritative source tags and the concept registry."""

import json
import re
from collections import Counter
from collections import defaultdict
from functools import lru_cache

from django.db import connection
from django.db.models import CharField
from django.db.models import Exists
from django.db.models import ExpressionWrapper
from django.db.models import OuterRef
from django.db.models import Q

from inspinia.pages.combinatorics_concept_context import RULES_BY_SOURCE
from inspinia.pages.concept_alias_policy import CONTEXT_BINDINGS
from inspinia.pages.concept_alias_policy import ROLE_FIELDS
from inspinia.pages.concept_alias_policy import SUBJECT_CODES
from inspinia.pages.concept_alias_policy import alias_resolution
from inspinia.pages.concept_alias_policy import caption_key
from inspinia.pages.concept_alias_policy import source_subjects
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.pages.technique_concepts import concept_for

SUPPRESSED = {"invalid", "corrupt", "metadata"}
TAG_FIELDS = (
    "technique",
    "canonical_subtopic",
    "main_topic",
    "domains",
    "normalization_status",
    "object_tags",
    "technique_tags",
    "lemma_theorem_tags",
    "proof_roles",
)


def _values(tag: dict, kind: str) -> list | tuple:
    value = tag.get(ROLE_FIELDS[kind]) or []
    return value if isinstance(value, (list, tuple)) else [value]


def _resolve_member(tag: dict, kind: str, caption: str, topic: str) -> set[str]:
    ids = set()
    for subject in source_subjects(tag, topic):
        decision = alias_resolution(subject, kind, caption, source=tag, fallback_topic=topic)
        if decision is not None:
            ids.update(decision.concept_ids)
        elif cid := concept_for(kind, caption, topic=subject):
            ids.add(cid)
        elif subject == "Combinatorics":
            rules = RULES_BY_SOURCE.get((caption_key(tag["technique"]), caption_key(tag["canonical_subtopic"])), ())
            ids.update(
                r["concept_id"] for r in rules if r["kind"] == kind and caption_key(r["label"]) == caption_key(caption)
            )
    return ids


def _tag_coverage(tag: dict, topic: str, roles: dict, review: dict) -> None:
    matched = False
    for kind in ROLE_FIELDS:
        for caption in _values(tag, kind):
            if not caption:
                continue
            ids = _resolve_member(tag, kind, caption, topic)
            matched |= bool(ids)
            for cid in ids:
                roles[cid].add(kind)
            held_alias = any(
                alias_resolution(subject, kind, caption) is not None for subject in source_subjects(tag, topic)
            )
            if not ids and (kind in {"object", "method", "lemma"} or held_alias):
                review[caption].add(kind)
    if not matched or caption_key(tag["normalization_status"]) == "needs_review":
        review[tag["technique"]].add("technique")


class TagCoverageResolver:
    """Resolve repeated source tags once, with a bounded cache owned by one request."""

    def __init__(self):
        self._resolve = lru_cache(maxsize=2048)(self._resolve_signature)

    @staticmethod
    def _resolve_signature(topic, signature):
        roles, review = defaultdict(set), defaultdict(set)
        _tag_coverage(dict(zip(TAG_FIELDS, signature, strict=True)), topic, roles, review)
        return tuple((cid, tuple(kinds)) for cid, kinds in roles.items()), tuple(
            (caption, tuple(kinds)) for caption, kinds in review.items()
        )

    def apply(self, tag, topic, roles, review):
        signature = tuple(tuple(tag[field]) if isinstance(tag[field], list) else tag[field] for field in TAG_FIELDS)
        resolved, held = self._resolve(topic, signature)
        for cid, kinds in resolved:
            roles[cid].update(kinds)
        for caption, kinds in held:
            review[caption].update(kinds)


def _coverage(tags: list[dict], *, topic: str, active: bool, resolver=None) -> dict:
    roles = defaultdict(set)
    review = defaultdict(set)
    valid = [tag for tag in tags if caption_key(tag["normalization_status"]) not in SUPPRESSED]
    if active:
        for tag in valid:
            if resolver is None:
                _tag_coverage(tag, topic, roles, review)
            else:
                resolver.apply(tag, topic, roles, review)
    concepts = [
        {
            "id": cid,
            "label": CONCEPTS[cid]["label"],
            "subject": CONCEPTS[cid].get("subject", "Algebra"),
            "area": CONCEPTS[cid]["area_label"],
            "roles": sorted(kinds),
        }
        for cid, kinds in roles.items()
    ]
    # Distinct identities with equal names are qualified until their merge is reviewed.
    repeated = Counter(c["label"].casefold() for c in concepts)
    for concept in concepts:
        concept["display"] = concept["label"] + (
            f" ({concept['subject']})" if repeated[concept["label"].casefold()] > 1 else ""
        )
    concepts.sort(key=lambda c: (c["display"].casefold(), c["id"]))
    areas = sorted({c["area"] for c in concepts}, key=str.casefold)
    status = "Mapped"
    if not active:
        status = "Inactive"
    elif not tags:
        status = "Untagged"
    elif not valid:
        status = "No valid tags"
    elif review or not concepts:
        status = "Needs review"
    return {
        "concept_areas": areas,
        "concept_coverage": concepts,
        "concept_review_labels": [
            f"{caption} ({', '.join(sorted(review[caption]))})" for caption in sorted(review, key=str.casefold)
        ],
        "concept_coverage_status": status,
        "concept_source_tags": [tag["technique"] for tag in tags],
    }


def statement_coverage_payloads(statements: list, *, resolver=None) -> dict:
    """Two bounded tag reads; statement tags suppress linked fallback even when invalid."""
    from inspinia.pages.concept_assignment_service import projection_enabled
    from inspinia.pages.concept_assignment_service import projection_payloads
    from inspinia.pages.concept_assignment_trace import load_sources

    if projection_enabled():
        keys = {s.pk: str(s.problem_uuid if s.pk else s.linked_problem.problem_uuid) for s in statements}
        payloads = projection_payloads(load_sources(keys.values()))
        return {s.pk: payloads[keys[s.pk]] for s in statements}
    by_statement, by_problem = defaultdict(list), defaultdict(list)
    seen_statement, seen_problem = set(), set()
    for model, relation, target, seen in (
        (StatementTopicTechnique, "statement_id", by_statement, seen_statement),
        (ProblemTopicTechnique, "record_id", by_problem, seen_problem),
    ):
        ids = [s.pk for s in statements] if model is StatementTopicTechnique else {
            s.linked_problem_id for s in statements if s.linked_problem_id and not by_statement[s.pk]
        }
        for tag in (
            model.objects.filter(**{f"{relation}__in": ids})
            .order_by("technique", "id")
            .values(
                relation,
                *TAG_FIELDS,
            )
        ):
            key = (tag[relation], caption_key(tag["technique"]))
            if key not in seen:
                seen.add(key)
                target[tag[relation]].append(tag)
    return {
        s.pk: _coverage(
            by_statement[s.pk] or by_problem[s.linked_problem_id], topic=effective_topic(s), active=s.is_active,
            resolver=resolver,
        )
        for s in statements
    }


def _captions(field: str, captions) -> Q:
    # Whole serialized JSON elements retain punctuation and domain qualifiers.
    values = sorted(set(captions))
    if field.endswith("_tags") or field == "proof_roles":
        values = [json.dumps(v, ensure_ascii=connection.vendor != "postgresql") for v in values]
        pattern = "(?:" + "|".join(re.escape(v) for v in values) + ")"
    else:
        pattern = "^(?:" + "|".join(re.escape(v) for v in values) + ")$"
    return Q(**{f"{field}__iregex": pattern}) if values else Q(pk__in=[])


def _topic(field: str, subject: str) -> Q:
    return _captions(field, SUBJECT_CODES[subject])


def _subject_scope(subject: str, *, parent: str) -> Q:
    # domains is also a JSON array, rather than a scalar caption.
    literal = "(?:" + "|".join(re.escape(json.dumps(c)) for c in SUBJECT_CODES[subject]) + ")"
    explicit = _topic("main_topic", subject) | Q(domains__iregex=literal)
    topic, linked_topic = (
        ("statement__topic", "statement__linked_problem__topic")
        if parent == "statement"
        else (
            "_coverage_topic",
            "_coverage_linked_topic",
        )
    )
    fallback = _topic(topic, subject) | (Q(**{topic: ""}) & _topic(linked_topic, subject))
    return explicit | (Q(main_topic="", domains=[]) & fallback)


def _context_match(kind: str, caption: str, rule: dict) -> Q:
    match = Q(technique__iexact=rule["technique"], canonical_subtopic__iexact=rule["family"])
    match &= _captions(ROLE_FIELDS[kind], [caption])
    for field, required in rule.get("requires", {}).items():
        for value in required:
            match &= _captions(field, [value])
    return match


def _subject_search(subject: str, ids: set) -> Q:
    aliases = defaultdict(set)
    result = Q(pk__in=[])
    for cid in ids:
        for kind, caption in CONCEPTS[cid]["aliases"]:
            aliases[ROLE_FIELDS[kind]].add(caption)
        for rule in CONCEPTS[cid].get("contextual_aliases", ()):
            result |= _context_match(rule["kind"], rule["label"], rule)
    for field, captions in aliases.items():
        result |= _captions(field, captions)
    return result | _policy_search(subject, ids)


def _policy_search(subject: str, ids: set) -> Q:
    result = Q(pk__in=[])
    for binding in CONTEXT_BINDINGS:
        if binding["subject"] != subject:
            continue
        for rule in binding["context_rules"]:
            if rule["concept_id"] not in ids:
                continue
            match = _context_match(binding["kind"], binding["caption"], rule)
            for other in binding["context_rules"]:
                if other["concept_id"] != rule["concept_id"]:
                    match &= ~_context_match(binding["kind"], binding["caption"], other)
            result |= match
    return result


def statement_concept_search(token: str) -> Q:
    """Search canonical names and areas before the row cap, without a fact rebuild."""
    from inspinia.pages.concept_assignment_registry import REGISTRY
    from inspinia.pages.concept_assignment_service import accepted_problem_ids
    from inspinia.pages.concept_assignment_service import projection_enabled

    if projection_enabled():
        ids = {
            cid
            for cid, definition in REGISTRY.definitions.items()
            if caption_key(token)
            in caption_key(" ".join([definition["label"], *(a["label"] for a in definition["area_memberships"])]))
        }
        return Q(problem_uuid__in=accepted_problem_ids(ids))
    by_subject = defaultdict(set)
    for cid, definition in CONCEPTS.items():
        if caption_key(token) in caption_key(f"{definition['label']} {definition['area_label']}"):
            by_subject[definition.get("subject", "Algebra")].add(cid)
    if not by_subject:
        return Q(pk__in=[])
    statement_match, problem_match = Q(pk__in=[]), Q(pk__in=[])
    for subject, ids in by_subject.items():
        source = _subject_search(subject, ids)
        statement_match |= source & _subject_scope(subject, parent="statement")
        problem_match |= source & _subject_scope(subject, parent="problem")
    valid = ~Q(normalization_status__iregex="^(?:invalid|corrupt|metadata)$")
    own = StatementTopicTechnique.objects.filter(statement_match & valid, statement_id=OuterRef("pk"))
    any_own = StatementTopicTechnique.objects.filter(statement_id=OuterRef("pk"))
    linked = ProblemTopicTechnique.objects.alias(
        _coverage_topic=ExpressionWrapper(OuterRef("topic"), output_field=CharField()),
        _coverage_linked_topic=ExpressionWrapper(OuterRef("linked_problem__topic"), output_field=CharField()),
    ).filter(problem_match & valid, record_id=OuterRef("linked_problem_id"))
    return Q(is_active=True) & (Q(Exists(own)) | (~Q(Exists(any_own)) & Q(Exists(linked))))
