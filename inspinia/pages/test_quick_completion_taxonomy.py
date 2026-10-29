"""Quick completion taxonomy uses the same bounded, read-only projection as the library."""

import re
from html import unescape
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.concept_assignment_service import apply_refresh
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ConceptAssignmentState
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressFact
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
PREVIEW_CONCEPT_COUNT = 2


def make_statement(number):
    problem = ProblemSolveRecord.objects.create(
        contest="TAXONOMY TEST", year=2026, problem=f"P{number}", topic="ALG", mohs=15,
    )
    return ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=problem.contest, contest_year=2026,
        problem_code=problem.problem, problem_number=number,
        statement_latex=f"Prove the inequality for positive integers x and {number}.",
    )


def add_tag(parent, caption, **fields):
    model, relation = (
        (StatementTopicTechnique, "statement")
        if isinstance(parent, ContestProblemStatement)
        else (ProblemTopicTechnique, "record")
    )
    return model.objects.create(
        **{relation: parent}, technique=caption, main_topic="ALG", domains=["ALG"], **fields,
    )


def quick_rows(client, **params):
    response = client.get(reverse("pages:completion_quick_update"), params)
    assert response.status_code == HTTPStatus.OK
    return response, {row["statement_uuid"]: row for row in response.context["completion_quick_update_rows"]}


def test_quick_taxonomy_matches_library_and_respects_statement_source_precedence(client):
    client.force_login(UserFactory())
    own, fallback, suppressed = [make_statement(number) for number in range(1, 4)]
    add_tag(own, "AM-GM", technique_tags=["AM-GM"], lemma_theorem_tags=["AM-GM"])
    add_tag(own.linked_problem, "VIETA")
    add_tag(fallback.linked_problem, "VIETA", lemma_theorem_tags=["VIETA"])
    add_tag(suppressed, "AM-GM", normalization_status="invalid")
    add_tag(suppressed.linked_problem, "VIETA")

    _, rows = quick_rows(client)
    own_row = rows[str(own.statement_uuid)]
    assert [concept["id"] for concept in own_row["concept_coverage"]] == ["am-gm"]
    assert own_row["concept_coverage"][0]["roles"] == ["lemma", "method", "technique"]
    assert own_row["concept_areas"] == ["Inequalities and optimization"]
    assert [concept["id"] for concept in rows[str(fallback.statement_uuid)]["concept_coverage"]] == ["vieta"]
    assert rows[str(suppressed.statement_uuid)]["concept_coverage"] == []
    assert rows[str(suppressed.statement_uuid)]["concept_areas"] == []
    assert rows[str(suppressed.statement_uuid)]["concept_coverage_status"] == "No valid tags"

    library = client.get(reverse("pages:problem_statement_list"))
    library_rows = {row["statement_uuid"]: row for row in library.context["statement_datatable_rows"]}
    for statement in (own, fallback, suppressed):
        key = str(statement.statement_uuid)
        assert rows[key]["concept_coverage"] == library_rows[key]["concept_coverage"]
        assert rows[key]["concept_areas"] == library_rows[key]["concept_areas"]
    assert not TechniqueProgressFact.objects.exists()
    assert not ProblemConceptAssignment.objects.exists()


@pytest.mark.parametrize("query", ["Polynomials and algebraic manipulation", "COMPLETING SQUARE"])
def test_quick_taxonomy_searches_canonical_area_and_concept_before_recent_cap(client, query):
    client.force_login(UserFactory())
    target = make_statement(1)
    add_tag(target, "COMPLETE SQUARE", technique_tags=["COMPLETING SQUARE"])
    newer = make_statement(2)
    with patch("inspinia.pages.views.COMPLETION_QUICK_UPDATE_RECENT_LIMIT", 1):
        _, recent = quick_rows(client)
        assert list(recent) == [str(newer.statement_uuid)]
        _, matching = quick_rows(client, q=query)
    assert list(matching) == [str(target.statement_uuid)]
    assert not TechniqueProgressFact.objects.exists()


