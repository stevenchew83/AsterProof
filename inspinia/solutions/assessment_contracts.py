"""Strict local assessment contracts; structural grounding is not proof verification."""

from copy import deepcopy

from inspinia.solutions.evaluation_contracts import ASSESSMENTS
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import integer
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import text

MODES = {
    "coach": "Coach feedback",
    "provisional": "Feedback + provisional score",
    "examiner": "Full examiner report",
}
MAX_ITEMS = 32
MAX_TEXT = 16_000
STRING = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}
BOOLEAN = {"type": "boolean"}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def array(item):
    return {"type": "array", "items": item, "maxItems": MAX_ITEMS}


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


ANCHOR_SCHEMA = obj(
    start={"type": "integer", "minimum": 0},
    end={"type": "integer", "minimum": 1},
    quote=STRING,
)
ASSESSMENT_SCHEMA = obj(
    assessment=enum(*sorted(ASSESSMENTS)),
    summary=STRING,
    human_review_required=BOOLEAN,
    limitations=array(STRING),
    claims=array(
        obj(
            id=STRING,
            verdict=enum("supported", "invalid", "unjustified", "unresolved"),
            evidence=ANCHOR_SCHEMA,
            justification=STRING,
            depends_on=array(STRING),
        ),
    ),
    findings=array(
        obj(
            id=STRING,
            claim_id=STRING,
            category=enum("invalid_step", "logical_gap", "missing_case", "unfinished", "unreadable"),
            severity=enum("minor", "major", "critical"),
            diagnosis=STRING,
        ),
    ),
)
FEEDBACK_FINDING = obj(finding_id=STRING, explanation=STRING, next_step=STRING)
COACH_SCHEMA = obj(
    summary=STRING,
    strengths=array(STRING),
    findings=array(FEEDBACK_FINDING),
    hints=array(obj(finding_id=STRING, levels={"type": "array", "items": STRING, "minItems": 1, "maxItems": 2})),
)
DECISION_SCHEMA = obj(
    criterion_id=STRING,
    status=enum("met", "not_met", "unresolved", "not_applicable"),
    claim_ids=array(STRING),
    justification=STRING,
)
PROVISIONAL_SCHEMA = obj(
    **deepcopy(COACH_SCHEMA["properties"]),
    rubric_fit=enum("applicable", "human_review_required"),
    decisions=array(DECISION_SCHEMA),
)
EXAMINER_SCHEMA = obj(
    summary=STRING,
    strengths=array(STRING),
    findings=array(FEEDBACK_FINDING),
    corrections=array(obj(finding_id=STRING, corrected_argument=STRING)),
    reference_id=STRING,
)
MODE_SCHEMAS = {"coach": COACH_SCHEMA, "provisional": PROVISIONAL_SCHEMA, "examiner": EXAMINER_SCHEMA}


def validate_schema(value, schema, path="report"):
    """Validate the small, explicit JSON Schema subset used by these contracts."""
    kind = schema["type"]
    if kind == "object":
        require(
            isinstance(value, dict) and set(value) == set(schema["required"]),
            f"Unexpected or missing fields at {path}.",
        )
        for key, child in schema["properties"].items():
            validate_schema(value[key], child, f"{path}.{key}")
    elif kind == "array":
        require(isinstance(value, list), f"Expected a list at {path}.")
        require(
            schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", MAX_ITEMS),
            f"Invalid list size at {path}.",
        )
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        require(text(value) and len(value) <= schema.get("maxLength", MAX_TEXT), f"Expected bounded text at {path}.")
    elif kind == "integer":
        require(integer(value, schema.get("minimum", 0), MAX_TEXT * MAX_ITEMS), f"Expected an integer at {path}.")
    elif kind == "boolean":
        require(type(value) is bool, f"Expected a boolean at {path}.")
    else:
        message = "Unsupported local schema type."
        raise EvaluationDataError(message)
    if "enum" in schema:
        require(value in schema["enum"], f"Unexpected value at {path}.")
    return value


def _indexed(rows, key="id"):
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "Identifiers must occur exactly once.")
    return result


