"""Compare imported, matched Astra/Sol outputs offline. This module never executes a model."""

import argparse
import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import mean

from inspinia.solutions.assessment_prompts import feedback_request
from inspinia.solutions.assessment_reporting import prepare_report
from inspinia.solutions.comparison_plans import build_comparison_plan
from inspinia.solutions.comparison_plans import validate_comparison_plan
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import canonical_digest
from inspinia.solutions.evaluation_contracts import integer
from inspinia.solutions.evaluation_contracts import keys
from inspinia.solutions.evaluation_contracts import load_json_file
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import text
from inspinia.solutions.evaluation_contracts import text_list
from inspinia.solutions.evaluation_harness import STATUSES
from inspinia.solutions.evaluation_harness import assessment_metric_row
from inspinia.solutions.evaluation_harness import summarize_metrics
from inspinia.solutions.reviewed_datasets import artifact_digest
from inspinia.solutions.reviewed_datasets import empty_review_template
from inspinia.solutions.reviewed_datasets import resolve_labels
from inspinia.solutions.reviewed_datasets import review_coverage
from inspinia.solutions.reviewed_datasets import validate_corpus

MAX_TOKENS = 10_000_000
MAX_LATENCY_MS = 86_400_000
PIPELINE_STAGES = 2


def _usage(value):
    if value is None:
        return
    require(keys(value, "input_tokens cached_input_tokens output_tokens reasoning_tokens"), "Invalid usage fields.")
    require(
        all(integer(value[key], 0, MAX_TOKENS) for key in ("input_tokens", "cached_input_tokens", "output_tokens")),
        "Token usage must be bounded nonnegative integers.",
    )
    require(value["cached_input_tokens"] <= value["input_tokens"], "Cached input exceeds total input tokens.")
    reasoning = value["reasoning_tokens"]
    require(
        reasoning is None or integer(reasoning, 0, value["output_tokens"]),
        "Reasoning tokens must be included in output.",
    )


def _validate_run(run, plan, slot):
    require(
        keys(run, "schema_version plan_digest model reasoning_effort execution_kind records digest"),
        "Invalid model run fields.",
    )
    require(type(run["schema_version"]) is int and run["schema_version"] == 1, "Use run schema version 1.")
    require(run["digest"] == artifact_digest(run), "The imported run no longer matches its digest.")
    require(
        run["plan_digest"] == plan["digest"]
        and run["model"] == plan["models"][slot]
        and run["reasoning_effort"] == plan["reasoning_effort"],
        "The run does not match its model, plan, or reasoning setting.",
    )
    require(run["execution_kind"] in ("synthetic_fixture", "imported_provider_results"), "Declare run provenance.")
    require(
        run["execution_kind"] != "synthetic_fixture" or plan["purpose"] == "smoke_test",
        "Synthetic runs cannot establish a human benchmark.",
    )
    require(isinstance(run["records"], list), "Supply explicit results for every case and repetition.")
    requests = {row["case_id"]: row for row in plan["cases"]}
    expected = {(case_id, trial) for case_id in requests for trial in range(1, plan["repetitions"] + 1)}
    records, provider_ids = {}, set()
    for row in run["records"]:
        require(
            keys(
                row,
                "case_id trial input_digest assessment_request_digest feedback_request_digest status "
                "assessment mode_feedback returned_models provider_request_ids usage latency_ms error_code",
            ),
            "Invalid model result envelope.",
        )
        require(
            isinstance(row["case_id"], str)
            and row["case_id"] in requests
            and integer(row["trial"], 1, plan["repetitions"]),
            "Unknown case or repetition in model run.",
        )
        key = (row["case_id"], row["trial"])
        require(key not in records, "Duplicate model result; repetitions must be explicit.")
        request = requests[row["case_id"]]
        require(
            row["input_digest"] == request["input_digest"]
            and row["assessment_request_digest"] == canonical_digest(request["assessment_request"]),
            "A result targets different mathematical input or assessment instructions.",
        )
        require(isinstance(row["status"], str) and row["status"] in STATUSES, "Invalid result completion status.")
        require(
            text_list(row["returned_models"]) and text_list(row["provider_request_ids"]),
            "Invalid provider metadata.",
        )
        ids = row["provider_request_ids"]
        require(
            len(row["returned_models"]) <= PIPELINE_STAGES
            and len(ids) <= PIPELINE_STAGES
            and len(set(ids)) == len(ids)
            and not (set(ids) & provider_ids),
            "Each case/repetition must retain distinct provider request provenance.",
        )
        provider_ids.update(ids)
        require(
            all(model == run["model"] or model.startswith(run["model"] + "-") for model in row["returned_models"]),
            "A returned model belongs to a different family.",
        )
        require(row["error_code"] is None or text(row["error_code"]), "Use a provider error code or null.")
        _usage(row["usage"])
        latency = row["latency_ms"]
        require(
            latency is None
            or (type(latency) in (int, float) and math.isfinite(latency) and 0 <= latency <= MAX_LATENCY_MS),
            "Latency must be a finite duration or null.",
        )
        if run["execution_kind"] == "synthetic_fixture":
            require(
                row["usage"] is None
                and latency is None
                and not row["returned_models"]
                and not row["provider_request_ids"],
                "Fixtures must not fabricate observed usage, latency, or provider IDs.",
            )
        elif row["status"] == "completed":
            require(
                len(row["returned_models"]) == PIPELINE_STAGES and len(ids) == PIPELINE_STAGES,
                "A completed imported pipeline needs provenance for both stages.",
            )
        if row["status"] != "completed":
            require(
                row["assessment"] is None and row["mode_feedback"] is None and row["feedback_request_digest"] is None,
                "Failed, refused, or incomplete results must not present a completed report.",
            )
        records[key] = row
    require(records.keys() == expected, "Missing model results cannot be silently omitted, including failures.")
    return records


