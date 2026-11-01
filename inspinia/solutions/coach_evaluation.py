"""Offline coach-labelled evaluation. This module never contacts a provider."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime

ASSESSMENTS = {"no_issues_found", "gap_found", "incomplete", "unable_to_assess"}
DOMAINS = {"ALG", "GEO", "NT", "COM"}
SPLIT_COUNTS = {"development": 20, "held_out": 60}
MIN_AGREEMENT = 0.90
TOTAL_CASES = 80
CASES_PER_DOMAIN = 20
MAX_FILE_BYTES = 1_048_576


class CoachEvaluationError(ValueError):
    pass


def canonical_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def approval_digest(case):
    """Bind a coach's approval to the exact mathematical input and label."""
    return canonical_digest(
        {
            key: case[key]
            for key in (
                "id",
                "domain",
                "split",
                "problem_statement",
                "body_source",
                "expected_assessment",
                "critical_error",
            )
        },
    )


def load_json_file(path):
    with path.open("rb") as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        message = "Evaluation files must be at most 1 MB."
        raise CoachEvaluationError(message)
    try:
        return json.loads(content)
    except (ValueError, UnicodeError) as error:
        message = "The evaluation file must contain valid JSON."
        raise CoachEvaluationError(message) from error


def _validate_dataset(dataset):
    if not isinstance(dataset, dict) or dataset.get("schema_version") != 1:
        message = "Use a version 1 coach evaluation dataset."
        raise CoachEvaluationError(message)
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != TOTAL_CASES:
        message = "The complete evaluation dataset must contain 80 cases."
        raise CoachEvaluationError(message)
    seen = set()
    for case in cases:
        if not _valid_case(case) or case["id"] in seen:
            message = "Evaluation cases must have unique identifiers and valid mathematical inputs."
            raise CoachEvaluationError(message)
        seen.add(case["id"])
    if Counter(case["domain"] for case in cases) != Counter(dict.fromkeys(DOMAINS, CASES_PER_DOMAIN)):
        message = "Include 20 cases in each of ALG, GEO, NT, and COM."
        raise CoachEvaluationError(message)
    if Counter(case["split"] for case in cases) != Counter(SPLIT_COUNTS):
        message = "Keep the fixed 20 development and 60 held-out cases."
        raise CoachEvaluationError(message)
    return cases


def _valid_case(case):
    return (
        isinstance(case, dict)
        and isinstance(case.get("id"), str)
        and bool(case["id"])
        and isinstance(case.get("domain"), str)
        and case["domain"] in DOMAINS
        and isinstance(case.get("split"), str)
        and case["split"] in SPLIT_COUNTS
        and isinstance(case.get("problem_statement"), str)
        and bool(case["problem_statement"].strip())
        and isinstance(case.get("body_source"), str)
        and bool(case["body_source"].strip())
        and type(case.get("critical_error")) is bool
    )


def _require_approval(case):
    expected = case.get("expected_assessment")
    if (
        case.get("label_status") != "coach_approved"
        or not isinstance(expected, str)
        or expected not in ASSESSMENTS
        or not isinstance(case.get("reviewed_by"), str)
        or not case["reviewed_by"].strip()
        or case.get("approval_digest") != approval_digest(case)
    ):
        message = "Selected labels require explicit coach approval bound to the exact inputs."
        raise CoachEvaluationError(message)
    try:
        reviewed_at = datetime.fromisoformat(case.get("reviewed_at", ""))
        if reviewed_at.tzinfo is None:
            message = "Coach review timestamps must include a timezone."
            raise CoachEvaluationError(message)
    except (ValueError, TypeError) as error:
        message = "Every approved case needs a valid coach review timestamp."
        raise CoachEvaluationError(message) from error
    if case["critical_error"] and expected == "no_issues_found":
        message = "A critical-error label cannot also assert that no issue is present."
        raise CoachEvaluationError(message)


def _reports_by_id(reports, selected):
    if (
        not isinstance(reports, dict)
        or reports.get("schema_version") != 1
        or not isinstance(reports.get("reports"), list)
    ):
        message = "Use version 1 externally supplied evaluation reports."
        raise CoachEvaluationError(message)
    mapped = {}
    for report in reports["reports"]:
        if not isinstance(report, dict) or not isinstance(report.get("case_id"), str):
            message = "Each evaluation report needs a case identifier."
            raise CoachEvaluationError(message)
        identifier = report["case_id"]
        if identifier not in selected or identifier in mapped:
            message = "Reports must contain each selected case exactly once, with no extra cases."
            raise CoachEvaluationError(message)
        status = report.get("status", "completed")
        if not isinstance(status, str) or status not in {"completed", "refused", "failed", "incomplete"}:
            message = "Evaluation reports have an unsupported completion status."
            raise CoachEvaluationError(message)
        assessment = report.get("assessment")
        if status == "completed" and (not isinstance(assessment, str) or assessment not in ASSESSMENTS):
            message = "Completed reports require one of the four assessment categories."
            raise CoachEvaluationError(message)
        mapped[identifier] = report
    if set(mapped) != set(selected):
        message = "Missing reports cannot be omitted from evaluation."
        raise CoachEvaluationError(message)
    return mapped


def evaluate_reports(dataset, reports, *, split="held_out"):
    if split not in SPLIT_COUNTS:
        message = "Evaluate either development or held_out."
        raise CoachEvaluationError(message)
    cases = _validate_dataset(dataset)
    selected = {case["id"]: case for case in cases if case["split"] == split}
    for case in selected.values():
        _require_approval(case)
    mapped = _reports_by_id(reports, selected)
    correct = 0
    critical_false_clears = []
    by_domain = {domain: {"total": 0, "correct": 0} for domain in sorted(DOMAINS)}
    by_category = {category: {"total": 0, "correct": 0} for category in sorted(ASSESSMENTS)}
    failures = Counter()
    for identifier, case in selected.items():
        report = mapped[identifier]
        status = report.get("status", "completed")
        matches = status == "completed" and report.get("assessment") == case["expected_assessment"]
        correct += int(matches)
        by_domain[case["domain"]]["total"] += 1
        by_domain[case["domain"]]["correct"] += int(matches)
        by_category[case["expected_assessment"]]["total"] += 1
        by_category[case["expected_assessment"]]["correct"] += int(matches)
        if status != "completed":
            failures[status] += 1
        if case["critical_error"] and status == "completed" and report.get("assessment") == "no_issues_found":
            critical_false_clears.append(identifier)
    agreement = correct / len(selected)
    return {
        "schema_version": 1,
        "split": split,
        "total": len(selected),
        "correct": correct,
        "category_agreement": agreement,
        "minimum_agreement": MIN_AGREEMENT,
        "critical_false_clear_count": len(critical_false_clears),
        "critical_false_clear_cases": critical_false_clears,
        "by_domain": by_domain,
        "by_category": by_category,
        "provider_failures": dict(failures),
        "dataset_digest": canonical_digest(list(selected.values())),
        "reports_digest": canonical_digest(reports),
        "release_gate_passed": split == "held_out" and agreement >= MIN_AGREEMENT and not critical_false_clears,
        "labels": "coach_approved",
        "evidence_origin": "unverified_import",
        "model_readiness": False,
        "activation_authorized": False,
    }
