"""Run with isolated PostgreSQL settings; SQLite cannot establish lock safety."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from decimal import Decimal
from threading import Event

import pytest
from django.db import close_old_connections
from django.db import connection
from django.db import connections

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import RankingCorrectionReceipt
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.corrections import StaleCorrection
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.import_protection import begin_import
from inspinia.rankings.services.import_protection import guard_import_row
from inspinia.rankings.services.import_protection import ranking_write_lock
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def pg_data():
    if connection.vendor != "postgresql":
        pytest.skip("Run this concurrency suite against isolated PostgreSQL")
    if (
        connection.settings_dict["HOST"] not in {"127.0.0.1", "localhost"}
        or "synthetic" not in connection.settings_dict["NAME"]
    ):
        pytest.skip("Requires the explicitly isolated synthetic PostgreSQL fixture")
    admin = UserFactory(role=User.Role.ADMIN)
    student = Student.objects.create(full_name="Synthetic concurrent student")
    assessment = Assessment.objects.create(
        code="CONCURRENT",
        display_name="Concurrent synthetic",
        category="test",
        season_year=2026,
    )
    result = StudentResult.objects.create(student=student, assessment=assessment, raw_score=1)
    return admin, result


def worker(function):
    close_old_connections()
    try:
        return function()
    finally:
        connections.close_all()


def proposal(admin, result, value):
    return create_proposal(
        actor=admin,
        reason="Synthetic lock test",
        evidence="Synthetic fixture",
        submit=True,
        operations=[{"kind": "result", "target_id": result.pk, "values": {"raw_score": str(value)}}],
    )


def test_two_applications_create_one_receipt(pg_data):
    admin, result = pg_data
    change = proposal(admin, result, 5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, lambda: apply_proposal(proposal_id=change.pk, actor=admin).status) for _ in range(2)
        ]
        assert [future.result(timeout=15) for future in futures] == ["applied", "applied"]
    assert RankingCorrectionReceipt.objects.filter(correction=change).count() == 1
    result.refresh_from_db()
    assert result.raw_score == Decimal(5)


def test_competing_previews_cannot_overwrite_each_other(pg_data):
    admin, result = pg_data
    first, second = proposal(admin, result, 5), proposal(admin, result, 9)

    def apply(change):
        try:
            apply_proposal(proposal_id=change.pk, actor=admin)
        except StaleCorrection:
            return "stale"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, lambda item=item: apply(item)) for item in (first, second)]
        assert sorted(future.result(timeout=15) for future in futures) == ["applied", "stale"]
    assert RankingCorrectionReceipt.objects.count() == 1


def test_import_waits_then_holds_approved_value(pg_data, monkeypatch):
    admin, result = pg_data
    change = proposal(admin, result, 5)
    batch = ImportBatch.objects.create(
        import_type="assessment_results",
        status="previewed",
        original_filename="synthetic.csv",
    )
    entered, release = Event(), Event()
    original = RankingCorrectionReceipt.objects.create

    def delayed_receipt(**kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(**kwargs)

    monkeypatch.setattr(RankingCorrectionReceipt.objects, "create", delayed_receipt)

    def importing():
        with ranking_write_lock():
            begin_import(batch)
            held = guard_import_row(
                batch,
                2,
                [{"kind": "result", "target_id": result.pk, "values": {"raw_score": "9"}}],
            )
            if not held:
                StudentResult.objects.filter(pk=result.pk).update(raw_score=9)
            batch.status = "partial" if held else "applied"
            batch.save()
            return held

    with ThreadPoolExecutor(max_workers=2) as pool:
        applying = pool.submit(worker, lambda: apply_proposal(proposal_id=change.pk, actor=admin))
        assert entered.wait(timeout=10)
        importing_future = pool.submit(worker, importing)
        try:
            with pytest.raises(FutureTimeout):
                importing_future.result(timeout=0.15)
        finally:
            release.set()
        applying.result(timeout=15)
        assert importing_future.result(timeout=15)
    result.refresh_from_db()
    assert result.raw_score == Decimal(5)
    assert batch.protected_conflicts.count() == 1
