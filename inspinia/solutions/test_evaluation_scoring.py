"""Human-grounded offline scores preserve denominators and never grant authority."""

import copy
import math

import pytest

from inspinia.solutions.evaluation_scoring import EvaluationScoringError
from inspinia.solutions.evaluation_scoring import evaluate_metamorphic_relationships
from inspinia.solutions.evaluation_scoring import score_reports

CASE_COUNT = 4
MATERIAL_DEFECT_COUNT = 3
TWO_ASSESSED_FAMILIES = 2


def finding_judgment(identifier, defects=(), **changes):
    return {
        "finding_id": identifier,
        "supported": True,
        "material": True,
        "localization_correct": True,
        "severity_correct": True,
        "context_correct": True,
        "hint_correct": True,
        "spoiler": False,
        "matched_defect_ids": list(defects),
        **changes,
    }


@pytest.fixture
def inputs():
    cases = [
        {
            "id": "alternative", "family_id": "geometry", "domain": "GEO",
            "expected_assessment": "no_issues_found", "critical_error": False,
            "valid_alternative": True, "input_complete": True, "defects": [],
        },
        {
            "id": "critical", "family_id": "divisibility", "domain": "NT",
            "expected_assessment": "gap_found", "critical_error": True,
            "valid_alternative": False, "input_complete": True,
            "defects": [{"id": "bad-cancellation", "significance": "fatal"},
                        {"id": "missing-case", "significance": "consequential"}],
        },
        {
            "id": "partial", "family_id": "inequality", "domain": "ALG",
            "expected_assessment": "incomplete", "critical_error": False,
            "valid_alternative": False, "input_complete": True,
            "defects": [{"id": "equality", "significance": "consequential"}],
        },
        {
            "id": "missing", "family_id": "construction", "domain": "COM",
            "expected_assessment": "unable_to_assess", "critical_error": False,
            "valid_alternative": False, "input_complete": False, "defects": [],
        },
    ]
    reports = {
        case["id"]: {"status": "completed", "assessment": case["expected_assessment"], "findings": []}
        for case in cases
    }
    reports["critical"]["findings"] = [{"id": "cancellation"}, {"id": "case"}]
    reports["partial"]["findings"] = [{"id": "equality"}]
    reports["missing"]["abstention_reason"] = "missing_diagram"
    judgments = {case["id"]: {"useful": True, "report_spoiler": False, "findings": []} for case in cases}
    judgments["critical"]["findings"] = [
        finding_judgment("cancellation", ["bad-cancellation"]),
        finding_judgment("case", ["missing-case"]),
    ]
    judgments["partial"]["findings"] = [finding_judgment("equality", ["equality"])]
    judgments["missing"]["abstention_appropriate"] = True
    protocol = {
        "min_usable_coverage": 0.7,
        "min_finding_precision": 1,
        "min_defect_recall": 1,
        "min_families": 4,
    }
    return cases, reports, judgments, protocol


def test_perfect_import_scores_but_never_claims_model_readiness(inputs):
    cases, reports, judgments, protocol = inputs
    reports["critical"]["origin"] = "verified_authorized_provider"
    protocol["model_readiness"] = True
    result = score_reports(cases, reports, judgments, protocol)
    assert result["candidate_passed"]
    assert result["model_readiness"] is False
    assert result["origin"] == "unverified_offline"
    assert result["metrics"]["category_agreement"] == {"numerator": 4, "denominator": 4, "value": 1}
    assert result["metrics"]["usable_coverage"] == {"numerator": 3, "denominator": 4, "value": 0.75}
    assert result["metrics"]["defect_recall"] == {"numerator": 3, "denominator": 3, "value": 1}
    assert result["by_domain"]["COM"]["counts"]["substantive"] == 0
    assert result["abstentions"] == {"missing_diagram": 1}


def test_right_verdict_for_wrong_reason_does_not_identify_the_defect(inputs):
    cases, reports, judgments, protocol = inputs
    judgments["critical"]["findings"][0]["supported"] = False
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["category_agreement"]["value"] == 1
    assert result["case_results"]["critical"]["missed_defect_ids"] == ["bad-cancellation"]
    assert result["metrics"]["defect_recall"]["numerator"] == MATERIAL_DEFECT_COUNT - 1
    assert result["counts"]["critical_errors_missed"] == 1
    assert not result["candidate_passed"]


