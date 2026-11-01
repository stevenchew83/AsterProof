# ruff: noqa: PLR2004 - Explicit fixture counts, rates, scores, and versions are regression expectations.
"""Offline comparison and simulated review records never create human approval evidence."""

import json
import socket
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from inspinia.solutions.assessment_prompts import MODE_PROMPTS
from inspinia.solutions.comparison_plans import build_comparison_plan
from inspinia.solutions.comparison_plans import validate_comparison_plan
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import load_json_file
from inspinia.solutions.evaluation_contracts import package_digest
from inspinia.solutions.evaluation_harness import case_input_digest
from inspinia.solutions.model_comparison import compare_runs
from inspinia.solutions.model_comparison import main
from inspinia.solutions.reviewed_datasets import artifact_digest
from inspinia.solutions.reviewed_datasets import empty_review_template
from inspinia.solutions.reviewed_datasets import resolve_labels
from inspinia.solutions.reviewed_datasets import review_coverage
from inspinia.solutions.reviewed_datasets import validate_corpus
from inspinia.solutions.reviewed_datasets import validate_reviews

DATA = Path(__file__).with_name("testdata")
VALID_CASE = "synthetic-nt-held_out-alternative"


def seal(value):
    value["digest"] = artifact_digest(value)
    return value


@pytest.fixture
def artifacts():
    return [
        load_json_file(DATA / name)
        for name in (
            "comparison_corpus_synthetic.json",
            "comparison_reviews_pending.json",
            "comparison_plan_synthetic.json",
            "comparison_astra_fixture.json",
            "comparison_sol_fixture.json",
        )
    ]


def human_records(corpus, pending):
    """In-memory test simulation only. No shipped example asserts real human review."""
    reviews = empty_review_template(corpus)
    reviews["reviewers"] = [
        {"id": "test-assessor-a", "roles": ["assessor", "adjudicator"]},
        {"id": "test-assessor-b", "roles": ["assessor"]},
        {"id": "test-adjudicator-c", "roles": ["adjudicator"]},
    ]
    for package in corpus["packages"]:
        reviews["package_reviews"].append(
            seal(
                {
                    "id": "approve-" + package["id"],
                    "package_id": package["id"],
                    "package_digest": package["digest"],
                    "reviewer_id": "test-assessor-a",
                    "reviewed_at": "2026-11-01T00:00:00+00:00",
                    "decision": "approved",
                    "rationale": "Simulated unit-test approval, not a real human decision.",
                    "supersedes": None,
                },
            ),
        )
    for candidate in pending["candidate_labels"]:
        for reviewer in ("test-assessor-a", "test-assessor-b"):
            reviews["annotations"].append(
                seal(
                    {
                        "id": candidate["case_id"] + "-" + reviewer,
                        "case_id": candidate["case_id"],
                        "input_digest": candidate["input_digest"],
                        "reviewer_id": reviewer,
                        "reviewed_at": "2026-11-01T01:00:00+00:00",
                        "decision": "labelled",
                        "labels": deepcopy(candidate["labels"]),
                        "rationale": "Simulated unit-test annotation only.",
                        "supersedes": None,
                    },
                ),
            )
    return seal(reviews)


def resolve(corpus, reviews):
    return resolve_labels(corpus, reviews, split="held_out", purpose="human_benchmark")


def dispute(reviews):
    rows = [row for row in reviews["annotations"] if row["case_id"] == VALID_CASE]
    rows[1]["labels"]["score"] = 6
    seal(rows[1])
    seal(reviews)
    return rows


def adjudicate(reviews, rows, reviewer="test-adjudicator-c"):
    reviews["adjudications"].append(
        seal(
            {
                "id": "test-resolution",
                "case_id": VALID_CASE,
                "input_digest": rows[0]["input_digest"],
                "reviewer_id": reviewer,
                "reviewed_at": "2026-11-01T02:00:00+00:00",
                "decision": "labelled",
                "labels": deepcopy(rows[0]["labels"]),
                "annotation_ids": [row["id"] for row in rows],
                "rationale": "Simulated unit-test adjudication only.",
                "supersedes": None,
            },
        ),
    )
    seal(reviews)


