# ruff: noqa: PLR2004 - Exact synthetic scores and contract versions are assertions.
"""Mathematical evidence, disclosure boundaries, and deterministic scoring rules."""

from copy import deepcopy

import pytest

from inspinia.solutions.assessment_contracts import ASSESSMENT_SCHEMA
from inspinia.solutions.assessment_contracts import MODE_SCHEMAS
from inspinia.solutions.assessment_contracts import MODES
from inspinia.solutions.assessment_contracts import validate_assessment
from inspinia.solutions.assessment_contracts import validate_feedback
from inspinia.solutions.assessment_prompts import feedback_request
from inspinia.solutions.assessment_reporting import prepare_report
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.rubric_scoring import calculate_score
from inspinia.solutions.synthetic_reviews import case_choices
from inspinia.solutions.synthetic_reviews import synthetic_bundle

CASE = "synthetic-nt-held_out-invalid"


@pytest.fixture
def bundle():
    return synthetic_bundle(CASE, "provisional")


def score(bundle):
    return calculate_score(
        bundle["packet"]["package"]["content"]["rubric"],
        bundle["assessment"],
        bundle["mode_feedback"]["decisions"],
        bundle["mode_feedback"]["rubric_fit"],
    )


def test_all_bundled_submissions_support_three_modes_without_changing_assessment():
    for case in case_choices():
        variants = {mode: synthetic_bundle(case["id"], mode) for mode in MODES}
        assert variants["coach"]["assessment"] == variants["provisional"]["assessment"]
        assert variants["coach"]["assessment"] == variants["examiner"]["assessment"]
        assert "score" not in variants["coach"]["report"]
        assert "reference" not in variants["coach"]["report"]
        assert "reference" not in variants["provisional"]["report"]
        assert not variants["examiner"]["private_hints"]


def test_coaching_request_omits_reference_rubric_and_internal_mathematical_justifications(bundle):
    request = feedback_request("coach", bundle["packet"], bundle["assessment"])
    assert set(request["input"]) == {"statement", "submission", "findings", "assessment", "human_review_required"}
    assert "package" not in request["input"]
    assert "mathematical_assessment" not in request["input"]


def test_distinct_schemas_forbid_scores_and_solutions_in_coach():
    assert "decisions" not in MODE_SCHEMAS["coach"]["properties"]
    assert "reference_id" not in MODE_SCHEMAS["coach"]["properties"]
    assert "decisions" in MODE_SCHEMAS["provisional"]["properties"]
    assert "score" not in MODE_SCHEMAS["provisional"]["properties"]
    assert "corrections" in MODE_SCHEMAS["examiner"]["properties"]
    assert ASSESSMENT_SCHEMA["additionalProperties"] is False


@pytest.mark.parametrize(
    "defect",
    ["quote", "offset", "unknown_claim", "cycle", "duplicate", "unsupported_dependency"],
)
def test_fabricated_or_inconsistent_evidence_is_rejected(bundle, defect):
    assessment = bundle["assessment"]
    claim = assessment["claims"][-1]
    if defect == "quote":
        claim["evidence"]["quote"] = "Invented student passage."
    elif defect == "offset":
        claim["evidence"]["start"] = 999999
    elif defect == "unknown_claim":
        assessment["findings"][0]["claim_id"] = "missing"
    elif defect == "cycle":
        claim["depends_on"] = [claim["id"]]
    elif defect == "duplicate":
        assessment["claims"].append(deepcopy(claim))
    else:
        assessment["claims"][0]["depends_on"] = [claim["id"]]
        claim["depends_on"] = []
    with pytest.raises(EvaluationDataError):
        validate_assessment(assessment, bundle["packet"]["submission"]["body_source"])


@pytest.mark.parametrize("field", ["score", "reference_solution", "solved", "extra"])
def test_coach_cannot_accept_forbidden_output_fields(bundle, field):
    feedback = synthetic_bundle(CASE, "coach")["mode_feedback"]
    feedback[field] = "Forbidden output"
    with pytest.raises(EvaluationDataError, match="Unexpected or missing"):
        validate_feedback("coach", feedback, bundle["assessment"], bundle["packet"]["package"]["content"])


def test_complete_reference_leakage_and_unknown_finding_ids_are_rejected(bundle):
    feedback = synthetic_bundle(CASE, "coach")["mode_feedback"]
    content = bundle["packet"]["package"]["content"]
    feedback["hints"][0]["levels"][0] = "\n".join(content["references"][0]["proof"].split())
    with pytest.raises(EvaluationDataError, match="complete reference"):
        validate_feedback("coach", feedback, bundle["assessment"], content)
    feedback["hints"][0]["levels"][0] = "Check the unsupported implication."
    feedback["findings"][0]["finding_id"] = "unknown"
    with pytest.raises(EvaluationDataError, match="unknown finding"):
        validate_feedback("coach", feedback, bundle["assessment"], content)


