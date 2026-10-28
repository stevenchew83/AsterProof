# ruff: noqa: PLR2004
"""Area practice lists preserve scope, source precedence and bounded page reads."""

from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.test_concept_progress import statement
from inspinia.pages.test_concept_progress import tag
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
CIRCLES = "Geometry:circles"
POWER = "geo-power-of-a-point"
ARCS = "geo-arc-midpoints"


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    return client


def circle_problem(number=1, *, mohs=20, concepts=(POWER, ARCS), **values):
    row = statement(number, topic="GEO", mohs=mohs, **values)
    for concept in concepts:
        tag(row, concept)
    return row


def get(client, **params):
    response = client.get(reverse("pages:topic_tag_dashboard"), {"area": CIRCLES, **params})
    assert response.status_code == 200
    return response


def test_area_opens_on_unique_problems_with_four_columns_and_structure_link(admin_client):
    row = circle_problem()
    tag(statement(2), "am-gm")
    rebuild_library_snapshot()
    response = get(admin_client, subject="geometry")
    assert response.context["tab"] == "problems"
    assert response.context["selected_subject"].name == "Geometry"
    assert response.context["examples"].paginator.count == 1
    problem = response.context["examples"][0]
    assert problem.statement_id == row.pk
    assert {c["id"] for c in problem.concepts} == {POWER, ARCS}
    assert problem.source_tags == sorted(row.statement_topic_techniques.values_list("technique", flat=True))
    assert problem.url == reverse("pages:problem_statement_detail", args=[row.statement_uuid])
    html = response.content.decode()
    for label in ("Problem</th>", "Concepts</th>", "Original tags</th>", "MOHS", "Concept structure"):
        assert label in html
    structure = admin_client.get(response.context["structure_url"])
    assert structure.context["tab"] == "structure"
    assert structure.context["page"].paginator.count == 45
    assert "Classification" in structure.content.decode()


def test_area_and_concept_memberships_filter_together_and_chips_open_problems(admin_client):
    circle_problem(1, concepts=(POWER,))
    arc = circle_problem(2, concepts=(ARCS,))
    tag(statement(3), "am-gm")
    rebuild_library_snapshot()
    response = get(admin_client, concept=ARCS, tab="problems")
    assert [p.statement_id for p in response.context["examples"]] == [arc.pk]
    chip = response.context["examples"][0].concepts[0]
    params = parse_qs(urlsplit(chip["url"]).query)
    assert params["area"] == [CIRCLES]
    assert params["concept"] == [ARCS]
    assert params["tab"] == ["problems"]
    choices = response.context["problem_concept_choices"]
    assert len(choices) == 45
    assert POWER in {c.pk for c in choices}
    assert "am-gm" not in {c.pk for c in choices}


def test_searches_all_pages_by_problem_concept_alias_source_tag_and_uuid(admin_client):
    for number in range(1, 28):
        circle_problem(number, concepts=(POWER,))
    last = circle_problem(28, concepts=(ARCS,))
    StatementTopicTechnique.objects.create(statement=last, technique="UNIQUE-SOURCE-CAPTION")
    rebuild_library_snapshot()
    first = get(admin_client, sort="problem")
    assert first.context["examples"].paginator.count == 28
    assert len(first.context["examples"]) == 25
    for query in ("IMO 2026 P28", "Arc-midpoint", ARCS, "UNIQUE-SOURCE-CAPTION", str(last.problem_uuid)):
        response = get(admin_client, q=query)
        assert [p.statement_id for p in response.context["examples"]] == [last.pk]
    alias = get(admin_client, q="arc midpoints")
    assert [p.statement_id for p in alias.context["examples"]] == [last.pk]


def test_mohs_sort_nulls_last_filters_and_urls_preserve_scope(admin_client):
    for number, difficulty in enumerate((None, 35, 0, 20), 1):
        circle_problem(number, mohs=difficulty)
    rebuild_library_snapshot()
    assert [p.mohs for p in get(admin_client).context["examples"]] == [0, 20, 35, None]
    high = get(admin_client, sort="mohs_desc")
    assert [p.mohs for p in high.context["examples"]] == [35, 20, 0, None]
    response = get(admin_client, q="IMO", concept=POWER, tab="problems", mohs_min="0", mohs_max="20")
    assert [p.mohs for p in response.context["examples"]] == [0, 20]
    for key in ("pagination_url", "mohs_sort_url"):
        params = parse_qs(urlsplit(response.context[key]).query)
        assert params["area"] == [CIRCLES]
        assert params["concept"] == [POWER]
        assert params["q"] == ["IMO"]
        assert params["mohs_min"] == ["0"]
        assert params["mohs_max"] == ["20"]
        assert params["tab"] == ["problems"]


