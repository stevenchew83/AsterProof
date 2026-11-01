"""Synthetic-only orchestration. There is no provider client or real-submission path."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404

from inspinia.solutions.assessment_contracts import MODES
from inspinia.solutions.assessment_prompts import prompt_manifest
from inspinia.solutions.assessment_reporting import prepare_report
from inspinia.solutions.evaluation_contracts import canonical_digest
from inspinia.solutions.evaluation_contracts import load_json_file
from inspinia.solutions.evaluation_contracts import require
from inspinia.solutions.evaluation_harness import validate_dataset
from inspinia.solutions.problem_evaluation_models import require_curator

DATA = Path(__file__).with_name("testdata")


def require_prototype(user, permission="view_syntheticreview"):
    if not getattr(settings, "SYNTHETIC_REVIEW_PROTOTYPE_ENABLED", False):
        raise Http404
    require_curator(user.pk, permission)


@lru_cache(maxsize=1)
def _fixtures():
    dataset = load_json_file(DATA / "problem_evaluation_synthetic.json")
    packages = validate_dataset(dataset)
    candidates = load_json_file(DATA / "prototype_assessments_synthetic.json")
    require(
        candidates.get("schema_version") == 1 and candidates.get("provenance") == "synthetic_unapproved",
        "Use explicitly unapproved synthetic assessment fixtures.",
    )
    cases = {row["id"]: row for row in dataset["cases"]}
    assessments = {row["case_id"]: row for row in candidates["cases"]}
    require(
        assessments.keys() == cases.keys() and len(assessments) == len(candidates["cases"]),
        "Synthetic assessments must cover each bundled case exactly once.",
    )
    return cases, packages, assessments


def case_choices():
    cases, packages, _assessments = _fixtures()
    return [
        {"id": case["id"], "label": f"{packages[case['package_id']]['content']['domain']} · {case['id']}"}
        for case in cases.values()
    ]


def synthetic_packet(case_id):
    cases, packages, _assessments = _fixtures()
    require(isinstance(case_id, str) and case_id in cases, "Select a bundled synthetic submission.")
    case = cases[case_id]
    return deepcopy(
        {
            "provenance": "synthetic_unapproved",
            "case_id": case_id,
            "input_digest": case["input_digest"],
            "submission": case["submission"],
            "package": packages[case["package_id"]],
        },
    )


def synthetic_bundle(case_id, mode):
    require(isinstance(mode, str) and mode in MODES, "Select a supported review mode.")
    packet = synthetic_packet(case_id)
    candidate = deepcopy(_fixtures()[2][case_id])
    require(candidate["input_digest"] == packet["input_digest"], "The synthetic candidate targets an earlier input.")
    assessment = candidate["assessment"]
    report, hints = prepare_report(packet, mode, assessment, candidate["feedback"][mode])
    return {
        "packet": packet,
        "assessment": assessment,
        "mode_feedback": candidate["feedback"][mode],
        "report": report,
        "private_hints": hints,
        "prompt_manifest": prompt_manifest(mode, packet, assessment),
    }


def create_synthetic_review(user, case_id, mode, idempotency_key):
    from inspinia.solutions.prototype_models import SyntheticReview

    require_prototype(user)
    require_prototype(user, "add_syntheticreview")
    bundle = synthetic_bundle(case_id, mode)
    with transaction.atomic():
        # Serialize requests before model full_clean performs uniqueness checks;
        # get_or_create alone retries IntegrityError, not validation races.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        require_prototype(user)
        require_prototype(user, "add_syntheticreview")
        review, created = SyntheticReview.objects.get_or_create(
            requested_by=user,
            idempotency_key=idempotency_key,
            defaults={"case_id": case_id, "mode": mode, **bundle},
        )
        if review.case_id != case_id or review.mode != mode or review.packet != bundle["packet"]:
            message = "This request identifier belongs to a different case, mode, or input version."
            raise ValidationError(message)
    return review, created


def reveal_hint(user, review, finding_id, level):
    from inspinia.solutions.prototype_models import SyntheticHintReveal
    from inspinia.solutions.prototype_models import SyntheticReview

    require_prototype(user)
    require_prototype(user, "add_synthetichintreveal")
    review.check_integrity()
    with transaction.atomic():
        review = SyntheticReview.objects.select_for_update().get(pk=review.pk)
        review.check_integrity()
        require_prototype(user)
        require_prototype(user, "add_synthetichintreveal")
        event, _created = SyntheticHintReveal.objects.get_or_create(
            review=review,
            reviewer=user,
            finding_id=finding_id,
            level=level,
        )
    return event


def private_report_payload(review, user):
    require_prototype(user)
    review.check_integrity()
    report = deepcopy(review.report)
    levels = {}
    for event in review.hint_reveals.filter(reviewer=user).order_by("level"):
        levels[event.finding_id] = max(levels.get(event.finding_id, 0), event.level)
    for finding in report["findings"]:
        available = review.private_hints.get(finding["id"], [])
        count = min(levels.get(finding["id"], 0), len(available))
        finding["hints"] = available[:count]
        finding["next_hint_level"] = count + 1 if count < len(available) else None
    return report


def stored_review_digest(review):
    return canonical_digest(
        {
            "case_id": review.case_id,
            "mode": review.mode,
            "requested_by": str(review.requested_by_id),
            "packet": review.packet,
            "assessment": review.assessment,
            "report": review.report,
            "mode_feedback": review.mode_feedback,
            "private_hints": review.private_hints,
            "prompt_manifest": review.prompt_manifest,
        },
    )
