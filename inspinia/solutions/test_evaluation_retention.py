"""Explicit retention runs touch scoped synthetic copies, never authored learner work."""

import copy
import json
import uuid
from datetime import timedelta
from io import BytesIO
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from PIL import Image

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import CoachJudgment
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationCase
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import EvaluationLifecycle
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.evaluation_models import ReadinessEvidence
from inspinia.solutions.evaluation_models import ReviewBundleAsset
from inspinia.solutions.test_evaluation_assistance import _learner_case
from inspinia.solutions.test_evaluation_contract import case_setup  # noqa: F401 - shared pytest fixture
from inspinia.solutions.test_evaluation_governance import _judged_run
from inspinia.solutions.test_evaluation_governance import frozen  # noqa: F401 - shared pytest fixture
from inspinia.solutions.test_reviews import coach as coach_fixture
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def coach(settings):
    return coach_fixture.__wrapped__(settings)


def _expire(case):
    # Deliberately inject elapsed permission into synthetic test data; creation requires a future deadline.
    provenance = {**case.provenance, "retention_until": (timezone.now() - timedelta(days=1)).isoformat()}
    EvaluationCase._base_manager.filter(pk=case.pk).update(provenance=provenance)  # noqa: SLF001
    case.provenance = provenance


def _retention(actor, **options):
    output = StringIO()
    call_command("evaluation_retention", actor=actor.pk, stdout=output, **options)
    return json.loads(output.getvalue())


def _readiness():
    output = StringIO()
    call_command("evaluation_readiness", stdout=output)
    return json.loads(output.getvalue())


def _dataset_pass(setup):
    ev.grant(setup.admin, setup.curator, "activation", setup.snapshot)
    return ev.record_readiness(
        setup.curator,
        "D",
        setup.snapshot,
        "passed",
        {
            "artifacts": [setup.snapshot.digest],
            "limitations": ["Synthetic engineering fixture only."],
        },
    )


def test_retention_preview_is_bounded_private_and_non_mutating(frozen):  # noqa: F811 - fixture injection
    _expire(frozen.cases[0])
    before = EvaluationAuditEvent.objects.count()
    result = _retention(frozen.curator)
    assert result["mode"] == "preview"
    assert result["expired_case_ids"] == [str(frozen.cases[0].pk)]
    assert result["purged_count"] == 0
    assert frozen.cases[0].bundle.payload["source"] not in json.dumps(result)
    assert EvaluationAuditEvent.objects.count() == before
    frozen.cases[0].bundle.refresh_from_db()
    assert frozen.cases[0].bundle.payload["source"]


def test_retention_apply_erases_source_and_dependent_labels_reports(frozen):  # noqa: F811
    source = frozen.cases[0].bundle.payload["source"]
    frozen.reports[str(frozen.cases[0].pk)]["summary"] = source
    run = _judged_run(frozen)
    case = frozen.cases[0]
    _expire(case)
    result = _retention(frozen.curator, apply=True)
    assert result["purged_case_ids"] == [str(case.pk)]
    case.bundle.refresh_from_db()
    assert case.bundle.payload == {}
    assert all(row.payload == {"withdrawn": True} for row in CoachJudgment.objects.filter(case=case))
    assert str(case.pk) not in EvaluationRun.objects.get(pk=run.pk).reports
    snapshot = EvaluationDatasetSnapshot.objects.get(pk=frozen.snapshot.pk)
    row = next(item for item in snapshot.manifest["cases"] if item["id"] == str(case.pk))
    assert row["ground_truth"] == {"withdrawn": True}
    assert row["defects"] == []
    assert EvaluationAuditEvent.objects.filter(target_id=case.pk, kind="retention_expired").exists()
    frozen.cases[1].bundle.refresh_from_db()
    assert frozen.cases[1].bundle.payload["source"]
    assert _retention(frozen.curator, apply=True)["purged_count"] == 0


def test_retention_apply_erases_copies_even_if_case_already_invalidated(frozen):  # noqa: F811
    case = frozen.cases[0]
    _expire(case)
    ev.invalidate(frozen.curator, case, "correction")
    assert _retention(frozen.curator, apply=True)["purged_count"] == 1
    case.bundle.refresh_from_db()
    assert case.bundle.payload == {}


def test_retention_apply_respects_actor_scope_without_global_admin_bypass(frozen):  # noqa: F811
    for case in frozen.cases:
        _expire(case)
    actor = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, actor, "curator", frozen.families[1])
    result = _retention(actor, apply=True)
    assert result["purged_case_ids"] == [str(frozen.cases[1].pk)]
    frozen.cases[0].bundle.refresh_from_db()
    assert frozen.cases[0].bundle.payload["source"]
    with pytest.raises(CommandError, match="explicit curator"):
        _retention(frozen.admin, apply=True)


def test_retention_cursor_reaches_later_cases_without_unbounded_scan(frozen):  # noqa: F811
    for case in frozen.cases:
        _expire(case)
    first = _retention(frozen.curator, limit=1)
    assert first["scanned"] == 1
    assert first["has_more"]
    second = _retention(frozen.curator, limit=1, after=uuid.UUID(first["next_after"]))
    assert second["scanned"] == 1
    assert not second["has_more"]
    assert set(first["expired_case_ids"] + second["expired_case_ids"]) == {str(case.pk) for case in frozen.cases}


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_retention_rejects_unbounded_limits(frozen, limit):  # noqa: F811
    with pytest.raises(CommandError, match="between 1 and 500"):
        _retention(frozen.curator, limit=limit)


