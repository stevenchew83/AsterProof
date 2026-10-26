# ruff: noqa: PLR2004
"""Coverage, drill-down, permissions, and bounded rendering for concept analytics."""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.concept_analytics import PAGE_SIZE
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    return client


def statement(number=1, **values):
    return ContestProblemStatement.objects.create(
        **{
            "contest_name": "IMO",
            "contest_year": 2026,
            "topic": "ALG",
            "mohs": 20,
            "problem_number": number,
            "problem_code": f"P{number}",
            "statement_latex": "Find x.",
            **values,
        },
    )


def tag(parent, caption="AM-GM", **values):
    model, field = (
        (StatementTopicTechnique, "statement")
        if isinstance(parent, ContestProblemStatement)
        else (
            ProblemTopicTechnique,
            "record",
        )
    )
    return model.objects.create(
        **{
            field: parent,
            "technique": caption,
            "main_topic": "ALG",
            "domains": ["ALG"],
            **values,
        },
    )


def get(client, **params):
    response = client.get(reverse("pages:topic_tag_dashboard"), params)
    assert response.status_code == 200
    return response


def concepts(response):
    return response.context["concept_page"].paginator.object_list


def test_area_concept_dashboard_counts_identities_and_roles_once(admin_client):
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=50)
    tag(archive)
    primary = statement(linked_problem=archive, mohs=10)
    tag(primary, technique_tags=["AM-GM"], lemma_theorem_tags=["AM-GM"])
    another = statement(3, contest_name="EGMO", mohs=30)
    tag(another)
    tag(another, "CAUCHY-SCHWARZ", lemma_theorem_tags=["CAUCHY-SCHWARZ"])
    response = get(admin_client, subject="Algebra")
    stats = response.context["stats"]
    assert stats["problems"] == 2
    assert stats["mapped"] == 2
    assert stats["covered"] == 2
    assert stats["catalogue"] > stats["covered"]
    assert stats["gaps"] == stats["catalogue"] - 2
    amgm = next(c for c in concepts(response) if c["id"] == "am-gm")
    assert (amgm["problem_count"], amgm["contest_count"], amgm["median_mohs"]) == (2, 2, 20)
    area = next(a for a in response.context["area_rows"] if a["key"] == amgm["area_key"])
    assert area["problem_count"] == 2
    assert area["covered"] == 2
    html = response.content.decode()
    assert "Areas &amp; concepts" in html
    assert 'id="concept-analytics-table"' in html
    assert 'id="concept-more-filters"' in html
    assert "Technique usage volume" not in html


def test_statement_precedence_orphan_archive_and_inactive_entries(admin_client):
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=10)
    tag(archive)
    primary = statement(linked_problem=archive)
    tag(primary, "UNRECOGNIZED", normalization_status="corrupt")
    orphan = ProblemSolveRecord.objects.create(year=2026, contest="BMO", problem="P2", topic="ALG", mohs=0)
    tag(orphan)
    hidden = ProblemSolveRecord.objects.create(year=2026, contest="BMO", problem="P3", topic="ALG", mohs=10)
    tag(hidden)
    statement(3, linked_problem=hidden, is_active=False)
    inactive = ProblemSolveRecord.objects.create(
        year=2026,
        contest="BMO",
        problem="P4",
        topic="ALG",
        mohs=10,
        is_active=False,
    )
    tag(inactive)
    untagged = statement(4)
    response = get(admin_client, subject="Algebra", concept="am-gm")
    assert response.context["stats"]["problems"] == 3
    assert response.context["stats"]["mapped"] == 1
    assert response.context["quality"]["review"] == 1
    assert response.context["quality"]["untagged"] == 1
    assert response.context["selected_concept"]["median_mohs"] == 0
    problems = response.context["problem_page"].object_list
    assert len(problems) == 1
    assert problems[0]["url"] == reverse("solutions:problem_solution_list", args=[orphan.problem_uuid])
    assert any(
        r["url"] == reverse("pages:problem_statement_detail", args=[untagged.statement_uuid])
        for r in response.context["quality"]["rows"]
    )


def test_global_scope_filters_and_clickable_area_links(admin_client):
    tag(statement(1, contest_name="IMO", contest_year=2026))
    tag(statement(2, contest_name="EGMO", contest_year=2025), "VIETA", lemma_theorem_tags=["VIETA"])
    response = get(admin_client, subject="Algebra", contest="EGMO", year="2025")
    assert response.context["stats"]["problems"] == 1
    assert response.context["stats"]["covered"] == 1
    assert response.context["filter_options"]["contests"] == ["EGMO", "IMO"]
    assert [r["label"] for r in response.context["active_filters"]] == ["Subject", "Contest", "Year"]
    area = next(a for a in response.context["area_rows"] if a["problem_count"])
    target = parse_qs(urlsplit(area["url"]).query)
    assert target["contest"] == ["EGMO"]
    filtered = get(admin_client, subject="Algebra", area=area["key"], contest="EGMO", year="2025")
    assert len(filtered.context["area_rows"]) == 1
    assert {c["area_key"] for c in concepts(filtered)} == {area["key"]}
    assert filtered.context["stats"]["covered"] == 1
    assert get(admin_client, year="9999999999999999999").context["filters"]["year"] == ""
    assert get(admin_client, year="²²²²").context["filters"]["year"] == ""


