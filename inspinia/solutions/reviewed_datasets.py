"""Offline review evidence bound to versioned mathematical inputs, never approval grants."""

from collections import Counter
from datetime import datetime
from itertools import combinations

from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import canonical_digest
from inspinia.solutions.evaluation_contracts import integer
from inspinia.solutions.evaluation_contracts import keys
from inspinia.solutions.evaluation_contracts import package_digest
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import text
from inspinia.solutions.evaluation_contracts import text_list
from inspinia.solutions.evaluation_harness import MAX_CASES
from inspinia.solutions.evaluation_harness import SPLITS
from inspinia.solutions.evaluation_harness import case_input_digest
from inspinia.solutions.evaluation_harness import validate_labels

MAX_REVIEW_RECORDS = 10_000
MIN_ASSESSORS = 2
MAX_ASSESSORS_PER_CASE = 10
CORPUS_SCHEMA_VERSION = 2


def artifact_digest(value):
    return canonical_digest({key: item for key, item in value.items() if key != "digest"})


def validate_corpus(corpus):
    require(
        keys(corpus, "schema_version id version source_kind packages cases digest"),
        "Invalid versioned corpus fields.",
    )
    require(
        type(corpus["schema_version"]) is int and corpus["schema_version"] == CORPUS_SCHEMA_VERSION,
        "Use corpus schema version 2.",
    )
    require(text(corpus["id"]) and integer(corpus["version"], 1, 1_000_000), "Supply a corpus identity and version.")
    require(corpus["source_kind"] in ("synthetic", "deidentified_human"), "Declare the corpus source kind.")
    require(corpus["digest"] == artifact_digest(corpus), "The corpus does not match its frozen digest.")
    require(
        isinstance(corpus["packages"], list) and 0 < len(corpus["packages"]) <= MAX_CASES,
        "Invalid package count.",
    )
    packages, versions = {}, set()
    for package in corpus["packages"]:
        require(
            keys(package, "id problem_id version content digest") and text(package["id"]),
            "Invalid package envelope.",
        )
        require(package["id"] not in packages, "Duplicate package identifier.")
        require(
            package["digest"] == package_digest(package["problem_id"], package["version"], package["content"]),
            "A package does not match its frozen digest.",
        )
        identity = (package["problem_id"], package["version"])
        require(identity not in versions, "Duplicate problem/package version.")
        versions.add(identity)
        packages[package["id"]] = package
    require(isinstance(corpus["cases"], list) and 0 < len(corpus["cases"]) <= MAX_CASES, "Invalid case count.")
    cases, splits, statement_splits = {}, {}, {}
    for case in corpus["cases"]:
        require(
            keys(case, "id package_id split submission input_digest"),
            "Keep labels and reviewer identities outside cases.",
        )
        require(text(case["id"]) and case["id"] not in cases, "Duplicate or invalid case identifier.")
        require(isinstance(case["package_id"], str) and case["package_id"] in packages, "Unknown case package.")
        require(isinstance(case["split"], str) and case["split"] in SPLITS, "Invalid corpus split.")
        require(
            keys(case["submission"], "body_source") and text(case["submission"]["body_source"]),
            "This offline corpus supports text submissions only.",
        )
        package = packages[case["package_id"]]
        require(case["input_digest"] == case_input_digest(case, package), "A case does not match its input digest.")
        previous = splits.setdefault(package["problem_id"], case["split"])
        require(previous == case["split"], "Split by problem, including across package versions.")
        statement = " ".join(package["content"]["statement"].split())
        require(
            statement_splits.setdefault(statement, case["split"]) == case["split"],
            "The same statement cannot cross splits under different problem identifiers.",
        )
        cases[case["id"]] = case
    require(set(splits.values()) == SPLITS, "Include distinct development and held-out problems.")
    return packages, cases


