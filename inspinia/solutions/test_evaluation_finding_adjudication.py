"""Finding disputes preserve both human assessments and require an independent resolution."""

import copy
import json
import uuid

import pytest

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_finding_adjudication import adjudicate_findings
from inspinia.solutions.evaluation_finding_adjudication import resolve_finding_judgments
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationFindingJudgment
from inspinia.solutions.test_evaluation_contract import case_setup  # noqa: F401 - shared pytest fixture
from inspinia.solutions.test_evaluation_governance import _annotation
from inspinia.solutions.test_evaluation_governance import _finding_annotation
from inspinia.solutions.test_evaluation_governance import frozen  # noqa: F401 - shared pytest fixture
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _run(setup, *, disagree=True):
    run = ev.import_run(setup.curator, setup.snapshot, setup.profile, setup.reports, setup.protocol)
    originals = []
    for index, actor in enumerate(setup.judges[:2]):
        ev.grant(setup.admin, actor, "finding_evaluator", setup.cases[0], expertise="Algebra")
        payload = _annotation()
        payload["useful"] = not disagree or index == 0
        originals.append(ev.assess_findings(actor, run, setup.cases[0], payload))
    ev.assess_findings(
        setup.judges[2],
        run,
        setup.cases[1],
        _annotation(
            [
                _finding_annotation("false-parity", setup.defect_id),
            ],
        ),
    )
    return run, originals


def test_finding_disagreement_blocks_aggregate_until_adjudicated(frozen):  # noqa: F811
    run, originals = _run(frozen)
    with pytest.raises(ev.EvaluationError, match="disagreement"):
        resolve_finding_judgments(run)
    with pytest.raises(ev.EvaluationError, match="disagreement"):
        ev.run_payload(frozen.curator, run)
    assert EvaluationFindingJudgment.objects.filter(run=run, case=frozen.cases[0]).count() == len(originals)


def test_distinct_assigned_third_actor_resolves_without_replacing_originals(frozen):  # noqa: F811
    run, originals = _run(frozen)
    before = {row.pk: copy.deepcopy(row.payload) for row in originals}
    reason = "The report provides actionable feedback, so the first usefulness assessment is supported."
    final = adjudicate_findings(frozen.judges[2], run, frozen.cases[0], _annotation(), reason)
    assert set(final.payload["_adjudicates"]) == {str(row.pk) for row in originals}
    assert final.payload["_reason"] == reason
    assert final.actor_id == frozen.judges[2].pk
    for row in originals:
        row.refresh_from_db()
        assert row.payload == before[row.pk]
    resolved = resolve_finding_judgments(run)
    assert resolved[str(frozen.cases[0].pk)] == _annotation()
    assert all(not key.startswith("_") for key in resolved[str(frozen.cases[0].pk)])
    assert ev.run_payload(frozen.curator, run)["metrics"]["candidate_passed"]
    receipt = EvaluationAuditEvent.objects.get(target_id=run.pk, kind="finding_adjudicated")
    assert reason not in json.dumps(receipt.metadata)


def test_matching_originals_need_no_additional_adjudication(frozen):  # noqa: F811
    run, _ = _run(frozen, disagree=False)
    assert resolve_finding_judgments(run)[str(frozen.cases[0].pk)] == _annotation()
    assert ev.run_payload(frozen.curator, run)["metrics"]["candidate_passed"]


def test_missing_reviewer_identity_cannot_count_as_matching_human_validation(frozen):  # noqa: F811
    run, originals = _run(frozen, disagree=False)
    # Simulate loss of the retained finding-review identity without changing mathematical ground truth.
    EvaluationFindingJudgment._base_manager.filter(pk=originals[0].pk).update(actor=None)  # noqa: SLF001
    with pytest.raises(ev.EvaluationError, match="authenticated reviewer identities"):
        resolve_finding_judgments(run)


def test_unannotated_cases_remain_pending_instead_of_becoming_a_dispute(frozen):  # noqa: F811
    run = ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol)
    assert resolve_finding_judgments(run) == {}
    result = ev.run_payload(frozen.curator, run)
    assert result["annotation_pending"] == len(frozen.cases)
    assert result["metrics"] is None


def test_unassigned_or_original_evaluator_cannot_supply_third_judgment(frozen):  # noqa: F811
    run, _ = _run(frozen)
    unassigned = UserFactory(role="trainer", is_approved=True)
    with pytest.raises(ev.EvaluationError):
        adjudicate_findings(unassigned, run, frozen.cases[0], _annotation(), "An unsupported appointment.")
    original_actor = frozen.judges[0]
    ev.grant(frozen.admin, original_actor, "adjudicator", frozen.cases[0], expertise="Algebra")
    with pytest.raises(ev.EvaluationError, match="distinct third"):
        adjudicate_findings(original_actor, run, frozen.cases[0], _annotation(), "Revising my own initial opinion.")