def test_pagination_is_bounded_and_does_not_recompute_assignments(admin_client):
    for number in range(1, 54):
        circle_problem(number)
    rebuild_library_snapshot()
    with (
        patch("inspinia.pages.catalogue_sources.iter_catalogue_sources", side_effect=AssertionError("Rebuild")),
        patch("inspinia.pages.concept_assignment_trace.load_sources", side_effect=AssertionError("Source scan")),
        CaptureQueriesContext(connection) as queries,
    ):
        response = get(admin_client)
    assert response.context["examples"].paginator.count == 53
    assert len(response.context["examples"]) == 25
    assert len(queries) < 40
    source_reads = [q["sql"] for q in queries if 'FROM "pages_statementtopictechnique"' in q["sql"]]
    assert len(source_reads) == 1
    assert '"statement_id" IN (' in source_reads[0]
    assert not any('FROM "pages_contestproblemstatement"' in q["sql"] for q in queries)
    pages = [get(admin_client, page=number).context["examples"] for number in (1, 2, 3)]
    ids = [p.problem_uuid for page in pages for p in page]
    assert len(ids) == len(set(ids)) == 53
    assert len(pages[-1]) == 3


def test_statement_tags_override_linked_tags_for_display_and_search(admin_client):
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="GEO", mohs=20)
    tag(archive, ARCS)
    tag(archive, "am-gm")
    own = circle_problem(1, concepts=(POWER,), linked_problem=archive)
    StatementTopicTechnique.objects.create(
        statement=own, technique="SUPPRESSED-OWN-TAG", normalization_status="corrupt",
    )
    fallback = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P2", topic="GEO", mohs=25)
    tag(fallback, ARCS)
    inherited = statement(2, topic="GEO", linked_problem=fallback)
    archive_only = ProblemSolveRecord.objects.create(year=2025, contest="IMO", problem="P3", topic="GEO", mohs=30)
    tag(archive_only, POWER)
    rebuild_library_snapshot()
    response = get(admin_client)
    by_uuid = {p.problem_uuid: p for p in response.context["examples"]}
    assert by_uuid[own.problem_uuid].source_tags == ["POWER OF A POINT", "SUPPRESSED-OWN-TAG"]
    assert by_uuid[inherited.problem_uuid].source_tags == ["ARC-MIDPOINT GEOMETRY"]
    assert by_uuid[archive_only.problem_uuid].url == reverse(
        "solutions:problem_solution_list", args=[archive_only.problem_uuid],
    )
    assert get(admin_client, q="AM-GM").context["examples"].paginator.count == 0
    assert get(admin_client, q="SUPPRESSED-OWN-TAG").context["examples"].paginator.count == 1


def test_missing_and_stale_snapshots_never_rebuild_during_get(admin_client):
    row = circle_problem()
    with patch("inspinia.pages.catalogue_sources.iter_catalogue_sources", side_effect=AssertionError("Rebuild")):
        assert get(admin_client).context["examples_unavailable"]
    rebuild_library_snapshot()
    row.mohs = 30
    row.save(update_fields=["mohs"])
    with patch("inspinia.pages.catalogue_sources.iter_catalogue_sources", side_effect=AssertionError("Rebuild")):
        response = get(admin_client)
    assert response.context["examples_unavailable"]
    assert "being updated" in response.content.decode()
    assert admin_client.get(response.context["structure_url"]).context["rows"]


def test_empty_invalid_and_escaped_filters_are_safe(admin_client):
    circle_problem()
    rebuild_library_snapshot()
    response = get(admin_client, mohs_min="-1", mohs_max="9" * 200, sort="bad-column", page="bad-page")
    assert response.context["examples"].paginator.count == 1
    assert response.context["problem_filters"] == {"q": "", "mohs_min": "", "mohs_max": "", "sort": "mohs"}
    empty = get(admin_client, q="<script>alert(1)</script>")
    assert empty.context["examples"].paginator.count == 0
    assert "No problems match" in empty.content.decode()
    assert "&lt;script&gt;" in empty.content.decode()
    assert "<script>alert(1)</script>" not in empty.content.decode()
    assert get(admin_client, mohs_min="30", mohs_max="10").context["examples"].paginator.count == 0
