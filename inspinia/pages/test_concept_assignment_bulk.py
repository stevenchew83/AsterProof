"""Bulk snapshots use the existing evidence engine and never write review decisions."""

import gzip
import json
from copy import deepcopy
from http import HTTPStatus
from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client
from django.urls import reverse

from inspinia.pages import concept_assignment_bulk as bulk
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_service import apply_refresh
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ConceptAssignmentReviewBatch
from inspinia.pages.models import ConceptAssignmentReviewEvent
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True)
PRIVATE_FILE_MODE = 0o600


@pytest.fixture
def example():
    problem = ProblemSolveRecord.objects.create(contest="BULK TEST", year=2026, problem="P1", topic="ALG", mohs=35)
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="BULK TEST",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        topic="A",
        statement_latex="Let x be real. The floor is the greatest integer not exceeding x.",
    )
    StatementTopicTechnique.objects.create(
        statement=statement,
        technique="FLOOR / ROUNDING / APPROXIMATION",
        main_topic="ALG",
        domains=["ALG"],
        object_tags=["FLOOR FUNCTION", "Farey fraction"],
    )
    apply_refresh(audit_sources(load_sources([problem.problem_uuid])))
    snapshot = bulk.capture_snapshot({"subject": "Algebra"})
    decision = {
        "problem_uuid": str(problem.problem_uuid),
        "concept_id": "floor-ceiling",
        "action": "confirm",
        "roles": ["object"],
        "subject_context": "Algebra",
        "rationale": "The statement defines the floor object.",
        "evidence": {"kind": "statement", "quote": "greatest integer not exceeding x"},
        "review_metadata": {
            "origin": "agent_assisted",
            "statement_sha256": snapshot["sources"][str(problem.problem_uuid)]["statement_hash"],
        },
    }
    return problem, statement, snapshot, decision


def deny_queries(*args, **kwargs):
    message = "Offline review attempted a database query"
    raise AssertionError(message)


def test_offline_preview_uses_exact_before_images_without_database_access(example):
    problem, _, snapshot, decision = example
    before = ProblemConceptAssignment.objects.values("concept_id", "disposition", "updated_at")
    before = list(before)
    with connection.execute_wrapper(deny_queries):
        packet = bulk.make_packet(snapshot, [decision])
        report = bulk.review_packet(snapshot, packet)
    assert report["ready"]
    assert not report["conflicts"]
    assert report["row_changes"] == 1
    change = report["batches"][0]["changes"][0]
    assert change["before"]["disposition"] == "suggested"
    assert change["after"]["disposition"] == "accepted"
    assert change["problem_uuid"] == str(problem.problem_uuid)
    assert list(ProblemConceptAssignment.objects.values("concept_id", "disposition", "updated_at")) == before
    assert report["assignment_writes"] == report["source_writes"] == 0


def test_snapshot_exports_suppressed_and_inactive_sources_but_no_private_drafts(example):
    problem, statement, _, _ = example
    author = UserFactory()
    published = ProblemSolution.objects.create(
        problem=problem,
        author=author,
        title="Published evidence",
        status="published",
    )
    ProblemSolutionBlock.objects.create(solution=published, position=0, body_source="Exact published proof.")
    draft_author = UserFactory()
    draft = ProblemSolution.objects.create(problem=problem, author=draft_author, title="PRIVATE DRAFT SENTINEL")
    ProblemSolutionBlock.objects.create(solution=draft, position=0, body_source="PRIVATE BODY SENTINEL")
    statement.is_active = False
    statement.save()
    StatementTopicTechnique.objects.create(
        statement=statement,
        technique="SUPPRESSED CAPTION",
        normalization_status="invalid",
    )
    counts = (ConceptAssignmentReviewBatch.objects.count(), ConceptAssignmentReviewEvent.objects.count())
    snapshot = bulk.capture_snapshot({"subject": "Algebra"})
    text = json.dumps(snapshot)
    assert not snapshot["sources"][str(problem.problem_uuid)]["active"]
    assert "SUPPRESSED CAPTION" in text
    assert "Exact published proof." in text
    assert "PRIVATE DRAFT SENTINEL" not in text
    assert "PRIVATE BODY SENTINEL" not in text
    assert author.email not in text
    assert draft_author.email not in text
    assert counts == (ConceptAssignmentReviewBatch.objects.count(), ConceptAssignmentReviewEvent.objects.count())
    assert snapshot["counts"]["published_solutions"] == 1


