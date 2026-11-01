"""Non-authoritative inventory of offline readiness and outstanding evidence."""

import json
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import EvaluationCase
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import EvaluationLifecycle
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.evaluation_models import ReadinessEvidence
from inspinia.solutions.review_models import SolutionReviewPolicy


def _dataset_currently_eligible(target_id):
    snapshot = EvaluationDatasetSnapshot.objects.filter(pk=target_id).first()
    if snapshot is None:
        return False
    try:
        rows = snapshot.manifest["cases"]
        if not isinstance(rows, list) or not rows:
            return False
        keys = {snapshot.pk}
        case_ids = {uuid.UUID(str(row["id"])) for row in rows}
        cases = list(EvaluationCase.objects.filter(pk__in=case_ids).only("pk", "family_id", "bundle_id", "provenance"))
        if len(cases) != len(rows):
            return False
        for case in cases:
            keys.update((case.pk, case.family_id, case.bundle_id))
            if case.provenance.get("construction") == "learner_submission":
                keys.add(uuid.UUID(case.provenance["consent_reference"]))
        states = dict(EvaluationLifecycle.objects.filter(target_id__in=keys).values_list("target_id", "eligible"))
        if set(states) != keys or not all(states.values()):
            return False
        # Preflight above prevents the service's lazy lifecycle creation: this inventory stays read-only.
        ev.snapshot_eligible(snapshot)
    except (ev.EvaluationError, ObjectDoesNotExist, ValidationError, KeyError, TypeError, ValueError):
        return False
    return True


def _gate_decisions():
    result = []
    evidence_rows = list(ReadinessEvidence.objects.order_by("created_at", "id"))
    latest = {(row.gate, row.target_id): row.pk for row in evidence_rows}
    eligibility_cache = {}
    for evidence in evidence_rows:
        current = evidence.decision
        eligibility = "not_automatically_assessed"
        if evidence.gate == "D":
            if evidence.target_id not in eligibility_cache:
                eligibility_cache[evidence.target_id] = _dataset_currently_eligible(evidence.target_id)
            eligible = eligibility_cache[evidence.target_id]
            eligibility = "eligible" if eligible else "ineligible"
            if not eligible:
                current = "blocked"
        elif evidence.gate in {"M", "P"}:
            current = "unassessed"
            eligibility = "requires_separately_authorized_evidence"
        if evidence.gate not in {"M", "P"} and latest[(evidence.gate, evidence.target_id)] != evidence.pk:
            current = "superseded"
        result.append(
            {
                "gate": evidence.gate,
                "recorded_decision": evidence.decision,
                "decision": current,
                "current_eligibility": eligibility,
            },
        )
    return result


class Command(BaseCommand):
    help = "Print offline readiness inventory. No provider calls, activation or data writes."

    def handle(self, **options):
        self.stdout.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "engineering_readiness": "requires_verified_test_and_isolation_artifacts",
                    "dataset_readiness": "requires_independent_mathematical_and_rights_review",
                    "real_model_performance": "untested",
                    "educational_effectiveness": "untested",
                    "provider_execution": "hard_disabled",
                    "paid_calls_authorized": 0,
                    "activation_authority": "none",
                    "student_flag": settings.SOLUTION_AI_REVIEW_ENABLED,
                    "enabled_policies": SolutionReviewPolicy.objects.filter(enabled=True).count(),
                    "case_count": EvaluationCase.objects.count(),
                    "snapshot_count": EvaluationDatasetSnapshot.objects.count(),
                    "run_count": EvaluationRun.objects.count(),
                    "invalidated_evidence_count": EvaluationLifecycle.objects.filter(eligible=False).count(),
                    "recorded_gate_decisions": _gate_decisions(),
                    "limitations": [
                        "Inventory is not a readiness decision.",
                        "Fixture and imported reports never establish model performance.",
                    ],
                },
                sort_keys=True,
            ),
        )
