"""Deterministic credit arithmetic; criterion judgments remain fallible assessments."""

from inspinia.solutions.assessment_contracts import DECISION_SCHEMA
from inspinia.solutions.assessment_contracts import array
from inspinia.solutions.assessment_contracts import validate_schema
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import validate_rubric


def calculate_score(rubric, assessment, decisions, rubric_fit):
    require(rubric is not None, "A provisional score requires a problem-specific rubric.")
    validate_rubric(rubric)
    require(
        isinstance(rubric_fit, str) and rubric_fit in {"applicable", "human_review_required"},
        "Invalid rubric fit.",
    )
    validate_schema(decisions, array(DECISION_SCHEMA), "decisions")
    criteria = {row["id"]: row for row in rubric["criteria"]}
    proposed = {row["criterion_id"]: row for row in decisions}
    require(
        len(proposed) == len(decisions) and proposed.keys() == criteria.keys(),
        "Supply exactly one decision for every rubric criterion.",
    )
    claims = {row["id"]: row for row in assessment["claims"]}
    for decision in decisions:
        evidence = decision["claim_ids"]
        require(
            bool(evidence) and len(set(evidence)) == len(evidence) and set(evidence) <= claims.keys(),
            "Every credit decision needs distinct known claim evidence.",
        )
        if decision["status"] == "met":
            require(
                all(claims[key]["verdict"] == "supported" for key in evidence),
                "Credit cannot be awarded on invalid, unjustified, or unresolved evidence.",
            )
    reasons = []
    if assessment["human_review_required"] or rubric_fit == "human_review_required":
        reasons.append("The mathematical assessment or rubric fit requires human review.")
    if any(row["status"] in {"unresolved", "not_applicable"} for row in decisions):
        reasons.append("At least one criterion cannot be fairly resolved.")
    met = {key for key, row in proposed.items() if row["status"] == "met"}
    if any(len(met & set(group)) > 1 for group in rubric["exclusive_groups"]):
        reasons.append("Mutually exclusive credit routes need human adjudication.")
    if reasons:
        return {
            "status": "human_review_required",
            "total": None,
            "max_score": rubric["max_score"],
            "criteria": [],
            "applied_caps": [],
            "reasons": reasons,
        }
    # Resolve dependencies to a fixed point; descendants cannot bypass a missing prerequisite.
    awarded = set()
    while True:
        ready = {key for key in met - awarded if set(criteria[key]["depends_on"]) <= awarded}
        if not ready:
            break
        awarded.update(ready)
    breakdown = [
        {
            "criterion_id": key,
            "description": criterion["description"],
            "status": proposed[key]["status"],
            "points": criterion["points"] if key in awarded else 0,
            "max_points": criterion["points"],
            "reason": "dependency_not_met" if key in met - awarded else proposed[key]["status"],
            "claim_ids": proposed[key]["claim_ids"],
            "justification": proposed[key]["justification"],
            "evidence": [claims[claim_id]["evidence"] for claim_id in proposed[key]["claim_ids"]],
        }
        for key, criterion in criteria.items()
    ]
    caps = [cap for cap in rubric["caps"] if any(key not in awarded for key in cap["missing_any_of"])]
    raw_total = sum(row["points"] for row in breakdown)
    total = min([raw_total, rubric["max_score"], *[cap["max_score"] for cap in caps]])
    return {
        "status": "provisional",
        "total": total,
        "raw_total": raw_total,
        "max_score": rubric["max_score"],
        "criteria": breakdown,
        "applied_caps": caps,
        "reasons": [],
    }
