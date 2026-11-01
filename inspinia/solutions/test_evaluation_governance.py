"""Frozen benchmark governance cannot manufacture model or activation authority."""

import copy
import json
import uuid
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.evaluation_models import ReadinessEvidence
from inspinia.solutions.evaluation_models import ReviewerProfile
from inspinia.solutions.test_evaluation_contract import case_setup  # noqa: F401 - shared pytest fixture registration
from inspinia.solutions.test_evaluation_contract import judgment
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _profile_payload(**changes):
    return {
        "model": "offline-deterministic-fixture",
        "prompt": "Review only the frozen mathematical input.",
        "rubric": {"version": "math-v1"},
        "output_schema": {"version": 2},
        "preprocessing": {"version": "managed-raster-v1"},
        "reasoning": {"effort": "medium"},
        "output_limit": 100,
        "timeout": 30,
        "retry_policy": "none",
        "pricing": {"currency": "USD", "input": 0, "output": 0},
        **changes,
    }


def _annotation(findings=()):
    return {"useful": True, "report_spoiler": False, "findings": list(findings)}


def _finding_annotation(identifier, defect_id):
    return {
        "finding_id": identifier, "supported": True, "material": True,
        "localization_correct": True, "severity_correct": True, "context_correct": True,
        "hint_correct": True, "spoiler": False, "matched_defect_ids": [defect_id],
    }


@pytest.fixture
def frozen(case_setup):  # noqa: F811 - pytest injects the imported fixture by name
    admin, curator, family, case, judges = case_setup
    for actor in judges[:2]:
        ev.submit_judgment(actor, case, judgment(), case.bundle.digest)
    second_family = ev.create_family(curator, {"title": "Parity reasoning", "domain": "NT", "metadata": {}})
    data = copy.deepcopy(case.bundle.payload)
    data.update(
        statement="Prove that n(n+1) is even for every integer n.",
        source="Every integer n is even, so n(n+1) is even.",
        provenance=copy.deepcopy(case.provenance),
    )
    second_case = ev.create_case(curator, second_family, data)
    defect_id = str(uuid.uuid4())
    ground = judgment(
        assessment="gap_found", logical_validity="invalid", method="conventional",
        defects=[{
            "id": defect_id, "root_id": defect_id, "significance": "fatal",
            "explanation": "Not every integer is even.", "justification": "The integer 1 is odd.",
            "depends_on": [], "spans": [],
        }],
    )
    for actor in judges[:2]:
        ev.grant(admin, actor, "reviewer", second_case, expertise="Number theory")
        ev.submit_judgment(actor, second_case, copy.deepcopy(ground), second_case.bundle.digest)
    for item in (family, second_family):
        ev.grant(admin, curator, "custodian", item)
        ev.grant(admin, judges[2], "finding_evaluator", item, expertise="Competition mathematics")
    protocol = {
        "minimum_agreement": 0.9, "min_usable_coverage": 1,
        "min_finding_precision": 1, "min_defect_recall": 1, "min_families": 2,
    }
    cases = [case, second_case]
    membership = [{"case_id": str(item.pk), "partition": "final_test"} for item in cases]
    snapshot = ev.freeze_dataset(curator, "Synthetic final-test governance", membership, protocol)
    profile = ev.create_profile(curator, _profile_payload())
    reports = {
        str(case.pk): {"status": "completed", "assessment": "no_issues_found", "findings": []},
        str(second_case.pk): {
            "status": "completed", "assessment": "gap_found", "findings": [{"id": "false-parity"}],
        },
    }
    return SimpleNamespace(
        admin=admin, curator=curator, cases=cases, families=[family, second_family], judges=judges,
        snapshot=snapshot, profile=profile, reports=reports, protocol=protocol, defect_id=defect_id,
    )


def _judged_run(frozen, origin="manual_import"):
    run = ev.import_run(
        frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol, origin=origin,
    )
    ev.assess_findings(frozen.judges[2], run, frozen.cases[0], _annotation())
    ev.assess_findings(
        frozen.judges[2], run, frozen.cases[1],
        _annotation([_finding_annotation("false-parity", frozen.defect_id)]),
    )
    return run


def _developer(frozen):
    actor = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, actor, "developer", frozen.snapshot)
    return actor


def test_t22_unapproved_labels_cannot_freeze(case_setup):  # noqa: F811 - shared fixture injection
    admin, curator, family, case, judges = case_setup
    ev.grant(admin, curator, "custodian", family)
    ev.submit_judgment(judges[0], case, judgment(), case.bundle.digest)
    with pytest.raises(ev.EvaluationError, match="independent agreement"):
        ev.freeze_dataset(curator, "Provisional is insufficient", [
            {"case_id": str(case.pk), "partition": "final_test"},
        ], {})
    assert not EvaluationDatasetSnapshot.objects.exists()


def test_t22_one_problem_family_cannot_cross_partitions(frozen):
    original = frozen.cases[0]
    data = copy.deepcopy(original.bundle.payload)
    data.update(source="The product of a real number with itself is nonnegative.",
                provenance=copy.deepcopy(original.provenance))
    variant = ev.create_case(frozen.curator, frozen.families[0], data)
    for actor in frozen.judges[:2]:
        ev.grant(frozen.admin, actor, "reviewer", variant, expertise="Algebra")
        ev.submit_judgment(actor, variant, judgment(), variant.bundle.digest)
    before = EvaluationDatasetSnapshot.objects.count()
    with pytest.raises(ev.EvaluationError, match="families cannot cross"):
        ev.freeze_dataset(frozen.curator, "Leaking variants", [
            {"case_id": str(original.pk), "partition": "development"},
            {"case_id": str(variant.pk), "partition": "final_test"},
        ], frozen.protocol)
    assert EvaluationDatasetSnapshot.objects.count() == before


