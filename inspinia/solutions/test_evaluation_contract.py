"""Trust contract acceptance: synthetic identities, local database, no provider."""

# ruff: noqa: PLR2004
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import CoachJudgment
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationLifecycle
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def judgment(**changes):
    result = {
        "assessment": "no_issues_found",
        "input_sufficiency": "present",
        "problem_integrity": "no_known_defect",
        "logical_validity": "valid",
        "proof_completeness": "complete",
        "justification": "sufficient",
        "method": "alternative",
        "task_compliance": "met",
        "explanation": "The argument is valid.",
        "defects": [],
    }
    result.update(changes)
    return result


@pytest.fixture
def case_setup():
    admin = UserFactory(is_superuser=True, role="admin")
    curator = UserFactory(role="trainer", is_approved=True)
    ev.grant(admin, curator, "curator", ev.WORKSPACE, expertise="Competition mathematics")
    family = ev.create_family(curator, {"title": "A synthetic family", "domain": "ALG", "metadata": {}})
    case = ev.create_case(
        curator,
        family,
        {
            "statement": "Prove x² is nonnegative for real x.",
            "source": "A square is nonnegative.",
            "language": "en",
            "completeness": "present",
            "problem_integrity": "no_known_defect",
            "provenance": {
                "source": "Original technical fixture",
                "rights": "Author permission",
                "permitted_uses": ["benchmark"],
                "construction": "coach_original",
                "retention_until": (timezone.now() + timedelta(days=90)).isoformat(),
            },
        },
    )
    judges = [UserFactory(role="trainer", is_approved=True) for _ in range(3)]
    for user in judges:
        ev.grant(admin, user, "reviewer", case, expertise="Algebra")
    ev.grant(admin, judges[2], "adjudicator", case, expertise="Algebra")
    return admin, curator, family, case, judges


def test_blind_independent_judgments_and_immutable_history(case_setup):
    _, _, _, case, judges = case_setup
    ev.submit_judgment(judges[0], case, judgment(), case.bundle.digest)
    assert "judgments" not in ev.case_payload(judges[1], case)
    assert ev.case_state(case)["status"] == "provisional"
    first = CoachJudgment.objects.get(case=case)
    first.payload = {}
    with pytest.raises(ValidationError):
        first.save()
    ev.submit_judgment(judges[1], case, judgment(), case.bundle.digest)
    assert ev.case_state(case)["status"] == "verified"


def test_preparer_unassigned_and_stale_judgments_rejected(case_setup):
    _, curator, _, case, judges = case_setup
    for user, digest in [(curator, case.bundle.digest), (UserFactory(), case.bundle.digest), (judges[0], "stale")]:
        with pytest.raises(ev.EvaluationError):
            ev.submit_judgment(user, case, judgment(), digest)


def test_disagreement_preserved_and_third_actor_adjudicates(case_setup):
    _, _, _, case, judges = case_setup
    ev.submit_judgment(judges[0], case, judgment(), case.bundle.digest)
    ev.submit_judgment(
        judges[1],
        case,
        judgment(proof_completeness="incomplete", assessment="incomplete"),
        case.bundle.digest,
    )
    assert ev.case_state(case)["status"] == "disputed"
    ev.adjudicate(
        judges[2],
        case,
        {**judgment(), "reason": "The assertion is a standard real-number property."},
        case.bundle.digest,
    )
    assert ev.case_state(case)["status"] == "adjudicated"
    assert CoachJudgment.objects.filter(case=case).count() == 3


def test_withdrawal_invalidates_access_and_preserves_minimal_event(case_setup):
    _, curator, _, case, _ = case_setup
    ev.invalidate(curator, case, "withdrawal", purge=True)
    assert not EvaluationLifecycle.objects.get(target_id=case.pk).eligible
    assert EvaluationAuditEvent.objects.filter(target_id=case.pk, kind="withdrawal").exists()
    with pytest.raises(ev.EvaluationError):
        ev.case_payload(curator, case)


def test_fake_verified_import_rejected_and_missing_context_never_cleared(case_setup):
    _, _, _, case, _ = case_setup
    with pytest.raises(ev.EvaluationError):
        ev.validate_judgment(judgment(input_sufficiency="missing_essential_context"), case.bundle.payload["source"])
    with pytest.raises(ev.EvaluationError):
        ev.require_offline_origin("verified_authorized_provider")


def test_critical_audit_failure_rolls_back_judgment(case_setup, monkeypatch):
    _, _, _, case, judges = case_setup

    def fail(*args, **kwargs):
        message = "audit unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(ev, "audit", fail)
    with pytest.raises(RuntimeError):
        ev.submit_judgment(judges[0], case, judgment(), case.bundle.digest)
    assert not CoachJudgment.objects.filter(case=case).exists()


def test_defect_dependencies_cannot_cycle():
    key = str(uuid.uuid4())
    with pytest.raises(ev.EvaluationError):
        ev.validate_judgment(
            judgment(
                assessment="gap_found",
                logical_validity="invalid",
                defects=[
                    {
                        "id": key,
                        "root_id": key,
                        "significance": "fatal",
                        "explanation": "Invalid implication",
                        "justification": "The converse need not hold",
                        "depends_on": [key],
                        "spans": [],
                    },
                ],
            ),
            "proof",
        )


def test_default_split_groups_variants_and_uses_family_level_ratios():
    from types import SimpleNamespace

    cases = []
    for domain in ("ALG", "GEO", "NT", "COM"):
        for _ in range(10):
            family_id = uuid.uuid4()
            cases.extend(
                SimpleNamespace(pk=uuid.uuid4(), family_id=family_id, family=SimpleNamespace(domain=domain))
                for _ in range(2)
            )
    membership = ev.default_membership(cases)
    by_case = {row["case_id"]: row["partition"] for row in membership}
    families = {}
    for case in cases:
        family = families.setdefault(case.family_id, by_case[str(case.pk)])
        assert family == by_case[str(case.pk)]
    assert list(families.values()).count("development") == 24
    assert list(families.values()).count("validation") == 8
    assert list(families.values()).count("final_test") == 8
    assert {row["case_id"]: row["partition"] for row in ev.default_membership(list(reversed(cases)))} == by_case