def _metric_result(row, request, case, package, labels, mode):  # noqa: PLR0913 - Bound inputs and target labels.
    normalized = {
        "case_id": case["id"],
        "input_digest": case["input_digest"],
        "status": row["status"],
        "assessment": None,
        "findings": [],
        "score_status": "unavailable",
        "score": None,
        "human_review_required": False,
    }
    invalid = None
    if row["status"] == "completed":
        # Bind the second stage before judging its output. An invalid quotation
        # or schema must not disguise a run that used different instructions.
        # A malformed first stage may be missing the fields needed to construct
        # that context; it remains an invalid output in the denominator below.
        try:
            expected = feedback_request(mode, request["assessment_request"]["input"], row["assessment"])
        except (KeyError, TypeError):
            expected = None
        if expected is not None:
            require(
                row["feedback_request_digest"] == canonical_digest(expected),
                "Feedback context or instructions changed.",
            )
        try:
            report, _hints = prepare_report(
                request["assessment_request"]["input"],
                mode,
                row["assessment"],
                row["mode_feedback"],
            )
        except EvaluationDataError as error:
            normalized["status"] = "failed"
            invalid = str(error)
        else:
            normalized.update(
                assessment=report["assessment"],
                human_review_required=report["human_review_required"],
                findings=[
                    {"source_quote": finding["source_quote"], "explanation": finding["explanation"]}
                    for finding in report["findings"]
                ],
            )
            if "score" in report:
                normalized["score_status"] = (
                    "provided" if report["score"]["total"] is not None else "human_review_required"
                )
                normalized["score"] = report["score"]["total"]
                if normalized["score_status"] == "human_review_required":
                    normalized["human_review_required"] = True
    metric_case = {**case, "candidate_labels": labels}
    metric = assessment_metric_row(normalized, metric_case, package)
    metric.update(trial=row["trial"], status=normalized["status"], score=normalized["score"], invalid_output=invalid)
    metric["raw_evidence_count"], metric["raw_grounded_evidence_count"] = _raw_grounding(row["assessment"], case)
    return metric