@pytest.mark.parametrize("origin", ["deterministic_fixture", "manual_import", "unverified_external"])
def test_t03_perfect_import_is_scored_without_model_readiness(frozen, origin):
    run = _judged_run(frozen, origin)
    payload = ev.run_payload(frozen.curator, run)
    assert payload["origin"] == origin
    assert payload["model_readiness"] is False
    assert payload["metrics"]["candidate_passed"]
    assert payload["metrics"]["metrics"]["category_agreement"]["value"] == 1
    assert payload["metrics"]["model_readiness"] is False


def test_t04_import_cannot_claim_trusted_dispatcher_origin(frozen):
    with pytest.raises(ev.EvaluationError, match="trusted dispatcher"):
        ev.import_run(
            frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol,
            origin="verified_authorized_provider",
        )
    assert not EvaluationRun.objects.exists()


def test_t04_perfect_import_cannot_authorize_model_or_pedagogical_readiness(frozen):
    run = _judged_run(frozen)
    ev.grant(frozen.admin, frozen.curator, "activation", run)
    for gate in ("M", "P"):
        with pytest.raises(ev.EvaluationError, match="cannot be established offline"):
            ev.record_readiness(frozen.curator, gate, run, "passed", {
                "artifacts": [str(run.pk)], "limitations": ["This is a manually authored report."],
            })
    assert not ReadinessEvidence.objects.filter(gate__in=["M", "P"], decision="passed").exists()


def test_t23_developer_receives_only_safe_aggregate_without_case_or_label_data(frozen):
    run = _judged_run(frozen)
    developer = _developer(frozen)
    payload = ev.run_payload(developer, run, aggregate_only=False)
    encoded = json.dumps(payload)
    assert "reports" not in payload
    assert "case_results" not in payload["metrics"]
    assert "protocol" not in payload["metrics"]
    assert "ground_truth" not in encoded
    assert "expected_assessment" not in encoded
    assert frozen.defect_id not in encoded
    for case in frozen.cases:
        assert str(case.pk) not in encoded
        assert case.bundle.payload["source"] not in encoded
        with pytest.raises(ev.EvaluationError):
            ev.case_payload(developer, case)
    assert payload["metrics"]["metrics"]["category_agreement"]["value"] == 1


def test_t24_final_aggregate_is_once_per_snapshot_across_developers(frozen):
    run = _judged_run(frozen)
    developer = _developer(frozen)
    other = _developer(frozen)
    ev.run_payload(developer, run)
    for actor in (developer, other):
        with pytest.raises(ev.EvaluationError, match="already been delivered"):
            ev.run_payload(actor, run)
    assert EvaluationAuditEvent.objects.filter(target_id=frozen.snapshot.pk, kind="aggregate_served").count() == 1


def test_t24_detailed_custodian_inspection_remains_available(frozen):
    run = _judged_run(frozen)
    for _ in range(2):
        payload = ev.run_payload(frozen.curator, run)
        assert payload["reports"] == frozen.reports
        assert set(payload["metrics"]["case_results"]) == {str(case.pk) for case in frozen.cases}
    assert not EvaluationAuditEvent.objects.filter(target_id=frozen.snapshot.pk, kind="aggregate_served").exists()


def test_t25_withdrawn_source_invalidates_dependent_snapshot_and_run(frozen):
    run = _judged_run(frozen)
    ev.grant(frozen.admin, frozen.curator, "activation", frozen.snapshot)
    recorded = ev.record_readiness(frozen.curator, "D", frozen.snapshot, "passed", {
        "artifacts": [frozen.snapshot.digest], "limitations": ["Synthetic governance fixture only."],
    })
    ev.invalidate(frozen.curator, frozen.cases[0], "withdrawal", purge=True)
    with pytest.raises(ev.EvaluationError, match="no longer eligible"):
        ev.snapshot_eligible(frozen.snapshot)
    with pytest.raises(ev.EvaluationError, match="no longer eligible"):
        ev.run_payload(frozen.curator, run)
    assert ReadinessEvidence.objects.get(pk=recorded.pk).decision == "passed"
    assert EvaluationAuditEvent.objects.filter(target_id=frozen.cases[0].pk, kind="withdrawal").exists()


def test_t31_changed_configuration_creates_new_profile_without_rewriting_run(frozen):
    run = _judged_run(frozen)
    original = copy.deepcopy(frozen.profile.payload)
    changed = ev.create_profile(frozen.curator, _profile_payload(prompt="A revised mathematical review prompt."))
    assert changed.pk != frozen.profile.pk
    assert changed.digest != frozen.profile.digest
    run.refresh_from_db()
    assert run.profile_id == frozen.profile.pk
    assert run.profile.payload == original
    frozen.profile.payload = changed.payload
    with pytest.raises(ValidationError, match="immutable"):
        frozen.profile.save()
    with pytest.raises(ValidationError, match="immutable"):
        ReviewerProfile.objects.filter(pk=run.profile_id).update(payload=changed.payload)


def test_t31_frozen_profile_is_reused_only_for_identical_configuration(frozen):
    same = ev.create_profile(frozen.curator, _profile_payload())
    assert same.pk == frozen.profile.pk
    assert same.digest == frozen.profile.digest


def test_t31_profile_rejects_automatic_paid_retry_configuration(frozen):
    with pytest.raises(ev.EvaluationError, match="retries disabled"):
        ev.create_profile(frozen.curator, _profile_payload(retry_policy="automatic"))