def imported(run):
    """Simulate imported metadata in memory; no provider is invoked."""
    run = deepcopy(run)
    run["execution_kind"] = "imported_provider_results"
    for row in run["records"]:
        if row["status"] == "completed":
            row["returned_models"] = [run["model"], run["model"]]
            row["provider_request_ids"] = [
                f"test-{run['model']}-{row['case_id']}-{row['trial']}-{stage}" for stage in ("assessment", "feedback")
            ]
    return seal(run)


def test_shipped_records_remain_unreviewed_and_cannot_form_a_human_benchmark(artifacts):
    corpus, pending, *_rest = artifacts
    coverage = review_coverage(corpus, pending)
    assert coverage["cases"] == 24
    assert coverage["cases_with_two_assessors"] == 0
    assert coverage["currently_approved_packages"] == 0
    assert not pending["reviewers"]
    assert not pending["annotations"]
    with pytest.raises(EvaluationDataError, match="independent human review"):
        resolve(corpus, pending)
    template = empty_review_template(corpus)
    assert not template["candidate_labels"]
    assert review_coverage(corpus, template)["cases_with_two_assessors"] == 0


def test_two_independent_annotations_resolve_and_produce_inter_rater_metrics(artifacts):
    corpus, pending, *_rest = artifacts
    reviews = human_records(corpus, pending)
    labels, evidence = resolve(corpus, reviews)
    assert len(labels) == 12
    assert labels[VALID_CASE]["score"] == 7
    assert evidence["inter_rater"]["category_agreement"] == 1
    assert evidence["inter_rater"]["score_mae"] == 0
    assert evidence["reviewer_identity_authenticated"] is False


def test_disagreements_require_independent_adjudication(artifacts):
    corpus, pending, *_rest = artifacts
    reviews = human_records(corpus, pending)
    rows = dispute(reviews)
    assert VALID_CASE in review_coverage(corpus, reviews)["disagreement_cases"]
    with pytest.raises(EvaluationDataError, match="Disagreeing assessors"):
        resolve(corpus, reviews)
    adjudicate(reviews, rows)
    labels, evidence = resolve(corpus, reviews)
    assert labels[VALID_CASE]["score"] == 7
    assert evidence["adjudicated_cases"] == 1
    assert evidence["inter_rater"]["score_mae"] > 0


@pytest.mark.parametrize("change", ["self_adjudication", "withdrawal", "stale_resolution", "revoked_package", "fork"])
def test_invalid_or_superseded_review_evidence_cannot_silently_supply_gold_labels(artifacts, change):
    corpus, pending, *_rest = artifacts
    reviews = human_records(corpus, pending)
    rows = dispute(reviews)
    if change == "self_adjudication":
        adjudicate(reviews, rows, "test-assessor-a")
    else:
        adjudicate(reviews, rows)
        if change == "revoked_package":
            old = next(row for row in reviews["package_reviews"] if "nt-held_out" in row["package_id"])
            reviews["package_reviews"].append(
                seal(
                    {
                        **old,
                        "id": "test-revocation",
                        "decision": "revoked",
                        "supersedes": old["id"],
                        "reviewed_at": "2026-11-01T03:00:00+00:00",
                    },
                ),
            )
        else:
            new = {
                **deepcopy(rows[1]),
                "id": "test-later-annotation",
                "supersedes": rows[1]["id"],
                "reviewed_at": "2026-11-01T03:00:00+00:00",
            }
            if change == "withdrawal":
                new.update(decision="withdrawn", labels=None)
            elif change == "fork":
                new["supersedes"] = None
            reviews["annotations"].append(seal(new))
    seal(reviews)
    with pytest.raises(EvaluationDataError):
        resolve(corpus, reviews)


