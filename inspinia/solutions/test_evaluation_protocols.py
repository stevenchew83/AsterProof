"""Preregistration tests use synthetic mathematics and never establish model evidence."""

# ruff: noqa: PLR2004
import copy
import json

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.test import Client
from django.urls import reverse

from inspinia.solutions import evaluation as ev
from inspinia.solutions import evaluation_protocols as protocols
from inspinia.solutions.evaluation_models import EvaluationAssignment
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.test_evaluation_governance import _annotation
from inspinia.solutions.test_evaluation_governance import _developer
from inspinia.solutions.test_evaluation_governance import _finding_annotation
from inspinia.solutions.test_evaluation_governance import _profile_payload
from inspinia.solutions.test_evaluation_governance import case_setup as case_setup_fixture
from inspinia.solutions.test_evaluation_governance import frozen as frozen_fixture
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def case_setup():
    return case_setup_fixture.__wrapped__()


@pytest.fixture
def frozen(case_setup):
    return frozen_fixture.__wrapped__(case_setup)


def protocol_spec(frozen, **changes):
    return {
        "partition": "final_test", "thresholds": copy.deepcopy(frozen.protocol),
        "min_cases": 2, "max_runs": 1,
        "sampling_plan": "Synthetic engineering fixtures; both independent families included.",
        "analysis_plan": "Keep failures; report family counts separately; no population inference.",
        "population": "Synthetic software tests, not a learner population.",
        "languages": ["English"], "levels": "Synthetic elementary examples only.",
        "custodian_ids": [str(frozen.curator.pk)], "aggregate_recipient_ids": [],
        **changes,
    }


def register(frozen, **changes):
    return protocols.freeze_protocol(frozen.curator, frozen.snapshot, frozen.profile, protocol_spec(frozen, **changes))


def import_registered(frozen, event, **changes):
    return ev.import_run(
        frozen.curator, frozen.snapshot, frozen.profile, changes.pop("reports", frozen.reports), {},
        registration=event, **changes,
    )


def test_freeze_binds_candidate_inputs_rules_and_no_authority(frozen):
    event = register(frozen)
    body = protocols.protocol_payload(frozen.curator, event)["body"]
    assert body["snapshot_digest"] == frozen.snapshot.digest
    assert body["profile_digest"] == frozen.profile.digest
    assert body["eligible_cases"] == body["independent_families"] == 2
    assert {item["input_digest"] for item in body["case_inputs"]} == {case.bundle.digest for case in frozen.cases}
    assert body["execution_authority"] == "none"
    assert body["financial_cap_minor_units"] == 0
    assert body["spec"]["thresholds"] == frozen.protocol
    assert event.metadata["digest"] == ev.digest(body)
    assert EvaluationAuditEvent.objects.filter(kind="protocol_served", target_id=frozen.snapshot.pk).count() == 1
    assert not EvaluationRun.objects.exists()


@pytest.mark.parametrize("field", [*protocols.THRESHOLD_FIELDS])
@pytest.mark.parametrize("value", [None, False, 0, "0.9"])
def test_unset_or_invalid_thresholds_fail_without_an_event(frozen, field, value):
    spec = protocol_spec(frozen)
    spec["thresholds"][field] = value
    with pytest.raises(ev.EvaluationError):
        protocols.freeze_protocol(frozen.curator, frozen.snapshot, frozen.profile, spec)
    assert not protocols.registrations(frozen.snapshot).exists()


@pytest.mark.parametrize("change", [
    {"min_cases": 3}, {"max_runs": 0}, {"sampling_plan": " "}, {"languages": []},
    {"partition": "empty"}, {"custodian_ids": []}, {"custodian_ids": ["not-an-account"]},
    {"partition": {}},
    {"aggregate_recipient_ids": ["not-an-account"]}, {"execution_authority": "approved"},
])
def test_incomplete_scope_recipients_or_extra_authority_are_rejected(frozen, change):
    with pytest.raises(ev.EvaluationError):
        register(frozen, **change)


def test_missing_explicit_threshold_does_not_use_scorer_default(frozen):
    spec = protocol_spec(frozen)
    del spec["thresholds"]["minimum_agreement"]
    with pytest.raises(ev.EvaluationError, match="explicitly"):
        protocols.freeze_protocol(frozen.curator, frozen.snapshot, frozen.profile, spec)