def test_exact_reference_is_attached_only_for_examiner():
    bundle = synthetic_bundle(CASE, "examiner")
    assert bundle["report"]["reference"] == bundle["packet"]["package"]["content"]["references"][0]
    assert bundle["report"]["reference_status"] == "synthetic_unapproved"
    bundle["mode_feedback"]["reference_id"] = "invented"
    with pytest.raises(EvaluationDataError, match="frozen package"):
        prepare_report(bundle["packet"], "examiner", bundle["assessment"], bundle["mode_feedback"])


@pytest.mark.parametrize(
    ("mode", "field"),
    [("coach", "limitations"), ("provisional", "limitations"), ("provisional", "criterion")],
)
def test_reference_leakage_cannot_bypass_coaching_guard_in_secondary_report_fields(mode, field):
    bundle = synthetic_bundle(CASE, mode)
    proof = bundle["packet"]["package"]["content"]["references"][0]["proof"]
    if field == "limitations":
        bundle["assessment"]["limitations"] = [proof]
    else:
        bundle["mode_feedback"]["decisions"][0]["justification"] = proof
    with pytest.raises(EvaluationDataError, match="complete reference"):
        prepare_report(bundle["packet"], mode, bundle["assessment"], bundle["mode_feedback"])


def test_supported_partial_progress_earns_only_permitted_credit(bundle):
    result = score(bundle)
    assert result["total"] == 3
    assert result["max_score"] == 7
    assert [row["points"] for row in result["criteria"]] == [3, 0]
    assert result["criteria"][0]["evidence"][0]["quote"] == "The product is even"


def test_a_met_child_cannot_bypass_a_missing_prerequisite(bundle):
    decisions = bundle["mode_feedback"]["decisions"]
    decisions[0]["status"] = "not_met"
    decisions[1].update(status="met", claim_ids=["parity"])
    result = score(bundle)
    assert result["total"] == 0
    assert result["criteria"][1]["reason"] == "dependency_not_met"
    assert result["applied_caps"][0]["id"] == "missing-milestone"


def test_conditional_caps_and_overall_maximum_apply_after_awards():
    bundle = synthetic_bundle("synthetic-nt-held_out-alternative", "provisional")
    rubric = bundle["packet"]["package"]["content"]["rubric"]
    rubric["criteria"][0]["points"] = 7
    assert score(bundle)["total"] == 7
    bundle["mode_feedback"]["decisions"][1]["status"] = "not_met"
    rubric["caps"] = [
        {
            "id": "unfinished",
            "description": "An unfinished proof is capped.",
            "missing_any_of": ["completion"],
            "max_score": 2,
        },
    ]
    result = score(bundle)
    assert result["raw_total"] == 7
    assert result["total"] == 2


@pytest.mark.parametrize("reason", ["unresolved", "not_applicable", "fit", "exclusive", "global"])
def test_uncertain_or_incompatible_credit_withholds_a_total(bundle, reason):
    if reason in {"unresolved", "not_applicable"}:
        bundle["mode_feedback"]["decisions"][0]["status"] = reason
    elif reason == "fit":
        bundle["mode_feedback"]["rubric_fit"] = "human_review_required"
    elif reason == "global":
        bundle["assessment"]["human_review_required"] = True
    else:
        bundle = synthetic_bundle("synthetic-nt-held_out-alternative", "provisional")
        bundle["packet"]["package"]["content"]["rubric"]["exclusive_groups"] = [["milestone", "completion"]]
    result = score(bundle)
    assert result["status"] == "human_review_required"
    assert result["total"] is None


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unknown", "invalid_evidence", "missing_evidence"])
def test_invalid_credit_evidence_is_rejected(bundle, defect):
    decisions = bundle["mode_feedback"]["decisions"]
    if defect == "missing":
        decisions.pop()
    elif defect == "duplicate":
        decisions.append(deepcopy(decisions[0]))
    elif defect == "unknown":
        decisions[0]["criterion_id"] = "invented"
    elif defect == "invalid_evidence":
        decisions[0]["claim_ids"] = ["argument"]
    else:
        decisions[0]["claim_ids"] = []
    with pytest.raises(EvaluationDataError):
        score(bundle)


@pytest.mark.parametrize("defect", ["negative_points", "unknown_dependency", "cycle", "invalid_cap", "unknown_fit"])
def test_score_calculator_revalidates_rubric_at_its_boundary(bundle, defect):
    rubric = bundle["packet"]["package"]["content"]["rubric"]
    if defect == "negative_points":
        rubric["criteria"][0]["points"] = -3
    elif defect == "unknown_dependency":
        rubric["criteria"][0]["depends_on"] = ["unknown"]
    elif defect == "cycle":
        rubric["criteria"][0]["depends_on"] = ["completion"]
    elif defect == "invalid_cap":
        rubric["caps"][0]["max_score"] = -1
    else:
        bundle["mode_feedback"]["rubric_fit"] = "guess"
    with pytest.raises(EvaluationDataError):
        score(bundle)
