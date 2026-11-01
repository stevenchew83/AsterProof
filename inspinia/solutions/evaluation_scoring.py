"""Pure offline mathematical feedback scoring; scores never grant model readiness.

Inputs are already-frozen manifests, model reports and authenticated human
judgments supplied by a caller. This module cannot authenticate those inputs or
establish that a provider ran. Every eligible case must have an explicit report
and judgment, including failed, unattempted and abstained cases.
"""

from __future__ import annotations

import math
from collections import Counter
from collections import defaultdict

from .coach_evaluation import ASSESSMENTS
from .coach_evaluation import DOMAINS

REPORT_STATUSES = {
    "completed",
    "not_attempted",
    "refused",
    "failed",
    "incomplete",
    "timeout",
    "outcome_unknown",
    "cancelled",
}
SIGNIFICANCES = {"minor", "consequential", "fatal", "critical", "major"}
FINDING_CHECKS = ("supported", "material", "localization_correct", "severity_correct", "context_correct")
DIAGNOSIS_CHECKS = ("supported", "localization_correct", "severity_correct", "context_correct")
REQUIRED_THRESHOLDS = ("min_usable_coverage", "min_finding_precision", "min_defect_recall")
RELATION_KINDS = {"same_assessment", "different_assessment", "same_dimension", "target_assessment"}
COUNT_FIELDS = (
    "eligible", "attempted", "completed", "substantive", "useful", "category_correct", "findings",
    "critical_errors_eligible", "critical_errors_judged", "critical_errors_identified", "critical_errors_missed",
    "critical_false_clears", "valid_proofs_eligible", "valid_proofs_judged", "valid_proof_false_accusations",
    "valid_alternatives_eligible", "valid_alternatives_judged", "valid_alternative_false_accusations",
    "cleared", "flawed_cleared", "missing_input_false_clears", "material_findings", "supported_material_findings",
    "sound_material_findings", "unsupported_material_findings", "material_defects", "identified_material_defects",
    "correct_material_hints", "unsound_material_hints", "spoiler_violations", "full_report_spoiler_checks",
    "abstentions", "abstentions_judged", "appropriate_abstentions",
)


class EvaluationScoringError(ValueError):
    """The frozen scoring input is missing, inconsistent or malformed."""


def _require(condition, message):
    if not condition:
        raise EvaluationScoringError(message)


def _identifier(value):
    return isinstance(value, str) and bool(value.strip())


def _boolean_fields(value, fields, context):
    _require(all(type(value.get(field)) is bool for field in fields), f"{context} needs boolean judgments.")


def _unique_ids(rows, context):
    _require(isinstance(rows, list), f"{context} must be a list.")
    identifiers = []
    for row in rows:
        _require(isinstance(row, dict) and _identifier(row.get("id")), f"{context} needs nonempty identifiers.")
        identifiers.append(row["id"])
    _require(len(set(identifiers)) == len(identifiers), f"{context} identifiers must be unique.")
    return set(identifiers)


def _validate_cases(cases):
    _unique_ids(cases, "Cases")
    for case in cases:
        _require(_identifier(case.get("family_id")), "Every case needs a problem-family identifier.")
        _require(_identifier(case.get("domain")) and case["domain"] in DOMAINS, "Every case needs a supported domain.")
        _require(
            _identifier(case.get("expected_assessment")) and case["expected_assessment"] in ASSESSMENTS,
            "Every case needs an expected assessment.",
        )
        _boolean_fields(case, ("critical_error", "valid_alternative", "input_complete"), "Every case")
        _unique_ids(case.get("defects"), "Case defects")
        for defect in case["defects"]:
            _require(
                _identifier(defect.get("significance")) and defect["significance"] in SIGNIFICANCES,
                "Every defect needs a supported significance.",
            )
        material = [defect for defect in case["defects"] if defect["significance"] != "minor"]
        clear = case["expected_assessment"] == "no_issues_found"
        _require(not clear or not material, "A valid proof cannot have a labelled material defect.")
        _require(not clear or case["input_complete"], "Missing essential input cannot support a positive label.")
        _require(not case["critical_error"] or (material and not clear), "A critical case needs a material defect.")
        _require(not case["valid_alternative"] or clear, "Verified alternatives must be labelled valid proofs.")


