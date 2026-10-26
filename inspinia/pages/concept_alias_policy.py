"""Source-controlled alias certainty, correction history and assignment lifecycle."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

POLICY_PATH = Path(__file__).parent / "data" / "concept_alias_policy_v1.json"
POLICY_BYTES = POLICY_PATH.read_bytes()
POLICY_SHA256 = hashlib.sha256(POLICY_BYTES).hexdigest()
POLICY = json.loads(POLICY_BYTES)
RESOLUTIONS = {"EXACT", "CONTEXTUAL", "AMBIGUOUS"}
LIFECYCLES = {"ACTIVE", "DEPRECATED"}
ROLE_FIELDS = {
    "technique": "technique", "canonical_subtopic": "canonical_subtopic", "object": "object_tags",
    "method": "technique_tags", "lemma": "lemma_theorem_tags", "proof_role": "proof_roles",
}
SUBJECT_CODES = {
    "Algebra": ("A", "ALG", "ALGEBRA"),
    "Number Theory": ("N", "NT", "NUMBER THEORY"),
    "Geometry": ("G", "GEO", "GEOMETRY"),
    "Combinatorics": ("C", "COMB", "COMBINATORICS"),
}


def caption_key(value: str) -> str:
    return str(value or "").strip().casefold()


def binding_key(subject: str, kind: str, caption: str) -> tuple:
    return subject, "canonical_subtopic" if kind == "subtopic" else kind, caption_key(caption)


def source_subjects(source: dict, fallback_topic: str = "") -> set[str]:
    codes = [source.get("main_topic", ""), *(source.get("domains") or [])]
    codes = [str(value).strip().upper() for value in codes if str(value).strip()]
    codes = codes or [str(fallback_topic).strip().upper()]
    return {subject for subject, values in SUBJECT_CODES.items() if set(values).intersection(codes)}


def validate_policy(policy: dict) -> None:
    seen = set()
    ids = set()
    for row in policy["bindings"]:
        key = binding_key(row["subject"], row["kind"], row["caption"])
        if key in seen or row["id"] in ids:
            message = "Duplicate alias binding or policy ID."
            raise ValueError(message)
        seen.add(key)
        ids.add(row["id"])
        if row["resolution"] not in RESOLUTIONS or row["lifecycle"] not in LIFECYCLES:
            message = "Unknown alias resolution or lifecycle."
            raise ValueError(message)
        if row["kind"] not in ROLE_FIELDS:
            message = "Unknown alias role."
            raise ValueError(message)
        if (row["resolution"] == "EXACT") != bool(row.get("concept_id")):
            message = "Only exact bindings have an unconditional concept target."
            raise ValueError(message)
        if (row["resolution"] == "CONTEXTUAL") != bool(row.get("context_rules")):
            message = "Contextual aliases require explicit rules; other aliases must not have them."
            raise ValueError(message)
        _validate_context_rules(row)
        if row.get("canonical_caption") and caption_key(row["canonical_caption"]) == caption_key(row["caption"]):
            message = "A deprecated replacement must differ from the legacy caption."
            raise ValueError(message)


def _validate_context_rules(row: dict) -> None:
    for rule in row.get("context_rules", ()):
        if not rule.get("technique") or not rule.get("family") or not rule.get("concept_id"):
            message = "Context rules require a full source caption, family and concept."
            raise ValueError(message)
        if not set(rule.get("requires", {})) <= set(ROLE_FIELDS.values()):
            message = "Context rules reference unsupported source fields."
            raise ValueError(message)


validate_policy(POLICY)
BINDINGS = {binding_key(r["subject"], r["kind"], r["caption"]): r for r in POLICY["bindings"]}
CONTEXT_BINDINGS = tuple(r for r in POLICY["bindings"] if r["resolution"] == "CONTEXTUAL")


@dataclass(frozen=True)
class AliasResolution:
    binding_id: str
    resolution: str
    lifecycle: str
    concept_ids: tuple[str, ...]
    matched_rules: tuple[str, ...]
    held_reason: str
    assignment_caption: str


def context_matches(rule: dict, source: dict) -> bool:
    if (caption_key(source.get("technique")) != caption_key(rule["technique"])
            or caption_key(source.get("canonical_subtopic")) != caption_key(rule["family"])):
        return False
    for field, required in rule.get("requires", {}).items():
        actual = source.get(field) or []
        actual = actual if isinstance(actual, (list, tuple)) else [actual]
        if not {caption_key(v) for v in required} <= {caption_key(v) for v in actual}:
            return False
    return True


def resolve_binding(row: dict, *, source: dict | None = None, fallback_topic: str = "") -> AliasResolution:
    eligible = source is not None and row["subject"] in source_subjects(source, fallback_topic)
    if eligible:
        values = source.get(ROLE_FIELDS[row["kind"]]) or []
        values = values if isinstance(values, (list, tuple)) else [values]
        eligible = caption_key(row["caption"]) in {caption_key(value) for value in values}
    matches = [r for r in row.get("context_rules", ()) if eligible and context_matches(r, source)]
    targets = {r["concept_id"] for r in matches}
    if row["resolution"] == "EXACT":
        targets = {row["concept_id"]}
    reason = ""
    if row["resolution"] == "AMBIGUOUS" or not targets:
        reason = "AMBIGUOUS" if row["resolution"] == "AMBIGUOUS" else "MISSING_SOURCE_CONTEXT"
    if len(targets) > 1:
        reason = "CONTRADICTORY_SOURCE_CONTEXT"
    return AliasResolution(
        row["id"], row["resolution"], row["lifecycle"], tuple(sorted(targets)) if not reason else (),
        tuple(sorted(r["id"] for r in matches)), reason,
        row.get("canonical_caption", "" if row["lifecycle"] == "DEPRECATED" else row["caption"]),
    )


def alias_resolution(
    subject: str, kind: str, caption: str, *, source: dict | None = None, fallback_topic: str = "",
):
    row = BINDINGS.get(binding_key(subject, kind, caption))
    return resolve_binding(row, source=source, fallback_topic=fallback_topic) if row else None


def apply_alias_policy(definitions: dict) -> dict:
    """Change identity membership only; retain every original assessment object."""
    revised = deepcopy(definitions)
    for cid, definition in revised.items():
        subject = definition.get("subject", "Algebra")
        definition["aliases"] = [
            pair for pair in definition["aliases"]
            if binding_key(subject, *pair) not in BINDINGS
        ]
        if cid in POLICY.get("display_names", {}):
            definition["label"] = POLICY["display_names"][cid]
    for row in POLICY["bindings"]:
        targets = [row["concept_id"]] if row.get("concept_id") else [
            rule["concept_id"] for rule in row.get("context_rules", ())
        ]
        if any(target not in revised for target in targets):
            message = "An alias policy target is missing from the concept registry."
            raise ValueError(message)
        if row["resolution"] == "EXACT":
            for caption in (row["caption"], row.get("canonical_caption")):
                pair = [row["kind"], caption]
                if caption and pair not in revised[row["concept_id"]]["aliases"]:
                    revised[row["concept_id"]]["aliases"].append(pair)
    return revised


def normalize_alias_assignments(fields: dict, *, topic: str = "", active: bool = True) -> dict:
    """Accept legacy input while preventing new assignment of a deprecated caption."""
    if not active or caption_key(fields.get("normalization_status")) in {"invalid", "corrupt", "metadata"}:
        return fields
    replacements = {}
    for subject in source_subjects(fields, topic):
        for kind, field in ROLE_FIELDS.items():
            values = fields.get(field) or []
            values = values if isinstance(values, list) else [values]
            for caption in values:
                row = BINDINGS.get(binding_key(subject, kind, caption))
                if row is None or row["lifecycle"] != "DEPRECATED":
                    continue
                key = (field, caption)
                replacement = _assignment_caption(row, fields, topic)
                if key in replacements and replacements[key] != replacement:
                    message = "Subject-specific deprecated aliases have conflicting replacement captions."
                    raise ValueError(message)
                replacements[key] = replacement
    if not replacements:
        return fields
    from inspinia.pages.algebra_tag_aliases import merge_raw_sources

    result = deepcopy(fields)
    for (field, caption), replacement in replacements.items():
        if isinstance(result[field], list):
            result[field] = list(dict.fromkeys(replacement if value == caption else value for value in result[field]))
        else:
            result[field] = replacement
    result["raw_tag"] = merge_raw_sources([str(fields.get("raw_tag") or ""), *(key[1] for key in replacements)])
    return result


def _assignment_caption(row: dict, fields: dict, topic: str) -> str:
    decision = resolve_binding(row, source=fields, fallback_topic=topic)
    if not decision.concept_ids or not row.get("canonical_caption"):
        message = "A deprecated alias requires source review before a new assignment."
        raise ValueError(message)
    return row["canonical_caption"].upper()
