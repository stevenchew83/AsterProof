# ruff: noqa: PLR2004
"""Single-row completion inventory and bounded canonical area metadata."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.completion_record_areas import completion_record_area_metadata
from inspinia.pages.concept_assignment_service import apply_refresh
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ConceptAssignmentState
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client):
    user = UserFactory(role=User.Role.ADMIN)
    client.force_login(user)
    return user, client


def archive(number=1):
    return ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem=f"P{number}", topic="ALG", mohs=20)


def statement(*, linked=None, **fields):
    return ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        statement_latex="Synthetic statement",
        linked_problem=linked,
        **fields,
    )


def tag(parent, caption="AM-GM", **fields):
    model, key = (
        (StatementTopicTechnique, "statement")
        if isinstance(parent, ContestProblemStatement)
        else (
            ProblemTopicTechnique,
            "record",
        )
    )
    return model.objects.create(
        **{key: parent, "technique": caption, "main_topic": "ALG", "domains": ["ALG"], **fields},
    )


def records(client, **params):
    response = client.get(reverse("pages:completion_record_list"), params)
    assert response.status_code == 200
    return response


def test_statement_only_completion_uses_own_topic_difficulty_area_and_link(admin):
    user, client = admin
    source = statement(topic="ALG", mohs=0)
    tag(source)
    UserProblemCompletion.objects.create(user=user, statement=source, status="solved")
    response = records(client)
    row = response.context["completion_record_rows"][0]
    assert row["topic"] == "Algebra"
    assert row["mohs"] == 0
    assert row["areas"] == ["Inequalities and optimization"]
    assert row["statement_url"] == reverse("pages:problem_statement_detail", args=[source.statement_uuid])
    assert row["area_mapping_status"] == "Mapped"
    assert len(records(client, q="Algebra").context["completion_record_rows"]) == 1


def test_orphan_archive_exposes_every_area_once(admin):
    user, client = admin
    source = archive()
    tag(source, lemma_theorem_tags=["AM-GM"])
    tag(source, "CAUCHY-SCHWARZ")
    tag(source, "VIETA", lemma_theorem_tags=["VIETA"])
    UserProblemCompletion.objects.create(user=user, problem=source)
    row = records(client).context["completion_record_rows"][0]
    assert row["areas"] == ["Inequalities and optimization", "Polynomials and algebraic manipulation"]


@pytest.mark.parametrize("suppressed", [False, True])
def test_legacy_completion_area_follows_statement_tag_precedence(admin, suppressed):
    user, client = admin
    problem = archive()
    tag(problem, "VIETA")
    source = statement(linked=problem, topic="ALG")
    tag(source, normalization_status="corrupt" if suppressed else "")
    UserProblemCompletion.objects.create(user=user, problem=problem)
    row = records(client).context["completion_record_rows"][0]
    assert row["areas"] == ([] if suppressed else ["Inequalities and optimization"])
    assert row["area_mapping_status"] == ("No valid tags" if suppressed else "Mapped")


def test_linked_statement_without_own_tags_falls_back_to_archive(admin):
    user, client = admin
    problem = archive()
    tag(problem)
    source = statement(linked=problem, topic="", mohs=None)
    UserProblemCompletion.objects.create(user=user, statement=source)
    row = records(client).context["completion_record_rows"][0]
    assert row["areas"] == ["Inequalities and optimization"]
    assert row["topic"] == "Algebra"
    assert row["mohs"] == 20


def test_inactive_statement_does_not_resurrect_archive_area(admin):
    user, client = admin
    problem = archive()
    tag(problem)
    statement(linked=problem, is_active=False)
    UserProblemCompletion.objects.create(user=user, problem=problem)
    row = records(client).context["completion_record_rows"][0]
    assert row["areas"] == []
    assert row["area_mapping_status"] == "Inactive"


def test_area_reads_are_bounded_to_the_loaded_window_and_exclude_bodies(admin):
    user, client = admin
    for number in range(105):
        problem = archive(number)
        tag(problem)
        UserProblemCompletion.objects.create(user=user, problem=problem)
    response = records(client)
    assert len(response.context["completion_record_rows"]) == 100
    visible_ids = [r["completion_id"] for r in response.context["completion_record_rows"]]
    completions = list(
        UserProblemCompletion.objects.filter(pk__in=visible_ids).select_related(
            "problem",
            "statement",
            "statement__linked_problem",
        ),
    )
    with CaptureQueriesContext(connection) as queries:
        payloads = completion_record_area_metadata(completions)
    assert len(payloads) == 100
    tag_reads = [q["sql"] for q in queries if 'FROM "pages_problemtopictechnique"' in q["sql"]]
    assert len(tag_reads) == 1
    assert " IN (" in tag_reads[0]
    area_statement_reads = [q["sql"] for q in queries if q["sql"].startswith('SELECT "pages_contestproblemstatement"')]
    assert len(area_statement_reads) == 1
    assert all('"statement_latex"' not in sql and '"rationale"' not in sql for sql in area_statement_reads)


def test_table_places_area_after_topic_and_keeps_full_details(admin):
    user, client = admin
    UserProblemCompletion.objects.create(user=user, problem=archive())
    html = records(client).content.decode()
    assert html.index('key: "topic"') < html.index('key: "area"') < html.index('key: "mohs"')
    assert "completion-record-ellipsis" in html
    assert "completion-record-problem-meta" not in html
    assert "completion-record-detail-email" in html
    assert "escapeHtml(row.user_email)" in html
    assert "completion-record-detail-areas" in html
    assert "including all mapped areas" in html
    assert 'search: "Filter loaded records:"' in html


@pytest.mark.parametrize("origin", ["statement", "linked_archive", "orphan_archive"])
def test_enabled_projection_uses_only_accepted_areas_for_every_completion_origin(admin, settings, origin):
    user, client = admin
    problem = archive()
    source = statement(linked=problem, topic="ALG") if origin != "orphan_archive" else problem
    tag(source, object_tags=["Farey fraction"], domains=["ALG", "NT"])
    completion = UserProblemCompletion.objects.create(
        user=user,
        **({"statement": source} if origin == "statement" else {"problem": problem}),
    )
    apply_refresh(audit_sources(load_sources([problem.problem_uuid])))
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    ConceptAssignmentState.objects.update_or_create(
        singleton_key=1, defaults={"enabled": True, "initial_seed_complete": True},
    )
    row = records(client).context["completion_record_rows"][0]
    assert row["completion_id"] == completion.pk
    assert row["areas"] == ["Inequalities and optimization"]
    assert row["area_mapping_status"] == "Needs review"
