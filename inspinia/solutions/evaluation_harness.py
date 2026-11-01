"""Evaluate supplied synthetic assessments locally, using only the standard library.

Run with python -m inspinia.solutions.evaluation_harness. No Django startup,
database access, provider import, network request, or approval promotion occurs.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from inspinia.solutions.evaluation_contracts import ASSESSMENTS
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import canonical_digest
from inspinia.solutions.evaluation_contracts import integer
from inspinia.solutions.evaluation_contracts import keys
from inspinia.solutions.evaluation_contracts import load_json_file
from inspinia.solutions.evaluation_contracts import package_digest
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import text

SPLITS = {"development", "held_out"}
STATUSES = {"completed", "refused", "failed", "incomplete"}
SCORE_STATUSES = {"provided", "human_review_required", "unavailable"}
MAX_CASES = 1000
MAX_FINDINGS = 100


def case_input_digest(case, package):
    """Bind candidate output to input, without including target labels in model input."""
    return canonical_digest(
        {
            "case_id": case["id"],
            "package_digest": package["digest"],
            "submission": case["submission"],
        },
    )


def _dataset_packages(dataset):
    require(keys(dataset, "schema_version provenance packages cases"), "Invalid dataset fields.")
    require(type(dataset["schema_version"]) is int and dataset["schema_version"] == 1, "Use dataset schema version 1.")
    require(dataset["provenance"] == "synthetic_unapproved", "Phase 1 accepts only unapproved synthetic examples.")
    packages = dataset["packages"]
    require(isinstance(packages, list) and 0 < len(packages) <= MAX_CASES, "Supply a bounded list of packages.")
    result, versions = {}, set()
    for package in packages:
        require(
            keys(package, "id problem_id version content digest") and text(package["id"]),
            "Invalid package envelope.",
        )
        require(package["id"] not in result, "Package identifiers must be unique.")
        digest = package_digest(package["problem_id"], package["version"], package["content"])
        require(package["digest"] == digest, "A package does not match its frozen digest.")
        identity = (package["problem_id"], package["version"])
        require(identity not in versions, "A problem/package version may appear only once.")
        versions.add(identity)
        result[package["id"]] = package
    return result


def validate_labels(labels, package):
    require(
        keys(labels, "assessment critical_error alternative_method score human_review_required"),
        "Invalid seed labels.",
    )
    require(isinstance(labels["assessment"], str) and labels["assessment"] in ASSESSMENTS, "Invalid assessment label.")
    require(
        all(type(labels[key]) is bool for key in ("critical_error", "alternative_method", "human_review_required")),
        "Seed flags must be booleans.",
    )
    require(
        not labels["critical_error"] or labels["assessment"] == "gap_found",
        "Critical errors must be labelled gaps.",
    )
    rubric = package["content"]["rubric"]
    score = labels["score"]
    require(score is None or (rubric is not None and integer(score, 0, rubric["max_score"])), "Invalid target score.")
    require(not labels["human_review_required"] or score is None, "Unresolved seed cases cannot have a target score.")
    require(
        labels["assessment"] != "unable_to_assess" or (score is None and labels["human_review_required"]),
        "Unassessable seed cases require human review and no target score.",
    )


def validate_dataset(dataset):
    packages = _dataset_packages(dataset)
    cases = dataset["cases"]
    require(isinstance(cases, list) and 0 < len(cases) <= MAX_CASES, "Supply a bounded nonempty case list.")
    identifiers, problem_splits = set(), {}
    for case in cases:
        require(keys(case, "id package_id split submission candidate_labels input_digest"), "Invalid case fields.")
        require(text(case["id"]) and case["id"] not in identifiers, "Case identifiers must be unique.")
        require(isinstance(case["package_id"], str) and case["package_id"] in packages, "Unknown case package.")
        require(isinstance(case["split"], str) and case["split"] in SPLITS, "Invalid dataset split.")
        package = packages[case["package_id"]]
        problem_id = package["problem_id"]
        previous_split = problem_splits.setdefault(problem_id, case["split"])
        require(previous_split == case["split"], "Split by problem: one problem cannot occur in both splits.")
        require(
            keys(case["submission"], "body_source") and text(case["submission"]["body_source"]),
            "Phase 1 cases require a text submission.",
        )
        validate_labels(case["candidate_labels"], package)
        require(
            case["input_digest"] == case_input_digest(case, package),
            "A submission does not match its input digest.",
        )
        identifiers.add(case["id"])
    require(set(problem_splits.values()) == SPLITS, "Include distinct development and held-out problems.")
    return packages


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize_metrics(rows):
    completed = [row for row in rows if row["completed"]]
    valid = [row for row in rows if row["expected"] == "no_issues_found"]
    invalid = [row for row in rows if row["expected"] in {"gap_found", "incomplete"}]
    critical = [row for row in rows if row["critical"]]
    scores = [row["score_error"] for row in rows if row["score_error"] is not None]
    eligible_scores = sum(row["score_eligible"] for row in rows)
    grounded = sum(row["grounded_findings"] for row in rows)
    finding_count = sum(row["finding_count"] for row in rows)
    return {
        "total": len(rows),
        "completed": len(completed),
        "category_agreement": _rate(sum(row["matches"] for row in rows), len(rows)),
        "critical_cases": len(critical),
        "critical_error_detection_rate": _rate(
            sum(row["assessment"] == "gap_found" for row in critical),
            len(critical),
        ),
        "critical_false_acceptance_count": sum(row["assessment"] == "no_issues_found" for row in critical),
        "valid_cases": len(valid),
        "false_criticism_rate": _rate(
            sum(row["assessment"] in {"gap_found", "incomplete"} for row in valid),
            len(valid),
        ),
        "invalid_cases": len(invalid),
        "false_acceptance_rate": _rate(sum(row["assessment"] == "no_issues_found" for row in invalid), len(invalid)),
        "finding_count": finding_count,
        "source_grounding_rate": _rate(grounded, finding_count),
        "score_eligible_cases": eligible_scores,
        "scored_cases": len(scores),
        "score_coverage": _rate(len(scores), eligible_scores),
        "score_mae": _rate(sum(scores), len(scores)),
        "scores_without_target_count": sum(row["score_without_target"] for row in rows),
        "scores_requiring_human_review_count": sum(row["scored_despite_required_review"] for row in rows),
        "human_review_required_count": sum(row["escalated"] for row in rows),
        "required_escalation_cases": sum(row["escalation_expected"] for row in rows),
        "required_escalation_recall": _rate(
            sum(row["escalated"] and row["escalation_expected"] for row in rows),
            sum(row["escalation_expected"] for row in rows),
        ),
    }


def _findings(report, source):
    findings = report["findings"]
    require(isinstance(findings, list) and len(findings) <= MAX_FINDINGS, "Supply a bounded findings list.")
    grounded = 0
    for finding in findings:
        require(keys(finding, "source_quote explanation") and text(finding["explanation"]), "Invalid finding.")
        quote = finding["source_quote"]
        require(isinstance(quote, str), "Finding quotations must be text.")
        grounded += int(bool(quote.strip()) and quote in source)
    return grounded


def assessment_metric_row(report, case, package):
    require(
        keys(report, "case_id input_digest status assessment findings score_status score human_review_required"),
        "Invalid report fields.",
    )
    require(report["input_digest"] == case["input_digest"], "A report targets a different submission or package.")
    require(isinstance(report["status"], str) and report["status"] in STATUSES, "Invalid report status.")
    require(type(report["human_review_required"]) is bool, "Escalation must be a boolean.")
    completed = report["status"] == "completed"
    assessment = report["assessment"]
    require(
        (isinstance(assessment, str) and assessment in ASSESSMENTS) if completed else assessment is None,
        "Only completed reports may have an assessment.",
    )
    require(
        isinstance(report["score_status"], str) and report["score_status"] in SCORE_STATUSES,
        "Invalid score status.",
    )
    score, rubric = report["score"], package["content"]["rubric"]
    if report["score_status"] == "provided":
        require(
            completed and rubric is not None and integer(score, 0, rubric["max_score"]),
            "Invalid candidate score.",
        )
        require(not report["human_review_required"], "An unresolved report cannot supply a score.")
        require(assessment != "unable_to_assess", "An unassessable report cannot supply a score.")
    else:
        require(score is None, "An unavailable or escalated score must be null.")
    require(
        report["score_status"] != "human_review_required" or report["human_review_required"],
        "Escalated scoring must also flag human review.",
    )
    grounded = _findings(report, case["submission"]["body_source"])
    require(completed or not report["findings"], "Failed reports cannot contain completed findings.")
    require(
        assessment != "no_issues_found" or not report["findings"],
        "A no-issues assessment cannot also list defects.",
    )
    labels = case["candidate_labels"]
    expected_score = labels["score"]
    return {
        "case_id": case["id"],
        "domain": package["content"]["domain"],
        "completed": completed,
        "expected": labels["assessment"],
        "assessment": assessment,
        "matches": completed and assessment == labels["assessment"],
        "critical": labels["critical_error"],
        "alternative": labels["alternative_method"],
        "escalated": report["human_review_required"],
        "escalation_expected": labels["human_review_required"],
        "grounded_findings": grounded,
        "finding_count": len(report["findings"]),
        "score_eligible": expected_score is not None,
        "score_without_target": score is not None and expected_score is None,
        "scored_despite_required_review": score is not None and labels["human_review_required"],
        "score_error": abs(score - expected_score) if score is not None and expected_score is not None else None,
    }


def evaluate_assessments(dataset, reports, *, split="held_out"):
    require(split in SPLITS, "Select development or held_out.")
    packages = validate_dataset(dataset)
    require(
        keys(reports, "schema_version producer reports")
        and type(reports["schema_version"]) is int
        and reports["schema_version"] == 1,
        "Use report schema version 1.",
    )
    require(text(reports["producer"]), "Identify the report producer; fixture results are not model measurements.")
    require(isinstance(reports["reports"], list), "Supply a reports list.")
    # Validate the entire file even when measuring only one split.
    cases = {case["id"]: case for case in dataset["cases"]}
    rows, seen = [], set()
    for report in reports["reports"]:
        require(isinstance(report, dict) and text(report.get("case_id")), "Each report needs a case identifier.")
        identifier = report["case_id"]
        require(identifier in cases and identifier not in seen, "Reports must target distinct known cases.")
        case = cases[identifier]
        row = assessment_metric_row(report, case, packages[case["package_id"]])
        if case["split"] == split:
            rows.append(row)
        seen.add(identifier)
    selected = {case["id"] for case in cases.values() if case["split"] == split}
    require(selected <= seen, "Missing reports cannot be omitted from the selected split.")
    return {
        "schema_version": 1,
        "split": split,
        "provenance": "synthetic_unapproved",
        "producer": reports["producer"],
        "human_validated": False,
        "release_gate_passed": False,
        "notice": (
            "Synthetic fixture metrics test the harness only; they do not establish mathematical or model reliability."
        ),
        "dataset_digest": canonical_digest(dataset),
        "reports_digest": canonical_digest(reports),
        "metrics": summarize_metrics(rows),
        "by_domain": {
            domain: summarize_metrics([row for row in rows if row["domain"] == domain])
            for domain in sorted({row["domain"] for row in rows})
        },
        "alternative_methods": summarize_metrics([row for row in rows if row["alternative"]]),
        "provider_failures": dict(
            Counter(
                report["status"]
                for report in reports["reports"]
                if report["case_id"] in selected and report["status"] != "completed"
            ),
        ),
        "critical_false_acceptance_cases": [
            row["case_id"] for row in rows if row["critical"] and row["assessment"] == "no_issues_found"
        ],
        "ungrounded_finding_cases": [
            row["case_id"] for row in rows if row["grounded_findings"] != row["finding_count"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--split", choices=sorted(SPLITS), default="held_out")
    options = parser.parse_args()
    try:
        result = evaluate_assessments(
            load_json_file(options.dataset),
            load_json_file(options.reports),
            split=options.split,
        )
    except (EvaluationDataError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, allow_nan=False))  # noqa: T201 - Local CLI output.


if __name__ == "__main__":
    main()
