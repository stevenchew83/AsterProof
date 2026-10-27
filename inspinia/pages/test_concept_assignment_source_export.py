"""The prerequisite audit export reads existing source tables only."""

import uuid
from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.pages.concept_assignment_source_export import assignment_source_export
from inspinia.pages.concept_assignment_source_export import read_assignment_sources
from inspinia.pages.concept_assignment_source_export import source_digest
from inspinia.pages.concept_assignment_source_export import source_fingerprint
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementTopicTechnique
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def source_statement():
    statement = ContestProblemStatement.objects.create(
        contest_name="SOURCE AUDIT",
        contest_year=2026,
        problem_number=1,
        problem_code="A1",
        topic="A",
        statement_latex="Prove the stated inequality.",
        is_active=False,
    )
    StatementTopicTechnique.objects.create(
        statement=statement,
        technique="REJECTED CAPTION",
        main_topic="ALG",
        domains=["ALG"],
        normalization_status="invalid",
        object_tags=["FLOOR FUNCTION"],
    )
    return statement


def test_snapshot_retains_inactive_suppressed_sources_and_never_reads_review_tables(client, django_assert_num_queries):
    statement = source_statement()
    with django_assert_num_queries(3):
        data = read_assignment_sources([statement.problem_uuid])
    source = data[str(statement.problem_uuid)]
    assert not source["active"]
    assert source["statement_uuid"] == str(statement.statement_uuid)
    assert source["tags"][0]["normalization_status"] == "invalid"
    assert source["tags"][0]["object_tags"] == ["FLOOR FUNCTION"]
    assert source["source_fingerprint"] == source_fingerprint(source)
    client.force_login(UserFactory(is_superuser=True))
    response = client.get(
        reverse("pages:concept_assignment_source_export"),
        {"problem_uuid": str(statement.problem_uuid)},
    )
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    checksum = payload.pop("sha256")
    assert checksum == source_digest(payload)
    assert payload["source_writes"] == 0
    assert response["Cache-Control"] == "private, no-store"
    assert "default" in assignment_source_export._non_atomic_requests  # noqa: SLF001 - Django view marker


def test_snapshot_requires_the_existing_admin_role(client, settings):
    settings.DEBUG = True
    client.force_login(UserFactory())
    response = client.get(reverse("pages:concept_assignment_source_export"), {"problem_uuid": str(uuid.uuid4())})
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("values", [[], ["invalid"], [str(uuid.uuid4())] * 51])
def test_snapshot_bounds_and_uuid_validation(client, values):
    client.force_login(UserFactory(is_superuser=True))
    response = client.get(reverse("pages:concept_assignment_source_export"), {"problem_uuid": values})
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_snapshot_reports_missing_identity(client):
    key = str(uuid.uuid4())
    client.force_login(UserFactory(is_superuser=True))
    response = client.get(reverse("pages:concept_assignment_source_export"), {"problem_uuid": key})
    assert response.json()["missing_problem_uuids"] == [key]


def test_fingerprint_matches_trace_normalization_and_array_order():
    from inspinia.pages.concept_assignment_trace import source_fingerprint as trace_fingerprint

    source = {
        "problem_uuid": str(uuid.uuid4()),
        "subject": "Algebra",
        "active": True,
        "source_owner_active": False,
        "effective_source": "statement",
        "tags": [{"technique": "CAPTION", "domains": [], "object_tags": ["B", "A"]}],
    }
    assert source_fingerprint(source) == trace_fingerprint(source)
    initial = source_fingerprint(source)
    source["tags"][0]["object_tags"].reverse()
    assert source_fingerprint(source) == initial
    source["source_owner_active"] = True
    assert source_fingerprint(source) != initial


def test_source_export_still_works_without_review_schema(client, monkeypatch):
    from inspinia.pages import concept_assignment_source_export as module

    statement = source_statement()
    original = module.connection.introspection.table_names
    monkeypatch.setattr(
        module.connection.introspection,
        "table_names",
        lambda: [
            name
            for name in original()
            if name
            not in {
                "pages_problemconceptassignment",
                "pages_conceptassignmentreviewbatch",
                "pages_conceptassignmentreviewevent",
                "pages_conceptassignmentstate",
            }
        ],
    )
    client.force_login(UserFactory(is_superuser=True))
    response = client.get(
        reverse("pages:concept_assignment_source_export"), {"problem_uuid": str(statement.problem_uuid)},
    )
    assert response.json()["review_storage"] == {"state": "absent", "assignment_count": 0}