@pytest.mark.parametrize(
    ("change", "code"),
    [("source", "SOURCE_CHANGED"), ("assignment", "ASSIGNMENTS_CHANGED"), ("scope", "SCOPE_CHANGED")],
)
def test_live_drift_blocks_the_entire_packet(example, change, code):
    problem, statement, snapshot, decision = example
    packet = bulk.make_packet(snapshot, [decision])
    if change == "source":
        statement.statement_latex += " Additional hypothesis."
        statement.save()
    elif change == "assignment":
        row = ProblemConceptAssignment.objects.filter(problem_uuid=problem.problem_uuid).first()
        row.rationale = "Another reviewer changed this assignment."
        row.save()
    else:
        ContestProblemStatement.objects.create(
            contest_name="NEW", contest_year=2026, problem_number=1, problem_code="P1", topic="A",
        )
    report = bulk.check_live_packet(packet)
    assert not report["ready"]
    assert code in {c["code"] for c in report["conflicts"]}
    assert report["batches"] == []
    assert report["row_changes"] == 0


def test_published_withdrawal_conflicts_but_private_draft_edits_do_not(example):
    problem, _, _, decision = example
    published = ProblemSolution.objects.create(problem=problem, author=UserFactory(), status="published")
    draft = ProblemSolution.objects.create(problem=problem, author=UserFactory(), title="private")
    snapshot = bulk.capture_snapshot({"subject": "Algebra"})
    packet = bulk.make_packet(snapshot, [decision])
    draft.title = "Still private and irrelevant"
    draft.save()
    assert bulk.check_live_packet(packet)["ready"]
    published.status = "draft"
    published.save()
    report = bulk.check_live_packet(packet)
    assert "PUBLISHED_EVIDENCE_CHANGED" in {c["code"] for c in report["conflicts"]}
    assert not report["batches"]


@pytest.mark.parametrize("replacement", [False, True])
def test_protection_covers_direct_actions_and_replacement_destinations(example, replacement):
    problem, _, snapshot, decision = example
    if replacement:
        decision = {
            **decision,
            "concept_id": "nt-farey",
            "replacement_concept_id": "floor-ceiling",
            "action": "replace",
            "subject_context": "",
        }
    protected = [str(problem.problem_uuid) + "|floor-ceiling"]
    packet = bulk.make_packet(snapshot, [decision], protected)
    report = bulk.review_packet(snapshot, packet)
    assert not report["ready"]
    assert report["conflicts"][0]["code"] == "PROTECTED_ASSIGNMENT"
    assert not report["batches"]


def test_duplicate_decisions_cannot_hide_across_batches(example):
    problem, _, snapshot, decision = example
    decisions = [{**decision, "concept_id": cid, "action": "hold"} for cid in list(REGISTRY.definitions)[:250]]
    decisions.append(decisions[0])
    report = bulk.review_packet(snapshot, bulk.make_packet(snapshot, decisions))
    assert not report["ready"]
    assert "Duplicate or conflicting" in report["conflicts"][0]["reason"]
    assert not report["batches"]


def test_invalid_excerpt_blocks_other_valid_decisions(example):
    _, _, snapshot, decision = example
    invalid = {
        **decision,
        "concept_id": "nt-farey",
        "subject_context": "Number Theory",
        "evidence": {"kind": "statement", "quote": "Not in the statement"},
    }
    report = bulk.review_packet(snapshot, bulk.make_packet(snapshot, [decision, invalid]))
    assert not report["ready"]
    assert not report["batches"]
    assert report["conflicts"][0]["code"] == "INVALID_DECISION"


@pytest.mark.parametrize("field", ["engine_fingerprint", "registry_fingerprint"])
def test_engine_or_catalog_mismatch_blocks_offline_preview(example, field):
    _, _, snapshot, decision = example
    changed = deepcopy(snapshot)
    changed[field] = "different"
    changed = bulk.seal({k: v for k, v in changed.items() if k != "sha256"})
    packet = bulk.make_packet(changed, [decision])
    report = bulk.review_packet(changed, packet)
    assert not report["ready"]
    assert not report["batches"]
    assert report["conflicts"][0]["code"] == field.upper() + "_CHANGED"


