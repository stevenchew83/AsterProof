"""One reviewed projection, immutable previews, and durable decision receipts."""

import uuid as uuid_module
from collections import Counter
from collections import defaultdict
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db import transaction
from django.db.models import F

from inspinia.pages.concept_alias_policy import ROLE_FIELDS
from inspinia.pages.concept_assignment_registry import POLICY
from inspinia.pages.concept_assignment_registry import REASON_LABELS
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_registry import RegistryError
from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.concept_assignment_trace import source_uuid_query
from inspinia.pages.concept_assignment_trace import trace_source
from inspinia.pages.models import ConceptAssignmentReviewBatch
from inspinia.pages.models import ConceptAssignmentReviewEvent
from inspinia.pages.models import ConceptAssignmentState
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.users.roles import user_has_admin_role

IMAGE_FIELDS = (
    "concept_id",
    "disposition",
    "decision_origin",
    "roles",
    "subject_context",
    "area_context",
    "evidence",
    "reasons",
    "source_fingerprint",
    "concept_signature",
    "is_stale",
    "is_current",
    "rationale",
    "reviewed_by_id",
)
MAX_BATCH = POLICY["max_batch_size"]


class AssignmentConflictError(ValueError):
    pass


def storage_ready():
    tables = set(connection.introspection.table_names())
    return all(
        model._meta.db_table in tables  # noqa: SLF001 - Django public model metadata
        for model in (
            ProblemConceptAssignment,
            ConceptAssignmentReviewBatch,
            ConceptAssignmentReviewEvent,
            ConceptAssignmentState,
        )
    )


def projection_enabled():
    if not getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False):
        return False
    return ConceptAssignmentState.objects.filter(singleton_key=1, enabled=True, initial_seed_complete=True).exists()


def _image(row):
    if row is None:
        return {}
    return {key: getattr(row, key) for key in IMAGE_FIELDS}


def _records(uuids):
    grouped = defaultdict(list)
    for row in ProblemConceptAssignment.objects.filter(problem_uuid__in=uuids, is_current=True).order_by(
        "concept_id",
        "pk",
    ):
        grouped[str(row.problem_uuid)].append(row)
    return grouped


def published_solution_evidence(uuids, ids=None):
    """Two batch queries, only published solutions belonging to these identities."""
    from inspinia.solutions.models import ProblemSolution
    from inspinia.solutions.models import ProblemSolutionBlock

    query = ProblemSolution.objects.filter(problem__problem_uuid__in=uuids, status=ProblemSolution.Status.PUBLISHED)
    if ids is not None:
        query = query.filter(pk__in=ids)
    solutions = {row["id"]: row for row in query.values("id", "title", "problem__problem_uuid")}
    blocks = defaultdict(list)
    for row in (
        ProblemSolutionBlock.objects.filter(solution_id__in=solutions)
        .order_by("position", "id")
        .values("solution_id", "title", "body_source")
    ):
        blocks[row["solution_id"]].append((row["title"], row["body_source"]))
    return {
        key: {
            "kind": "published_solution",
            "reference": key,
            "problem_uuid": str(row["problem__problem_uuid"]),
            "title": row["title"] or f"Published solution {key}",
            "text": "\n".join([row["title"], *("\n".join(block) for block in blocks[key])]),
            "content_hash": digest([row["title"], blocks[key]]),
        }
        for key, row in solutions.items()
    }


def _proofs_for_records(sources, records):
    ids = {
        int(e["reference"])
        for rows in records.values()
        for row in rows
        for e in row.evidence
        if e.get("kind") == "published_solution"
    }
    return published_solution_evidence(list(sources), ids) if ids else {}


def _review_evidence(item, source, proofs):
    kind = item.get("kind")
    quote = str(item.get("quote") or "").strip()
    if not quote:
        message = "Confirmation requires an exact supporting excerpt."
        raise AssignmentConflictError(message)
    if kind == "statement":
        if not source["statement_id"]:
            message = "This problem has no statement evidence."
            raise AssignmentConflictError(message)
        reference, text, content_hash = source["statement_id"], source["statement_text"], source["statement_hash"]
    elif kind == "published_solution":
        proof = proofs.get(int(item.get("reference") or 0))
        if not proof or proof["problem_uuid"] != source["problem_uuid"]:
            message = "Evidence must be a published solution for this problem."
            raise AssignmentConflictError(message)
        reference, text, content_hash = proof["reference"], proof["text"], proof["content_hash"]
    else:
        message = "Use statement or published-solution evidence; private drafts are excluded."
        raise AssignmentConflictError(message)
    if quote not in text:
        message = "The supporting excerpt is not present in the selected evidence."
        raise AssignmentConflictError(message)
    return {"kind": kind, "reference": reference, "quote": quote, "content_hash": content_hash}


