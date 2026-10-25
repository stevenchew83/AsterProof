"""Approved Algebra concept identities, exact role membership and reference policy."""

import hashlib
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "data" / "algebra_concepts_v1.json"
CATALOG_SHA256 = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
CATALOG = json.loads(CATALOG_PATH.read_bytes())
CONCEPTS = {row["concept_id"]: row for row in CATALOG["concepts"]}
# Preserve the established captions while retaining full reviewed names in data.
for _cid, _label in {
    "am-gm": "AM-GM", "cauchy-schwarz": "CAUCHY-SCHWARZ", "engel": "ENGEL FORM",
    "weighted-am-gm": "WEIGHTED AM-GM", "vieta": "VIETA", "completing-square": "COMPLETING SQUARE",
    "coefficient-comparison": "COEFFICIENT COMPARISON", "factorization": "FACTORIZATION",
}.items():
    CONCEPTS[_cid]["label"] = _label

CONCEPT_BY_MEMBER = {
    (kind, label.strip().casefold()): cid
    for cid, definition in CONCEPTS.items() for kind, label in definition["aliases"]
}
CONCEPT_BY_PROFILE = {
    (profile["kind"], profile["label_key"]): cid
    for cid, definition in CONCEPTS.items() for profile in definition["profiles"]
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


def concept_for(kind: str, label: str) -> str:
    """Match full source captions, retaining punctuation, signs and domains."""
    kind = "canonical_subtopic" if kind == "subtopic" else kind
    return CONCEPT_BY_MEMBER.get((kind, str(label).strip().casefold()), "")


def concept_for_benchmark(kind: str, label_key: str) -> str:
    """Benchmark profile keys have their own reviewed ownership, separate from captions."""
    return CONCEPT_BY_PROFILE.get((kind, label_key), "")


def is_algebra_fact(fact: dict) -> bool:
    return "Algebra" in {
        fact.get("main_topic", ""), *(fact.get("main_topic_labels") or []),
        *(fact.get("domain_topic_labels") or []),
    }


def conflicting_concept_profiles(concept_ids: set[str]) -> set[str]:
    """Explicit references resolve rating differences; missing references fail closed."""
    from django.db.models import Q

    from inspinia.pages.models import TechniqueBenchmark

    expected = {cid: CONCEPTS[cid]["preferred"] for cid in concept_ids if CONCEPTS[cid]["preferred"]}
    query = Q(pk__in=[])
    for key in expected.values():
        kind, label_key = key.split(":", 1)
        query |= Q(kind=kind, label_key=label_key)
    present = {f"{p.kind}:{p.label_key}" for p in TechniqueBenchmark.objects.filter(query)}
    return {cid for cid, key in expected.items() if key not in present}


def concept_fact_filter(concept_id: str):
    """The exact Algebra-associated statement union used by concept counts."""
    from django.db import connection
    from django.db.models import Q

    query = Q(pk__in=[])
    for kind, display in CONCEPTS.get(concept_id, {}).get("aliases", ()):
        layer = "subtopic" if kind == "canonical_subtopic" else kind
        query |= Q(layer=layer, label__iexact=display)
    scope = Q(main_topic="Algebra")
    if connection.vendor == "postgresql":
        scope |= Q(main_topic_labels__contains=["Algebra"])
    else:
        scope |= Q(main_topic_labels__icontains='"Algebra"')
    return query & scope