def test_rules_cannot_be_replaced_or_retroactively_registered(frozen):
    event = register(frozen)
    assert register(frozen).pk == event.pk
    with pytest.raises(ev.EvaluationError, match="already preregistered"):
        register(frozen, max_runs=2)
    other = ev.create_profile(frozen.curator, _profile_payload(prompt="Another candidate"))
    ev.import_run(frozen.curator, frozen.snapshot, other, frozen.reports, frozen.protocol)
    with pytest.raises(ev.EvaluationError, match="too late"):
        protocols.freeze_protocol(frozen.curator, frozen.snapshot, other, protocol_spec(frozen))
    assert protocols.registrations(frozen.snapshot).count() == 1


def test_import_cannot_override_forge_or_omit_registration(frozen):
    event = register(frozen)
    with pytest.raises(ev.EvaluationError, match="override"):
        ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports,
                      frozen.protocol, registration=event)
    with pytest.raises(ev.EvaluationError, match="Select the frozen"):
        ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol)
    with pytest.raises(ev.EvaluationError, match="Caller-supplied"):
        ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, {
            **frozen.protocol, "preregistration": {"id": str(event.pk), "digest": event.metadata["digest"]},
        })
    assert not EvaluationRun.objects.exists()


def test_registration_cannot_be_used_for_another_candidate_or_origin(frozen):
    event = register(frozen)
    other = ev.create_profile(frozen.curator, _profile_payload(prompt="Changed candidate"))
    with pytest.raises(ev.EvaluationError, match="binding"):
        ev.import_run(frozen.curator, frozen.snapshot, other, frozen.reports, {}, registration=event)
    with pytest.raises(ev.EvaluationError, match="trusted dispatcher"):
        import_registered(frozen, event, origin="verified_authorized_provider")


def test_rubric_mismatch_cannot_be_preregistered(frozen):
    other = ev.create_profile(frozen.curator, _profile_payload(rubric={"version": "different-rubric"}))
    with pytest.raises(ev.EvaluationError, match="rubric versions"):
        protocols.freeze_protocol(frozen.curator, frozen.snapshot, other, protocol_spec(frozen))


def test_rehashed_in_memory_protocol_cannot_replace_the_authenticated_record(frozen):
    event = register(frozen)
    event.metadata["body"]["spec"]["max_runs"] = 99
    event.metadata["digest"] = ev.digest(event.metadata["body"])
    with pytest.raises(ev.EvaluationError, match="integrity"):
        import_registered(frozen, event)


def test_failed_outcomes_consume_slots_and_cannot_be_reset(frozen):
    event = register(frozen)
    failed = {key: {"status": "outcome_unknown"} for key in frozen.reports}
    run = import_registered(frozen, event, reports=failed)
    assert all(item["status"] == "outcome_unknown" for item in run.reports.values())
    assert register(frozen).pk == event.pk
    with pytest.raises(ev.EvaluationError, match="repetition limit"):
        import_registered(frozen, event)
    assert EvaluationRun.objects.count() == 1


def test_invalid_import_rolls_back_without_consuming_a_slot(frozen):
    event = register(frozen)
    with pytest.raises(ev.EvaluationError, match="every eligible"):
        import_registered(frozen, event, reports={})
    assert import_registered(frozen, event).protocol["preregistration"]["id"] == str(event.pk)


def test_perfect_preregistered_import_still_cannot_establish_model_readiness(frozen):
    developer = _developer(frozen)
    event = register(frozen, aggregate_recipient_ids=[str(developer.pk)])
    run = import_registered(frozen, event)
    ev.assess_findings(frozen.judges[2], run, frozen.cases[0], _annotation())
    ev.assess_findings(frozen.judges[2], run, frozen.cases[1],
                       _annotation([_finding_annotation("false-parity", frozen.defect_id)]))
    outsider = _developer(frozen)
    with pytest.raises(ev.EvaluationError):
        ev.run_payload(outsider, run)
    result = ev.run_payload(developer, run)
    assert result["metrics"]["candidate_passed"] is True
    assert result["model_readiness"] is False
    assert "reports" not in result
    with pytest.raises(ev.EvaluationError, match="already been delivered"):
        ev.run_payload(developer, run)
    other = ev.create_profile(frozen.curator, _profile_payload(prompt="Tuned after aggregate feedback"))
    with pytest.raises(ev.EvaluationError, match="fresh final-test"):
        protocols.freeze_protocol(frozen.curator, frozen.snapshot, other, protocol_spec(frozen))