def _validate_report(report):
    _require(isinstance(report, dict), "Every report must be an object.")
    _require(
        _identifier(report.get("status")) and report["status"] in REPORT_STATUSES,
        "Every report needs an explicit supported status.",
    )
    finding_ids = _unique_ids(report.get("findings", []), "Report findings")
    if report["status"] == "completed":
        _require(
            _identifier(report.get("assessment")) and report["assessment"] in ASSESSMENTS,
            "Completed reports need a supported assessment.",
        )
        if report["assessment"] == "unable_to_assess":
            _require(_identifier(report.get("abstention_reason")), "Abstentions need an explicit reason.")
    else:
        _require(not finding_ids and report.get("assessment") is None, "Uncompleted reports cannot assert feedback.")
    return finding_ids


def _validate_judgment(judgment, finding_ids, defect_ids):
    _require(isinstance(judgment, dict), "Every case needs a human-judgment object.")
    _boolean_fields(judgment, ("useful",), "Case judgment")
    rows = judgment.get("findings")
    _require(isinstance(rows, list), "Finding judgments must be a list.")
    seen = set()
    for row in rows:
        _require(isinstance(row, dict), "Every finding judgment must be an object.")
        identifier = row.get("finding_id")
        _require(_identifier(identifier) and identifier not in seen, "Finding judgments need unique identifiers.")
        seen.add(identifier)
        _boolean_fields(row, (*FINDING_CHECKS, "hint_correct", "spoiler"), "Finding judgment")
        matched = row.get("matched_defect_ids")
        _require(isinstance(matched, list), "Matched defect identifiers must be a list.")
        _require(all(_identifier(item) for item in matched), "Matched defects need nonempty identifiers.")
        _require(len(set(matched)) == len(matched), "Matched defect identifiers must be unique.")
        _require(set(matched) <= defect_ids, "A finding cannot match a defect from another case.")
    _require(seen == finding_ids, "Judge every reported finding exactly once, without additional findings.")
    for field in ("abstention_appropriate", "report_spoiler"):
        if field in judgment:
            _boolean_fields(judgment, (field,), "Case judgment")


def _validate_inputs(cases, reports, judgments):
    _validate_cases(cases)
    selected = {case["id"] for case in cases}
    _require(isinstance(reports, dict) and set(reports) == selected, "Include every eligible report exactly once.")
    _require(isinstance(judgments, dict) and set(judgments) == selected, "Include every eligible case judgment once.")
    for case in cases:
        finding_ids = _validate_report(reports[case["id"]])
        defect_ids = {defect["id"] for defect in case["defects"]}
        _validate_judgment(judgments[case["id"]], finding_ids, defect_ids)
        if reports[case["id"]]["status"] != "completed":
            _require(not judgments[case["id"]]["useful"], "An uncompleted report cannot be judged useful.")


def _protocol(protocol):
    _require(isinstance(protocol, dict), "The evaluation protocol must be an object.")
    result = {"minimum_agreement": protocol.get("minimum_agreement", 0.9)}
    for field in REQUIRED_THRESHOLDS:
        result[field] = protocol.get(field)
    for field, value in result.items():
        if value is not None:
            lower_bound = 0.9 if field == "minimum_agreement" else 0
            _require(
                type(value) in (int, float) and math.isfinite(value)
                and value <= 1 and (value >= lower_bound if field == "minimum_agreement" else value > lower_bound),
                f"{field} must be a finite fraction within the minimum readiness requirements.",
            )
    minimum = protocol.get("min_families")
    _require(minimum is None or (type(minimum) is int and minimum > 0), "min_families must be a positive integer.")
    result["min_families"] = minimum
    return result