@pytest.mark.parametrize("check", ["localization_correct", "severity_correct", "context_correct"])
def test_material_criticism_requires_location_severity_and_context(inputs, check):
    cases, reports, judgments, protocol = inputs
    judgments["critical"]["findings"][0][check] = False
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["mathematical_support_precision"]["value"] == 1
    assert result["metrics"]["finding_precision"]["numerator"] == MATERIAL_DEFECT_COUNT - 1
    assert result["case_results"]["critical"]["identified_defect_ids"] == ["missing-case"]
    assert not result["candidate_passed"]


def test_independent_root_defects_are_counted_once_despite_duplicate_findings(inputs):
    cases, reports, judgments, protocol = inputs
    reports["critical"]["findings"].append({"id": "consequence"})
    judgments["critical"]["findings"].append(finding_judgment("consequence", ["bad-cancellation"]))
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["material_findings"] == MATERIAL_DEFECT_COUNT + 1
    assert result["metrics"]["defect_recall"] == {"numerator": 3, "denominator": 3, "value": 1}


def test_false_allegation_on_valid_alternative_is_a_separate_failure(inputs):
    cases, reports, judgments, protocol = inputs
    reports["alternative"]["findings"] = [{"id": "unfamiliar-inversion"}]
    judgments["alternative"]["findings"] = [finding_judgment("unfamiliar-inversion", supported=False)]
    protocol["min_finding_precision"] = 0.5
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["valid_alternative_false_accusations"] == 1
    assert result["metrics"]["valid_proof_false_accusation_rate"]["value"] == 1
    assert not result["gates"]["no_valid_proof_false_accusations"]
    assert not result["candidate_passed"]


