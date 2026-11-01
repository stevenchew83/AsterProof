"""Bounded, provider-free contracts for mathematical reference packages."""

import hashlib
import json
import re

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1_048_576
DOMAINS = {"ALG", "GEO", "NT", "COM"}
ASSESSMENTS = {"no_issues_found", "gap_found", "incomplete", "unable_to_assess"}
SHA256 = re.compile(r"[0-9a-f]{64}")
MIN_EXCLUSIVE_CRITERIA = 2


class EvaluationDataError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvaluationDataError(message)


def canonical_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON keys are not permitted.")
        result[key] = value
    return result


def load_json_file(path):
    with path.open("rb") as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    require(len(content) <= MAX_FILE_BYTES, "Evaluation files must be at most 1 MB.")
    try:
        return json.loads(content, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as error:
        message = "Use valid JSON without duplicate keys or non-finite numbers."
        raise EvaluationDataError(message) from error


def _invalid_constant(_value):
    message = "Non-finite numbers are not permitted."
    raise EvaluationDataError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def text_list(value):
    return isinstance(value, list) and all(text(item) for item in value)


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def keys(value, expected):
    return isinstance(value, dict) and set(value) == set(expected.split())


def _identified(rows, required_keys):
    require(isinstance(rows, list), "Package entries must be lists.")
    identifiers = set()
    for row in rows:
        require(keys(row, required_keys) and text(row.get("id")), "Invalid package entry fields or identifier.")
        require(row["id"] not in identifiers, "Package entry identifiers must be unique.")
        identifiers.add(row["id"])
    return identifiers


def validate_rubric(rubric):
    require(keys(rubric, "max_score criteria caps exclusive_groups"), "Invalid marking rubric fields.")
    maximum = rubric["max_score"]
    require(integer(maximum, 1, 100), "The rubric maximum must be an integer from 1 to 100.")
    identifiers = _identified(rubric["criteria"], "id description points depends_on")
    require(bool(identifiers), "A marking rubric needs at least one criterion.")
    dependencies = {}
    for criterion in rubric["criteria"]:
        require(text(criterion["description"]), "Describe each marking criterion.")
        require(integer(criterion["points"], 1, maximum), "Criterion points must fit the rubric maximum.")
        required = criterion["depends_on"]
        require(text_list(required) and len(set(required)) == len(required), "Invalid criterion dependencies.")
        require(set(required) <= identifiers, "A criterion dependency references an unknown criterion.")
        dependencies[criterion["id"]] = set(required)
    # Resolve a dependency graph without recursion or an assumption about criterion order.
    resolved = set()
    while len(resolved) < len(identifiers):
        ready = {key for key, needs in dependencies.items() if key not in resolved and needs <= resolved}
        require(bool(ready), "Marking criterion dependencies must not contain cycles.")
        resolved.update(ready)
    _identified(rubric["caps"], "id description missing_any_of max_score")
    for cap in rubric["caps"]:
        require(text(cap["description"]) and integer(cap["max_score"], 0, maximum), "Invalid scoring cap.")
        missing = cap["missing_any_of"]
        require(text_list(missing) and bool(missing) and set(missing) <= identifiers, "Invalid cap dependencies.")
    groups = rubric["exclusive_groups"]
    require(isinstance(groups, list), "Exclusive criterion groups must be a list.")
    for group in groups:
        require(
            text_list(group)
            and len(set(group)) == len(group)
            and len(group) >= MIN_EXCLUSIVE_CRITERIA
            and set(group) <= identifiers,
            "Exclusive groups need at least two distinct known criteria.",
        )


def validate_package_content(content):
    require(
        keys(content, "schema_version statement assumptions domain level references rubric known_pitfalls images"),
        "Use the versioned mathematical package fields; approval is recorded separately.",
    )
    require(
        type(content["schema_version"]) is int and content["schema_version"] == SCHEMA_VERSION,
        "Unsupported package schema version.",
    )
    require(text(content["statement"]) and text(content["level"]), "Supply the exact statement and problem level.")
    require(isinstance(content["domain"], str) and content["domain"] in DOMAINS, "Use ALG, GEO, NT, or COM.")
    require(text_list(content["assumptions"]) and text_list(content["known_pitfalls"]), "Invalid mathematical notes.")
    _identified(content["references"], "id method proof source")
    for reference in content["references"]:
        require(
            all(text(reference[key]) for key in ("method", "proof", "source")),
            "Complete each reference solution.",
        )
    _identified(content["images"], "id sha256 description")
    for image in content["images"]:
        require(text(image["sha256"]) and SHA256.fullmatch(image["sha256"]), "Supply each image's SHA-256 digest.")
        require(text(image["description"]), "Describe each image's mathematical role.")
    if content["rubric"] is not None:
        validate_rubric(content["rubric"])
    size = len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode())
    require(size <= MAX_FILE_BYTES, "A reference package must be at most 1 MB.")
    return content


def package_digest(problem_id, version, content):
    require(
        text(problem_id) and integer(version, 1, 1_000_000),
        "Supply a problem identity and positive package version.",
    )
    validate_package_content(content)
    return canonical_digest({"problem_id": problem_id, "version": version, "content": content})