def test_quick_taxonomy_distinguishes_untagged_and_needs_review(client):
    client.force_login(UserFactory())
    untagged, unresolved = make_statement(1), make_statement(2)
    add_tag(unresolved, "UNRECOGNIZED CAPTION")
    _, rows = quick_rows(client)
    assert rows[str(untagged.statement_uuid)]["concept_coverage_status"] == "Untagged"
    assert rows[str(unresolved.statement_uuid)]["concept_coverage_status"] == "Needs review"
    assert rows[str(unresolved.statement_uuid)]["concept_coverage"] == []


def test_quick_taxonomy_active_projection_shows_only_accepted_concepts(client, settings):
    client.force_login(UserFactory())
    accepted = make_statement(1)
    add_tag(accepted, "AM-GM")
    apply_refresh(audit_sources(load_sources([accepted.problem_uuid])))
    pending = make_statement(2)
    add_tag(pending, "VIETA")
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    ConceptAssignmentState.objects.update_or_create(
        singleton_key=1, defaults={"enabled": True, "initial_seed_complete": True},
    )
    before = list(ProblemConceptAssignment.objects.values())

    _, rows = quick_rows(client)

    assert [concept["id"] for concept in rows[str(accepted.statement_uuid)]["concept_coverage"]] == ["am-gm"]
    assert rows[str(pending.statement_uuid)]["concept_coverage"] == []
    assert rows[str(pending.statement_uuid)]["concept_areas"] == []
    assert rows[str(pending.statement_uuid)]["concept_coverage_status"] == "Needs review"
    assert list(ProblemConceptAssignment.objects.values()) == before
    _, matching = quick_rows(client, q="Inequalities and optimization")
    assert list(matching) == [str(accepted.statement_uuid)]


def test_quick_taxonomy_queries_do_not_grow_per_visible_statement(client):
    client.force_login(UserFactory())
    add_tag(make_statement(1), "AM-GM")
    with CaptureQueriesContext(connection) as small:
        quick_rows(client)
    for number in range(2, 9):
        add_tag(make_statement(number), "AM-GM")
    with CaptureQueriesContext(connection) as large:
        quick_rows(client)
    assert len(large) <= len(small) + 1


def test_quick_taxonomy_preview_is_compact_and_full_values_remain_searchable(client):
    client.force_login(UserFactory())
    statement = make_statement(1)
    add_tag(statement, "AM-GM")
    add_tag(statement, "VIETA", lemma_theorem_tags=["VIETA"])
    add_tag(statement, "FACTORIZATION")
    add_tag(statement, "COMPLETING SQUARE", technique_tags=["COMPLETING SQUARE"])
    response, rows = quick_rows(client)
    row = rows[str(statement.statement_uuid)]
    assert {concept["id"] for concept in row["concept_coverage"]} == {
        "am-gm", "vieta", "factorization", "completing-square",
    }
    assert row["area_overflow_count"] == 1
    assert row["concept_overflow_count"] == PREVIEW_CONCEPT_COUNT
    html = response.content.decode()
    header = html[html.index("<thead>"):html.index("</thead>")]
    assert re.findall(r"<th [^>]*>(.*?)</th>", header) == [
        "Problem", "Day", "Topic", "Area", "Concepts", "MOHS", "Progress", "Quick action", "More",
    ]
    concept_cell = re.search(r'<td class="quick-completion-concept-cell"(.*?)</td>', html, re.DOTALL).group(1)
    visible, details = concept_cell.split('<div class="d-none js-quick-completion-row-details">')
    assert visible.count('class="badge bg-light text-dark border"') == PREVIEW_CONCEPT_COUNT
    assert "+2 more" in visible
    for concept in row["concept_coverage"]:
        assert concept["display"] in unescape(details)
        assert concept["display"] in unescape(visible)
    area_cell = re.search(r'<td class="quick-completion-area-cell"[^>]*>', html).group(0)
    assert all(area in unescape(area_cell) for area in row["concept_areas"])
    assert "VIETA" in details
