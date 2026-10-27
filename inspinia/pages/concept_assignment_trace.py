"""Read-only provenance and selective acceptance across all four subjects."""

from django.db.models import Q

from inspinia.pages.concept_alias_policy import ROLE_FIELDS
from inspinia.pages.concept_alias_policy import SUBJECT_CODES
from inspinia.pages.concept_alias_policy import caption_key
from inspinia.pages.concept_alias_policy import source_subjects
from inspinia.pages.concept_assignment_registry import POLICY
from inspinia.pages.concept_assignment_registry import REASON_LABELS
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.technique_concepts import SUBJECT_LABELS

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


def subject_label(value):
    return SUBJECT_LABELS.get(str(value or "").strip().casefold(), "")


def source_uuid_query(*, subject="", year="", contest="", q="", include_inactive=False, exclude_uuids=None):  # noqa: PLR0913
    statements = ContestProblemStatement.objects.all()
    problems = ProblemSolveRecord.objects.filter(statement_entries__isnull=True)
    if not include_inactive:
        statements = statements.filter(is_active=True)
        problems = problems.filter(is_active=True)
    if subject:
        codes = SUBJECT_CODES[subject_label(subject)]
        statements = statements.filter(
            Q(topic__iregex="^(" + "|".join(codes) + ")$")
            | ((Q(topic="") | Q(topic__isnull=True)) & Q(linked_problem__topic__iregex="^(" + "|".join(codes) + ")$")),
        )
        problems = problems.filter(topic__iregex="^(" + "|".join(codes) + ")$")
    if year:
        statements = statements.filter(contest_year=int(year))
        problems = problems.filter(year=int(year))
    if contest:
        statements = statements.filter(contest_name__icontains=contest)
        problems = problems.filter(contest__icontains=contest)
    if q:
        statements = statements.filter(
            Q(contest_year_problem__icontains=q)
            | Q(contest_name__icontains=q)
            | Q(problem_code__icontains=q)
            | Q(problem_uuid__icontains=q)
            | Q(topic_tags__icontains=q),
        )
        problems = problems.filter(
            Q(contest_year_problem__icontains=q)
            | Q(contest__icontains=q)
            | Q(problem_uuid__icontains=q)
            | Q(topic_tags__icontains=q),
        )
    if exclude_uuids is not None:
        statements = statements.exclude(problem_uuid__in=exclude_uuids)
        problems = problems.exclude(problem_uuid__in=exclude_uuids)
    return (
        statements.order_by()
        .values_list("problem_uuid", flat=True)
        .union(problems.order_by().values_list("problem_uuid", flat=True))
        .order_by("problem_uuid")
    )


def _tag_snapshot(tag):
    result = {}
    for key in TAG_FIELDS:
        value = tag.get(key) or ([] if key in ROLE_FIELDS.values() and key.endswith("s") else "")
        result[key] = sorted(str(item) for item in value) if isinstance(value, list) else str(value)
    return result


def source_fingerprint(source):
    return digest(
        {
            "uuid": source["problem_uuid"],
            "subject": source["subject"],
            "active": source["active"],
            "source_owner_active": source.get("source_owner_active", source["active"]),
            "effective_source": source["effective_source"],
            "tags": sorted([_tag_snapshot(t) for t in source["tags"]], key=lambda t: digest(t)),
        },
    )


def load_sources(uuids):
    from inspinia.pages.concept_assignment_source_export import read_assignment_sources

    return read_assignment_sources(uuids)