@pytest.mark.parametrize("defect", ["stale_input", "unknown_reviewer", "naive_time", "bad_time", "bad_digest"])
def test_review_records_bind_exact_input_identity_time_and_content(artifacts, defect):
    corpus, pending, *_rest = artifacts
    reviews = human_records(corpus, pending)
    row = reviews["annotations"][0]
    if defect == "stale_input":
        row["input_digest"] = "0" * 64
    elif defect == "unknown_reviewer":
        row["reviewer_id"] = "not-registered"
    elif defect == "naive_time":
        row["reviewed_at"] = "2026-11-01T01:00:00"
    elif defect == "bad_time":
        row["reviewed_at"] = "not a timestamp"
    else:
        row["rationale"] = "Changed after review."
    if defect != "bad_digest":
        seal(row)
    seal(reviews)
    with pytest.raises(EvaluationDataError):
        validate_reviews(corpus, reviews)


def test_candidate_labels_cannot_masquerade_as_human_review(artifacts):
    corpus, pending, *_rest = artifacts
    pending["provenance"] = "human_review_records"
    seal(pending)
    with pytest.raises(EvaluationDataError, match="fall back to candidate"):
        validate_reviews(corpus, pending)


def test_same_problem_or_identical_statement_cannot_leak_across_splits(artifacts):
    corpus = artifacts[0]
    corpus["cases"][0]["split"] = "held_out"
    seal(corpus)
    with pytest.raises(EvaluationDataError, match="Split by problem"):
        validate_corpus(corpus)
    corpus["cases"][0]["split"] = "development"
    package = deepcopy(corpus["packages"][0])
    package.update(id="renamed-package", problem_id="renamed-problem")
    package["digest"] = package_digest(package["problem_id"], package["version"], package["content"])
    case = {**deepcopy(corpus["cases"][0]), "id": "renamed-case", "package_id": package["id"], "split": "held_out"}
    case["input_digest"] = case_input_digest(case, package)
    corpus["packages"].append(package)
    corpus["cases"].append(case)
    seal(corpus)
    with pytest.raises(EvaluationDataError, match="same statement"):
        validate_corpus(corpus)


def test_plan_freezes_matched_inputs_and_excludes_gold_labels_and_people(artifacts):
    corpus, reviews, plan, *_runs = artifacts
    assert build_comparison_plan(corpus, reviews, repetitions=2) == plan
    assert plan["models"] == {"astra": "gpt-6-astra", "sol": "gpt-6.1-sol"}
    assert plan["reasoning_effort"] == "high"
    assert len(plan["cases"]) == 12
    for case in plan["cases"]:
        packet = case["assessment_request"]["input"]
        assert set(packet) == {"provenance", "case_id", "input_digest", "submission", "package"}
        assert "labels" not in packet
    assert "reviewer_id" not in json.dumps(plan)
    plan["reasoning_effort"] = "medium"
    seal(plan)
    with pytest.raises(EvaluationDataError, match="experiment settings changed"):
        validate_comparison_plan(plan, corpus, reviews)


def test_prompt_changes_require_new_plans(artifacts, monkeypatch):
    corpus, reviews, plan, *_runs = artifacts
    monkeypatch.setitem(MODE_PROMPTS, "provisional", MODE_PROMPTS["provisional"] + " New instructions.")
    with pytest.raises(EvaluationDataError, match="prompts"):
        validate_comparison_plan(plan, corpus, reviews)


