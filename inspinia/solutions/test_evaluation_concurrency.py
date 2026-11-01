"""PostgreSQL-only evidence races; SQLite cannot demonstrate row-lock behavior."""
# ruff: noqa: PLR2004

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Barrier
from threading import Event

import pytest
from django.db import close_old_connections
from django.db import connection
from django.db import transaction

from inspinia.solutions import evaluation as ev
from inspinia.solutions import evaluation_execution as execution
from inspinia.solutions.evaluation_models import CoachJudgment
from inspinia.solutions.evaluation_models import EvaluationAssignment
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import HintRevealEvent
from inspinia.solutions.test_evaluation_contract import case_setup as case_setup_fixture
from inspinia.solutions.test_evaluation_contract import judgment
from inspinia.solutions.test_evaluation_execution import completed_review
from inspinia.solutions.test_evaluation_governance import _developer
from inspinia.solutions.test_evaluation_governance import _judged_run
from inspinia.solutions.test_evaluation_governance import frozen as frozen_fixture
from inspinia.solutions.test_reviews import coach as coach_fixture

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def postgres_required():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL is required to verify evidence row-lock races")


@pytest.fixture
def coach(settings):
    return coach_fixture.__wrapped__(settings)


@pytest.fixture
def case_setup():
    return case_setup_fixture.__wrapped__()


@pytest.fixture
def frozen(case_setup):
    return frozen_fixture.__wrapped__(case_setup)


def database_thread(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


def test_postgres_duplicate_hint_reveal_records_one_event(coach):
    review = completed_review(coach)
    finding = review.feedback["findings"][0]
    identifier = execution.finding_identity(review, finding, 0)
    barrier = Barrier(2)

    def reveal():
        barrier.wait(timeout=5)
        return execution.reveal_hint(coach.user, review, identifier, 1).pk

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(database_thread, reveal) for _ in range(2)]
        identifiers = [future.result(timeout=10) for future in futures]
    assert identifiers[0] == identifiers[1]
    assert HintRevealEvent.objects.filter(review=review).count() == 1
    assert EvaluationAuditEvent.objects.filter(target_id=review.pk, kind="hint_released").count() == 1


def test_postgres_freeze_racing_with_withdrawal_preserves_invalidity(case_setup):
    admin, curator, family, case, judges = case_setup
    for actor in judges[:2]:
        ev.submit_judgment(actor, case, judgment(), case.bundle.digest)
    ev.grant(admin, curator, "custodian", family)
    barrier = Barrier(2)

    def freeze():
        barrier.wait(timeout=5)
        try:
            return ev.freeze_dataset(curator, "Race fixture", [
                {"case_id": str(case.pk), "partition": "final_test"},
            ], {}).pk
        except ev.EvaluationError:
            return None

    def withdraw():
        barrier.wait(timeout=5)
        ev.invalidate(curator, case, "withdrawal", purge=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        frozen = executor.submit(database_thread, freeze)
        withdrawn = executor.submit(database_thread, withdraw)
        frozen.result(timeout=10)
        withdrawn.result(timeout=10)
    for snapshot in EvaluationDatasetSnapshot.objects.all():
        with pytest.raises(ev.EvaluationError, match="no longer eligible"):
            ev.snapshot_eligible(snapshot)
    with pytest.raises(ev.EvaluationError):
        ev.case_payload(curator, case)


def test_postgres_final_aggregate_is_delivered_once_across_actors(frozen):
    run = _judged_run(frozen)
    actors = [_developer(frozen), _developer(frozen)]
    barrier = Barrier(2)

    def deliver(actor):
        barrier.wait(timeout=5)
        try:
            ev.run_payload(actor, run)
        except ev.EvaluationError as error:
            return "denied", error.status
        else:
            return "served", 200

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(database_thread, lambda actor=actor: deliver(actor)) for actor in actors]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(results) == [("denied", 409), ("served", 200)]
    assert EvaluationAuditEvent.objects.filter(target_id=run.snapshot_id, kind="aggregate_served").count() == 1


def test_postgres_revocation_serializes_with_judgment(case_setup):
    admin, _, _, case, judges = case_setup
    reviewer = judges[0]
    started = Event()

    def submit():
        started.set()
        try:
            ev.submit_judgment(reviewer, case, judgment(), case.bundle.digest)
        except ev.EvaluationError:
            return "denied"
        else:
            return "accepted"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            appointment = EvaluationAssignment.objects.select_for_update().get(
                actor=reviewer, role="reviewer", scope_id=case.pk,
            )
            ev.revoke_assignment(admin, appointment)
            pending = executor.submit(database_thread, submit)
            assert started.wait(timeout=5)
            with pytest.raises(FutureTimeout):
                pending.result(timeout=0.2)
        assert pending.result(timeout=10) == "denied"
    assert not CoachJudgment.objects.filter(case=case, actor=reviewer).exists()
