"""Adversarial regressions for holdout custody and private evidence withdrawal."""

import copy
import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import CoachJudgment
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.evaluation_models import ReviewConsent
from inspinia.solutions.test_evaluation_contract import case_setup  # noqa: F401 - shared pytest fixture
from inspinia.solutions.test_evaluation_contract import judgment
from inspinia.solutions.test_evaluation_governance import _annotation
from inspinia.solutions.test_evaluation_governance import _finding_annotation
from inspinia.solutions.test_evaluation_governance import _profile_payload
from inspinia.solutions.test_evaluation_governance import frozen  # noqa: F401 - shared pytest fixture
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _verified_snapshot(case_setup):  # noqa: F811 - shared fixture tuple
    admin, curator, family, case, judges = case_setup
    for actor in judges[:2]:
        ev.submit_judgment(actor, case, judgment(), case.bundle.digest)
    ev.grant(admin, curator, "custodian", family)
    protocol = {
        "minimum_agreement": 0.9, "min_usable_coverage": 1,
        "min_finding_precision": 1, "min_defect_recall": 1, "min_families": 1,
    }
    return ev.freeze_dataset(curator, "Private final test", [
        {"case_id": str(case.pk), "partition": "final_test"},
    ], protocol), protocol


def _mixed_snapshot(frozen):  # noqa: F811 - shared fixture tuple
    family = ev.create_family(frozen.curator, {"title": "Development divisibility", "domain": "NT", "metadata": {}})
    data = copy.deepcopy(frozen.cases[0].bundle.payload)
    data.update(
        statement="If an integer n is even, prove n² is divisible by 4.",
        source="Write n=2k for an integer k. Then n²=4k² is divisible by 4.",
        provenance=copy.deepcopy(frozen.cases[0].provenance),
    )
    case = ev.create_case(frozen.curator, family, data)
    for actor in frozen.judges[:2]:
        ev.grant(frozen.admin, actor, "reviewer", case, expertise="Number theory")
        ev.submit_judgment(actor, case, judgment(method="conventional"), case.bundle.digest)
    ev.grant(frozen.admin, frozen.curator, "custodian", family)
    ev.grant(frozen.admin, frozen.judges[2], "finding_evaluator", family, expertise="Number theory")
    snapshot = ev.freeze_dataset(frozen.curator, "Partition-specific evidence", [
        {"case_id": str(frozen.cases[0].pk), "partition": "final_test"},
        {"case_id": str(case.pk), "partition": "development"},
    ], frozen.protocol)
    reports = {
        str(frozen.cases[0].pk): frozen.reports[str(frozen.cases[0].pk)],
        str(case.pk): {"status": "completed", "assessment": "no_issues_found", "findings": []},
    }
    return snapshot, reports


def test_preexisting_adjudicator_cannot_become_blinded_developer(frozen):  # noqa: F811 - fixture injection
    actor = frozen.judges[2]
    with pytest.raises(ev.EvaluationError):
        ev.grant(frozen.admin, actor, "developer", frozen.snapshot)


def test_preparer_exposure_survives_revocation_of_case_assignments(case_setup):  # noqa: F811 - fixture injection
    admin, curator, family, case, judges = case_setup
    for actor in judges[:2]:
        ev.submit_judgment(actor, case, judgment(), case.bundle.digest)
    ev.grant(admin, judges[2], "custodian", family)
    snapshot = ev.freeze_dataset(judges[2], "Prepared by a future developer", [
        {"case_id": str(case.pk), "partition": "final_test"},
    ], {})
    for assignment in list(ev.assignments(curator)):
        ev.revoke_assignment(admin, assignment)
    with pytest.raises(ev.EvaluationError):
        ev.grant(admin, curator, "developer", snapshot)


def test_exposure_to_an_unselected_variant_blocks_final_family_development(case_setup):  # noqa: F811
    admin, curator, family, case, _ = case_setup
    data = copy.deepcopy(case.bundle.payload)
    data.update(source="The square of any real value is nonnegative.", provenance=copy.deepcopy(case.provenance))
    variant = ev.create_case(curator, family, data)
    developer = UserFactory(role="trainer", is_approved=True)
    appointment = ev.grant(admin, developer, "reviewer", variant, expertise="Algebra")
    ev.case_payload(developer, variant)
    ev.revoke_assignment(admin, appointment)
    snapshot, _ = _verified_snapshot(case_setup)
    with pytest.raises(ev.EvaluationError):
        ev.grant(admin, developer, "developer", snapshot)


def test_final_import_rejects_reports_from_development_partition(frozen):  # noqa: F811 - fixture injection
    snapshot, reports = _mixed_snapshot(frozen)
    with pytest.raises(ev.EvaluationError):
        ev.import_run(frozen.curator, snapshot, frozen.profile, reports, frozen.protocol)


def test_final_metrics_include_only_selected_partition(frozen):  # noqa: F811 - fixture injection
    snapshot, _ = _mixed_snapshot(frozen)
    case = frozen.cases[0]
    reports = {str(case.pk): frozen.reports[str(case.pk)]}
    run = ev.import_run(frozen.curator, snapshot, frozen.profile, reports, frozen.protocol)
    ev.assess_findings(frozen.judges[2], run, case, {"useful": True, "report_spoiler": False, "findings": []})
    result = ev.run_payload(frozen.curator, run)
    assert result["metrics"]["counts"]["eligible"] == 1
    assert result["metrics"]["by_domain"]["NT"]["counts"]["eligible"] == 0
    assert set(result["reports"]) == {str(case.pk)}


