"""Canonical identities for assignment review, without changing legacy assessment profiles."""

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from inspinia.pages.concept_alias_policy import alias_resolution
from inspinia.pages.concept_alias_policy import caption_key
from inspinia.pages.technique_concepts import CONCEPT_REDIRECTS
from inspinia.pages.technique_concepts import CONCEPTS

DATA = Path(__file__).parent / "data"
MANIFEST = json.loads((DATA / "concept_assignment_identity_manifest_v1.json").read_text())
POLICY = json.loads((DATA / "concept_assignment_review_policy_v1.json").read_text())

REASON_LABELS = {
    "CAPTION_SCOPE_REVIEW": "Caption scope needs review",
    "STRUCTURED_ONLY": "Inferred from structured tags",
    "CONTEXT_REQUIRED": "Source context needs review",
    "AMBIGUOUS_IDENTITY": "More than one possible identity",
    "SOURCE_NEEDS_REVIEW": "Original tag needs review",
    "CROSS_SUBJECT": "Additional subject needs evidence",
    "SPECIALIST_REVIEW": "Specialist concept needs evidence",
    "PROBLEM_UUID_MISMATCH": "Problem linkage is inconsistent",
    "CONFLICTING_REVIEW_DECISIONS": "Existing review decisions conflict",
    "EVIDENCE_CHANGED": "Supporting evidence changed",
    "REFRESH_PENDING": "Assignment refresh pending",
    "SOURCE_REMOVED": "Original source was removed",
    "CONFLICTING_REVIEW_CONTEXTS": "Reviewed area contexts conflict",
    "AREA_CONTEXT_CHANGED": "Reviewed area context is no longer valid",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(),
    ).hexdigest()


class RegistryError(ValueError):
    pass


