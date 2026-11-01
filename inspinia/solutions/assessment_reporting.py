"""Validate shared findings, then construct only the selected disclosure policy."""

from copy import deepcopy

from inspinia.solutions.assessment_contracts import validate_assessment
from inspinia.solutions.assessment_contracts import validate_feedback
from inspinia.solutions.rubric_scoring import calculate_score


def prepare_report(packet, mode, assessment, feedback):
    validate_assessment(assessment, packet["submission"]["body_source"])
    content = packet["package"]["content"]
    validate_feedback(mode, feedback, assessment, content)
    claims = {row["id"]: row for row in assessment["claims"]}
    findings = {row["id"]: row for row in assessment["findings"]}
    displayed = []
    for row in feedback["findings"]:
        finding = findings[row["finding_id"]]
        anchor = claims[finding["claim_id"]]["evidence"]
        displayed.append(
            {
                "id": finding["id"],
                "category": finding["category"],
                "severity": finding["severity"],
                "source_quote": anchor["quote"],
                "source_start": anchor["start"],
                "source_end": anchor["end"],
                "explanation": row["explanation"],
                "next_step": row["next_step"],
            },
        )
    report = {
        "mode": mode,
        "assessment": assessment["assessment"],
        "summary": feedback["summary"],
        "strengths": feedback["strengths"],
        "findings": displayed,
        "limitations": assessment["limitations"],
        "human_review_required": assessment["human_review_required"],
        "assurance": "synthetic_fixture",
        "reference_status": "synthetic_unapproved",
    }
    private_hints = {}
    if mode == "provisional":
        report["score"] = calculate_score(content["rubric"], assessment, feedback["decisions"], feedback["rubric_fit"])
        report["score"]["label"] = "Synthetic provisional score; not calibrated against human marks"
    if mode == "examiner":
        report["corrections"] = deepcopy(feedback["corrections"])
        report["reference"] = deepcopy(
            next(row for row in content["references"] if row["id"] == feedback["reference_id"]),
        )
    else:
        private_hints = {row["finding_id"]: row["levels"] for row in feedback["hints"]}
    return deepcopy(report), deepcopy(private_hints)