def test_aggregate_abstention_reasons_do_not_deliver_free_text_or_case_identifiers(frozen):  # noqa: F811
    private_reason = f"Unable to assess {frozen.cases[0].pk}: {frozen.cases[0].bundle.payload['source']}"
    reports = copy.deepcopy(frozen.reports)
    reports[str(frozen.cases[0].pk)] = {
        "status": "completed", "assessment": "unable_to_assess", "findings": [],
        "abstention_reason": private_reason,
    }
    run = ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, reports, frozen.protocol)
    ev.assess_findings(frozen.judges[2], run, frozen.cases[0], {
        "useful": False, "abstention_appropriate": False, "report_spoiler": False, "findings": [],
    })
    ev.assess_findings(frozen.judges[2], run, frozen.cases[1], _annotation([
        _finding_annotation("false-parity", frozen.defect_id),
    ]))
    developer = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, developer, "developer", frozen.snapshot)
    aggregate = ev.run_payload(developer, run)
    encoded = json.dumps(aggregate)
    assert private_reason not in encoded
    assert str(frozen.cases[0].pk) not in encoded
    assert frozen.cases[0].bundle.payload["source"] not in encoded


def test_withdrawal_erases_copied_source_from_judgments_manifests_and_reports(case_setup):  # noqa: F811
    admin, curator, family, case, judges = case_setup
    marker = "WITHDRAWN_PRIVATE_MATHEMATICAL_PASSAGE"
    for actor in judges[:2]:
        ev.submit_judgment(actor, case, judgment(explanation=marker), case.bundle.digest)
    ev.grant(admin, curator, "custodian", family)
    snapshot = ev.freeze_dataset(curator, "Private copied annotations", [
        {"case_id": str(case.pk), "partition": "final_test"},
    ], {})
    profile = ev.create_profile(curator, _profile_payload())
    run = ev.import_run(curator, snapshot, profile, {str(case.pk): {
        "status": "completed", "assessment": "no_issues_found", "findings": [], "summary": marker,
    }}, {})
    ev.invalidate(curator, case, "withdrawal", purge=True)
    retained = {
        "judgments": list(CoachJudgment.objects.filter(case=case).values_list("payload", flat=True)),
        "manifest": EvaluationDatasetSnapshot.objects.get(pk=snapshot.pk).manifest,
        "reports": EvaluationRun.objects.get(pk=run.pk).reports,
    }
    assert marker not in json.dumps(retained)


def test_unscoped_benchmark_consent_cannot_authorize_an_unidentified_learner_source(case_setup):  # noqa: F811
    _, curator, family, case, _ = case_setup
    consenting_learner = UserFactory()
    consent = ReviewConsent.objects.create(
        actor=consenting_learner, purpose="benchmark_reuse", expires_at=timezone.now() + timedelta(days=120),
        payload={"lawful_eligibility": "Recorded", "retention_policy": "One hundred twenty days"},
    )
    data = copy.deepcopy(case.bundle.payload)
    data["provenance"] = {
        **copy.deepcopy(case.provenance), "construction": "learner_submission",
        "consent_reference": str(consent.pk), "lawful_eligibility": "Unverified source identity",
        "withdrawal_policy": "Withdraw on learner request",
    }
    with pytest.raises(ev.EvaluationError):
        ev.create_case(curator, family, data)


def test_scoped_consent_cannot_be_reused_after_swapping_the_actual_proof(case_setup):  # noqa: F811
    _, curator, family, case, _ = case_setup
    learner = UserFactory()
    scope = {
        "learner_id": str(learner.pk), "source_revision_id": str(uuid.uuid4()),
        "source_digest": hashlib.sha256(b"The separately authorized original proof.").hexdigest(),
    }
    consent = ReviewConsent.objects.create(
        actor=learner, purpose="benchmark_reuse", expires_at=timezone.now() + timedelta(days=120),
        payload={"lawful_eligibility": "Recorded", "retention_policy": "One hundred twenty days", **scope},
    )
    data = copy.deepcopy(case.bundle.payload)
    data["provenance"] = {
        **copy.deepcopy(case.provenance), **scope, "construction": "learner_submission",
        "consent_reference": str(consent.pk), "lawful_eligibility": "Documented in the original consent",
        "withdrawal_policy": "Withdraw on learner request",
    }
    with pytest.raises(ev.EvaluationError):
        ev.create_case(curator, family, data)


def test_sound_partial_alternative_is_not_mislabelled_as_a_verified_complete_alternative(case_setup):  # noqa: F811
    admin, curator, family, original, judges = case_setup
    data = copy.deepcopy(original.bundle.payload)
    data.update(
        source="For x≥0, multiplying x by itself gives x²≥0.",
        provenance=copy.deepcopy(original.provenance),
    )
    case = ev.create_case(curator, family, data)
    defect_id = str(uuid.uuid4())
    ground = judgment(
        assessment="incomplete", proof_completeness="incomplete", method="alternative",
        defects=[{
            "id": defect_id, "root_id": defect_id, "significance": "consequential",
            "explanation": "The negative values of x remain untreated.",
            "justification": "The statement applies to every real x, including negative values.",
            "depends_on": [], "spans": [],
        }],
    )
    for actor in judges[:2]:
        ev.grant(admin, actor, "reviewer", case, expertise="Algebra")
        ev.submit_judgment(actor, case, copy.deepcopy(ground), case.bundle.digest)
    ev.grant(admin, curator, "custodian", family)
    snapshot = ev.freeze_dataset(curator, "A valid but incomplete argument", [
        {"case_id": str(case.pk), "partition": "final_test"},
    ], {})
    row = snapshot.manifest["cases"][0]
    assert row["ground_truth"]["method"] == "alternative"
    assert row["valid_alternative"] is False