class AssignmentRegistry:
    def __init__(self, definitions=None, manifest=None):  # noqa: C901, PLR0912
        originals = deepcopy(CONCEPTS if definitions is None else definitions)
        self.manifest = deepcopy(MANIFEST if manifest is None else manifest)
        self.redirects = dict(CONCEPT_REDIRECTS) if definitions is None else {}
        seen = set()
        for merge in self.manifest.get("approved_merges", []):
            if not merge.get("reviewed_by") or not merge.get("reason") or not merge.get("evidence"):
                message = "An approved identity merge needs reviewer, reason and equivalence evidence."
                raise RegistryError(message)
            target = merge["target"]
            if target not in originals:
                message = "Identity destination is missing."
                raise RegistryError(message)
            for source in merge["sources"]:
                if source not in originals or source == target or source in seen:
                    message = "Identity source is missing, duplicated or self-referential."
                    raise RegistryError(message)
                seen.add(source)
                self.redirects[source] = target
        for source in self.redirects:
            target = self.canonical(source)
            if target not in originals:
                message = "Identity redirect destination is missing."
                raise RegistryError(message)
        self.definitions = {}
        self.members = defaultdict(set)
        for cid, source in originals.items():
            target = self.canonical(cid)
            subject = source.get("subject", "Algebra")
            if target not in self.definitions:
                definition = deepcopy(originals[target])
                definition.update(
                    concept_id=target,
                    subjects=[],
                    area_memberships=[],
                    legacy_ids=[],
                    aliases=[],
                    source_notes={},
                    assessment_references=[],
                )
                self.definitions[target] = definition
            definition = self.definitions[target]
            definition["subjects"] = sorted({*definition["subjects"], subject})
            area = {"subject": subject, "area": source["area"], "label": source["area_label"]}
            if area not in definition["area_memberships"]:
                definition["area_memberships"].append(area)
            definition["legacy_ids"].append(cid)
            definition["source_notes"][cid] = source.get("note", "")
            definition["assessment_references"].append(
                {
                    "legacy_concept_id": cid,
                    "profiles": source.get("profiles", []),
                    "canonical_benchmark_id": source.get("canonical_benchmark_id"),
                },
            )
            self.members[(subject, "technique", caption_key(source["label"]))].add(target)
            for kind, caption in source["aliases"]:
                self.members[(subject, kind, caption_key(caption))].add(target)
                if [kind, caption] not in definition["aliases"]:
                    definition["aliases"].append([kind, caption])
        self.areas = {
            f"{area['subject']}:{area['area']}": area
            for definition in self.definitions.values()
            for area in definition["area_memberships"]
        }
        self.previous_signatures = {}
        for cid, source in originals.items():
            subject = source.get("subject", "Algebra")
            previous = {
                **source,
                "concept_id": cid,
                "subjects": [subject],
                "area_memberships": [{"subject": subject, "area": source["area"], "label": source["area_label"]}],
                "source_notes": {cid: source.get("note", "")},
            }
            self.previous_signatures[cid] = self._signature(previous)
        self.fingerprint = digest({"definitions": self.definitions, "manifest": self.manifest, "policy": POLICY})

    def canonical(self, cid):
        visited = set()
        while cid in self.redirects:
            if cid in visited:
                message = "Identity redirect cycle."
                raise RegistryError(message)
            visited.add(cid)
            cid = self.redirects[cid]
        return cid

    def resolve(self, subject, kind, caption, source):
        decision = alias_resolution(subject, kind, caption, source=source, fallback_topic=subject)
        if decision is not None:
            return {
                "ids": sorted({self.canonical(cid) for cid in decision.concept_ids}),
                "resolution": decision.resolution,
                "rule": decision.binding_id,
                "reason": decision.held_reason,
            }
        ids = self.members.get((subject, kind, caption_key(caption)), set())
        if not ids and subject == "Combinatorics":
            from inspinia.pages.combinatorics_concept_context import RULES_BY_SOURCE

            rules = RULES_BY_SOURCE.get(
                (caption_key(source["technique"]), caption_key(source["canonical_subtopic"])),
                (),
            )
            ids = {
                self.canonical(rule["concept_id"])
                for rule in rules
                if rule["kind"] == kind and caption_key(rule["label"]) == caption_key(caption)
            }
            if ids:
                return {
                    "ids": sorted(ids),
                    "resolution": "CONTEXTUAL",
                    "rule": "combinatorics-source-context",
                    "reason": "",
                }
        return {
            "ids": sorted(ids),
            "resolution": "EXACT" if len(ids) == 1 else "AMBIGUOUS",
            "rule": "catalog-alias",
            "reason": "",
        }

    @staticmethod
    def _signature(definition):
        return digest(
            {
                key: definition.get(key)
                for key in (
                    "concept_id",
                    "label",
                    "note",
                    "parent_concept",
                    "subjects",
                    "area_memberships",
                    "source_notes",
                )
            },
        )

    def signature(self, cid):
        return self._signature(self.definitions[self.canonical(cid)])

    def compatible_signature(self, cid, signature):
        target = self.canonical(cid)
        if signature == self.signature(target):
            return True
        merged = {key for key in self.definitions[target]["legacy_ids"] if key != target}
        return bool(merged and signature == self.previous_signatures.get(cid))

    def presentation(self, cid, subject, roles=(), *, area_context=""):
        cid = self.canonical(cid)
        definition = self.definitions[cid]
        areas = [a for a in definition["area_memberships"] if a["subject"] == subject]
        areas = areas or definition["area_memberships"][:1]
        if area_context:
            selected = self.areas.get(area_context)
            if selected is None or selected["subject"] not in definition["subjects"]:
                message = "The reviewed area must be an existing area in a subject membership of this concept."
                raise RegistryError(message)
            areas = [selected]
        return {
            "id": cid,
            "label": definition["label"],
            "display": definition["label"],
            "subject": areas[0]["subject"],
            "subjects": definition["subjects"],
            "area": areas[0]["label"],
            "area_id": areas[0]["area"],
            "roles": sorted(set(roles)),
        }

    def identity_proposals(self):
        groups = defaultdict(list)
        for cid, definition in self.definitions.items():
            groups[caption_key(definition["label"])].append(cid)
        rows = list(self.manifest.get("proposals", []))
        covered = {tuple(sorted([r["target"], *r["sources"]])) for r in rows}
        rows.extend(
            {
                "sources": sorted(ids)[1:],
                "target": sorted(ids)[0],
                "status": "scope_review",
                "reason": "Equal names require definition and scope review; no automatic merge.",
            }
            for ids in groups.values()
            if len(ids) > 1 and tuple(sorted(ids)) not in covered
        )
        return rows


REGISTRY = AssignmentRegistry()