def _raw_grounding(assessment, case):
    if not isinstance(assessment, dict) or not isinstance(assessment.get("claims"), list):
        return 0, 0
    source = case["submission"]["body_source"]
    total, grounded = 0, 0
    for claim in assessment["claims"]:
        total += 1
        if not isinstance(claim, dict) or not isinstance(claim.get("evidence"), dict):
            continue
        anchor = claim["evidence"]
        start, end, quote = anchor.get("start"), anchor.get("end"), anchor.get("quote")
        if integer(start, 0, len(source)) and integer(end, 1, len(source)) and start < end and text(quote):
            grounded += int(source[start:end] == quote)
    return total, grounded


def _operational_metrics(records, plan, slot):
    rows = list(records.values())
    latencies = sorted(row["latency_ms"] for row in rows if row["latency_ms"] is not None)
    usage = [row["usage"] for row in rows if row["usage"] is not None]
    totals = {key: sum(row[key] for row in usage) for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
    known_reasoning = [row["reasoning_tokens"] for row in usage if row["reasoning_tokens"] is not None]
    estimate = None
    if plan["pricing_snapshot"] is not None and usage:
        rates = plan["pricing_snapshot"]["models"][slot]
        estimate = str(
            (
                Decimal(totals["input_tokens"] - totals["cached_input_tokens"])
                * Decimal(rates["input_usd_per_million"])
                + Decimal(totals["cached_input_tokens"]) * Decimal(rates["cached_input_usd_per_million"])
                + Decimal(totals["output_tokens"]) * Decimal(rates["output_usd_per_million"])
            )
            / Decimal(1_000_000),
        )
    return {
        "usage_observations": len(usage),
        "usage_coverage": len(usage) / len(rows),
        "tokens": totals if usage else None,
        "known_reasoning_tokens": sum(known_reasoning) if known_reasoning else None,
        "latency_observations": len(latencies),
        "latency_coverage": len(latencies) / len(rows),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "p95_latency_ms": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
        "estimated_cost_usd_for_known_usage": estimate,
        "invoiced_cost_observed": False,
    }


def _model_metrics(rows):
    repeated = {}
    for row in rows:
        repeated.setdefault(row["case_id"], []).append((row["status"], row["assessment"], row["score"]))
    repeatable = [values for values in repeated.values() if len(values) > 1]
    raw_evidence = sum(row["raw_evidence_count"] for row in rows)
    raw_grounded = sum(row["raw_grounded_evidence_count"] for row in rows)
    return {
        "metrics": summarize_metrics(rows),
        "by_domain": {
            domain: summarize_metrics([row for row in rows if row["domain"] == domain])
            for domain in sorted({row["domain"] for row in rows})
        },
        "alternative_methods": summarize_metrics([row for row in rows if row["alternative"]]),
        "failures": dict(Counter(row["status"] for row in rows if row["status"] != "completed")),
        "invalid_output_count": sum(row["invalid_output"] is not None for row in rows),
        "raw_claim_evidence_count": raw_evidence,
        "raw_claim_grounding_rate": raw_grounded / raw_evidence if raw_evidence else None,
        "source_grounding_rate_scope": (
            "accepted report findings only; raw claim grounding also includes rejected outputs"
        ),
        "invalid_outputs": [
            {"case_id": row["case_id"], "trial": row["trial"], "reason": row["invalid_output"]}
            for row in rows
            if row["invalid_output"] is not None
        ],
        "repeatability": {
            "cases_with_repeats": len(repeatable),
            "cases_with_different_outcomes": sum(len(set(values)) > 1 for values in repeatable),
        },
    }


def compare_runs(corpus, reviews, plan, astra_run, sol_run):
    validate_comparison_plan(plan, corpus, reviews)
    labels, evidence = resolve_labels(corpus, reviews, split=plan["split"], purpose=plan["purpose"])
    packages, cases = validate_corpus(corpus)
    requests = {row["case_id"]: row for row in plan["cases"]}
    results, maps = {}, {}
    for slot, run in (("astra", astra_run), ("sol", sol_run)):
        records = _validate_run(run, plan, slot)
        rows = [
            _metric_result(
                row,
                requests[row["case_id"]],
                cases[row["case_id"]],
                packages[cases[row["case_id"]]["package_id"]],
                labels[row["case_id"]],
                plan["mode"],
            )
            for _key, row in sorted(records.items())
        ]
        maps[slot] = {(row["case_id"], row["trial"]): row for row in rows}
        results[slot] = {
            "model": run["model"],
            "run_digest": run["digest"],
            **_model_metrics(rows),
            "operations": _operational_metrics(records, plan, slot),
        }
    require(
        astra_run["execution_kind"] == sol_run["execution_kind"],
        "Do not compare a fixture run with a provider run.",
    )
    common, disagreements = [], []
    for key, astra in maps["astra"].items():
        sol = maps["sol"][key]
        if astra["score_error"] is not None and sol["score_error"] is not None:
            common.append((astra["score_error"], sol["score_error"]))
        if (astra["status"], astra["assessment"], astra["score"]) != (sol["status"], sol["assessment"], sol["score"]):
            disagreements.append(
                {
                    "case_id": key[0],
                    "trial": key[1],
                    "astra": {field: astra[field] for field in ("status", "assessment", "score")},
                    "sol": {field: sol[field] for field in ("status", "assessment", "score")},
                },
            )
    return {
        "schema_version": 1,
        "plan_digest": plan["digest"],
        "corpus_digest": corpus["digest"],
        "reviews_digest": reviews["digest"],
        "source_kind": corpus["source_kind"],
        "execution_kind": astra_run["execution_kind"],
        "split": plan["split"],
        "mode": plan["mode"],
        "review_evidence": evidence,
        "models": results,
        "disagreements": disagreements,
        "paired_scoring": {
            "common_scored_case_trials": len(common),
            "astra_mae": mean(left for left, _right in common) if common else None,
            "sol_mae": mean(right for _left, right in common) if common else None,
        },
        "release_gate_passed": False,
        "recommended_model": None,
        "notice": (
            "Synthetic fixture outcomes are not Astra/Sol measurements. No model or release is approved."
            if astra_run["execution_kind"] == "synthetic_fixture"
            else "Imported outputs evaluated offline against supplied review records; "
            "identities and provider metadata are not authenticated. No model or release is approved."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("review-template", "coverage", "plan", "compare"):
        command = subparsers.add_parser(name)
        command.add_argument("--corpus", type=Path, required=True)
        if name != "review-template":
            command.add_argument("--reviews", type=Path, required=True)
        if name == "plan":
            command.add_argument("--split", choices=["development", "held_out"], default="held_out")
            command.add_argument("--mode", choices=["coach", "provisional", "examiner"], default="provisional")
            command.add_argument("--purpose", choices=["smoke_test", "human_benchmark"], default="smoke_test")
            command.add_argument("--repetitions", type=int, default=1)
            command.add_argument("--pricing", type=Path)
        if name == "compare":
            for flag in ("plan", "astra", "sol"):
                command.add_argument(f"--{flag}", type=Path, required=True)
    options = parser.parse_args()
    try:
        corpus = load_json_file(options.corpus)
        reviews = load_json_file(options.reviews) if options.command != "review-template" else None
        if options.command == "review-template":
            result = empty_review_template(corpus)
        elif options.command == "coverage":
            result = review_coverage(corpus, reviews)
        elif options.command == "plan":
            result = build_comparison_plan(
                corpus,
                reviews,
                split=options.split,
                mode=options.mode,
                purpose=options.purpose,
                repetitions=options.repetitions,
                pricing=load_json_file(options.pricing) if options.pricing else None,
            )
        else:
            result = compare_runs(
                corpus,
                reviews,
                load_json_file(options.plan),
                load_json_file(options.astra),
                load_json_file(options.sol),
            )
    except (EvaluationDataError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, allow_nan=False))  # noqa: T201 - Local CLI output.


if __name__ == "__main__":
    main()