def trace_source(source, registry=REGISTRY):  # noqa: C901, PLR0912
    candidates, unresolved, excluded = {}, [], []
    for tag in source["tags"]:
        status = caption_key(tag.get("normalization_status"))
        if (
            not source["active"]
            or not source.get("source_owner_active", True)
            or status in POLICY["suppressed_statuses"]
        ):
            excluded.append(
                {
                    "source_row_id": tag.get("id"),
                    "caption": tag["technique"],
                    "reason": "INACTIVE"
                    if not source["active"] or not source.get("source_owner_active", True)
                    else "SUPPRESSED_SOURCE",
                },
            )
            continue
        for role, field in ROLE_FIELDS.items():
            values = tag.get(field) or []
            values = values if isinstance(values, list) else [values]
            for value_index, caption in enumerate(values):
                decisions = [
                    (subject, registry.resolve(subject, role, caption, tag))
                    for subject in sorted(source_subjects(tag, source["subject"]))
                ]
                all_ids = {cid for _, decision in decisions for cid in decision["ids"]}
                if not all_ids:
                    unresolved.append(
                        {
                            "source_row_id": tag.get("id"),
                            "source_caption": tag["technique"],
                            "field": field,
                            "role": role,
                            "caption": caption,
                            "reason": "NO_CONFIRMED_ALIAS",
                        },
                    )
                for subject, decision in decisions:
                    for cid in decision["ids"]:
                        if cid not in registry.definitions:
                            continue
                        reasons = []
                        if caption_key(caption) in {
                            caption_key(value) for value in POLICY.get("ambiguous_captions", [])
                        }:
                            reasons.append("CAPTION_SCOPE_REVIEW")
                        if role != "technique":
                            reasons.append("STRUCTURED_ONLY")
                        if decision["resolution"] != "EXACT":
                            reasons.append("CONTEXT_REQUIRED")
                        if len(all_ids) > 1:
                            reasons.append("AMBIGUOUS_IDENTITY")
                        if status in POLICY["review_statuses"]:
                            reasons.append("SOURCE_NEEDS_REVIEW")
                        if source["subject"] not in registry.definitions[cid]["subjects"]:
                            reasons.append("CROSS_SUBJECT")
                        if any(registry.canonical(specialist) == cid for specialist in POLICY["specialist_concepts"]):
                            reasons.append("SPECIALIST_REVIEW")
                        reasons.extend(source["conflicts"])
                        direct = not reasons
                        entry = {
                            "source_model": "StatementTopicTechnique"
                            if source["effective_source"] == "statement"
                            else "ProblemTopicTechnique",
                            "source_row_id": tag.get("id"),
                            "source_caption": tag["technique"],
                            "field": field,
                            "value_index": value_index if isinstance(tag.get(field), list) else None,
                            "caption": caption,
                            "role": role,
                            "subject": subject,
                            "rule": decision["rule"],
                            "resolution": decision["resolution"],
                            "direct": direct,
                            "reasons": sorted(set(reasons)),
                            "source_fingerprint": digest(_tag_snapshot(tag)),
                        }
                        row = candidates.setdefault(
                            cid,
                            {
                                **registry.presentation(cid, source["subject"]),
                                "evidence": [],
                                "reasons": [],
                                "auto_eligible": False,
                                "accepted_roles": [],
                            },
                        )
                        row["evidence"].append(entry)
                        row["roles"] = sorted({*row["roles"], role})
                        row["reasons"] = sorted({*row["reasons"], *reasons})
                        row["auto_eligible"] |= direct
                        if direct:
                            row["accepted_roles"] = sorted({*row["accepted_roles"], role})
    for row in candidates.values():
        row["reason_labels"] = [REASON_LABELS.get(reason, reason) for reason in row["reasons"]]
        row["concept_signature"] = registry.signature(row["id"])
        row["disposition"] = "accepted" if row["auto_eligible"] else "suggested"
        row["support_basis"] = "Exact legacy tag" if row["auto_eligible"] else "Needs evidence review"
    return {
        "problem_uuid": source["problem_uuid"],
        "label": source["label"],
        "subject": source["subject"],
        "active": source["active"],
        "source_fingerprint": source["source_fingerprint"],
        "effective_source": source["effective_source"],
        "candidates": sorted(candidates.values(), key=lambda c: (c["label"].casefold(), c["id"])),
        "unresolved": unresolved,
        "excluded": excluded,
        "conflicts": source["conflicts"],
    }