def test_invalid_retention_metadata_is_reported_without_automatic_erasure(frozen):  # noqa: F811
    case = frozen.cases[0]
    provenance = {**case.provenance, "retention_until": "not-a-deadline"}
    EvaluationCase._base_manager.filter(pk=case.pk).update(provenance=provenance)  # noqa: SLF001
    result = _retention(frozen.curator, apply=True)
    assert result["invalid_deadline_count"] == 1
    assert result["purged_count"] == 0
    case.bundle.refresh_from_db()
    assert case.bundle.payload["source"]


def test_retention_rechecks_permission_before_erasing_anything(frozen, monkeypatch):  # noqa: F811
    case = frozen.cases[0]
    _expire(case)
    monkeypatch.setattr(ev, "allowed", lambda *_args: False)
    with pytest.raises(CommandError, match="authority changed"):
        _retention(frozen.curator, apply=True)
    case.bundle.refresh_from_db()
    assert case.bundle.payload["source"]


def test_failed_retention_audit_rolls_back_content_erasure(frozen, monkeypatch):  # noqa: F811
    case = frozen.cases[0]
    _expire(case)
    original = ev.audit

    def fail_expiry_audit(actor, target, kind, metadata=None):
        if kind == "retention_expired":
            message = "Synthetic audit failure"
            raise RuntimeError(message)
        return original(actor, target, kind, metadata)

    monkeypatch.setattr(ev, "audit", fail_expiry_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit"):
        _retention(frozen.curator, apply=True)
    case.bundle.refresh_from_db()
    assert case.bundle.payload["source"]
    assert EvaluationLifecycle.objects.get(target_id=case.pk).eligible


def test_retention_erases_managed_asset_bytes(case_setup):  # noqa: F811
    admin, curator, family, template, _ = case_setup
    image = BytesIO()
    Image.new("RGB", (4, 4), "white").save(image, format="PNG")
    data = {**copy.deepcopy(template.bundle.payload), "provenance": copy.deepcopy(template.provenance)}
    case = ev.create_case(curator, family, data, assets=[{"data": image.getvalue(), "role": "official_diagram"}])
    assert ReviewBundleAsset.objects.filter(bundle=case.bundle).exists()
    ev.grant(admin, curator, "curator", family)
    _expire(case)
    assert _retention(curator, apply=True)["purged_count"] == 1
    assert not ReviewBundleAsset.objects.filter(bundle=case.bundle).exists()


def test_retention_preserves_original_authored_learner_revision(case_setup, coach):  # noqa: F811
    _, curator, _, _, _ = case_setup
    _, case = _learner_case(case_setup, coach)
    original = coach.revision.body_source
    _expire(case)
    assert _retention(curator, apply=True)["purged_case_ids"] == [str(case.pk)]
    coach.revision.refresh_from_db()
    assert coach.revision.body_source == original


def test_readiness_checks_current_dataset_eligibility_without_mutating_history(frozen):  # noqa: F811
    evidence = _dataset_pass(frozen)
    before = EvaluationAuditEvent.objects.count()
    result = _readiness()
    assert result["recorded_gate_decisions"][0]["decision"] == "passed"
    assert EvaluationAuditEvent.objects.count() == before
    _expire(frozen.cases[0])
    current = _readiness()["recorded_gate_decisions"][0]
    assert current["recorded_decision"] == "passed"
    assert current["decision"] == "blocked"
    assert current["current_eligibility"] == "ineligible"
    assert ReadinessEvidence.objects.get(pk=evidence.pk).decision == "passed"


def test_readiness_withdrawal_and_missing_lifecycle_fail_closed_without_creating_state(frozen):  # noqa: F811
    _dataset_pass(frozen)
    EvaluationLifecycle.objects.filter(target_id=frozen.cases[0].bundle_id).delete()
    count = EvaluationLifecycle.objects.count()
    assert _readiness()["recorded_gate_decisions"][0]["decision"] == "blocked"
    assert EvaluationLifecycle.objects.count() == count


def test_readiness_preserves_later_human_block_and_never_reports_model_or_learning_passes(frozen):  # noqa: F811
    _dataset_pass(frozen)
    ev.record_readiness(
        frozen.curator,
        "D",
        frozen.snapshot,
        "blocked",
        {
            "artifacts": [frozen.snapshot.digest],
            "limitations": ["Further mathematical review required."],
        },
    )
    for gate in ("M", "P"):
        ReadinessEvidence.objects.create(
            gate=gate,
            target_id=frozen.snapshot.pk,
            actor=frozen.curator,
            decision="passed",
            payload={},
        )
    result = _readiness()
    dataset = [row for row in result["recorded_gate_decisions"] if row["gate"] == "D"]
    assert dataset[0]["decision"] == "superseded"
    assert dataset[1]["decision"] == "blocked"
    assert all(
        row["decision"] == "unassessed" for row in result["recorded_gate_decisions"] if row["gate"] in {"M", "P"}
    )
    assert result["real_model_performance"] == result["educational_effectiveness"] == "untested"
    assert result["paid_calls_authorized"] == 0
