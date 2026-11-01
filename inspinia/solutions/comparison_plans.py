"""Create frozen Astra/Sol experiments without SDK imports, credentials, or dispatch."""

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation

from inspinia.solutions.assessment_contracts import MODES
from inspinia.solutions.assessment_prompts import MODE_PROMPTS
from inspinia.solutions.assessment_prompts import MODE_SCHEMAS
from inspinia.solutions.assessment_prompts import PROMPT_VERSION
from inspinia.solutions.assessment_prompts import SCHEMA_VERSION
from inspinia.solutions.assessment_prompts import assessment_request
from inspinia.solutions.evaluation_contracts import MAX_FILE_BYTES
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import integer
from inspinia.solutions.evaluation_contracts import keys
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_contracts import text
from inspinia.solutions.reviewed_datasets import artifact_digest
from inspinia.solutions.reviewed_datasets import resolve_labels
from inspinia.solutions.reviewed_datasets import validate_corpus

MODELS = {"astra": "gpt-6-astra", "sol": "gpt-6.1-sol"}
MAX_REPETITIONS = 5
MAX_RATE = 1_000_000
RATE_KEYS = "input_usd_per_million cached_input_usd_per_million output_usd_per_million"


def validate_pricing(pricing):
    if pricing is None:
        return
    require(
        keys(pricing, "currency source verified_at models")
        and pricing["currency"] == "USD"
        and text(pricing["source"]),
        "Supply an explicit USD pricing snapshot or null.",
    )
    require(text(pricing["verified_at"]), "Pricing needs a verification timestamp.")
    try:
        at = datetime.fromisoformat(pricing["verified_at"])
    except ValueError as error:
        message = "Invalid pricing verification timestamp."
        raise EvaluationDataError(message) from error
    require(at.utcoffset() is not None, "Pricing verification needs a timezone.")
    require(
        isinstance(pricing["models"], dict) and pricing["models"].keys() == MODELS.keys(),
        "Price both model slots.",
    )
    for rates in pricing["models"].values():
        require(keys(rates, RATE_KEYS), "Invalid token pricing fields.")
        for value in rates.values():
            require(isinstance(value, str), "Use decimal strings for monetary rates.")
            try:
                rate = Decimal(value)
            except InvalidOperation as error:
                message = "Invalid monetary rate."
                raise EvaluationDataError(message) from error
            require(rate.is_finite() and 0 <= rate <= MAX_RATE, "Rates must be finite and nonnegative.")


def build_comparison_plan(  # noqa: PLR0913 - Explicit immutable experiment options.
    corpus,
    reviews,
    *,
    split="held_out",
    mode="provisional",
    purpose="smoke_test",
    repetitions=1,
    pricing=None,
):
    require(isinstance(mode, str) and mode in MODES, "Choose a supported comparison mode.")
    require(integer(repetitions, 1, MAX_REPETITIONS), "Use one to five matched repetitions.")
    validate_pricing(pricing)
    # Review evidence is checked now and rechecked at comparison time.
    resolve_labels(corpus, reviews, split=split, purpose=purpose)
    packages, cases = validate_corpus(corpus)
    requests = []
    for case in sorted(cases.values(), key=lambda item: item["id"]):
        if case["split"] != split:
            continue
        package = packages[case["package_id"]]
        require(not package["content"]["images"], "Image manifests need image-byte transport before comparison.")
        require(mode != "provisional" or package["content"]["rubric"] is not None, "Scoring needs a problem rubric.")
        require(mode != "examiner" or bool(package["content"]["references"]), "Examiner reports need a reference.")
        packet = {
            "provenance": corpus["source_kind"],
            "case_id": case["id"],
            "input_digest": case["input_digest"],
            "submission": case["submission"],
            "package": package,
        }
        requests.append(
            {
                "case_id": case["id"],
                "input_digest": case["input_digest"],
                "assessment_request": assessment_request(packet),
            },
        )
    plan = {
        "schema_version": 1,
        "corpus_digest": corpus["digest"],
        "reviews_digest": reviews["digest"],
        "split": split,
        "purpose": purpose,
        "mode": mode,
        "models": deepcopy(MODELS),
        "reasoning_effort": "high",
        "repetitions": repetitions,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": SCHEMA_VERSION,
        "pricing_snapshot": deepcopy(pricing),
        "feedback_template": {"instructions": MODE_PROMPTS[mode], "schema": deepcopy(MODE_SCHEMAS[mode])},
        "cases": requests,
    }
    plan["digest"] = artifact_digest(plan)
    require(
        len(json.dumps(plan, ensure_ascii=False, indent=2).encode()) <= MAX_FILE_BYTES,
        "The comparison plan exceeds the 1 MB artifact limit; use a smaller versioned corpus.",
    )
    return plan


def validate_comparison_plan(plan, corpus, reviews):
    require(
        keys(
            plan,
            "schema_version corpus_digest reviews_digest split purpose mode models reasoning_effort "
            "repetitions prompt_version output_schema_version pricing_snapshot feedback_template cases digest",
        ),
        "Invalid comparison plan fields.",
    )
    require(plan["digest"] == artifact_digest(plan), "The comparison plan no longer matches its digest.")
    expected = build_comparison_plan(
        corpus,
        reviews,
        split=plan["split"],
        mode=plan["mode"],
        purpose=plan["purpose"],
        repetitions=plan["repetitions"],
        pricing=plan["pricing_snapshot"],
    )
    require(
        plan == expected,
        "Corpus, reviews, prompts, schemas, models, or experiment settings changed; create a new plan.",
    )
    return plan