def test_checksum_size_and_exclusive_output_guards(example, tmp_path, monkeypatch):
    _, _, snapshot, _ = example
    tampered = deepcopy(snapshot)
    tampered["sources"].clear()
    with pytest.raises(bulk.BulkReviewError, match="checksum"):
        bulk.validate_snapshot(tampered)
    path = tmp_path / "snapshot.json.gz"
    bulk.write_document(path, snapshot)
    assert bulk.read_document(path) == snapshot
    assert path.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    with pytest.raises(FileExistsError):
        bulk.write_document(path, snapshot)
    bomb = tmp_path / "large.json.gz"
    bomb.write_bytes(gzip.compress(b" " * 1000))
    monkeypatch.setattr(bulk, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(bulk.BulkReviewError, match="Decompressed"):
        bulk.read_document(bomb)


def test_sqlite_read_only_restores_connection_after_exception(example):
    if connection.vendor != "sqlite":
        pytest.skip("SQLite connection lifecycle")
    with pytest.raises(ValueError, match="stop"):  # noqa: PT012, SIM117 - inspect state inside the failing context
        with bulk.read_only_snapshot(), connection.cursor() as cursor:
            cursor.execute("PRAGMA query_only")
            assert cursor.fetchone()[0] == 1
            message = "stop"
            raise ValueError(message)
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA query_only")
        assert cursor.fetchone()[0] == 0


def test_snapshot_problem_bound_and_missing_explicit_identity(example, monkeypatch):
    problem, _, _, _ = example
    with pytest.raises(bulk.BulkReviewError, match="missing"):
        bulk.capture_snapshot({"problem_uuids": ["00000000-0000-4000-8000-000000000001"]})
    monkeypatch.setattr(bulk, "MAX_PROBLEMS", 0)
    with pytest.raises(bulk.BulkReviewError, match="exceeds"):
        bulk.capture_snapshot({"subject": "Algebra"})


def test_local_command_and_live_check_have_no_apply_mode(example, tmp_path):
    _, _, snapshot, decision = example
    source = tmp_path / "snapshot.json"
    decisions = tmp_path / "decisions.json"
    bulk.write_document(source, snapshot)
    bulk.write_document(decisions, [decision])
    output = tmp_path / "review"
    with connection.execute_wrapper(deny_queries):
        call_command(
            "review_concept_snapshot",
            snapshot=source,
            decisions=decisions,
            output_directory=output,
            stdout=StringIO(),
        )
    assert bulk.read_document(output / "dry-run.json")["ready"]
    assert (output / "decisions-001.json").is_file()
    assert len(list(output.glob("decisions-*.json"))) == 1
    call_command(
        "check_concept_review_packet",
        packet=output / "review-packet.json",
        output=tmp_path / "live.json",
        stdout=StringIO(),
    )
    assert bulk.read_document(tmp_path / "live.json")["ready"]
    from inspinia.pages.management.commands.check_concept_review_packet import Command

    assert (
        "--apply"
        not in Command().create_parser("manage.py", "check_concept_review_packet").format_help().split("options:")[-1]
    )


def test_conflicting_local_command_emits_no_executable_batch(example, tmp_path):
    problem, _, snapshot, decision = example
    bulk.write_document(tmp_path / "snapshot.json", snapshot)
    bulk.write_document(tmp_path / "decisions.json", [decision])
    bulk.write_document(tmp_path / "protected.json", [str(problem.problem_uuid) + "|floor-ceiling"])
    with pytest.raises(CommandError, match="no executable"):
        call_command(
            "review_concept_snapshot",
            snapshot=tmp_path / "snapshot.json",
            decisions=tmp_path / "decisions.json",
            protected_keys=tmp_path / "protected.json",
            output_directory=tmp_path / "review",
            stdout=StringIO(),
        )
    assert not list((tmp_path / "review").glob("decisions-*.json"))
    assert bulk.read_document(tmp_path / "review/dry-run.json")["conflicts"]


def test_admin_download_and_check_are_read_only_and_private(example, client):
    _, _, _, decision = example
    client.force_login(UserFactory(is_superuser=True))
    response = client.get(reverse("pages:concept_review_snapshot_export"), {"subject": "Algebra"})
    assert response.status_code == HTTPStatus.OK
    snapshot = json.loads(gzip.decompress(response.content))
    assert snapshot["counts"]["problems"] == 1
    assert response["Cache-Control"] == "private, no-store"
    packet = bulk.make_packet(snapshot, [decision])
    counts = (ConceptAssignmentReviewBatch.objects.count(), ConceptAssignmentReviewEvent.objects.count())
    response = client.post(
        reverse("pages:concept_review_bulk_check"),
        {"packet": SimpleUploadedFile("packet.json", json.dumps(packet).encode())},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["ready"]
    assert response.json()["assignment_writes"] == 0
    assert counts == (ConceptAssignmentReviewBatch.objects.count(), ConceptAssignmentReviewEvent.objects.count())


def test_admin_and_csrf_boundaries(example, client, settings):
    settings.DEBUG = True
    client.force_login(UserFactory())
    assert (
        client.get(reverse("pages:concept_review_snapshot_export"), {"subject": "Algebra"}).status_code
        == HTTPStatus.FORBIDDEN
    )
    assert client.post(reverse("pages:concept_review_bulk_check")).status_code == HTTPStatus.FORBIDDEN
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(UserFactory(is_superuser=True))
    assert protected.post(reverse("pages:concept_review_bulk_check")).status_code == HTTPStatus.FORBIDDEN
    assert protected.get(reverse("pages:concept_review_bulk_check")).status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_local_and_live_previews_match_existing_native_engine(example):
    from inspinia.pages.concept_assignment_service import preview_review

    _, _, snapshot, decision = example
    packet = bulk.make_packet(snapshot, [decision])
    local = bulk.review_packet(snapshot, packet)
    live = bulk.check_live_packet(packet)
    assert local["sha256"] == live["sha256"]
    batch = local["batches"][0]
    assert preview_review([decision], operation_id=batch["operation_id"])["sha256"] == batch["sha256"]


def test_protected_legacy_identity_cannot_be_retired_implicitly(example):
    problem, _, _, decision = example
    source = load_sources([problem.problem_uuid])[str(problem.problem_uuid)]
    assert REGISTRY.canonical("nt-floor-ceiling") == "floor-ceiling"
    ProblemConceptAssignment.objects.create(
        problem_uuid=problem.problem_uuid,
        concept_id="nt-floor-ceiling",
        disposition="suggested",
        source_fingerprint=source["source_fingerprint"],
        concept_signature=REGISTRY.signature("floor-ceiling"),
    )
    snapshot = bulk.capture_snapshot({"subject": "Algebra"})
    protected = [str(problem.problem_uuid) + "|nt-floor-ceiling"]
    report = bulk.review_packet(snapshot, bulk.make_packet(snapshot, [decision], protected))
    assert not report["ready"]
    assert any(row["key"] == protected[0] for row in report["conflicts"])


def test_more_than_250_decisions_are_bounded_without_splitting_a_problem(example):
    problem, _, _, decision = example
    other = ContestProblemStatement.objects.create(
        contest_name="OTHER",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        topic="A",
    )
    snapshot = bulk.capture_snapshot({"subject": "Algebra"})
    decisions = [
        {**decision, "concept_id": cid, "action": "hold", "subject_context": ""}
        for cid in list(REGISTRY.definitions)[:250]
    ]
    decisions.append(
        {
            "problem_uuid": str(other.problem_uuid),
            "concept_id": "floor-ceiling",
            "action": "hold",
            "rationale": "Retain this as a suggestion pending mathematical review.",
        },
    )
    report = bulk.review_packet(snapshot, bulk.make_packet(snapshot, decisions))
    assert report["ready"]
    assert sorted(len(batch["decisions"]) for batch in report["batches"]) == [1, 250]
    assert all(len({row["problem_uuid"] for row in batch["decisions"]}) == 1 for batch in report["batches"])


def test_malformed_packet_returns_bad_request_instead_of_partial_results(example, client):
    _, _, snapshot, decision = example
    packet = bulk.make_packet(snapshot, [decision])
    packet["baselines"] = []
    packet = bulk.seal({key: value for key, value in packet.items() if key != "sha256"})
    client.force_login(UserFactory(is_superuser=True))
    response = client.post(
        reverse("pages:concept_review_bulk_check"),
        {
            "packet": SimpleUploadedFile("packet.json", json.dumps(packet).encode()),
        },
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_sqlite_rejects_writes_and_remains_usable_after_rollback(example):
    from django.db import OperationalError

    if connection.vendor != "sqlite":
        pytest.skip("SQLite read-only enforcement")
    with pytest.raises(OperationalError, match="readonly"), bulk.read_only_snapshot(), connection.cursor() as cursor:
        cursor.execute("UPDATE pages_problemsolverecord SET topic = topic")
    assert ProblemSolveRecord.objects.count() == 1
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA query_only")
        assert cursor.fetchone()[0] == 0