def _fresh(row, source, candidate, proofs, registry):
    cid = registry.canonical(row.concept_id)
    if cid not in registry.definitions:
        return False
    if not registry.compatible_signature(row.concept_id, row.concept_signature):
        return False
    if row.area_context:
        area = registry.areas.get(row.area_context)
        if not area or area["subject"] not in registry.definitions[cid]["subjects"]:
            return False
        if row.subject_context and area["subject"] != row.subject_context:
            return False
    if row.decision_origin == "auto_direct_tag":
        return bool(
            candidate and candidate["auto_eligible"] and row.source_fingerprint == source["source_fingerprint"],
        )
    witnesses = []
    for evidence in row.evidence:
        if evidence.get("kind") == "statement":
            witnesses.append(
                evidence["reference"] == source["statement_id"]
                and evidence["content_hash"] == source["statement_hash"],
            )
        elif evidence.get("kind") == "published_solution":
            proof = proofs.get(evidence["reference"])
            witnesses.append(
                bool(
                    proof
                    and proof["problem_uuid"] == source["problem_uuid"]
                    and proof["content_hash"] == evidence["content_hash"],
                ),
            )
    return any(witnesses)


def project_source(source, rows, proofs=None, registry=REGISTRY):  # noqa: C901, PLR0912
    trace = trace_source(source, registry)
    candidates = {c["id"]: c for c in trace["candidates"]}
    groups = defaultdict(list)
    for row in rows:
        groups[registry.canonical(row.concept_id)].append(row)
    accepted, suggestions, rejected = [], [], []
    for cid in sorted(set(candidates) | set(groups)):
        if cid not in registry.definitions:
            continue
        candidate = candidates.get(cid)
        records = groups.get(cid, [])
        dispositions = {r.disposition for r in records if r.decision_origin == "reviewed"}
        if dispositions == {"rejected"}:
            rejected.append(cid)
            continue
        conflict = "rejected" in dispositions and "accepted" in dispositions
        valid = [
            r for r in records if r.disposition == "accepted" and _fresh(r, source, candidate, proofs or {}, registry)
        ]
        contexts = {r.area_context for r in valid if r.decision_origin == "reviewed" and r.area_context}
        area_conflict = len(contexts) > 1
        conflict = conflict or area_conflict
        if source["active"] and not source["conflicts"] and valid and not conflict:
            context = next((r.subject_context for r in valid if r.subject_context), source["subject"])
            selected_area = next((r.area_context for r in valid if r.area_context), "")
            row = registry.presentation(
                cid,
                context,
                [role for r in valid for role in r.roles],
                area_context=selected_area,
            )
            row["support_basis"] = (
                "Evidence reviewed" if any(r.decision_origin == "reviewed" for r in valid) else "Exact legacy tag"
            )
            # Public coverage never contains solution excerpts or historical private content.
            row["evidence"] = candidate["evidence"] if candidate else []
            accepted.append(row)
        elif source["active"] and (candidate or records):
            row = dict(candidate or registry.presentation(cid, source["subject"]))
            reasons = list(row.get("reasons", []))
            if conflict:
                reasons.append("CONFLICTING_REVIEW_CONTEXTS" if area_conflict else "CONFLICTING_REVIEW_DECISIONS")
            elif any(r.disposition == "accepted" for r in records):
                reasons.append("EVIDENCE_CHANGED")
            elif candidate and candidate["auto_eligible"] and not records:
                reasons.append("REFRESH_PENDING")
            row.update(
                reasons=sorted(set(reasons)),
                reason_labels=[REASON_LABELS.get(reason, reason) for reason in sorted(set(reasons))],
                disposition="suggested",
            )
            suggestions.append(row)
    review = sorted({f"{e['caption']} ({e['role']})" for e in trace["unresolved"]})
    status = "Mapped"
    if not source["active"]:
        status = "Inactive"
    elif not source["tags"] and not accepted:
        status = "Untagged"
    elif source["tags"] and not accepted and len(trace["excluded"]) == len(source["tags"]):
        status = "No valid tags"
    elif suggestions or review or source["conflicts"]:
        status = "Needs review"
    accepted.sort(key=lambda c: (c["display"].casefold(), c["id"]))
    return {
        "assignment_projection": True,
        "concept_coverage": accepted,
        "concept_areas": sorted({c["area"] for c in accepted}, key=str.casefold),
        "concept_suggestions": suggestions,
        "concept_review_labels": review,
        "concept_source_tags": [t["technique"] for t in source["tags"]],
        "concept_coverage_status": status,
        "concept_review_summary": {"accepted": len(accepted), "suggested": len(suggestions)},
        "rejected_concepts": rejected,
    }