def test_critical_false_clear_has_conditional_and_eligible_denominators(inputs):
    cases, reports, judgments, protocol = inputs
    reports["critical"] = {"status": "completed", "assessment": "no_issues_found", "findings": []}
    judgments["critical"]["findings"] = []
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["critical_false_clear_rate"] == {"numerator": 1, "denominator": 1, "value": 1}
    assert result["metrics"]["critical_false_clear_rate_all_eligible"]["denominator"] == 1
    assert result["metrics"]["flawed_among_cleared"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert not result["candidate_passed"]


def test_missing_diagram_positive_report_fails_the_input_safety_gate(inputs):
    cases, reports, judgments, protocol = inputs
    reports["missing"].update(assessment="no_issues_found")
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["missing_input_false_clears"] == 1
    assert not result["gates"]["no_missing_input_false_clears"]
    assert not result["candidate_passed"]


def test_all_abstaining_cannot_pass_even_with_low_coverage_threshold(inputs):
    cases, reports, judgments, protocol = inputs
    for identifier in reports:
        reports[identifier] = {
            "status": "completed", "assessment": "unable_to_assess", "findings": [],
            "abstention_reason": "mathematical_uncertainty",
        }
        judgments[identifier] = {"useful": True, "findings": []}
    protocol.update(min_usable_coverage=0.01, min_defect_recall=0.01)
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["completed"] == CASE_COUNT
    assert result["counts"]["substantive"] == result["counts"]["useful"] == 0
    assert result["metrics"]["critical_false_clear_rate"]["value"] is None
    assert result["metrics"]["finding_precision"]["value"] is None
    assert result["metrics"]["appropriate_abstention"]["value"] is None
    assert result["family_statistics"]["zero_error_upper_bound_95"] is None
    assert not result["candidate_passed"]


@pytest.mark.parametrize("status", ["not_attempted", "refused", "failed", "timeout", "outcome_unknown", "incomplete"])
def test_failures_remain_in_eligible_denominator_and_have_distinct_statuses(inputs, status):
    cases, reports, judgments, protocol = inputs
    reports["critical"] = {"status": status, "findings": []}
    judgments["critical"] = {"useful": False, "findings": []}
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["eligible"] == CASE_COUNT
    assert result["counts"]["attempted"] == (3 if status == "not_attempted" else 4)
    assert result["counts"]["completed"] == CASE_COUNT - 1
    assert result["metrics"]["category_agreement"]["value"] == (CASE_COUNT - 1) / CASE_COUNT
    assert result["failures"] == {status: 1}
    assert result["metrics"]["critical_false_clear_rate"]["value"] is None


@pytest.mark.parametrize(
    "field", ["min_usable_coverage", "min_finding_precision", "min_defect_recall", "min_families"],
)
def test_missing_protocol_threshold_cannot_pass(inputs, field):
    cases, reports, judgments, protocol = inputs
    protocol.pop(field)
    assert not score_reports(cases, reports, judgments, protocol)["candidate_passed"]


@pytest.mark.parametrize("value", [True, 0, -0.1, 1.1, "0.9", math.nan, math.inf])
def test_invalid_protocol_fraction_is_rejected(inputs, value):
    cases, reports, judgments, protocol = inputs
    protocol["min_usable_coverage"] = value
    with pytest.raises(EvaluationScoringError, match="finite fraction"):
        score_reports(cases, reports, judgments, protocol)


def test_category_agreement_floor_cannot_be_weakened(inputs):
    cases, reports, judgments, protocol = inputs
    protocol["minimum_agreement"] = 0.89
    with pytest.raises(EvaluationScoringError, match="minimum readiness"):
        score_reports(cases, reports, judgments, protocol)


def test_full_report_spoiler_assessment_cannot_be_inferred_from_findings(inputs):
    cases, reports, judgments, protocol = inputs
    judgments["alternative"].pop("report_spoiler")
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["finding_precision"]["value"] == 1
    assert not result["gates"]["full_report_spoiler_assessment"]
    assert not result["candidate_passed"]


def test_dependent_defect_does_not_create_an_additional_root_recall_requirement(inputs):
    cases, reports, judgments, protocol = inputs
    cases[1]["defects"].append({
        "id": "downstream-conclusion", "root_id": "bad-cancellation", "significance": "consequential",
    })
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["defect_recall"] == {"numerator": 3, "denominator": 3, "value": 1}
    assert result["candidate_passed"]


@pytest.mark.parametrize("kind", ["hint", "finding_spoiler", "summary_spoiler"])
def test_unsound_hints_and_spoilers_fail_independently_of_category(inputs, kind):
    cases, reports, judgments, protocol = inputs
    if kind == "hint":
        judgments["critical"]["findings"][0]["hint_correct"] = False
    elif kind == "finding_spoiler":
        judgments["critical"]["findings"][0]["spoiler"] = True
    else:
        judgments["alternative"]["report_spoiler"] = True
    result = score_reports(cases, reports, judgments, protocol)
    assert result["metrics"]["category_agreement"]["value"] == 1
    assert result["family_statistics"]["zero_error_upper_bound_95"] is None
    assert not result["candidate_passed"]


def test_family_bound_uses_independent_family_count_not_case_variants(inputs):
    cases, reports, judgments, protocol = inputs
    cases[2]["family_id"] = cases[1]["family_id"]
    result = score_reports(cases, reports, judgments, protocol)
    family = result["family_statistics"]
    assert family["eligible_families"] == CASE_COUNT - 1
    assert family["fully_assessed_families"] == TWO_ASSESSED_FAMILIES
    assert family["zero_error_upper_bound_95"] == pytest.approx(1 - math.sqrt(0.05))
    assert not result["gates"]["family_sample"]


def test_empty_dataset_has_null_metrics_and_cannot_pass():
    result = score_reports([], {}, {}, {})
    assert result["counts"]["eligible"] == result["counts"]["material_findings"] == 0
    assert all(metric["value"] is None for metric in result["metrics"].values())
    assert all(row["counts"]["eligible"] == 0 for row in result["by_domain"].values())
    assert not result["candidate_passed"]


@pytest.mark.parametrize("target", ["reports", "judgments"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_every_eligible_case_requires_exact_report_and_judgment_keys(inputs, target, change):
    cases, reports, judgments, protocol = inputs
    values = reports if target == "reports" else judgments
    if change == "missing":
        values.pop("partial")
    else:
        values["unselected"] = copy.deepcopy(values["partial"])
    with pytest.raises(EvaluationScoringError, match="every eligible"):
        score_reports(cases, reports, judgments, protocol)


def test_duplicate_cases_and_finding_ids_are_rejected(inputs):
    cases, reports, judgments, protocol = inputs
    cases.append(copy.deepcopy(cases[0]))
    with pytest.raises(EvaluationScoringError, match="unique"):
        score_reports(cases, reports, judgments, protocol)
    cases.pop()
    reports["critical"]["findings"].append({"id": "case"})
    with pytest.raises(EvaluationScoringError, match="unique"):
        score_reports(cases, reports, judgments, protocol)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "non_boolean", "cross_case"])
def test_invalid_finding_judgments_are_rejected(inputs, change):
    cases, reports, judgments, protocol = inputs
    rows = judgments["critical"]["findings"]
    if change == "missing":
        rows.pop()
    elif change == "extra":
        rows.append(finding_judgment("nonexistent"))
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "non_boolean":
        rows[0]["supported"] = "true"
    else:
        rows[0]["matched_defect_ids"] = ["equality"]
    with pytest.raises(EvaluationScoringError):
        score_reports(cases, reports, judgments, protocol)


def test_scorer_does_not_mutate_frozen_inputs(inputs):
    before = copy.deepcopy(inputs)
    score_reports(*inputs)
    assert inputs == before


@pytest.fixture
def metamorphic():
    reports = {
        "source": {"status": "completed", "assessment": "no_issues_found", "findings": [],
                   "dimensions": {"logical_validity": "valid", "justification": "compressed"}},
        "expanded": {"status": "completed", "assessment": "no_issues_found", "findings": [],
                     "dimensions": {"logical_validity": "valid", "justification": "sufficient"}},
    }
    relationship = {
        "id": "expanded-calculation", "source_case_id": "source", "target_case_id": "expanded",
        "kind": "same_dimension", "dimension": "logical_validity", "coach_approved": True,
    }
    return reports, [relationship]


def test_metamorphic_checks_invariant_dimensions_without_requiring_identical_feedback(metamorphic):
    result = evaluate_metamorphic_relationships(*metamorphic)
    assert result["all_passed"]
    assert result["consistency"] == {"numerator": 1, "denominator": 1, "value": 1}
    assert not result["model_readiness"]


def test_metamorphic_inconsistency_is_a_failure(metamorphic):
    reports, relationships = metamorphic
    reports["expanded"]["dimensions"]["logical_validity"] = "invalid"
    result = evaluate_metamorphic_relationships(reports, relationships)
    assert result["assessed"] == 1
    assert result["passed"] == 0
    assert not result["all_passed"]


def test_unapproved_transformations_cannot_be_scored(metamorphic):
    reports, relationships = metamorphic
    relationships[0]["coach_approved"] = False
    with pytest.raises(EvaluationScoringError, match="coach approval"):
        evaluate_metamorphic_relationships(reports, relationships)


@pytest.mark.parametrize("change", ["abstain", "failed", "missing_dimension"])
def test_unassessed_metamorphic_pair_does_not_silently_disappear(metamorphic, change):
    reports, relationships = metamorphic
    if change == "abstain":
        reports["expanded"].update(assessment="unable_to_assess", abstention_reason="uncertainty")
    elif change == "failed":
        reports["expanded"] = {"status": "timeout", "findings": []}
    else:
        reports["expanded"].pop("dimensions")
    result = evaluate_metamorphic_relationships(reports, relationships)
    assert result["total"] == 1
    assert result["assessed"] == result["passed"] == 0
    assert result["consistency"]["denominator"] == 1
    assert not result["all_passed"]


@pytest.mark.parametrize("kind", ["same_assessment", "different_assessment", "target_assessment"])
def test_coach_can_specify_preserved_or_changed_expected_assessment(metamorphic, kind):
    reports, relationships = metamorphic
    relationships[0].update(kind=kind, expected_assessment="gap_found")
    if kind != "same_assessment":
        reports["expanded"]["assessment"] = "gap_found"
    assert evaluate_metamorphic_relationships(reports, relationships)["all_passed"]


@pytest.mark.parametrize("incorrect_dimension", ["severity_correct", "context_correct", "localization_correct"])
def test_materially_unsound_criticism_on_valid_alternative_is_a_protected_failure(inputs, incorrect_dimension):
    cases, reports, judgments, protocol = inputs
    reports["alternative"]["findings"] = [{"id": "overstated-notation"}]
    judgments["alternative"]["findings"] = [finding_judgment("overstated-notation", **{incorrect_dimension: False})]
    result = score_reports(cases, reports, judgments, protocol)
    assert result["counts"]["valid_alternative_false_accusations"] == 1
    assert not result["gates"]["no_valid_proof_false_accusations"]
    assert not result["candidate_passed"]
