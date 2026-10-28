# ruff: noqa: PLR2004, SLF001
"""Catalogue navigation is independent of problems and preserves reviewed identities."""

from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages import statement_concept_coverage as coverage
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptAlias
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.concept_assignment_registry import REGISTRY
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


def get(client, **params):
    response = client.get(reverse("pages:topic_tag_dashboard"), params)
    assert response.status_code == 200
    return response


def params_for(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_frozen_catalogue_preserves_every_id_and_reviewed_redirect():
    assert set(CatalogueConcept.objects.values_list("pk", flat=True)) == set(CONCEPTS) | set(REGISTRY.redirects)
    assert CatalogueConcept.objects.filter(redirect__isnull=True).count() == len(REGISTRY.definitions)
    assert CatalogueSubject.objects.count() == 4
    for legacy in REGISTRY.redirects:
        assert CatalogueConcept.objects.get(pk=legacy).redirect_id == REGISTRY.canonical(legacy)
    assert CatalogueConceptAlias.objects.filter(resolution="CONTEXTUAL").exists()
    assert CatalogueConceptAlias.objects.filter(rules__id="A01").exists()
    assert CatalogueConceptAlias.objects.filter(rules__id="A07", concept__isnull=True).exists()


def test_root_subject_area_concept_and_up_navigation(admin_client):
    root = get(admin_client)
    assert root.context["level"] == "subjects"
    assert len(root.context["rows"]) == 4
    subject = get(admin_client, **params_for(root.context["rows"][0]["url"]))
    assert subject.context["level"] == "areas"
    area = get(admin_client, **{**params_for(subject.context["rows"][0]["url"]), "tab": "structure"})
    assert area.context["level"] == "concepts"
    detail = get(admin_client, **params_for(area.context["rows"][0]["url"]))
    assert detail.context["selected_concept"]
    assert detail.context["breadcrumbs"][0]["label"] == "All subjects"
    assert get(admin_client, **params_for(detail.context["up_url"])).context["heading"] != detail.context["heading"]
    html = detail.content.decode()
    assert "Names, tags &amp; roles" in html
    assert "Problems</a>" in html
    assert "Up one level" in html


def test_legacy_id_bookmarks_resolve_without_rewriting_id_records(admin_client):
    old = next(iter(REGISTRY.redirects))
    response = get(admin_client, concept=old)
    assert response.context["selected_concept"].pk == REGISTRY.canonical(old)
    assert CatalogueConcept.objects.filter(pk=old).exists()


def test_alias_search_and_role_filters_are_scoped_and_escaped(admin_client):
    response = get(admin_client, subject="Algebra", q="Vieta's formulas")
    assert [r["id"] for r in response.context["rows"]] == ["vieta"]
    roles = get(admin_client, subject="Geometry", role="object")
    assert roles.context["rows"]
    empty = get(admin_client, q="<script>bad</script>")
    assert "&lt;script&gt;" in empty.content.decode()
    assert "<script>bad</script>" not in empty.content.decode()
    assert empty.context["page"].paginator.count == 0


def test_catalogue_get_never_reads_problem_or_completion_sources(admin_client):
    with patch(
        "inspinia.pages.catalogue_sources.iter_catalogue_sources",
        side_effect=AssertionError("GET rebuilt sources"),
    ):
        for params in (
            {}, {"subject": "Algebra"}, {"area": "Algebra:inequalities", "tab": "structure"}, {"concept": "am-gm"},
        ):
            with CaptureQueriesContext(connection) as captured:
                response = get(admin_client, **params)
            sql = "\n".join(q["sql"] for q in captured)
            assert all(
                f'FROM "{name}"' not in sql
                for name in (
                    "pages_contestproblemstatement",
                    "pages_problemsolverecord",
                    "pages_statementtopictechnique",
                    "pages_problemtopictechnique",
                    "pages_userproblemcompletion",
                    "pages_catalogueproblem",
                )
            )
            assert len(response.content) < 150_000
            assert len(captured) < 35


def test_examples_are_explicit_and_missing_snapshot_never_rebuilds(admin_client):
    row = ContestProblemStatement.objects.create(
        contest_name="IMO",
        contest_year=2026,
        problem_code="P1",
        problem_number=1,
        topic="ALG",
    )
    StatementTopicTechnique.objects.create(
        statement=row,
        technique="AM-GM",
        main_topic="ALG",
        lemma_theorem_tags=["AM-GM"],
    )
    missing = get(admin_client, concept="am-gm", tab="problems")
    assert missing.context["examples_unavailable"]
    assert "being updated" in missing.content.decode()
    rebuild_library_snapshot()
    ready = get(admin_client, concept="am-gm", tab="problems")
    assert ready.context["examples"].paginator.count == 1
    assert ready.context["examples"][0].statement_id == row.pk
    assert ready.context["examples"][0].url == reverse("pages:problem_statement_detail", args=[row.statement_uuid])


def test_catalogue_permissions_are_unchanged(client):
    assert client.get(reverse("pages:topic_tag_dashboard")).status_code == 302
    client.force_login(UserFactory(role=User.Role.NORMAL))
    assert client.get(reverse("pages:topic_tag_dashboard")).status_code == 403
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assert get(client).context["rows"]


def test_unknown_concept_is_404_and_cycles_are_bounded(admin_client):
    assert admin_client.get(reverse("pages:topic_tag_dashboard"), {"concept": "missing"}).status_code == 404
    CatalogueConcept.objects.filter(pk="am-gm").update(redirect_id="vieta")
    CatalogueConcept.objects.filter(pk="vieta").update(redirect_id="am-gm")
    assert admin_client.get(reverse("pages:topic_tag_dashboard"), {"concept": "am-gm"}).status_code == 404


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


def test_own_statement_tags_do_not_fetch_shadowed_archive_tags():
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=20)
    tag(archive)
    own = statement(linked_problem=archive)
    tag(own, "INVALID", normalization_status="corrupt")
    with CaptureQueriesContext(connection) as queries:
        result = coverage.statement_coverage_payloads([own], resolver=coverage.TagCoverageResolver())
    assert result[own.pk]["concept_coverage_status"] == "No valid tags"
    assert result[own.pk]["concept_coverage"] == []
    assert not any('FROM "pages_problemtopictechnique"' in q["sql"] for q in queries)


def test_request_resolution_cache_keeps_subject_context_and_source_edits_distinct():
    source = {
        "technique": "AM-GM", "canonical_subtopic": "", "main_topic": "", "domains": [],
        "normalization_status": "", "object_tags": [], "technique_tags": ["AM-GM"],
        "lemma_theorem_tags": [], "proof_roles": [],
    }
    resolver = coverage.TagCoverageResolver()
    for topic in ("ALG", "GEO", "NT", "COMB"):
        expected = coverage._coverage([source], topic=topic, active=True)
        assert coverage._coverage([source], topic=topic, active=True, resolver=resolver) == expected
    source["technique"] = "CAUCHY-SCHWARZ"
    source["technique_tags"] = ["CAUCHY-SCHWARZ"]
    actual = coverage._coverage([source], topic="ALG", active=True, resolver=resolver)
    assert {c["id"] for c in actual["concept_coverage"]} == {"cauchy-schwarz"}
    assert actual == coverage._coverage([source], topic="ALG", active=True)