def _timestamp(value):
    require(text(value), "Every review needs a timestamp.")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        message = "Use an ISO-8601 review timestamp."
        raise EvaluationDataError(message) from error
    require(result.utcoffset() is not None, "Review timestamps must include a timezone.")
    return result


def _reviewers(rows):
    require(isinstance(rows, list) and len(rows) <= MAX_REVIEW_RECORDS, "Invalid reviewer registry.")
    result = {}
    for row in rows:
        require(keys(row, "id roles") and text(row["id"]) and row["id"] not in result, "Invalid reviewer identifier.")
        roles = row["roles"]
        require(
            text_list(roles)
            and bool(roles)
            and len(set(roles)) == len(roles)
            and set(roles) <= {"assessor", "adjudicator"},
            "Invalid reviewer roles.",
        )
        result[row["id"]] = set(roles)
    return result


def _record(record, fields, reviewers, identifiers):
    require(keys(record, fields), "Invalid review record fields.")
    require(text(record["id"]) and record["id"] not in identifiers, "Review record IDs must be unique.")
    require(
        isinstance(record["reviewer_id"], str) and record["reviewer_id"] in reviewers,
        "Unknown reviewer identity.",
    )
    require(text(record["rationale"]), "Review and adjudication decisions need reasons.")
    require(record["digest"] == artifact_digest(record), "A review record no longer matches its digest.")
    identifiers.add(record["id"])
    return _timestamp(record["reviewed_at"])


def _advance(record, current, key, reviewed_at):
    previous = current.get(key)
    require(
        record["supersedes"] == (previous["id"] if previous else None),
        "Review history must explicitly supersede the previous record without forks.",
    )
    require(
        previous is None or reviewed_at >= _timestamp(previous["reviewed_at"]),
        "Review history cannot run backwards.",
    )
    current[key] = record


def _case_record(record, cases, packages):
    require(isinstance(record["case_id"], str) and record["case_id"] in cases, "A review references an unknown case.")
    case = cases[record["case_id"]]
    require(record["input_digest"] == case["input_digest"], "Review evidence targets a different case input.")
    require(record["decision"] in ("labelled", "withdrawn"), "Invalid annotation decision.")
    if record["decision"] == "labelled":
        validate_labels(record["labels"], packages[case["package_id"]])
    else:
        require(record["labels"] is None, "Withdrawn labels must be null.")


