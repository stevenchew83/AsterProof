# ruff: noqa: PLR2004 - Exact fixture counts, scores, and rates are regression assertions.
"""Exercise local metrics with deliberate synthetic successes and failures."""

import copy
import json
import socket
import sys
from pathlib import Path

import pytest

from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import load_json_file
from inspinia.solutions.evaluation_contracts import package_digest
from inspinia.solutions.evaluation_contracts import validate_package_content
from inspinia.solutions.evaluation_harness import case_input_digest
from inspinia.solutions.evaluation_harness import evaluate_assessments
from inspinia.solutions.evaluation_harness import main
from inspinia.solutions.evaluation_harness import validate_dataset

DATA = Path(__file__).with_name("testdata")


@pytest.fixture
def corpus():
    return (
        load_json_file(DATA / "problem_evaluation_synthetic.json"),
        load_json_file(DATA / "assessment_reports_synthetic.json"),
    )


def test_fixture_metrics_expose_known_failures_without_claiming_release_readiness(corpus):
    dataset, reports = corpus
    result = evaluate_assessments(dataset, reports)
    metrics = result["metrics"]
    assert metrics["total"] == 12
    assert metrics["category_agreement"] == 0.75
    assert metrics["critical_error_detection_rate"] == 0.75
    assert metrics["false_criticism_rate"] == 0.25
    assert metrics["score_mae"] == 6 / 9
    assert metrics["source_grounding_rate"] == 0.75
    assert metrics["required_escalation_recall"] == 1
    assert result["provider_failures"] == {"failed": 1}
    assert result["critical_false_acceptance_cases"] == ["synthetic-nt-held_out-invalid"]
    assert result["ungrounded_finding_cases"] == ["synthetic-alg-held_out-invalid"]
    assert not result["human_validated"]
    assert not result["release_gate_passed"]
    assert result["alternative_methods"]["false_criticism_rate"] == 0.25
    assert evaluate_assessments(dataset, reports) == result


def test_all_problem_versions_and_submissions_stay_within_one_split(corpus):
    dataset, _ = corpus
    dataset["cases"][0]["split"] = "held_out"
    with pytest.raises(EvaluationDataError, match="Split by problem"):
        validate_dataset(dataset)


@pytest.mark.parametrize("target", ["package", "submission", "report"])
def test_changed_input_or_stale_report_digest_is_rejected(corpus, target):
    dataset, reports = corpus
    if target == "package":
        dataset["packages"][0]["content"]["statement"] += " Changed."
    elif target == "submission":
        dataset["cases"][0]["submission"]["body_source"] += " Changed."
    else:
        reports["reports"][0]["input_digest"] = "0" * 64
    with pytest.raises(EvaluationDataError, match="digest|different submission"):
        evaluate_assessments(dataset, reports)


def test_reports_are_bound_to_reference_package_version(corpus):
    dataset, reports = corpus
    package = dataset["packages"][0]
    package["version"] += 1
    package["digest"] = package_digest(package["problem_id"], package["version"], package["content"])
    for case in dataset["cases"]:
        if case["package_id"] == package["id"]:
            case["input_digest"] = case_input_digest(case, package)
    with pytest.raises(EvaluationDataError, match="different submission or package"):
        evaluate_assessments(dataset, reports, split="development")


def test_missing_duplicate_unknown_and_failed_reports_cannot_disappear(corpus):
    dataset, reports = corpus
    held_out = next(row for row in reports["reports"] if "held_out" in row["case_id"])
    reports["reports"].remove(held_out)
    with pytest.raises(EvaluationDataError, match="Missing reports"):
        evaluate_assessments(dataset, reports)
    reports["reports"].extend([held_out, held_out])
    with pytest.raises(EvaluationDataError, match="distinct known"):
        evaluate_assessments(dataset, reports)
    reports["reports"].pop()
    reports["reports"][-1]["case_id"] = "unknown"
    with pytest.raises(EvaluationDataError, match="distinct known"):
        evaluate_assessments(dataset, reports)