def test_catalogue_gaps_and_explorer_search_preserve_scope_totals(admin_client):
    tag(statement())
    base = get(admin_client, subject="Algebra")
    gaps = get(admin_client, subject="Algebra", state="gaps", q="Jensen")
    assert gaps.context["stats"] == base.context["stats"]
    assert gaps.context["concept_page"].paginator.count == 1
    assert concepts(gaps)[0]["problem_count"] == 0
    assert "No problems" in gaps.content.decode()
    covered = get(admin_client, subject="Algebra", state="covered")
    assert [c["id"] for c in concepts(covered)] == ["am-gm"]
    empty = get(admin_client, q="<script>alert(1)</script>")
    assert empty.context["concept_page"].paginator.count == 0
    assert "No concepts match" in empty.content.decode()
    assert "&lt;script&gt;" in empty.content.decode()
    assert "<script>alert(1)</script>" not in empty.content.decode()


def test_concept_and_problem_pagination_keep_full_totals(admin_client):
    for number in range(1, 122):
        tag(statement(number))
    result = get(admin_client, subject="Algebra", concept="am-gm")
    assert result.context["stats"]["problems"] == 121
    assert result.context["selected_concept"]["problem_count"] == 121
    assert len(result.context["problem_page"].object_list) == PAGE_SIZE
    last = get(admin_client, subject="Algebra", concept="am-gm", problem_page=5)
    assert last.context["problem_page"].end_index() == 121
    assert last.context["problem_page"].paginator.count == 121
    assert len(result.context["concept_page"].object_list) == PAGE_SIZE
    seen = set()
    for number in range(1, result.context["concept_page"].paginator.num_pages + 1):
        page = get(admin_client, subject="Algebra", page=number)
        seen.update(c["id"] for c in page.context["concept_page"])
    assert len(seen) == result.context["stats"]["catalogue"]


def test_sorting_and_missing_difficulty(admin_client):
    tag(statement(1, mohs=None))
    tag(statement(2, mohs=59), "JENSEN", lemma_theorem_tags=["JENSEN"])
    result = get(admin_client, subject="Algebra", sort="mohs")
    assert result.context["concept_page"][0]["id"] == "jensen"
    assert next(c for c in concepts(result) if c["id"] == "am-gm")["median_mohs"] is None
    assert concepts(result)[-1]["median_mohs"] is None
    alphabetical = get(admin_client, sort="name", page="nonsense")
    labels = [c["label"].casefold() for c in concepts(alphabetical)]
    assert labels == sorted(labels)


def test_dashboard_empty_state_and_permissions(client, admin_client):
    response = get(admin_client)
    assert response.context["stats"]["problems"] == 0
    assert response.context["stats"]["catalogue"] == len(CONCEPTS)
    assert response.context["stats"]["covered"] == 0
    assert "Import problems" in response.content.decode()
    client.logout()
    assert client.get(reverse("pages:topic_tag_dashboard")).status_code == 302
    client.force_login(UserFactory(role=User.Role.NORMAL))
    assert client.get(reverse("pages:topic_tag_dashboard")).status_code == 403


def test_dashboard_queries_and_html_stay_bounded(admin_client):
    for number in range(1, 32):
        tag(statement(number, statement_latex="large statement " * 1000, rationale="large rationale " * 1000))
    with CaptureQueriesContext(connection) as queries:
        response = get(admin_client)
    source_queries = [
        q["sql"]
        for q in queries
        if any(
            name in q["sql"]
            for name in (
                'FROM "pages_contestproblemstatement"',
                'FROM "pages_problemsolverecord"',
                'FROM "pages_statementtopictechnique"',
                'FROM "pages_problemtopictechnique"',
            )
        )
    ]
    assert len(source_queries) <= 12
    assert all(
        '"statement_latex"' not in q and '"rationale"' not in q and '"core_ideas"' not in q for q in source_queries
    )
    assert len(response.content) < 150_000
    assert len(response.context["concept_page"].object_list) == PAGE_SIZE


def test_cross_subject_concepts_follow_their_catalogue_subject(admin_client):
    tag(statement(1, topic="GEO"))
    statement(2, topic="GEO")
    response = get(admin_client, subject="Algebra", state="covered")
    assert response.context["stats"]["problems"] == 1
    assert response.context["stats"]["covered"] == 1
    assert concepts(response)[0]["id"] == "am-gm"


def test_all_mapping_review_problems_are_reachable(admin_client):
    for number in range(1, 28):
        statement(number)
    first = get(admin_client)
    assert first.context["quality"]["total"] == 27
    assert len(first.context["quality"]["rows"]) == PAGE_SIZE
    second = get(admin_client, review_page=2)
    assert len(second.context["quality"]["rows"]) == 2
    assert second.context["quality"]["expanded"] is True
    assert second.context["quality"]["page"].end_index() == 27
    assert not ({r["url"] for r in first.context["quality"]["rows"]}
                & {r["url"] for r in second.context["quality"]["rows"]})


def test_concept_detail_preserves_explorer_page(admin_client):
    response = get(admin_client, page=3, sort="name")
    concept = response.context["concept_page"][0]
    params = {k: v[0] for k, v in parse_qs(urlsplit(concept["url"]).query).items()}
    assert params["page"] == "3"
    detail = get(admin_client, **params)
    assert detail.context["selected_concept"]["id"] == concept["id"]
    assert parse_qs(urlsplit(detail.context["close_detail_url"]).query)["page"] == ["3"]