def projection_payloads(sources):
    records = _records(list(sources))
    proofs = _proofs_for_records(sources, records)
    return {key: project_source(source, records[key], proofs) for key, source in sources.items()}


def _auto_image(source, candidate):
    return {
        "concept_id": candidate["id"],
        "disposition": candidate["disposition"],
        "decision_origin": "auto_direct_tag",
        "roles": candidate["accepted_roles"] if candidate["auto_eligible"] else candidate["roles"],
        "subject_context": source["subject"],
        "area_context": "",
        "evidence": candidate["evidence"],
        "reasons": candidate["reasons"],
        "source_fingerprint": source["source_fingerprint"],
        "concept_signature": candidate["concept_signature"],
        "is_stale": False,
        "is_current": True,
        "rationale": "",
        "reviewed_by_id": None,
    }


def _count_sets(payloads):
    values = defaultdict(set)
    for uuid, payload in payloads.items():
        for concept in payload["concept_coverage"]:
            values[("concept", concept["id"])].add(uuid)
            values[("area", f"{concept['subject']}:{concept['area']}")].add(uuid)
            values[("subject", concept["subject"])].add(uuid)
    return values


def _count_deltas(sources, records, proofs, changes, *, legacy=False):
    if legacy:
        from inspinia.pages.statement_concept_coverage import _coverage

        before = {
            key: _coverage(source["tags"], topic=source["subject"], active=source["active"])
            for key, source in sources.items()
        }
    else:
        before = {key: project_source(source, records[key], proofs) for key, source in sources.items()}
    images = {(key, row.concept_id): _image(row) for key, rows in records.items() for row in rows}
    for change in changes:
        images[(change["problem_uuid"], change["concept_id"])] = change["after"]
    after_records = defaultdict(list)
    for (key, _), image in images.items():
        if image.get("is_current", True):
            after_records[key].append(SimpleNamespace(**image))
    after = {key: project_source(source, after_records[key], proofs) for key, source in sources.items()}
    old, new = _count_sets(before), _count_sets(after)
    return [
        {
            "dimension": dimension,
            "id": key,
            "before": len(old[(dimension, key)]),
            "after": len(new[(dimension, key)]),
            "delta": len(new[(dimension, key)]) - len(old[(dimension, key)]),
        }
        for dimension, key in sorted(set(old) | set(new))
        if old[(dimension, key)] != new[(dimension, key)]
    ]