def _ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _finding_counts(judgment):
    counts = Counter()
    identified = set()
    for finding in judgment["findings"]:
        counts["findings"] += 1
        counts["spoiler_violations"] += int(finding["spoiler"])
        if not finding["material"]:
            continue
        counts["material_findings"] += 1
        counts["supported_material_findings"] += int(finding["supported"])
        sound = all(finding[field] for field in DIAGNOSIS_CHECKS)
        counts["sound_material_findings"] += int(sound)
        counts["correct_material_hints"] += int(finding["hint_correct"])
        counts["unsound_material_hints"] += int(not finding["hint_correct"])
        counts["unsupported_material_findings"] += int(not finding["supported"])
        if sound:
            identified.update(finding["matched_defect_ids"])
    counts["full_report_spoiler_checks"] = int("report_spoiler" in judgment)
    counts["spoiler_violations"] += int(judgment.get("report_spoiler", False))
    return counts, identified


def _case_result(case, report, judgment):
    counts, identified = _finding_counts(judgment)
    completed = report["status"] == "completed"
    substantive = completed and report["assessment"] != "unable_to_assess"
    abstained = completed and not substantive
    clear = completed and report["assessment"] == "no_issues_found"
    valid = case["expected_assessment"] == "no_issues_found"
    roots = [defect for defect in case["defects"] if defect.get("root_id", defect["id"]) == defect["id"]]
    material_defects = {defect["id"] for defect in roots if defect["significance"] != "minor"}
    critical_defects = {defect["id"] for defect in roots if defect["significance"] in {"critical", "fatal"}}
    if case["critical_error"] and not critical_defects:
        critical_defects = material_defects
    identified &= material_defects
    false_allegation = valid and counts["material_findings"] != counts["sound_material_findings"]
    category_correct = completed and report["assessment"] == case["expected_assessment"]
    critical_identified = substantive and bool(critical_defects) and critical_defects <= identified
    counts.update(
        eligible=1,
        attempted=int(report["status"] != "not_attempted"),
        completed=int(completed),
        substantive=int(substantive),
        useful=int(substantive and judgment["useful"]),
        category_correct=int(category_correct),
        critical_errors_eligible=int(case["critical_error"]),
        critical_errors_judged=int(case["critical_error"] and substantive),
        critical_errors_identified=int(case["critical_error"] and critical_identified),
        critical_errors_missed=int(case["critical_error"] and substantive and not critical_identified),
        critical_false_clears=int(case["critical_error"] and clear),
        valid_proofs_eligible=int(valid),
        valid_proofs_judged=int(valid and substantive),
        valid_proof_false_accusations=int(false_allegation),
        valid_alternatives_eligible=int(case["valid_alternative"]),
        valid_alternatives_judged=int(case["valid_alternative"] and substantive),
        valid_alternative_false_accusations=int(case["valid_alternative"] and false_allegation),
        cleared=int(clear),
        flawed_cleared=int(clear and bool(material_defects)),
        missing_input_false_clears=int(clear and not case["input_complete"]),
        material_defects=len(material_defects),
        identified_material_defects=len(identified),
        abstentions=int(abstained),
        abstentions_judged=int(abstained and "abstention_appropriate" in judgment),
        appropriate_abstentions=int(abstained and judgment.get("abstention_appropriate", False)),
    )
    result = {
        "category_correct": category_correct,
        "substantive": substantive,
        "useful": bool(counts["useful"]),
        "identified_defect_ids": sorted(identified),
        "missed_defect_ids": sorted(material_defects - identified),
        "critical_defects_identified": critical_identified,
        "material_false_allegation": false_allegation,
        "missing_input_false_clear": bool(counts["missing_input_false_clears"]),
        "material_feedback_error": bool(
            counts["material_findings"] != counts["sound_material_findings"]
            or counts["unsound_material_hints"]
            or counts["spoiler_violations"],
        ),
    }
    return counts, result


