"""Reviewed, exact algebra aliases shared by cleanup, imports, and search."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

ALGEBRA_TOPICS = frozenset({"A", "ALG", "ALGEBRA"})
SUPPRESSED_STATUSES = frozenset({"invalid", "corrupt", "metadata"})
MAX_RAW_TAG_LENGTH = 512
ARRAY_FIELDS = ("domains", "object_tags", "technique_tags", "lemma_theorem_tags", "proof_roles")
TAG_FIELDS = (
    "technique",
    "main_topic",
    "canonical_subtopic",
    "raw_tag",
    "normalization_status",
    "normalization_confidence",
    *ARRAY_FIELDS,
)


class AlgebraAliasError(ValueError):
    """An alias operation would lose information or violate its reviewed scope."""


@lru_cache(maxsize=1)
def load_policy() -> dict:
    return json.loads((Path(__file__).parent / "data" / "algebra_aliases_v1.json").read_text())


def is_algebra_scope(topic: str | None, *, active: bool = True) -> bool:
    return active and str(topic or "").strip().upper() in ALGEBRA_TOPICS


def unique(values: list) -> list:
    return list(dict.fromkeys(values))


def normalize_tag_fields(
    fields: dict,
    *,
    topic: str | None,
    active: bool = True,
    problem_uuid: str | None = None,
    policy: dict | None = None,
) -> dict:
    """Rename exact values simultaneously; preserve layers, scope, and provenance."""
    result = deepcopy(fields)
    if not is_algebra_scope(topic, active=active):
        return result
    if str(fields.get("normalization_status") or "").strip().casefold() in SUPPRESSED_STATUSES:
        return result
    policy = policy or load_policy()
    aliases = {}
    for rule in policy["mappings"]:
        aliases.setdefault(rule["field"], {})[rule["source"]] = rule["target"]
    for field, replacements in aliases.items():
        value = fields.get(field, [] if field in ARRAY_FIELDS else "")
        if field in ARRAY_FIELDS:
            if not isinstance(value, list):
                message = f"Expected an array for algebra tag field {field}."
                raise AlgebraAliasError(message)
            result[field] = unique([replacements.get(item, item) for item in value])
        else:
            result[field] = replacements.get(value, value)
    _apply_specificity(result, source=fields.get("technique", ""), problem_uuid=problem_uuid, policy=policy)
    return result


def _apply_specificity(result: dict, *, source: str, problem_uuid: str | None, policy: dict) -> None:
    specificity = policy["specificity"]
    if str(problem_uuid) == specificity["problem_uuid"] and source in specificity["sources"]:
        result["technique"] = specificity["target"]
        generic = {
            "INJECTIVITY",
            "INJECTIVITY TRICKS",
            "INJECTIVITY / SURJECTIVITY",
            "INJECTIVITY / SURJECTIVITY / BIJECTIVITY",
        }
        result["technique_tags"] = unique(
            [
                *[value for value in result.get("technique_tags", []) if value not in generic],
                specificity["target"],
            ],
        )


def normalize_import_tag_fields(
    fields: dict,
    source_technique: str,
    *,
    topic: str | None,
    active: bool = True,
    problem_uuid: str | None = None,
) -> dict:
    result = normalize_tag_fields(fields, topic=topic, active=active, problem_uuid=problem_uuid)
    if (
        not is_algebra_scope(topic, active=active)
        or str(fields.get("normalization_status", "")).strip().casefold() in SUPPRESSED_STATUSES
    ):
        return result
    policy = load_policy()
    aliases = {r["source"]: r["target"] for r in policy["mappings"] if r["field"] == "technique"}
    # Do not let classification restore an older umbrella name on re-import.
    if source_technique in aliases:
        result["technique"] = aliases[source_technique]
    elif source_technique in aliases.values():
        result["technique"] = source_technique
    _apply_specificity(result, source=source_technique, problem_uuid=problem_uuid, policy=policy)
    return result


def merge_raw_sources(values: list[str]) -> str:
    """Keep complete, individually recoverable source strings; never truncate."""
    sources = unique([value.strip() for value in values if value and value.strip()])
    combined = ""
    for source in sources:
        # An existing merged value already contains its individual source strings.
        # Keep that complete string and avoid growing provenance on repeat imports.
        if f"; {source}; " not in f"; {combined}; ":
            combined = f"{combined}; {source}" if combined else source
    if len(combined) > MAX_RAW_TAG_LENGTH:
        message = "Algebra source tags exceed 512 characters; a lossless merge is required."
        raise AlgebraAliasError(message)
    return combined


def search_aliases(fields: dict, *, topic: str | None, active: bool = True, policy: dict | None = None) -> set[str]:
    """Expand only names already present; aliases never create coverage facts."""
    if not is_algebra_scope(topic, active=active):
        return set()
    if str(fields.get("normalization_status") or "").strip().casefold() in SUPPRESSED_STATUSES:
        return set()
    policy = policy or load_policy()
    terms = set()
    for rule in policy["mappings"]:
        values = fields.get(rule["field"], []) if rule["field"] in ARRAY_FIELDS else [fields.get(rule["field"], "")]
        if rule["source"] in values or rule["target"] in values:
            terms.update((rule["source"], rule["target"]))
    if str(fields.get("raw_tag") or "").strip():
        terms.add(str(fields["raw_tag"]).strip())
    return terms