def validate_reviews(corpus, reviews):
    packages, cases = validate_corpus(corpus)
    require(
        keys(
            reviews,
            "schema_version corpus_digest provenance reviewers candidate_labels "
            "package_reviews annotations adjudications digest",
        ),
        "Invalid review sidecar fields.",
    )
    require(type(reviews["schema_version"]) is int and reviews["schema_version"] == 1, "Use review schema version 1.")
    require(reviews["corpus_digest"] == corpus["digest"], "Reviews target a different corpus version or split.")
    require(reviews["digest"] == artifact_digest(reviews), "The review sidecar does not match its frozen digest.")
    require(
        reviews["provenance"] in ("synthetic_unreviewed", "human_review_records"),
        "Declare review evidence provenance.",
    )
    reviewers = _reviewers(reviews["reviewers"])
    for field in ("candidate_labels", "package_reviews", "annotations", "adjudications"):
        require(
            isinstance(reviews[field], list) and len(reviews[field]) <= MAX_REVIEW_RECORDS,
            "Invalid review record count.",
        )
    if reviews["provenance"] == "synthetic_unreviewed":
        require(
            corpus["source_kind"] == "synthetic"
            and not reviewers
            and not any(reviews[key] for key in ("package_reviews", "annotations", "adjudications")),
            "Synthetic smoke tests cannot claim human reviewers or approvals.",
        )
    else:
        require(not reviews["candidate_labels"], "Human benchmarks cannot fall back to candidate labels.")
    candidates = {}
    for row in reviews["candidate_labels"]:
        require(keys(row, "case_id input_digest labels"), "Invalid candidate label fields.")
        require(
            isinstance(row["case_id"], str) and row["case_id"] in cases and row["case_id"] not in candidates,
            "Candidate labels must target distinct known cases.",
        )
        require(row["input_digest"] == cases[row["case_id"]]["input_digest"], "Stale candidate label input.")
        validate_labels(row["labels"], packages[cases[row["case_id"]]["package_id"]])
        candidates[row["case_id"]] = row["labels"]
    identifiers, package_current, annotation_current, adjudication_current, all_annotations = set(), {}, {}, {}, {}
    for row in reviews["package_reviews"]:
        at = _record(
            row,
            "id package_id package_digest reviewer_id reviewed_at decision rationale supersedes digest",
            reviewers,
            identifiers,
        )
        require(isinstance(row["package_id"], str) and row["package_id"] in packages, "Unknown reviewed package.")
        package = packages[row["package_id"]]
        require(row["package_digest"] == package["digest"], "Package approval targets different mathematics.")
        require(row["decision"] in ("approved", "rejected", "revoked"), "Invalid package decision.")
        require(
            row["decision"] != "approved" or bool(package["content"]["references"]),
            "Package approval requires a reference solution.",
        )
        _advance(row, package_current, row["package_id"], at)
    for row in reviews["annotations"]:
        at = _record(
            row,
            "id case_id input_digest reviewer_id reviewed_at decision labels rationale supersedes digest",
            reviewers,
            identifiers,
        )
        _case_record(row, cases, packages)
        require("assessor" in reviewers[row["reviewer_id"]], "Annotation requires an assessor role.")
        _advance(row, annotation_current, (row["case_id"], row["reviewer_id"]), at)
        all_annotations[row["id"]] = row
    for row in reviews["adjudications"]:
        at = _record(
            row,
            "id case_id input_digest reviewer_id reviewed_at decision labels "
            "annotation_ids rationale supersedes digest",
            reviewers,
            identifiers,
        )
        _case_record(row, cases, packages)
        require("adjudicator" in reviewers[row["reviewer_id"]], "Resolution requires an adjudicator role.")
        ids = row["annotation_ids"]
        require(
            text_list(ids) and len(ids) >= MIN_ASSESSORS and len(set(ids)) == len(ids),
            "Identify independent annotations.",
        )
        require(set(ids) <= all_annotations.keys(), "Adjudication references unknown annotations.")
        require(
            all(
                all_annotations[key]["case_id"] == row["case_id"]
                and all_annotations[key]["decision"] == "labelled"
                and _timestamp(all_annotations[key]["reviewed_at"]) <= at
                for key in ids
            ),
            "Adjudication must reference earlier labels for the same input.",
        )
        participants = {all_annotations[key]["reviewer_id"] for key in ids}
        require(
            len(participants) == len(ids) and row["reviewer_id"] not in participants,
            "Adjudication must be independent of the original assessors.",
        )
        _advance(row, adjudication_current, row["case_id"], at)
    return {
        "packages": packages,
        "cases": cases,
        "candidates": candidates,
        "package_reviews": package_current,
        "annotations": annotation_current,
        "adjudications": adjudication_current,
    }