def _metrics(counts):
    pairs = {
        "category_agreement": ("category_correct", "eligible"),
        "attempt_coverage": ("attempted", "eligible"),
        "completion_coverage": ("completed", "eligible"),
        "substantive_coverage": ("substantive", "eligible"),
        "usable_coverage": ("useful", "eligible"),
        "critical_false_clear_rate": ("critical_false_clears", "critical_errors_judged"),
        "critical_false_clear_rate_all_eligible": ("critical_false_clears", "critical_errors_eligible"),
        "critical_error_identification": ("critical_errors_identified", "critical_errors_judged"),
        "valid_proof_false_accusation_rate": ("valid_proof_false_accusations", "valid_proofs_judged"),
        "valid_proof_false_accusation_rate_all_eligible": ("valid_proof_false_accusations", "valid_proofs_eligible"),
        "valid_alternative_false_accusation_rate": (
            "valid_alternative_false_accusations", "valid_alternatives_judged",
        ),
        "flawed_among_cleared": ("flawed_cleared", "cleared"),
        "finding_precision": ("sound_material_findings", "material_findings"),
        "mathematical_support_precision": ("supported_material_findings", "material_findings"),
        "defect_recall": ("identified_material_defects", "material_defects"),
        "material_hint_correctness": ("correct_material_hints", "material_findings"),
        "appropriate_abstention": ("appropriate_abstentions", "abstentions_judged"),
        "abstention_judgment_coverage": ("abstentions_judged", "abstentions"),
    }
    return {name: _ratio(counts[numerator], counts[denominator]) for name, (numerator, denominator) in pairs.items()}


def _family_statistics(cases, results):
    families = defaultdict(list)
    for case in cases:
        families[case["family_id"]].append(results[case["id"]])
    assessed = [rows for rows in families.values() if all(row["substantive"] for row in rows)]
    errors = sum(
        any(
            not row["category_correct"] or row["material_feedback_error"] or row["missed_defect_ids"]
            for row in rows
        )
        for rows in assessed
    )
    return {
        "eligible_families": len(families),
        "fully_assessed_families": len(assessed),
        "families_with_observed_errors": errors,
        "zero_error_upper_bound_95": -math.expm1(math.log(0.05) / len(assessed)) if assessed and not errors else None,
        "bound_assumption": "Independent families sampled from the intended population; not established here.",
    }


def _gates(counts, metrics, families, protocol):
    thresholds = {
        "category_agreement": protocol["minimum_agreement"],
        "usable_coverage": protocol["min_usable_coverage"],
        "finding_precision": protocol["min_finding_precision"],
        "defect_recall": protocol["min_defect_recall"],
    }
    gates = {
        name: threshold is not None and metrics[name]["value"] is not None and metrics[name]["value"] >= threshold
        for name, threshold in thresholds.items()
    }
    gates.update(
        substantive_judgments=counts["substantive"] > 0,
        family_sample=protocol["min_families"] is not None
        and families["eligible_families"] >= protocol["min_families"],
        no_critical_false_clears=not counts["critical_false_clears"],
        no_missed_judged_critical_defects=not counts["critical_errors_missed"],
        no_valid_proof_false_accusations=not counts["valid_proof_false_accusations"],
        no_unsound_material_hints=not counts["unsound_material_hints"],
        no_spoilers=not counts["spoiler_violations"],
        full_report_spoiler_assessment=counts["full_report_spoiler_checks"] == counts["eligible"],
        no_missing_input_false_clears=not counts["missing_input_false_clears"],
    )
    return gates


def score_reports(cases, reports, judgments, protocol):
    """Score every eligible case without authenticating origin or granting authority.

    ``reports`` and ``judgments`` are keyed by case ID. A human must judge every
    finding exactly once. Optional ``report_spoiler`` and
    ``abstention_appropriate`` judgments preserve whether those checks occurred.
    ``finding_precision`` requires support, localization, severity and context;
    unsupported or misplaced diagnoses cannot earn defect recall.
    """
    _validate_inputs(cases, reports, judgments)
    frozen_protocol = _protocol(protocol)
    counts = Counter()
    by_domain = {domain: Counter() for domain in sorted(DOMAINS)}
    results = {}
    failures = Counter()
    abstentions = Counter()
    for case in cases:
        identifier = case["id"]
        case_counts, results[identifier] = _case_result(case, reports[identifier], judgments[identifier])
        counts.update(case_counts)
        by_domain[case["domain"]].update(case_counts)
        report = reports[identifier]
        if report["status"] != "completed":
            failures[report["status"]] += 1
        elif report["assessment"] == "unable_to_assess":
            abstentions[report["abstention_reason"]] += 1
    metrics = _metrics(counts)
    families = _family_statistics(cases, results)
    gates = _gates(counts, metrics, families, frozen_protocol)
    return {
        "schema_version": 2,
        "origin": "unverified_offline",
        "model_readiness": False,
        "candidate_passed": bool(cases) and all(gates.values()),
        "counts": {field: counts[field] for field in COUNT_FIELDS},
        "metrics": metrics,
        "gates": gates,
        "protocol": frozen_protocol,
        "by_domain": {
            domain: {"counts": {field: value[field] for field in COUNT_FIELDS}, "metrics": _metrics(value)}
            for domain, value in by_domain.items()
        },
        "case_results": results,
        "failures": dict(failures),
        "abstentions": dict(abstentions),
        "family_statistics": families,
        "limitations": [
            "Scores do not authenticate model execution, coach identity, dataset approval or activation authority.",
            "Attempt counts describe review attempts, not authenticated provider requests.",
            "Unknown abstention and full-report spoiler judgments are not inferred from finding judgments.",
            "Family confidence bounds require a justified independent sampling design.",
        ],
    }