def test_fixture_comparison_reports_errors_coverage_pairing_and_unknown_operations(artifacts):
    result = compare_runs(*artifacts)
    astra, sol = result["models"]["astra"], result["models"]["sol"]
    assert astra["metrics"]["total"] == sol["metrics"]["total"] == 24
    assert sol["failures"] == {"failed": 2}
    assert sol["invalid_output_count"] == 1
    assert sol["raw_claim_grounding_rate"] < 1
    assert sol["metrics"]["score_coverage"] == 16 / 18
    assert sol["repeatability"]["cases_with_different_outcomes"] == 3
    assert result["paired_scoring"] == {"common_scored_case_trials": 16, "astra_mae": 0, "sol_mae": 7 / 16}
    assert sol["operations"]["tokens"] is None
    assert sol["operations"]["mean_latency_ms"] is None
    assert sol["operations"]["estimated_cost_usd_for_known_usage"] is None
    assert result["recommended_model"] is None
    assert not result["release_gate_passed"]


@pytest.mark.parametrize(
    "defect",
    ["missing", "duplicate", "model", "reasoning", "input", "feedback_context", "fabricated_usage"],
)
def test_unmatched_or_misrepresented_runs_are_rejected(artifacts, defect):
    run = artifacts[3]
    if defect == "missing":
        run["records"].pop()
    elif defect == "duplicate":
        run["records"].append(deepcopy(run["records"][0]))
    elif defect == "model":
        run["model"] = "gpt-6.1-sol"
    elif defect == "reasoning":
        run["reasoning_effort"] = "medium"
    elif defect == "input":
        run["records"][0]["input_digest"] = "0" * 64
    elif defect == "feedback_context":
        run["records"][0]["feedback_request_digest"] = "0" * 64
    else:
        run["records"][0]["latency_ms"] = 100
    seal(run)
    with pytest.raises(EvaluationDataError):
        compare_runs(*artifacts)


def test_refusals_and_invalid_mode_outputs_stay_in_the_denominator(artifacts):
    run = artifacts[3]
    run["records"][0].update(status="refused", assessment=None, mode_feedback=None, feedback_request_digest=None)
    run["records"][1]["mode_feedback"]["score"] = 7
    seal(run)
    astra = compare_runs(*artifacts)["models"]["astra"]
    assert astra["metrics"]["total"] == 24
    assert astra["failures"] == {"refused": 1, "failed": 1}
    assert astra["invalid_output_count"] == 1


@pytest.mark.parametrize("defect", ["evidence", "mode_output", "assessment_shape"])
def test_invalid_output_cannot_hide_a_changed_feedback_context(artifacts, defect):
    row = artifacts[3]["records"][0]
    row["feedback_request_digest"] = "0" * 64
    if defect == "evidence":
        row["assessment"]["claims"][0]["evidence"]["quote"] = "Invented source passage."
    elif defect == "mode_output":
        row["mode_feedback"]["score"] = 7
    else:
        row["assessment"]["unexpected"] = True
    seal(artifacts[3])
    with pytest.raises(EvaluationDataError, match="Feedback context"):
        compare_runs(*artifacts)


def test_imported_usage_counts_reasoning_once_and_exposes_cost_coverage(artifacts):
    corpus, reviews, _plan, astra, sol = artifacts
    pricing = {
        "currency": "USD",
        "source": "Unit-test arithmetic rates, not verified current pricing",
        "verified_at": "2026-11-01T00:00:00+00:00",
        "models": {
            "astra": {
                "input_usd_per_million": "10",
                "cached_input_usd_per_million": "1",
                "output_usd_per_million": "50",
            },
            "sol": {
                "input_usd_per_million": "2",
                "cached_input_usd_per_million": "0.1",
                "output_usd_per_million": "10",
            },
        },
    }
    plan = build_comparison_plan(corpus, reviews, repetitions=2, pricing=pricing)
    runs = [imported(astra), imported(sol)]
    for run in runs:
        run["plan_digest"] = plan["digest"]
        for row in run["records"]:
            row.update(
                usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 50, "reasoning_tokens": 30},
                latency_ms=100,
            )
        seal(run)
    result = compare_runs(corpus, reviews, plan, *runs)
    ops = result["models"]["astra"]["operations"]
    assert Decimal(ops["estimated_cost_usd_for_known_usage"]) == Decimal("0.07968")
    assert ops["known_reasoning_tokens"] == 720
    assert ops["usage_coverage"] == 1
    assert ops["p95_latency_ms"] == 100
    assert not ops["invoiced_cost_observed"]