def _normalize_identity_records(source, rows, candidates, proofs):
    groups = defaultdict(list)
    for row in rows:
        groups[REGISTRY.canonical(row.concept_id)].append(row)
    normalized, changes, conflicts = [], [], []
    for cid, members in groups.items():
        if all(row.concept_id == cid for row in members):
            normalized.extend(members)
            continue
        reviewed = [row for row in members if row.decision_origin == "reviewed"]
        review_contexts = {row.area_context for row in reviewed if row.disposition == "accepted" and row.area_context}
        if len({row.disposition for row in reviewed}) > 1 or len(review_contexts) > 1:
            conflicts.append(
                {
                    "problem_uuid": source["problem_uuid"],
                    "concept_id": cid,
                    "reason": "CONFLICTING_REVIEW_CONTEXTS"
                    if len(review_contexts) > 1
                    else "CONFLICTING_REVIEW_DECISIONS",
                },
            )
            normalized.extend(members)
            continue
        preferred = (
            next((row for row in reviewed if row.concept_id == cid), None)
            or (reviewed[0] if reviewed else None)
            or next((row for row in members if row.concept_id == cid), members[0])
        )
        after = _image(preferred)
        after.update(concept_id=cid, is_current=True)
        if review_contexts:
            after["area_context"] = next(iter(review_contexts))
            after["subject_context"] = REGISTRY.areas[after["area_context"]]["subject"]
        if REGISTRY.compatible_signature(preferred.concept_id, preferred.concept_signature):
            after["concept_signature"] = REGISTRY.signature(cid)
        after["roles"] = sorted(
            {role for row in members if row.disposition == preferred.disposition for role in row.roles},
        )
        evidence = {digest(item): item for row in members for item in row.evidence}
        after["evidence"] = [evidence[key] for key in sorted(evidence)]
        if preferred.disposition == "accepted":
            after["is_stale"] = not any(
                _fresh(row, source, candidates.get(cid), proofs, REGISTRY)
                for row in members
                if row.disposition == "accepted"
            )
        current = next((row for row in members if row.concept_id == cid), None)
        if after != _image(current):
            changes.append(
                {
                    "problem_uuid": source["problem_uuid"],
                    "concept_id": cid,
                    "action": "merge_identity",
                    "before": _image(current),
                    "after": after,
                },
            )
        changes.extend(
            {
                "problem_uuid": source["problem_uuid"],
                "concept_id": row.concept_id,
                "action": "retire_identity",
                "before": _image(row),
                "after": {**_image(row), "is_current": False},
            }
            for row in members
            if row.concept_id != cid
        )
        normalized.append(SimpleNamespace(**after))
    return normalized, changes, conflicts


def _fold_changes(changes):
    folded = {}
    for change in changes:
        key = (change["problem_uuid"], change["concept_id"])
        if key in folded:
            folded[key] = {
                **change,
                "action": folded[key].get("action", change.get("action", "refresh")),
                "before": folded[key]["before"],
            }
        else:
            folded[key] = change
    return [change for _, change in sorted(folded.items()) if change["before"] != change["after"]]


def audit_sources(sources, *, include_records=True):
    records = _records(list(sources)) if include_records and storage_ready() else defaultdict(list)
    changes, traces, conflicts = [], [], []
    proofs = _proofs_for_records(sources, records)
    for key, source in sources.items():
        trace = trace_source(source)
        traces.append(trace)
        conflicts.extend({"problem_uuid": key, "reason": reason} for reason in source["conflicts"])
        normalized, identity_changes, identity_conflicts = _normalize_identity_records(
            source,
            records[key],
            {c["id"]: c for c in trace["candidates"]},
            proofs,
        )
        changes.extend(identity_changes)
        conflicts.extend(identity_conflicts)
        before = {row.concept_id: row for row in normalized}
        for candidate in trace["candidates"]:
            row = before.pop(candidate["id"], None)
            if row and row.decision_origin == "reviewed":
                after = _image(row)
                if row.disposition == "accepted":
                    after["is_stale"] = not _fresh(row, source, candidate, proofs, REGISTRY)
            else:
                after = _auto_image(source, candidate)
            if _image(row) != after:
                changes.append(
                    {"problem_uuid": key, "concept_id": candidate["id"], "before": _image(row), "after": after},
                )
        for cid, row in before.items():
            after = _image(row)
            if row.decision_origin == "reviewed":
                if row.disposition == "accepted":
                    after["is_stale"] = not _fresh(row, source, None, proofs, REGISTRY)
            else:
                after.update(disposition="suggested", is_stale=True, reasons=["SOURCE_REMOVED"])
            if after != _image(row):
                changes.append({"problem_uuid": key, "concept_id": cid, "before": _image(row), "after": after})
    changes = _fold_changes(changes)
    report = {
        "version": 1,
        "registry_fingerprint": REGISTRY.fingerprint,
        "policy_version": POLICY["version"],
        "problems": len(sources),
        "changes": changes,
        "traces": traces,
        "conflicts": conflicts,
        "counts": dict(
            Counter(
                change["after"]["disposition"] if change["after"].get("is_current", True) else "superseded"
                for change in changes
            ),
        ),
        "identity_proposals": REGISTRY.identity_proposals(),
        "source_writes": 0,
    }
    report["assignment_fingerprint"] = digest(
        {key: [_image(row) for row in rows] for key, rows in sorted(records.items())},
    )
    report["comparison_basis"] = (
        "accepted_assignments" if include_records and storage_ready() and projection_enabled() else "legacy_mapping"
    )
    report["count_deltas"] = _count_deltas(
        sources,
        records,
        proofs,
        changes,
        legacy=report["comparison_basis"] == "legacy_mapping",
    )
    report["sha256"] = digest(report)
    return report


