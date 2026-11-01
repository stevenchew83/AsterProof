"""Offline scoring cannot promote synthetic labels into approved evidence."""

import copy
import json
from collections import Counter
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from inspinia.solutions.coach_evaluation import CoachEvaluationError
from inspinia.solutions.coach_evaluation import approval_digest
from inspinia.solutions.coach_evaluation import evaluate_reports
from inspinia.solutions.coach_evaluation import load_json_file

SEED_PATH = Path(__file__).with_name("testdata") / "coach_evaluation_seed.json"
HELD_OUT_COUNT = 60
DEVELOPMENT_COUNT = 20
AGREEMENT_WITH_ONE_ERROR = 59 / 60
DIGEST_LENGTH = 64


@pytest.fixture
def dataset():
    return load_json_file(SEED_PATH)


def approved_test_dataset(dataset):
    """Only in-memory test data is approved; the bundled seeds remain pending."""
    result = copy.deepcopy(dataset)
    for case in result["cases"]:
        case.update(
            label_status="coach_approved",
            expected_assessment=case["candidate_assessment"],
            reviewed_by="Synthetic unit-test reviewer",
            reviewed_at="2026-11-01T00:00:00+00:00",
        )
        case["approval_digest"] = approval_digest(case)
    return result


def reports_for(dataset, split="held_out"):
    return {
        "schema_version": 1,
        "reports": [
            {"case_id": case["id"], "status": "completed", "assessment": case["expected_assessment"]}
            for case in dataset["cases"]
            if case["split"] == split
        ],
    }


def test_seed_corpus_is_balanced_but_explicitly_unapproved(dataset):
    assert len(dataset["cases"]) == HELD_OUT_COUNT + DEVELOPMENT_COUNT
    assert Counter(case["domain"] for case in dataset["cases"]) == {"ALG": 20, "GEO": 20, "NT": 20, "COM": 20}
    assert Counter(case["split"] for case in dataset["cases"]) == {"development": 20, "held_out": 60}
    assert Counter(case["candidate_assessment"] for case in dataset["cases"]) == {
        "no_issues_found": 20,
        "gap_found": 20,
        "incomplete": 20,
        "unable_to_assess": 20,
    }
    assert all(case["label_status"] == "needs_coach_review" for case in dataset["cases"])
    assert all(case["expected_assessment"] is None for case in dataset["cases"])


def test_unapproved_held_out_labels_cannot_produce_a_score(dataset):
    with pytest.raises(CoachEvaluationError, match="coach approval"):
        evaluate_reports(dataset, {"schema_version": 1, "reports": []})


def test_approved_fixture_scores_all_cases(dataset):
    approved = approved_test_dataset(dataset)
    result = evaluate_reports(approved, reports_for(approved))
    assert result["total"] == HELD_OUT_COUNT
    assert result["category_agreement"] == 1
    assert result["critical_false_clear_count"] == 0
    assert result["release_gate_passed"]
    assert all(row["correct"] == row["total"] for row in result["by_domain"].values())


def test_one_false_clear_fails_even_with_high_agreement(dataset):
    approved = approved_test_dataset(dataset)
    reports = reports_for(approved)
    critical_id = next(
        case["id"] for case in approved["cases"] if case["split"] == "held_out" and case["critical_error"]
    )
    next(row for row in reports["reports"] if row["case_id"] == critical_id)["assessment"] = "no_issues_found"
    result = evaluate_reports(approved, reports)
    assert result["category_agreement"] == AGREEMENT_WITH_ONE_ERROR
    assert result["critical_false_clear_cases"] == [critical_id]
    assert not result["release_gate_passed"]


def test_provider_refusals_count_as_failures_not_silent_omissions(dataset):
    approved = approved_test_dataset(dataset)
    reports = reports_for(approved)
    reports["reports"][0].update(status="refused", assessment=None)
    result = evaluate_reports(approved, reports)
    assert result["category_agreement"] == AGREEMENT_WITH_ONE_ERROR
    assert result["provider_failures"] == {"refused": 1}


def test_missing_duplicate_or_extra_reports_are_rejected(dataset):
    approved = approved_test_dataset(dataset)
    reports = reports_for(approved)
    reports["reports"].pop()
    with pytest.raises(CoachEvaluationError, match="Missing reports"):
        evaluate_reports(approved, reports)
    reports = reports_for(approved)
    reports["reports"].append(reports["reports"][0])
    with pytest.raises(CoachEvaluationError, match="exactly once"):
        evaluate_reports(approved, reports)


def test_approval_is_invalidated_by_changes_to_proof_or_expected_label(dataset):
    approved = approved_test_dataset(dataset)
    held_out = next(case for case in approved["cases"] if case["split"] == "held_out")
    held_out["body_source"] += " Changed after approval."
    with pytest.raises(CoachEvaluationError, match="exact inputs"):
        evaluate_reports(approved, reports_for(approved))


def test_development_score_is_never_release_approval(dataset):
    approved = approved_test_dataset(dataset)
    result = evaluate_reports(approved, reports_for(approved, "development"), split="development")
    assert result["total"] == DEVELOPMENT_COUNT
    assert result["category_agreement"] == 1
    assert not result["release_gate_passed"]


def test_management_command_is_offline_and_refuses_unapproved_data(dataset, tmp_path):
    cases = tmp_path / "cases.json"
    reports = tmp_path / "reports.json"
    cases.write_text(json.dumps(dataset))
    reports.write_text(json.dumps({"schema_version": 1, "reports": []}))
    with pytest.raises(CommandError, match="coach approval"):
        call_command("evaluate_coach_reports", cases=cases, reports=reports, stdout=StringIO())


def test_offline_command_emits_reproducible_metrics(dataset, tmp_path):
    approved = approved_test_dataset(dataset)
    cases = tmp_path / "cases.json"
    reports = tmp_path / "reports.json"
    cases.write_text(json.dumps(approved))
    reports.write_text(json.dumps(reports_for(approved)))
    output = StringIO()
    call_command("evaluate_coach_reports", cases=cases, reports=reports, stdout=output)
    result = json.loads(output.getvalue())
    assert result["release_gate_passed"]
    assert len(result["dataset_digest"]) == len(result["reports_digest"]) == DIGEST_LENGTH