def test_provider_request_reuse_and_wrong_returned_family_are_rejected(artifacts):
    corpus, reviews, plan, astra, sol = artifacts
    astra, sol = imported(astra), imported(sol)
    original = astra["records"][1]["provider_request_ids"]
    astra["records"][1]["provider_request_ids"] = astra["records"][0]["provider_request_ids"]
    seal(astra)
    with pytest.raises(EvaluationDataError, match="distinct provider"):
        compare_runs(corpus, reviews, plan, astra, sol)
    astra["records"][1]["provider_request_ids"] = original
    astra["records"][0]["returned_models"] = ["gpt-6-luna", "gpt-6-luna"]
    seal(astra)
    with pytest.raises(EvaluationDataError, match="different family"):
        compare_runs(corpus, reviews, plan, astra, sol)


def test_human_benchmark_requires_real_run_provenance_and_still_cannot_approve_release(artifacts):
    corpus, pending, _old_plan, astra, sol = artifacts
    reviews = human_records(corpus, pending)
    plan = build_comparison_plan(corpus, reviews, repetitions=2, purpose="human_benchmark")
    astra["plan_digest"] = sol["plan_digest"] = plan["digest"]
    seal(astra)
    seal(sol)
    with pytest.raises(EvaluationDataError, match="Synthetic runs"):
        compare_runs(corpus, reviews, plan, astra, sol)
    result = compare_runs(corpus, reviews, plan, imported(astra), imported(sol))
    assert result["review_evidence"]["status"] == "human_review_records"
    assert result["review_evidence"]["reviewer_identity_authenticated"] is False
    assert result["recommended_model"] is None
    assert result["release_gate_passed"] is False


def test_cli_is_offline_and_does_not_emit_proof_bodies(artifacts, monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline comparison must not open a network connection.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "model_comparison",
            "compare",
            "--corpus",
            str(DATA / "comparison_corpus_synthetic.json"),
            "--reviews",
            str(DATA / "comparison_reviews_pending.json"),
            "--plan",
            str(DATA / "comparison_plan_synthetic.json"),
            "--astra",
            str(DATA / "comparison_astra_fixture.json"),
            "--sol",
            str(DATA / "comparison_sol_fixture.json"),
        ],
    )
    main()
    output = capsys.readouterr().out
    assert json.loads(output) == compare_runs(*artifacts)
    assert artifacts[0]["cases"][0]["submission"]["body_source"] not in output


@pytest.mark.parametrize("command", ["review-template", "coverage", "plan"])
def test_preparation_commands_produce_bound_artifacts_without_promoting_labels(command, monkeypatch, capsys):
    args = ["model_comparison", command, "--corpus", str(DATA / "comparison_corpus_synthetic.json")]
    if command != "review-template":
        args += ["--reviews", str(DATA / "comparison_reviews_pending.json")]
    if command == "plan":
        args += ["--repetitions", "2"]
    monkeypatch.setattr(sys, "argv", args)
    main()
    result = json.loads(capsys.readouterr().out)
    if command == "review-template":
        assert result["annotations"] == []
        assert result["package_reviews"] == []
    elif command == "coverage":
        assert result["cases_with_two_assessors"] == 0
        assert not result["release_gate_passed"]
    else:
        assert result == load_json_file(DATA / "comparison_plan_synthetic.json")


def test_cli_refuses_a_human_benchmark_with_pending_synthetic_labels(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "model_comparison",
            "plan",
            "--corpus",
            str(DATA / "comparison_corpus_synthetic.json"),
            "--reviews",
            str(DATA / "comparison_reviews_pending.json"),
            "--purpose",
            "human_benchmark",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 2
    assert "independent human review records" in capsys.readouterr().err
