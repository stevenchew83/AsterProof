"""Canonical training concepts retain roles, profiles, and exact practice unions."""
# ruff: noqa: PLR2004 -- fixed reviewed catalog sizes and fixture scores are regression contracts.

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.core.cache import cache
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_benchmarking.dashboard import build_technique_benchmark_dashboard_context
from inspinia.pages.technique_concepts import concept_for
from inspinia.pages.technique_progress import _enrich_gap_rows_with_benchmarks
from inspinia.pages.technique_progress import _scoped_subtopic_gap_rows
from inspinia.pages.technique_progress import _score_gap_rows
from inspinia.pages.technique_progress import technique_progress_gap_rows_for_benchmark_export
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def statement(number, *, family="Inequalities and optimization", methods=(), lemmas=()):
    row = ContestProblemStatement.objects.create(
        contest_name="CONCEPT TEST",
        contest_year=2026,
        problem_number=number,
        problem_code=f"A{number}",
        topic="A",
        statement_latex="Find x.",
        mohs=10,
    )
    StatementTopicTechnique.objects.create(
        statement=row,
        technique=f"SOURCE {number}",
        domains=["ALG"],
        main_topic="ALG",
        canonical_subtopic=family,
        technique_tags=list(methods),
        lemma_theorem_tags=list(lemmas),
    )
    return row


def benchmark(kind, key, *, load=2):
    return TechniqueBenchmark.objects.create(
        kind=kind,
        label=key,
        label_key=key,
        primary_area="Algebra",
        syllabus_core=5,
        contest_frequency=5,
        transfer_value=5,
        prerequisite_value=5,
        concept_load=load,
        recognition_burden=2,
        execution_load=2,
        proof_fragility=2,
        cross_topic_dependency=2,
        training_type="Drill",
        target_level="National",
        typical_mohs_min=0,
        typical_mohs_max=35,
        benchmark_confidence=94,
    )


def test_registry_preserves_specializations_and_rejects_fuzzy_matches():
    assert concept_for("method", "AM-GM") == concept_for("lemma", "AM-GM") == "am-gm"
    assert concept_for("method", "WEIGHTED AM-GM") == "weighted-am-gm"
    assert concept_for("lemma", "ENGEL") != concept_for("method", "CAUCHY-SCHWARZ")
    assert not concept_for("object", "MEAN INEQUALITY")
    assert concept_for("method", "CAUCHY EQUATION ON Q+") == "additive-functions"
    assert not concept_for("method", "CAUCHY EQUATION ON Q")
    assert concept_for("method", "ENGEL FORM (TITU'S LEMMA)") == concept_for("lemma", "ENGEL")
    assert concept_for("technique", "CAUCHY-SCHWARZ / ENGEL FORM") == "engel"


def test_benchmark_map_has_one_concept_and_retains_every_rating_profile():
    first = benchmark("lemma", "weighted-am-gm", load=2)
    second = benchmark("method", "weighted-am-gm", load=4)
    before = list(TechniqueBenchmark.objects.values())
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all(), paginate=True)
    assert context["technique_benchmark_total"] == 1
    row = context["technique_benchmark_rows"][0]
    assert row["concept_id"] == "weighted-am-gm"
    assert set(row["profile_ids"]) == {first.pk, second.pk}
    assert row["roles"] == ["Lemma/Theorem", "Method"]
    assert not row["profile_conflicts"]
    assert row["chartable"]
    assert row["benchmark_id"] == first.pk
    assert row["difficulty_score_number"] == 2.0
    assert len(row["profiles"]) == len((first, second))
    assert list(TechniqueBenchmark.objects.values()) == before


def test_benchmark_filter_by_role_loads_the_whole_concept():
    first = benchmark("lemma", "am-gm")
    second = benchmark("method", "am-gm")
    context = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.filter(pk=second.pk), paginate=True,
    )
    row = context["technique_benchmark_rows"][0]
    assert row["benchmark_id"] == first.pk
    assert set(row["profile_ids"]) == {first.pk, second.pk}
    assert not row["profile_conflicts"]


def test_benchmark_map_renders_one_concept_with_role_profiles(client):
    client.force_login(UserFactory())
    benchmark("lemma", "am-gm")
    benchmark("method", "am-gm")
    response = client.get(reverse("pages:technique_benchmark_list"))
    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "concept:am-gm" in html
    assert "Roles: Lemma/Theorem, Method" in html
    assert response.context["technique_benchmark_total"] == 1