def test_one_original_judgment_is_insufficient_for_adjudication(frozen):  # noqa: F811
    run = ev.import_run(frozen.curator, frozen.snapshot, frozen.profile, frozen.reports, frozen.protocol)
    ev.assess_findings(frozen.judges[2], run, frozen.cases[0], _annotation())
    actor = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, actor, "adjudicator", frozen.cases[0], expertise="Algebra")
    with pytest.raises(ev.EvaluationError, match="two original"):
        adjudicate_findings(actor, run, frozen.cases[0], _annotation(), "The second initial assessment is missing.")


@pytest.mark.parametrize("reason", ["", " ", None, "x" * 4001], ids=["empty", "blank", "missing", "oversized"])
def test_adjudication_requires_a_bounded_mathematical_reason(frozen, reason):  # noqa: F811
    run, _ = _run(frozen)
    with pytest.raises(ev.EvaluationError, match="Explain the mathematical"):
        adjudicate_findings(frozen.judges[2], run, frozen.cases[0], _annotation(), reason)


def test_resolved_annotation_is_validated_and_server_metadata_cannot_be_supplied(frozen):  # noqa: F811
    run, _ = _run(frozen)
    for payload in ({**_annotation(), "useful": "true"}, {**_annotation(), "_adjudicates": []}):
        with pytest.raises(ev.EvaluationError):
            adjudicate_findings(frozen.judges[2], run, frozen.cases[0], payload, "A proposed mathematical resolution.")
    assert not EvaluationFindingJudgment.objects.filter(run=run, actor=frozen.judges[2], case=frozen.cases[0]).exists()


def test_existing_final_cannot_be_overwritten_by_another_actor(frozen):  # noqa: F811
    run, _ = _run(frozen)
    first = adjudicate_findings(frozen.judges[2], run, frozen.cases[0], _annotation(), "First supported resolution.")
    other = UserFactory(role="trainer", is_approved=True)
    ev.grant(frozen.admin, other, "adjudicator", frozen.cases[0], expertise="Algebra")
    with pytest.raises(ev.EvaluationError, match="already preserved"):
        adjudicate_findings(other, run, frozen.cases[0], _annotation(), "An attempted replacement.")
    first.refresh_from_db()
    assert first.payload["_reason"] == "First supported resolution."


@pytest.mark.parametrize(
    "invalid_reference", [True, False], ids=["wrong-original-reference", "missing-authenticated-receipt"],
)
def test_manually_fabricated_final_cannot_resolve_a_dispute(frozen, invalid_reference):  # noqa: F811
    run, originals = _run(frozen)
    references = [str(row.pk) for row in originals]
    if invalid_reference:
        references[1] = str(uuid.uuid4())
    EvaluationFindingJudgment.objects.create(
        run=run,
        case=frozen.cases[0],
        actor=frozen.judges[2],
        payload={**_annotation(), "_adjudicates": references, "_reason": "A manually forged resolution."},
    )
    with pytest.raises(ev.EvaluationError):
        resolve_finding_judgments(run)


def test_critical_audit_failure_rolls_back_only_the_new_adjudication(frozen, monkeypatch):  # noqa: F811
    run, originals = _run(frozen)
    audit = ev.audit

    def unavailable(actor, target, kind, metadata=None):
        if kind == "finding_adjudicated":
            message = "Synthetic critical audit failure"
            raise RuntimeError(message)
        return audit(actor, target, kind, metadata)

    monkeypatch.setattr(ev, "audit", unavailable)
    with pytest.raises(RuntimeError, match="critical audit"):
        adjudicate_findings(frozen.judges[2], run, frozen.cases[0], _annotation(), "A supported final opinion.")
    assert EvaluationFindingJudgment.objects.filter(run=run, case=frozen.cases[0]).count() == len(originals)
    assert not EvaluationAuditEvent.objects.filter(target_id=run.pk, kind="finding_adjudicated").exists()


def test_source_withdrawal_purges_originals_and_final_without_hidden_reason_copy(frozen):  # noqa: F811
    run, _ = _run(frozen)
    marker = "PRIVATE_FINDING_ADJUDICATION_EXPLANATION"
    adjudicate_findings(frozen.judges[2], run, frozen.cases[0], _annotation(), marker)
    ev.invalidate(frozen.curator, frozen.cases[0], "withdrawal", purge=True)
    assert all(
        row.payload == {"withdrawn": True}
        for row in EvaluationFindingJudgment.objects.filter(run=run, case=frozen.cases[0])
    )
    assert marker not in json.dumps(
        list(EvaluationAuditEvent.objects.filter(target_id=run.pk).values_list("metadata", flat=True)),
    )
    with pytest.raises(ev.EvaluationError, match="no longer eligible"):
        resolve_finding_judgments(run)