def test_revocation_withdrawal_and_integrity_fail_closed(frozen):
    event = register(frozen)
    assignment = EvaluationAssignment.objects.get(actor=frozen.curator, scope_id=frozen.snapshot.pk, role="custodian")
    ev.revoke_assignment(frozen.admin, assignment)
    with pytest.raises(ev.EvaluationError):
        import_registered(frozen, event)
    ev.grant(frozen.admin, frozen.curator, "custodian", frozen.snapshot)
    event.metadata["body"]["spec"]["max_runs"] = 99
    with pytest.raises(ev.EvaluationError, match="integrity"):
        import_registered(frozen, event)
    event.refresh_from_db()
    ev.invalidate(frozen.curator, frozen.cases[0], "withdrawal")
    with pytest.raises(ev.EvaluationError, match="no longer eligible"):
        protocols.protocol_payload(frozen.curator, event)


def test_protocol_audit_failure_is_atomic(frozen, monkeypatch):
    original = ev.audit

    def fail(actor, target, kind, metadata=None):
        if kind == protocols.KIND:
            raise IntegrityError
        return original(actor, target, kind, metadata)

    monkeypatch.setattr(ev, "audit", fail)
    with pytest.raises(IntegrityError), transaction.atomic():
        register(frozen)
    assert not protocols.registrations(frozen.snapshot).exists()


def test_protocol_read_fails_closed_when_critical_audit_cannot_persist(frozen, monkeypatch):
    event = register(frozen)
    original = ev.audit

    def fail(actor, target, kind, metadata=None):
        if kind == "protocol_served":
            raise IntegrityError
        return original(actor, target, kind, metadata)

    monkeypatch.setattr(ev, "audit", fail)
    with pytest.raises(IntegrityError), transaction.atomic():
        protocols.protocol_payload(frozen.curator, event)
    assert not EvaluationAuditEvent.objects.filter(kind="protocol_served").exists()


def test_private_protocol_pages_and_import_flow(frozen):
    client = Client(enforce_csrf_checks=True)
    client.force_login(frozen.curator)
    url = reverse("solutions:evaluation_protocol_create", args=[frozen.snapshot.pk])
    post = {"profile": frozen.profile.pk, "spec": json.dumps(protocol_spec(frozen))}
    assert client.post(url, post).status_code == 403
    page = client.get(url)
    assert page.status_code == 200
    assert "private" in page["Cache-Control"]
    assert "no-store" in page["Cache-Control"]
    token = client.cookies["csrftoken"].value
    response = client.post(url, {"profile": frozen.profile.pk, "spec": json.dumps(protocol_spec(frozen)),
                                "csrfmiddlewaretoken": token})
    assert response.status_code == 302
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"no execution, spending or activation authority" in detail.content
    event = protocols.registrations(frozen.snapshot).get()
    import_url = reverse("solutions:evaluation_run_import", args=[frozen.snapshot.pk])
    response = client.post(import_url, {"profile": frozen.profile.pk, "registration": event.pk,
                                      "reports": json.dumps(frozen.reports), "csrfmiddlewaretoken": token})
    assert response.status_code == 302
    assert EvaluationRun.objects.get().protocol["minimum_agreement"] == 0.9
    client.force_login(frozen.admin)
    assert client.get(url).status_code in {403, 404}
    assert client.get(reverse("solutions:evaluation_protocol_detail", args=[event.pk])).status_code in {403, 404}


def test_new_custodian_cannot_obtain_unnamed_protocol(frozen):
    event = register(frozen)
    actor = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, actor, "custodian", frozen.snapshot)
    assert not protocols.visible_registrations(actor, frozen.snapshot).exists()
    with pytest.raises(ev.EvaluationError):
        protocols.protocol_payload(actor, event)


def test_legacy_diagnostic_import_remains_supported(frozen):
    run = ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol)
    assert "preregistration" not in run.protocol
    assert run.origin == "manual_import"