def review_problem_uuids(decisions):
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= MAX_BATCH:
        message = f"Select between 1 and {MAX_BATCH} assignments."
        raise AssignmentConflictError(message)
    if any(not isinstance(row, dict) for row in decisions):
        message = "Every review decision must be an object."
        raise AssignmentConflictError(message)
    return sorted({str(uuid_module.UUID(str(d["problem_uuid"]))) for d in decisions})


def preview_review(decisions, *, operation_id=None):
    uuids = review_problem_uuids(decisions)
    return build_review_preview(
        decisions,
        sources=load_sources(uuids),
        records=_records(uuids) if storage_ready() else {},
        proofs=published_solution_evidence(uuids),
        operation_id=operation_id,
    )


def build_review_preview(decisions, *, sources, records=None, proofs=None, operation_id=None):  # noqa: C901, PLR0912, PLR0915
    """Pure preview engine shared by live reads and verified native snapshot replay."""
    uuids = review_problem_uuids(decisions)
    if set(sources) != set(uuids):
        message = "A selected problem no longer exists."
        raise AssignmentConflictError(message)
    records = defaultdict(list, records or {})
    proofs = proofs or {}
    current = {(key, row.concept_id): row for key, rows in records.items() for row in rows}
    changes, normalized, touched = [], [], set()
    for decision in decisions:
        key = str(uuid_module.UUID(str(decision["problem_uuid"])))
        source = sources[key]
        metadata = decision.get("review_metadata") or {}
        if not isinstance(metadata, dict):
            message = "Review metadata must be an object."
            raise AssignmentConflictError(message)
        expected = metadata.get("statement_sha256")
        if metadata.get("origin") == "agent_assisted" and not expected:
            message = "Delegated review needs its full statement hash."
            raise AssignmentConflictError(message)
        if expected and expected != source["statement_hash"]:
            message = "The reviewed statement changed; refresh the expert decision before previewing."
            raise AssignmentConflictError(message)
        expected_uuid = metadata.get("source_statement_uuid")
        if expected_uuid and str(expected_uuid) != source.get("statement_uuid"):
            message = "The reviewed statement identity changed."
            raise AssignmentConflictError(message)
        cid = REGISTRY.canonical(str(decision["concept_id"]))
        action = decision.get("action")
        rationale = str(decision.get("rationale") or "").strip()
        if (
            cid not in REGISTRY.definitions
            or action not in {"confirm", "reject", "hold", "replace", "add"}
            or not rationale
        ):
            message = "Choose an existing concept, valid action and a rationale."
            raise AssignmentConflictError(message)
        if not source["active"] or source["conflicts"]:
            message = "Inactive or conflicting identities cannot receive review decisions."
            raise AssignmentConflictError(message)
        targets = [
            (cid, "rejected" if action in {"reject", "replace"} else "suggested" if action == "hold" else "accepted"),
        ]
        if action == "replace":
            target = REGISTRY.canonical(str(decision.get("replacement_concept_id") or ""))
            if target not in REGISTRY.definitions or target == cid:
                message = "Replacement must be another existing concept."
                raise AssignmentConflictError(message)
            targets.append((target, "accepted"))
        clean = {**decision, "problem_uuid": key, "concept_id": cid, "rationale": rationale}
        normalized.append(clean)
        trace = {c["id"]: c for c in trace_source(source)["candidates"]}
        for target, disposition in targets:
            if (key, target) in touched:
                message = "A batch contains conflicting actions for the same assignment."
                raise AssignmentConflictError(message)
            touched.add((key, target))
            candidate = trace.get(target)
            before = current.get((key, target))
            roles = sorted(set(decision.get("roles") or []))
            evidence = list(candidate["evidence"] if candidate else [])
            if disposition == "accepted":
                if not roles or not set(roles) <= set(ROLE_FIELDS):
                    message = "Confirmation requires at least one valid mathematical role."
                    raise AssignmentConflictError(message)
                evidence.append(_review_evidence(decision.get("evidence") or {}, source, proofs))
            else:
                roles = list(before.roles) if before else list(candidate["roles"] if candidate else [])
            context = str(decision.get("subject_context") or "")
            if context and context not in REGISTRY.definitions[target]["subjects"]:
                message = "The selected subject is not a membership of this concept."
                raise AssignmentConflictError(message)
            area_context = str(decision.get("area_context") or "")
            if area_context:
                try:
                    area = REGISTRY.presentation(target, context or source["subject"], area_context=area_context)
                except RegistryError as exc:
                    raise AssignmentConflictError(str(exc)) from exc
                if context and area["subject"] != context:
                    message = "Reviewed area and subject contexts disagree."
                    raise AssignmentConflictError(message)
            after = {
                "concept_id": target,
                "disposition": disposition,
                "decision_origin": "reviewed",
                "roles": roles,
                "subject_context": context,
                "area_context": area_context,
                "evidence": evidence,
                "reasons": ["HUMAN_REVIEW"],
                "source_fingerprint": source["source_fingerprint"],
                "concept_signature": REGISTRY.signature(target),
                "is_stale": False,
                "is_current": True,
                "rationale": rationale,
                "reviewed_by_id": None,
            }
            changes.append(
                {
                    "problem_uuid": key,
                    "concept_id": target,
                    "action": action,
                    "before": _image(before),
                    "after": after,
                },
            )
            for old in records[key]:
                if old.concept_id != target and REGISTRY.canonical(old.concept_id) == target:
                    retired = {**_image(old), "is_current": False}
                    changes.append(
                        {
                            "problem_uuid": key,
                            "concept_id": old.concept_id,
                            "action": "retire_identity",
                            "before": _image(old),
                            "after": retired,
                        },
                    )
    report = {
        "version": 1,
        "registry_fingerprint": REGISTRY.fingerprint,
        "decisions": normalized,
        "changes": changes,
        "conflicts": [],
        "source_writes": 0,
    }
    report["count_deltas"] = _count_deltas(sources, records, proofs, changes)
    report["sha256"] = digest(report)
    report["operation_id"] = str(uuid_module.UUID(str(operation_id))) if operation_id else str(uuid_module.uuid4())
    # Per-pair changes and union deltas are explicit; roles are not counted as assignments.
    report["assignment_delta"] = sum(
        c["after"]["disposition"] == "accepted" and c["after"].get("is_current", True) for c in changes
    ) - sum(
        c["before"].get("disposition") == "accepted"
        and c["before"].get("is_current", True)
        and not c["before"].get("is_stale")
        for c in changes
    )
    return report