def test_differing_profiles_use_the_reviewed_reference_without_averaging():
    benchmark("canonical_subtopic", "factorization", load=2)
    other = benchmark("method", "factorization", load=4)
    other.syllabus_core = 2
    other.save()
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all(), paginate=True)
    row = context["technique_benchmark_rows"][0]
    from inspinia.pages.technique_benchmarking.scoring import calculate_static_importance_score

    assert row["benchmark_id"] == other.pk
    assert row["value_score_number"] == float(calculate_static_importance_score(other))
    assert {p["difficulty_score_number"] for p in row["profiles"]} == {2.0, 2.5}


def test_explicit_reference_resolves_gap_ranking_and_keeps_role_values():
    benchmark("lemma", "weighted-am-gm", load=2)
    benchmark("method", "weighted-am-gm", load=4)
    rows = _enrich_gap_rows_with_benchmarks([
        {"label": "WEIGHTED AM-GM", "type": "Concept", "concept_id": "weighted-am-gm", "remaining": 10, "total": 10},
    ])
    scored = _score_gap_rows(rows, target_profile="national")[0]
    assert scored["benchmark_status"] == "needs_review"
    assert scored["priority_score"] is not None
    assert float(scored["difficulty_score"]) == 2.0
    assert TechniqueBenchmark.objects.get(kind="method", label_key="weighted-am-gm").concept_load == 4


def test_gap_concept_counts_statement_union_and_practice_includes_all_roles(client):
    user = UserFactory()
    client.force_login(user)
    both = statement(1, methods=["AM-GM"], lemmas=["AM-GM"])
    statement(2, methods=["AM-GM"])
    statement(3, lemmas=["AM-GM"])
    statement(4, methods=["WEIGHTED AM-GM"])
    rebuild_technique_progress_catalog()
    UserProblemCompletion.objects.create(user=user, statement=both, status=UserProblemCompletion.Status.SOLVED)
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(request_user=user, raw_kind="all", raw_topic="algebra")
    amgm = [row for row in rows if row.get("concept_id") == "am-gm"]
    assert len(amgm) == 1
    row = amgm[0]
    assert (row["total"], row["solved"], row["remaining"]) == (3, 1, 2)
    assert row["roles"] == ["lemma", "method"]
    assert parse_qs(urlsplit(row["practice_url"]).query) == {"layer_kind": ["concepts"], "layer_tag": ["am-gm"]}
    response = client.get(row["practice_url"])
    assert response.status_code == HTTPStatus.OK
    # The exact concept filter must include either role and exclude weighted AM-GM.
    from inspinia.pages.views import _completion_quick_update_apply_layer_filter

    selected = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(),
        raw_kind="concepts",
        raw_tag="am-gm",
    )
    assert set(selected.values_list("problem_code", flat=True)) == {"A1", "A2", "A3"}
    assert not _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(),
        raw_kind="concepts",
        raw_tag="unknown",
    ).exists()


def test_existing_punctuated_aliases_share_counts_and_exact_practice_membership():
    user = UserFactory()
    first = statement(1, methods=["ENGEL FORM (TITU'S LEMMA)"], lemmas=["ENGEL"])
    second = statement(2, methods=["ENGEL FORM"])
    rebuild_technique_progress_catalog()
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(request_user=user, raw_kind="all", raw_topic="algebra")
    assert len(rows) == 1
    assert rows[0]["concept_id"] == "engel"
    assert rows[0]["total"] == len((first, second))
    from inspinia.pages.views import _completion_quick_update_apply_layer_filter

    selected = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(), raw_kind="concepts", raw_tag="engel",
    )
    assert set(selected.values_list("pk", flat=True)) == {first.pk, second.pk}


def test_subtopic_gaps_use_local_counts_union_roles_and_suppress_self_heading(client):
    user = UserFactory()
    client.force_login(user)
    statement(1, methods=["AM-GM", "FACTORIZATION", "INEQUALITIES AND OPTIMIZATION"], lemmas=["AM-GM"])
    statement(2, family="Polynomials", methods=["FACTORIZATION"])
    statement(3, family="Polynomials", methods=["FACTORIZATION"])
    rebuild_technique_progress_catalog()
    rows = _scoped_subtopic_gap_rows(user=user, gap_topic="algebra")
    inequalities = [row for row in rows if row["canonical_subtopic_labels"] == ["Inequalities and optimization"]]
    assert next(row for row in inequalities if row["label"] == "FACTORIZATION")["remaining"] == 1
    assert next(row for row in inequalities if row["label"] == "AM-GM")["remaining"] == 1
    cache.clear()
    response = client.get(reverse("pages:technique_progress_topic_detail", kwargs={"topic_slug": "algebra"}))
    row = next(
        row
        for row in response.context["technique_progress_topic_subtopic_rows"]
        if row["label"] == "Inequalities and optimization"
    )
    assert {item["label"] for item in row["layer_gap_preview"]} == {"AM-GM", "FACTORIZATION"}
    assert row["total"] == 1