def resolve_labels(corpus, reviews, *, split, purpose):
    require(isinstance(split, str) and split in SPLITS, "Select a corpus split.")
    require(purpose in ("smoke_test", "human_benchmark"), "Select an offline evaluation purpose.")
    state = validate_reviews(corpus, reviews)
    selected = {key: row for key, row in state["cases"].items() if row["split"] == split}
    if purpose == "smoke_test":
        require(
            reviews["provenance"] == "synthetic_unreviewed",
            "Smoke tests require explicitly unreviewed synthetic data.",
        )
        require(selected.keys() <= state["candidates"].keys(), "Missing synthetic candidate labels.")
        return {key: state["candidates"][key] for key in selected}, {
            "status": "synthetic_unreviewed",
            "reviewer_identity_authenticated": False,
            "adjudicated_cases": 0,
            "inter_rater": None,
        }
    require(
        reviews["provenance"] == "human_review_records",
        "Human benchmarks require independent human review records.",
    )
    labels, pairs, adjudicated = {}, [], 0
    for case_id, case in selected.items():
        approval = state["package_reviews"].get(case["package_id"])
        require(
            approval is not None and approval["decision"] == "approved",
            "The selected package is not currently approved.",
        )
        active = [
            row
            for (identifier, _reviewer), row in state["annotations"].items()
            if identifier == case_id and row["decision"] == "labelled"
        ]
        require(len(active) >= MIN_ASSESSORS, "Each selected case needs at least two independent current annotations.")
        require(
            len(active) <= MAX_ASSESSORS_PER_CASE,
            "Use at most ten current assessors per case for bounded pair metrics.",
        )
        pairs.extend((left["labels"], right["labels"]) for left, right in combinations(active, 2))
        distinct = {canonical_digest(row["labels"]) for row in active}
        resolution = state["adjudications"].get(case_id)
        if resolution is not None:
            require(
                resolution["decision"] == "labelled",
                "An adjudication was withdrawn; a fresh resolution is required.",
            )
            require(
                set(resolution["annotation_ids"]) == {row["id"] for row in active},
                "Adjudication is stale after an annotation changed or was withdrawn.",
            )
            labels[case_id] = resolution["labels"]
            adjudicated += 1
        else:
            require(len(distinct) == 1, "Disagreeing assessors require an explicit independent adjudication.")
            labels[case_id] = active[0]["labels"]
    score_errors = [
        abs(left["score"] - right["score"])
        for left, right in pairs
        if left["score"] is not None and right["score"] is not None
    ]
    return labels, {
        "status": "human_review_records",
        "reviewer_identity_authenticated": False,
        "adjudicated_cases": adjudicated,
        "inter_rater": {
            "annotation_pairs": len(pairs),
            "category_agreement": sum(left["assessment"] == right["assessment"] for left, right in pairs) / len(pairs),
            "full_label_agreement": sum(left == right for left, right in pairs) / len(pairs),
            "score_pairs": len(score_errors),
            "score_mae": sum(score_errors) / len(score_errors) if score_errors else None,
        },
    }


def review_coverage(corpus, reviews):
    state = validate_reviews(corpus, reviews)
    counts = Counter(row["case_id"] for row in state["annotations"].values() if row["decision"] == "labelled")
    active = {}
    for row in state["annotations"].values():
        if row["decision"] == "labelled":
            active.setdefault(row["case_id"], []).append(row)
    return {
        "corpus_digest": corpus["digest"],
        "reviews_digest": reviews["digest"],
        "provenance": reviews["provenance"],
        "cases": len(state["cases"]),
        "cases_with_two_assessors": sum(count >= MIN_ASSESSORS for count in counts.values()),
        "missing_independent_annotations": sorted(key for key in state["cases"] if counts[key] < MIN_ASSESSORS),
        "currently_approved_packages": sum(row["decision"] == "approved" for row in state["package_reviews"].values()),
        "disagreement_cases": sorted(
            key for key, rows in active.items() if len({canonical_digest(row["labels"]) for row in rows}) > 1
        ),
        "stale_or_withdrawn_adjudications": sorted(
            key
            for key, row in state["adjudications"].items()
            if row["decision"] == "withdrawn"
            or set(row["annotation_ids"]) != {item["id"] for item in active.get(key, [])}
        ),
        "release_gate_passed": False,
    }


def empty_review_template(corpus):
    validate_corpus(corpus)
    result = {
        "schema_version": 1,
        "corpus_digest": corpus["digest"],
        "provenance": "human_review_records",
        "reviewers": [],
        "candidate_labels": [],
        "package_reviews": [],
        "annotations": [],
        "adjudications": [],
    }
    result["digest"] = artifact_digest(result)
    return result