def validate_assessment(assessment, source):
    validate_schema(assessment, ASSESSMENT_SCHEMA, "assessment")
    claims = _indexed(assessment["claims"])
    require(bool(claims), "An assessment needs at least one anchored claim.")
    for claim in claims.values():
        anchor = claim["evidence"]
        require(
            0 <= anchor["start"] < anchor["end"] <= len(source),
            "Evidence location lies outside the frozen submission.",
        )
        require(
            source[anchor["start"] : anchor["end"]] == anchor["quote"],
            "Evidence quotation does not match its location.",
        )
        dependencies = claim["depends_on"]
        require(
            len(set(dependencies)) == len(dependencies) and set(dependencies) <= claims.keys(),
            "Claim dependencies must refer to distinct known claims.",
        )
    resolved = set()
    while len(resolved) < len(claims):
        ready = {key for key, claim in claims.items() if key not in resolved and set(claim["depends_on"]) <= resolved}
        require(bool(ready), "Claim dependencies must not be circular.")
        resolved.update(ready)
    findings = _indexed(assessment["findings"])
    for claim in claims.values():
        if claim["verdict"] == "supported":
            require(
                all(claims[key]["verdict"] == "supported" for key in claim["depends_on"]),
                "A supported claim cannot depend on an unsupported claim.",
            )
    for finding in findings.values():
        require(finding["claim_id"] in claims, "A finding refers to an unknown claim.")
        require(claims[finding["claim_id"]]["verdict"] != "supported", "A defect cannot target a supported claim.")
    _validate_conclusion(assessment, {claim["verdict"] for claim in claims.values()}, findings)
    return assessment


def _validate_conclusion(assessment, verdicts, findings):
    result = assessment["assessment"]
    if result == "no_issues_found":
        require(
            verdicts == {"supported"} and not findings,
            "A no-issues assessment cannot contain defects or uncertainty.",
        )
    else:
        require(bool(findings), "An adverse or unresolved assessment needs an anchored finding.")
    if result == "gap_found":
        require(bool(verdicts & {"invalid", "unjustified"}), "A gap assessment needs an invalid or unjustified claim.")
    if result == "incomplete":
        require(
            "invalid" not in verdicts and bool(verdicts & {"unjustified", "unresolved"}),
            "Incomplete work must identify an unfinished obligation rather than hide an invalid step.",
        )
    if result == "unable_to_assess":
        require("unresolved" in verdicts, "An unassessable report must identify unresolved material.")
    if result == "unable_to_assess" or "unresolved" in verdicts:
        require(assessment["human_review_required"], "Unresolved mathematics requires human review.")


def validate_feedback(mode, feedback, assessment, package):
    require(isinstance(mode, str) and mode in MODES, "Choose a supported review mode.")
    validate_schema(feedback, MODE_SCHEMAS[mode])
    findings = _indexed(assessment["findings"])
    rendered = _indexed(feedback["findings"], "finding_id")
    require(rendered.keys() <= findings.keys(), "Feedback refers to an unknown finding.")
    if findings:
        require(next(iter(findings)) in rendered, "Feedback must address the first consequential finding.")
    if mode == "examiner":
        corrections = _indexed(feedback["corrections"], "finding_id")
        require(
            rendered.keys() == findings.keys() == corrections.keys(),
            "Examiner corrections must cover every finding.",
        )
        require(
            feedback["reference_id"] in {reference["id"] for reference in package["references"]},
            "The examiner must cite a reference in the frozen package.",
        )
    else:
        hints = _indexed(feedback["hints"], "finding_id")
        require(hints.keys() == rendered.keys(), "Each coaching finding needs its own private hints.")
        # A lexical guard catches verbatim reference leakage, not all possible spoilers.
        passages = [feedback["summary"], *feedback["strengths"], *assessment["limitations"]]
        passages.extend(row[key] for row in feedback["findings"] for key in ("explanation", "next_step"))
        passages.extend(hint for row in feedback["hints"] for hint in row["levels"])
        if mode == "provisional":
            passages.extend(row["justification"] for row in feedback["decisions"])
        copy = " ".join(" ".join(passages).split())
        require(
            not any(" ".join(reference["proof"].split()) in copy for reference in package["references"]),
            "Coaching feedback must not reproduce a complete reference proof.",
        )
    return feedback