def _dimension_comparison(source, target, dimension):
    left_values, right_values = source.get("dimensions"), target.get("dimensions")
    if not isinstance(left_values, dict) or not isinstance(right_values, dict):
        return False, False, "missing_dimension"
    left, right = left_values.get(dimension), right_values.get(dimension)
    if not _identifier(left) or not _identifier(right):
        return False, False, "missing_dimension"
    return True, left == right, "dimension_comparison"


def _relationship_result(source, target, relation):
    if source.get("status") != "completed" or target.get("status") != "completed":
        return False, False, "incomplete_execution"
    if source.get("assessment") == "unable_to_assess" or target.get("assessment") == "unable_to_assess":
        return False, False, "abstention"
    kind = relation["kind"]
    if kind == "same_dimension":
        return _dimension_comparison(source, target, relation["dimension"])
    if kind == "target_assessment":
        return True, target["assessment"] == relation["expected_assessment"], "target_comparison"
    same = source["assessment"] == target["assessment"]
    return True, same if kind == "same_assessment" else not same, "assessment_comparison"


def evaluate_metamorphic_relationships(reports, relationships):
    """Evaluate coach-approved relations, not identical prose or inferred equivalence.

    Relations require ``id``, ``source_case_id``, ``target_case_id``, ``kind`` and
    ``coach_approved=True``. ``same_dimension`` names an explicit report
    ``dimensions`` key; ``target_assessment`` supplies ``expected_assessment``.
    Unexecuted or abstaining pairs remain in the denominator and cannot pass.
    """
    _require(isinstance(reports, dict), "Metamorphic reports must be keyed by case identifier.")
    _unique_ids(relationships, "Metamorphic relationships")
    rows = []
    for relation in relationships:
        _require(relation.get("coach_approved") is True, "Every metamorphic relationship needs coach approval.")
        _require(
            _identifier(relation.get("kind")) and relation["kind"] in RELATION_KINDS,
            "Unsupported metamorphic relationship.",
        )
        source_id, target_id = relation.get("source_case_id"), relation.get("target_case_id")
        _require(
            _identifier(source_id) and _identifier(target_id)
            and source_id in reports and target_id in reports and source_id != target_id,
            "Relation cases must exist.",
        )
        if relation["kind"] == "same_dimension":
            _require(_identifier(relation.get("dimension")), "Specify the invariant mathematical dimension.")
        if relation["kind"] == "target_assessment":
            _require(
                _identifier(relation.get("expected_assessment")) and relation["expected_assessment"] in ASSESSMENTS,
                "Specify the expected target assessment.",
            )
        source, target = reports[source_id], reports[target_id]
        _validate_report(source)
        _validate_report(target)
        assessed, passed, reason = _relationship_result(source, target, relation)
        rows.append({"id": relation["id"], "assessed": assessed, "passed": passed, "reason": reason})
    passed = sum(row["passed"] for row in rows)
    return {
        "total": len(rows),
        "assessed": sum(row["assessed"] for row in rows),
        "passed": passed,
        "all_passed": bool(rows) and passed == len(rows),
        "consistency": _ratio(passed, len(rows)),
        "relationships": rows,
        "model_readiness": False,
    }