def _state_lock():
    ConceptAssignmentState.objects.get_or_create(singleton_key=1)
    return ConceptAssignmentState.objects.select_for_update().get(singleton_key=1)


def _write_changes(report, batch, actor):
    for change in report["changes"]:
        key, cid = change["problem_uuid"], change["concept_id"]
        after = dict(change["after"])
        if actor is not None and after["decision_origin"] == "reviewed" and change.get("action") != "retire_identity":
            after["reviewed_by_id"] = actor.pk
        ProblemConceptAssignment.objects.update_or_create(problem_uuid=key, concept_id=cid, defaults=after)
        ConceptAssignmentReviewEvent.objects.create(
            batch=batch,
            problem_uuid=key,
            concept_id=cid,
            action=change.get("action", "refresh"),
            before=change["before"],
            after=after,
            actor=actor,
        )


def apply_review(report, actor):
    if not actor.is_authenticated or not actor.is_active or not user_has_admin_role(actor):
        raise PermissionDenied
    if not storage_ready():
        message = "Review storage is not installed; complete the schema prerequisite first."
        raise AssignmentConflictError(message)
    with transaction.atomic():
        state = _state_lock()
        previous = ConceptAssignmentReviewBatch.objects.filter(operation_id=report["operation_id"]).first()
        if previous:
            if (
                previous.preview_sha256 != report["sha256"]
                or previous.manifest.get("decisions") != report["decisions"]
            ):
                message = "This operation ID belongs to a different review."
                raise AssignmentConflictError(message)
            return previous.receipt
        fresh = preview_review(report["decisions"], operation_id=report["operation_id"])
        if fresh["sha256"] != report["sha256"]:
            message = "Evidence or assignment decisions changed. Generate a new preview."
            raise AssignmentConflictError(message)
        batch = ConceptAssignmentReviewBatch.objects.create(
            operation_id=report["operation_id"],
            preview_sha256=fresh["sha256"],
            registry_fingerprint=REGISTRY.fingerprint,
            manifest=fresh,
            actor=actor,
        )
        _write_changes(fresh, batch, actor)
        state.revision = F("revision") + 1
        state.save(update_fields=["revision", "updated_at"])
        receipt = {
            "operation_id": str(batch.operation_id),
            "status": "applied",
            "assignments_changed": len(fresh["changes"]),
            "source_writes": 0,
        }
        batch.receipt = receipt
        batch.save(update_fields=["receipt"])
        return receipt


