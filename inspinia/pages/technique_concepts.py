"""Subject-scoped mathematical identities with original assessment profiles retained."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from inspinia.pages.concept_alias_policy import POLICY_BYTES
from inspinia.pages.concept_alias_policy import apply_alias_policy

DATA = Path(__file__).parent / "data"
CATALOG_PATH = DATA / "algebra_concepts_v1.json"
NUMBER_THEORY_CATALOG_PATH = DATA / "number_theory_concepts_v1.json"
GEOMETRY_CATALOG_PATH = DATA / "geometry_concepts_v1.json"
COMBINATORICS_CATALOG_PATH = DATA / "combinatorics_concepts_v1.json"
CATALOG_SHA256 = hashlib.sha256(
    CATALOG_PATH.read_bytes() + NUMBER_THEORY_CATALOG_PATH.read_bytes() + GEOMETRY_CATALOG_PATH.read_bytes()
    + COMBINATORICS_CATALOG_PATH.read_bytes() + POLICY_BYTES,
).hexdigest()
CATALOG = json.loads(CATALOG_PATH.read_bytes())
NUMBER_THEORY_CATALOG = json.loads(NUMBER_THEORY_CATALOG_PATH.read_bytes())
GEOMETRY_CATALOG = json.loads(GEOMETRY_CATALOG_PATH.read_bytes())
COMBINATORICS_CATALOG = json.loads(COMBINATORICS_CATALOG_PATH.read_bytes())
ALGEBRA_CONCEPTS = {row["concept_id"]: row for row in CATALOG["concepts"]}
NUMBER_THEORY_CONCEPTS = {row["concept_id"]: row for row in NUMBER_THEORY_CATALOG["concepts"]}
GEOMETRY_CONCEPTS = {row["concept_id"]: row for row in GEOMETRY_CATALOG["concepts"]}
COMBINATORICS_CONCEPTS = {row["concept_id"]: row for row in COMBINATORICS_CATALOG["concepts"]}
CONCEPTS = apply_alias_policy({
    **ALGEBRA_CONCEPTS, **NUMBER_THEORY_CONCEPTS, **GEOMETRY_CONCEPTS, **COMBINATORICS_CONCEPTS,
})
ALGEBRA_CONCEPTS = {cid: CONCEPTS[cid] for cid in ALGEBRA_CONCEPTS}
NUMBER_THEORY_CONCEPTS = {cid: CONCEPTS[cid] for cid in NUMBER_THEORY_CONCEPTS}
GEOMETRY_CONCEPTS = {cid: CONCEPTS[cid] for cid in GEOMETRY_CONCEPTS}
COMBINATORICS_CONCEPTS = {cid: CONCEPTS[cid] for cid in COMBINATORICS_CONCEPTS}
CONCEPT_REDIRECTS = {**NUMBER_THEORY_CATALOG["redirects"], **COMBINATORICS_CATALOG["redirects"]}
# Preserve established Algebra captions and public identifiers.
for _cid, _label in {
    "am-gm": "AM-GM", "cauchy-schwarz": "CAUCHY-SCHWARZ", "engel": "ENGEL FORM",
    "weighted-am-gm": "WEIGHTED AM-GM", "vieta": "VIETA", "completing-square": "COMPLETING SQUARE",
    "coefficient-comparison": "COEFFICIENT COMPARISON", "factorization": "FACTORIZATION",
}.items():
    CONCEPTS[_cid]["label"] = _label

CONCEPT_BY_MEMBER = {
    (kind, label.strip().casefold()): cid
    for cid, definition in ALGEBRA_CONCEPTS.items() for kind, label in definition["aliases"]
}
NUMBER_THEORY_BY_MEMBER = {
    (kind, label.strip().casefold()): cid
    for cid, definition in NUMBER_THEORY_CONCEPTS.items() for kind, label in definition["aliases"]
}
GEOMETRY_BY_MEMBER = {
    (kind, label.strip().casefold()): cid
    for cid, definition in GEOMETRY_CONCEPTS.items() for kind, label in definition["aliases"]
}
COMBINATORICS_BY_MEMBER = {
    (kind, label.strip().casefold()): cid
    for cid, definition in COMBINATORICS_CONCEPTS.items() for kind, label in definition["aliases"]
}
CONCEPT_BY_PROFILE = {
    (profile["kind"], profile["label_key"]): cid
    for cid, definition in ALGEBRA_CONCEPTS.items() for profile in definition["profiles"]
}
NUMBER_THEORY_BY_PROFILE = {
    (profile["kind"], profile["label_key"]): cid
    for cid, definition in NUMBER_THEORY_CONCEPTS.items() for profile in definition["profiles"]
}
GEOMETRY_BY_PROFILE = {
    (profile["kind"], profile["label_key"]): cid
    for cid, definition in GEOMETRY_CONCEPTS.items() for profile in definition["profiles"]
}
COMBINATORICS_BY_PROFILE = {
    (profile["kind"], profile["label_key"]): cid
    for cid, definition in COMBINATORICS_CONCEPTS.items() for profile in definition["profiles"]
}
CONCEPT_MEMBER_KEYS = {
    cid: tuple(f"{p['kind']}:{p['label_key']}" for p in definition["profiles"])
    for cid, definition in CONCEPTS.items()
}
PROFILE_FIELDS = (
    "syllabus_core", "contest_frequency", "transfer_value", "prerequisite_value", "mohs_scalability",
    "concept_load", "recognition_burden", "execution_load", "proof_fragility", "cross_topic_dependency",
    "typical_mohs_min", "typical_mohs_max", "jbmo_weight", "national_weight", "imo_tst_weight",
    "training_type", "target_level",
)
SUBJECT_LABELS = {
    "a": "Algebra", "alg": "Algebra", "algebra": "Algebra",
    "n": "Number Theory", "nt": "Number Theory", "number theory": "Number Theory",
    "number-theory": "Number Theory",
    "g": "Geometry", "geo": "Geometry", "geometry": "Geometry",
    "c": "Combinatorics", "comb": "Combinatorics", "combinatorics": "Combinatorics",
}


def concept_subject(concept_id: str) -> str:
    definition = CONCEPTS.get(resolve_concept_id(concept_id), {})
    return definition.get("subject", "Algebra") if definition else ""


def resolve_concept_id(concept_id: str) -> str:
    return CONCEPT_REDIRECTS.get(concept_id, concept_id)


def catalog_concept_ids(topic: str = "Algebra", *, scope: str = "core") -> tuple[str, ...]:
    subject = SUBJECT_LABELS.get(str(topic).strip().casefold(), "")
    if subject == "Algebra":
        return tuple(ALGEBRA_CONCEPTS)
    if subject == "Geometry":
        return tuple(GEOMETRY_CONCEPTS)
    if subject == "Combinatorics":
        return tuple(COMBINATORICS_CONCEPTS)
    if subject != "Number Theory":
        return ()
    return tuple(cid for cid, definition in NUMBER_THEORY_CONCEPTS.items() if (
        scope == "all" or (definition["scope"] == "shared_appendix") == (scope == "shared")
    ))


def benchmark_catalog_filters(params) -> dict | None:
    """Select a subject catalog or leave the original role-profile view intact."""
    if params.get("view") == "profiles":
        return None
    raw_key = params.get("row_key", "")
    if raw_key and not raw_key.startswith("concept:"):
        return None
    concept_id = resolve_concept_id(raw_key.partition(":")[2]) if raw_key.startswith("concept:") else ""
    subject = SUBJECT_LABELS.get(params.get("area", "").strip().casefold(), "") or concept_subject(concept_id)
    if not subject:
        return None
    return {
        "topic": subject,
        "scope": "all" if concept_id else params.get("scope", "core"),
        "row_key": f"concept:{concept_id}" if concept_id else raw_key,
        "search": (params.get("q") or "").strip(), "family": params.get("family", ""),
    }


def concept_for(kind: str, label: str, *, topic: str = "Algebra") -> str:
    """Match exact captions in their role and subject, retaining signs and domains."""
    kind = "canonical_subtopic" if kind == "subtopic" else kind
    members = {
        "Algebra": CONCEPT_BY_MEMBER, "Number Theory": NUMBER_THEORY_BY_MEMBER,
        "Geometry": GEOMETRY_BY_MEMBER,
        "Combinatorics": COMBINATORICS_BY_MEMBER,
    }.get(SUBJECT_LABELS.get(str(topic).strip().casefold(), ""), {})
    return members.get((kind, str(label).strip().casefold()), "")


def concept_for_benchmark(kind: str, label_key: str, *, topic: str = "") -> str:
    """Shared source profiles can be viewed in either subject without being copied."""
    pair = (kind, label_key)
    subject = SUBJECT_LABELS.get(str(topic).strip().casefold(), "")
    if subject == "Number Theory":
        return NUMBER_THEORY_BY_PROFILE.get(pair, "")
    if subject == "Algebra":
        return CONCEPT_BY_PROFILE.get(pair, "")
    if subject == "Geometry":
        return GEOMETRY_BY_PROFILE.get(pair, "")
    if subject == "Combinatorics":
        return COMBINATORICS_BY_PROFILE.get(pair, "")
    # Preserve established ownership in the unfiltered map. Area catalogs use
    # explicit subject ownership for shared source profiles.
    return (
        CONCEPT_BY_PROFILE.get(pair, "") or NUMBER_THEORY_BY_PROFILE.get(pair, "")
        or GEOMETRY_BY_PROFILE.get(pair, "")
        or COMBINATORICS_BY_PROFILE.get(pair, "")
    )


def is_algebra_fact(fact: dict) -> bool:
    return "Algebra" in {
        fact.get("main_topic", ""), *(fact.get("main_topic_labels") or []),
        *(fact.get("domain_topic_labels") or []),
    }


def concept_for_fact(fact: dict, *, topic: str = "") -> str:
    """Compatibility lookup for facts that identify exactly one concept."""
    ids = concepts_for_fact(fact, topic=topic)
    return ids[0] if len(ids) == 1 else ""


def concepts_for_fact(fact: dict, *, topic: str = "") -> tuple[str, ...]:
    """A merged fact may have separate graph/permutation source occurrences."""
    labels = [fact.get("main_topic", ""), *(fact.get("main_topic_labels") or []),
              *(fact.get("domain_topic_labels") or [])]
    subjects = list(dict.fromkeys(SUBJECT_LABELS.get(str(label).casefold(), "") for label in labels))
    requested = SUBJECT_LABELS.get(str(topic).casefold(), "")
    if requested:
        subjects = [requested] if requested in subjects else []
    for subject in subjects:
        if subject and (cid := concept_for(str(fact["layer"]), str(fact["label"]), topic=subject)):
            return (cid,)
        if subject and fact.get("_alias_context_ids", {}).get(subject):
            return tuple(fact["_alias_context_ids"][subject])
        if subject == "Combinatorics" and fact.get("_comb_context_ids"):
            return tuple(fact["_comb_context_ids"])
    return ()


def conflicting_concept_profiles(concept_ids: set[str]) -> set[str]:
    """Use reviewed references; differing retained vectors never acquire a combined rating."""
    from inspinia.pages.models import TechniqueBenchmark

    definitions = {cid: CONCEPTS[cid] for cid in concept_ids if cid in CONCEPTS}
    member_keys = set()
    for definition in definitions.values():
        keys = CONCEPT_MEMBER_KEYS[definition["concept_id"]] if definition.get("reference_policy") else (
            (definition["preferred"],) if definition["preferred"] else ()
        )
        member_keys.update(keys)
    profiles = {
        f"{p.kind}:{p.label_key}": p for p in TechniqueBenchmark.objects.filter(benchmark_member_filter(member_keys))
    }
    conflicts = set()
    for cid, definition in definitions.items():
        preferred = definition["preferred"]
        if preferred and preferred not in profiles:
            conflicts.add(cid)
        if definition.get("reference_policy") == "identical_profiles_only" and definition["profiles"]:
            retained = [profiles[key] for key in CONCEPT_MEMBER_KEYS[cid] if key in profiles]
            signatures = {tuple(str(getattr(p, field)) for field in PROFILE_FIELDS) for p in retained}
            if not preferred or len(signatures) > 1:
                conflicts.add(cid)
    return conflicts


def benchmark_member_filter(members):
    """Keep exact role/key membership without a deep OR tree per profile."""
    from django.db.models import Q

    by_kind = defaultdict(set)
    for member in members:
        kind, label_key = member.split(":", 1)
        by_kind[kind].add(label_key)
    query = Q(pk__in=[])
    for kind, keys in by_kind.items():
        query |= Q(kind=kind, label_key__in=sorted(keys))
    return query


def concept_fact_filter(concept_id: str):
    """Exact role/name union with the same subject boundary used by gap counts."""
    from django.db import connection
    from django.db.models import Q

    from inspinia.pages.concept_alias_context import contextual_fact_filter as alias_context_filter

    concept_id = resolve_concept_id(concept_id)
    query = Q(pk__in=[])
    for kind, display in CONCEPTS.get(concept_id, {}).get("aliases", ()):
        layer = "subtopic" if kind == "canonical_subtopic" else kind
        query |= Q(layer=layer, label__iexact=display)
    query |= alias_context_filter(concept_id)
    if concept_id in COMBINATORICS_CONCEPTS:
        from inspinia.pages.combinatorics_concept_context import contextual_fact_filter

        query |= contextual_fact_filter(concept_id)
    subject = concept_subject(concept_id)
    scope = Q(main_topic=subject)
    if connection.vendor == "postgresql":
        scope |= Q(main_topic_labels__contains=[subject])
    else:
        scope |= Q(main_topic_labels__icontains=json.dumps(subject))
    return query & scope