def test_score_abstention_changes_coverage_without_improving_denominator_silently(corpus):
    dataset, reports = corpus
    report = next(row for row in reports["reports"] if row["case_id"] == "synthetic-nt-held_out-invalid")
    report.update(score=None, score_status="human_review_required", human_review_required=True)
    metrics = evaluate_assessments(dataset, reports)["metrics"]
    assert metrics["score_eligible_cases"] == 9
    assert metrics["scored_cases"] == 8
    assert metrics["score_coverage"] == 8 / 9
    assert metrics["score_mae"] == 2 / 8
    assert metrics["critical_false_acceptance_count"] == 1


def test_scoring_a_case_without_target_credit_is_reported(corpus):
    dataset, reports = corpus
    report = next(row for row in reports["reports"] if row["case_id"] == "synthetic-geo-held_out-partial")
    report.update(assessment="no_issues_found", score=7, score_status="provided", human_review_required=False)
    metrics = evaluate_assessments(dataset, reports)["metrics"]
    assert metrics["scores_without_target_count"] == 1
    assert metrics["scores_requiring_human_review_count"] == 1
    assert metrics["required_escalation_recall"] == 0


@pytest.mark.parametrize("score", [-1, 8, True, 1.5])
def test_invalid_candidate_scores_are_rejected(corpus, score):
    dataset, reports = corpus
    reports["reports"][0]["score"] = score
    with pytest.raises(EvaluationDataError, match="candidate score"):
        evaluate_assessments(dataset, reports)


def test_dataset_cannot_assert_human_approval(corpus):
    dataset, reports = corpus
    dataset["provenance"] = "human_approved"
    with pytest.raises(EvaluationDataError, match="only unapproved synthetic"):
        evaluate_assessments(dataset, reports)


@pytest.mark.parametrize("defect", ["unknown_dependency", "cycle", "bad_cap", "duplicate_id", "bad_image"])
def test_invalid_mathematical_package_contracts_fail(corpus, defect):
    content = corpus[0]["packages"][0]["content"]
    criteria = content["rubric"]["criteria"]
    if defect == "unknown_dependency":
        criteria[0]["depends_on"] = ["missing"]
    elif defect == "cycle":
        criteria[0]["depends_on"] = ["completion"]
    elif defect == "bad_cap":
        content["rubric"]["caps"][0]["max_score"] = 8
    elif defect == "duplicate_id":
        criteria[1]["id"] = criteria[0]["id"]
    else:
        content["images"] = [{"id": "diagram", "sha256": "not-a-hash", "description": "A triangle"}]
    with pytest.raises(EvaluationDataError):
        validate_package_content(content)


@pytest.mark.parametrize("value", ['{"a":1,"a":2}', '{"a": NaN}', '{"a": Infinity}', "not json"])
def test_json_loader_rejects_ambiguous_or_nonfinite_input(tmp_path, value):
    path = tmp_path / "invalid.json"
    path.write_text(value)
    with pytest.raises(EvaluationDataError):
        load_json_file(path)


def test_oversized_files_are_rejected_before_json_parsing(tmp_path):
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * (1_048_576 + 1))
    with pytest.raises(EvaluationDataError, match="at most 1 MB"):
        load_json_file(path)


def test_cli_runs_without_provider_or_network_and_emits_no_proof_bodies(corpus, monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        pytest.fail("The local harness must never open a network connection.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluation_harness",
            "--dataset",
            str(DATA / "problem_evaluation_synthetic.json"),
            "--reports",
            str(DATA / "assessment_reports_synthetic.json"),
        ],
    )
    main()
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result == evaluate_assessments(*corpus)
    assert corpus[0]["cases"][0]["submission"]["body_source"] not in output


def test_perfect_synthetic_reports_still_never_approve_a_release(corpus):
    dataset, reports = copy.deepcopy(corpus)
    cases = {case["id"]: case for case in dataset["cases"]}
    for report in reports["reports"]:
        labels = cases[report["case_id"]]["candidate_labels"]
        report.update(
            status="completed",
            assessment=labels["assessment"],
            findings=[],
            score=labels["score"],
            score_status="provided" if labels["score"] is not None else "unavailable",
            human_review_required=labels["human_review_required"],
        )
    result = evaluate_assessments(dataset, reports)
    assert result["metrics"]["category_agreement"] == 1
    assert not result["release_gate_passed"]