def apply_refresh(report, *, operation_id=None):
    if report["problems"] > MAX_BATCH:
        message = "Refresh batches are limited to 250 problems."
        raise AssignmentConflictError(message)
    if report["conflicts"]:
        message = "Resolve identity conflicts before applying this batch."
        raise AssignmentConflictError(message)
    with transaction.atomic():
        state = _state_lock()
        if operation_id:
            previous = ConceptAssignmentReviewBatch.objects.filter(operation_id=operation_id).first()
            if previous:
                if previous.preview_sha256 != report["sha256"]:
                    message = "Operation ID already used for another report."
                    raise AssignmentConflictError(message)
                return previous.receipt
        sources = load_sources([trace["problem_uuid"] for trace in report["traces"]])
        fresh = audit_sources(sources)
        if fresh["sha256"] != report["sha256"]:
            message = "Source evidence changed since the reviewed audit."
            raise AssignmentConflictError(message)
        if not fresh["changes"]:
            return {"status": "unchanged", "assignments_changed": 0, "source_writes": 0}
        batch = ConceptAssignmentReviewBatch.objects.create(
            operation_id=operation_id or uuid_module.uuid4(),
            preview_sha256=fresh["sha256"],
            registry_fingerprint=REGISTRY.fingerprint,
            kind="refresh",
            manifest=fresh,
        )
        _write_changes(fresh, batch, None)
        state.revision = F("revision") + 1
        state.registry_fingerprint = REGISTRY.fingerprint
        state.save(update_fields=["revision", "registry_fingerprint", "updated_at"])
        receipt = {
            "operation_id": str(batch.operation_id),
            "status": "applied",
            "assignments_changed": len(fresh["changes"]),
            "source_writes": 0,
        }
        batch.receipt = receipt
        batch.save(update_fields=["receipt"])
        return receipt


def invalidate_assignments(uuids):
    if not getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False):
        return
    values = {value for value in uuids if value}
    if values:
        ProblemConceptAssignment.objects.filter(
            problem_uuid__in=values,
            disposition="accepted",
            is_current=True,
        ).update(is_stale=True)
        ConceptAssignmentState.objects.filter(singleton_key=1).update(needs_refresh=True, revision=F("revision") + 1)


def verify_seed():
    """An activation proof scans the complete active population in bounded batches."""
    values = list(source_uuid_query())
    conflicts, changes, fingerprints = [], 0, []
    for start in range(0, len(values), MAX_BATCH):
        report = audit_sources(load_sources(values[start : start + MAX_BATCH]))
        changes += len(report["changes"])
        fingerprints.append(report["sha256"])
        conflicts.extend(report["conflicts"])
    return {
        "problems": len(values),
        "pending_changes": changes,
        "batch_fingerprints": fingerprints,
        "conflicts": conflicts,
        "registry_fingerprint": REGISTRY.fingerprint,
    }