def test_full_algebra_catalog_contains_180_including_unscored_definitions(client):
    from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS as CONCEPTS

    user = UserFactory()
    client.force_login(user)
    before = list(TechniqueBenchmark.objects.values())
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Algebra"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["technique_benchmark_total"] == 180
    assert len(CONCEPTS) == 180
    assert sum(c["canonical_benchmark_id"] is None for c in CONCEPTS.values()) == 29
    assert list(TechniqueBenchmark.objects.values()) == before
    response = client.get(
        reverse("pages:technique_benchmark_list"), {"area": "Algebra", "q": "Lagrange interpolation"},
    )
    assert response.context["technique_benchmark_total"] == 1
    assert response.context["technique_benchmark_rows"][0]["concept_id"] == "polynomial-interpolation"


def test_reviewed_membership_preserves_exclusions_domains_and_profile_ownership():
    from inspinia.pages.technique_concepts import concept_for_benchmark

    for kind, label in [
        ("method", "BIJECTION"), ("method", "FOURIER TRANSFORM"),
        ("object", "RECIPROCAL POLYNOMIAL"), ("object", "FLOOR / ROUNDING / APPROXIMATION"),
        ("technique", "FLOOR / ROUNDING / APPROXIMATION"),
    ]:
        assert not concept_for(kind, label)
    assert concept_for_benchmark("method", "eigenvalue-method") == "modular-spectral-methods"
    assert concept_for("method", "EIGENVALUE METHOD") == "eigenvalues"
    assert concept_for("lemma", "LAGRANGE INTERPOLATION") == "polynomial-interpolation"
    assert concept_for("method", "VIETA JUMPING") != "vieta"


def test_concept_union_includes_legacy_role_and_excludes_non_algebra_population():
    from inspinia.pages.models import TechniqueProgressFact
    from inspinia.pages.technique_concepts import concept_fact_filter

    user = UserFactory()
    legacy = statement(1)
    tag = StatementTopicTechnique.objects.get(statement=legacy)
    tag.technique = "AM-GM"
    tag.save()
    typed = statement(2, methods=["AM-GM"])
    outside = statement(3, methods=["AM-GM"])
    outside.topic = "N"
    outside.save()
    tag = StatementTopicTechnique.objects.get(statement=outside)
    tag.main_topic = "NT"
    tag.domains = ["NT"]
    tag.save()
    rebuild_technique_progress_catalog()
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(request_user=user, raw_kind="all", raw_topic="algebra")
    row = next(r for r in rows if r.get("concept_id") == "am-gm")
    assert row["total"] == 2
    selected = TechniqueProgressFact.objects.filter(concept_fact_filter("am-gm"))
    assert set(selected.values_list("statement_id", flat=True)) == {legacy.pk, typed.pk}


def test_missing_selected_reference_is_not_replaced_by_another_role():
    benchmark("method", "weighted-am-gm", load=4)
    rows = _enrich_gap_rows_with_benchmarks([
        {"label": "WEIGHTED AM-GM", "type": "Concept", "concept_id": "weighted-am-gm", "remaining": 10, "total": 10},
    ])
    assert rows[0]["_benchmark"] is None
    assert rows[0]["concept_profile_conflict"]
    assert _score_gap_rows(rows, target_profile="national")[0]["priority_score"] is None


def test_full_captured_catalog_resolves_151_references_and_keeps_29_unrated():
    from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS as CONCEPTS
    from inspinia.pages.technique_concepts import CONCEPT_BY_MEMBER

    profiles = json.loads((Path(__file__).parent / "testdata/algebra_concept_benchmarks_v1.json").read_text())
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row) for row in profiles])
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all(), catalog_filters={})
    rows = context["technique_benchmark_rows"]
    assert len(rows) == len(CONCEPTS) == 180
    assert len(CONCEPT_BY_MEMBER) == 543
    assert sum(row["training_type"] == "Unrated" for row in rows) == 29
    assert not any(row["profile_conflicts"] for row in rows)
    for row in rows:
        assert row["benchmark_id"] == CONCEPTS[row["concept_id"]]["canonical_benchmark_id"]
    assert TechniqueBenchmark.objects.count() == len(profiles)


def test_outside_area_keeps_source_profile_and_concept_deep_link_works(client):
    client.force_login(UserFactory())
    source = benchmark("method", "factorization")
    source.primary_area = "Number Theory"
    source.save()
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Number Theory", "view": "profiles"})
    assert response.context["technique_benchmark_rows"][0]["row_key"] == "method:factorization"
    response = client.get(reverse("pages:technique_benchmark_list"), {"row_key": "concept:factorization"})
    assert response.context["technique_benchmark_total"] == 1
    assert response.context["technique_benchmark_rows"][0]["benchmark_id"] == source.pk