def accepted_problem_ids(concept_ids):
    """Explicit canonical filters use the same fresh projection as displayed counts."""
    values = [concept_ids] if isinstance(concept_ids, str) else concept_ids
    canonical = {REGISTRY.canonical(value) for value in values} & REGISTRY.definitions.keys()
    aliases = [cid for cid in [*REGISTRY.definitions, *REGISTRY.redirects] if REGISTRY.canonical(cid) in canonical]
    uuids = list(
        ProblemConceptAssignment.objects.filter(concept_id__in=aliases, disposition="accepted", is_current=True)
        .values_list("problem_uuid", flat=True)
        .distinct(),
    )
    accepted = []
    for start in range(0, len(uuids), MAX_BATCH):
        payloads = projection_payloads(load_sources(uuids[start : start + MAX_BATCH]))
        accepted.extend(
            key for key, payload in payloads.items() if any(c["id"] in canonical for c in payload["concept_coverage"])
        )
    return accepted


def observed_area_memberships(library):
    result = defaultdict(list)
    for problem in library.values():
        for concept in problem["concept_coverage"]:
            area = {"subject": concept["subject"], "area": concept["area_id"], "label": concept["area"]}
            if area not in result[concept["id"]]:
                result[concept["id"]].append(area)
    return result


def catalogue_definitions(subject="", area="", *, observed=None):
    """One identity, with its area selected in the requested subject context."""
    result = {}
    for cid, definition in REGISTRY.definitions.items():
        memberships = [*definition["area_memberships"]]
        memberships.extend(a for a in (observed or {}).get(cid, []) if a not in memberships)
        eligible = [
            a
            for a in memberships
            if (not subject or a["subject"] == subject) and (not area or f"{a['subject']}:{a['area']}" == area)
        ]
        if not eligible:
            continue
        chosen = eligible[0]
        result[cid] = {
            **definition,
            "area_memberships": memberships,
            "subject": chosen["subject"],
            "area": chosen["area"],
            "area_label": chosen["label"],
            "area_keys": [f"{a['subject']}:{a['area']}" for a in memberships],
        }
    return result


def activate_projection(expected_sha, *, enable=True, operation_id=None):
    with transaction.atomic():
        state = _state_lock()
        if operation_id:
            previous = ConceptAssignmentReviewBatch.objects.filter(operation_id=operation_id).first()
            if previous:
                if (
                    previous.kind != "activation"
                    or previous.preview_sha256 != expected_sha
                    or previous.manifest.get("enable") != enable
                ):
                    message = "Activation operation ID was already used for a different request."
                    raise AssignmentConflictError(message)
                return previous.receipt
        verification = verify_seed() if enable else {"revision": state.revision, "enabled": state.enabled}
        if digest(verification) != expected_sha:
            message = "Activation evidence changed; verify the seed again."
            raise AssignmentConflictError(message)
        if enable and (verification["pending_changes"] or verification["conflicts"]):
            message = "The complete seed must be current and conflict-free before activation."
            raise AssignmentConflictError(message)
        if enable and not getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False):
            message = "Enable the deployment setting only after the schema prerequisite is complete."
            raise AssignmentConflictError(message)
        state.enabled = enable
        state.initial_seed_complete = enable or state.initial_seed_complete
        state.registry_fingerprint = REGISTRY.fingerprint
        state.needs_refresh = False
        state.revision = F("revision") + 1
        state.save()
        receipt = {"status": "projection_enabled" if enable else "projection_disabled", "source_writes": 0}
        ConceptAssignmentReviewBatch.objects.create(
            operation_id=operation_id or uuid_module.uuid4(),
            preview_sha256=expected_sha,
            registry_fingerprint=REGISTRY.fingerprint,
            kind="activation",
            manifest={"verification": verification, "enable": enable},
            receipt=receipt,
        )
        return receipt


def refresh_current_projection():
    if not projection_enabled():
        return {"changes": 0, "conflicts": 0}
    values = list(source_uuid_query())
    changed, conflicts = 0, 0
    for start in range(0, len(values), MAX_BATCH):
        sources = load_sources(values[start : start + MAX_BATCH])
        conflicts += sum(bool(s["conflicts"]) for s in sources.values())
        valid = {key: source for key, source in sources.items() if not source["conflicts"]}
        report = audit_sources(valid)
        changed += apply_refresh(report)["assignments_changed"]
    ConceptAssignmentState.objects.filter(singleton_key=1).update(needs_refresh=bool(conflicts))
    return {"changes": changed, "conflicts": conflicts}
