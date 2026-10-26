"""Geometry identities retain assessments, subject boundaries, and exact unions."""

# ruff: noqa: PLR2004 -- frozen catalog sizes and regression examples

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from django.core.cache import cache
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.technique_benchmarking.dashboard import build_technique_benchmark_dashboard_context
from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS
from inspinia.pages.technique_concepts import GEOMETRY_CATALOG
from inspinia.pages.technique_concepts import GEOMETRY_CONCEPTS
from inspinia.pages.technique_concepts import NUMBER_THEORY_CONCEPTS
from inspinia.pages.technique_concepts import PROFILE_FIELDS
from inspinia.pages.technique_concepts import catalog_concept_ids
from inspinia.pages.technique_concepts import concept_fact_filter
from inspinia.pages.technique_concepts import concept_for
from inspinia.pages.technique_concepts import concept_for_benchmark
from inspinia.pages.technique_progress import _enrich_gap_rows_with_benchmarks
from inspinia.pages.technique_progress import _scoped_subtopic_gap_rows
from inspinia.pages.technique_progress import _score_gap_rows
from inspinia.pages.technique_progress import technique_progress_gap_rows_for_benchmark_export
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.pages.views import _completion_quick_update_apply_layer_filter
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
DATA = Path(__file__).parent / "testdata"


@pytest.fixture
def retained_geometry_profiles():
    rows = json.loads((DATA / "geometry_concept_benchmarks_v1.json").read_text())
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row) for row in rows])
    return rows


def geometry_statement(number, *, methods=(), lemmas=(), objects=(), topic="G"):
    statement = ContestProblemStatement.objects.create(
        contest_name="GEOMETRY CONCEPT TEST", contest_year=2026, problem_number=number,
        problem_code=f"G{number}", topic=topic, statement_latex="Prove the claim.", mohs=10,
    )
    subject = "GEO" if topic == "G" else "ALG"
    StatementTopicTechnique.objects.create(
        statement=statement, technique=f"SOURCE {number}", domains=[subject], main_topic=subject,
        canonical_subtopic="Triangle centers and configurations", technique_tags=list(methods),
        lemma_theorem_tags=list(lemmas), object_tags=list(objects),
    )
    return statement


def geometry_benchmark(kind, key, *, load=2):
    return TechniqueBenchmark.objects.create(
        kind=kind, label=key, label_key=key, primary_area="Geometry",
        syllabus_core=5, contest_frequency=5, transfer_value=5, prerequisite_value=5,
        concept_load=load, recognition_burden=2, execution_load=2, proof_fragility=2,
        cross_topic_dependency=2, typical_mohs_min=0, typical_mohs_max=35,
        training_type="Drill", target_level="National", benchmark_confidence=94,
    )


def test_catalog_is_complete_namespaced_and_has_a_valid_hierarchy():
    assert len(catalog_concept_ids("Geometry")) == 334
    assert len(GEOMETRY_CATALOG["areas"]) == 10
    assert len(ALGEBRA_CONCEPTS) == 180
    assert len(NUMBER_THEORY_CONCEPTS) == 268
    assert not set(GEOMETRY_CONCEPTS) & (set(ALGEBRA_CONCEPTS) | set(NUMBER_THEORY_CONCEPTS))
    assert all(cid.startswith("geo-") for cid in GEOMETRY_CONCEPTS)
    aliases = [(kind, label.casefold()) for c in GEOMETRY_CONCEPTS.values() for kind, label in c["aliases"]]
    profiles = [(p["kind"], p["label_key"]) for c in GEOMETRY_CONCEPTS.values() for p in c["profiles"]]
    assert len(aliases) == len(set(aliases)) == 1823
    assert len(profiles) == len(set(profiles)) == 364
    assert sum(not c["profiles"] for c in GEOMETRY_CONCEPTS.values()) == 191
    assert sum(bool(c["profiles"]) and not c["preferred"] for c in GEOMETRY_CONCEPTS.values()) == 79
    for cid, definition in GEOMETRY_CONCEPTS.items():
        concept = definition
        seen = {cid}
        while concept["parent_concept"]:
            parent = concept["parent_concept"]
            assert parent not in seen
            seen.add(parent)
            concept = GEOMETRY_CONCEPTS[parent]
    assert GEOMETRY_CONCEPTS["geo-orthogonal-projections"]["parent_concept"] == "geo-projections"
    assert GEOMETRY_CONCEPTS["geo-parallel-projection"]["parent_concept"] == "geo-projections"
    assert GEOMETRY_CONCEPTS["geo-stereographic-projection"]["parent_concept"] == "geo-central-projection"
    assert not GEOMETRY_CONCEPTS["geo-geodesics"]["parent_concept"]


@pytest.mark.parametrize(("kind", "label", "expected"), [
    ("lemma", "CEVA'S THEOREM", "ceva"),
    ("lemma", "Ceva theorem", "ceva"),
    ("lemma", "Pythagorean theorem", "pythagoras"),
    ("method", "RADICAL AXIS", "radical-axis"),
    ("method", "POWER OF A POINT", "power-of-a-point"),
    ("lemma", "MASS POINTS", "mass-points"),
    ("object", "CONTACT TRIANGLE", "contact-triangle"),
    ("method", "SPIRAL SIMILARITY", "spiral-similarity"),
    ("object", "CONVEX POLYGON", "convex-polygons"),
    ("method", "DIRECTED ANGLES", "directed-angles"),
    ("technique", "orthogonal projections", "orthogonal-projections"),
    ("method", "projection", "projections"),
    ("technique", "parallel projection", "parallel-projection"),
    ("technique", "stereographic projection", "stereographic-projection"),
    ("object", "BROCARD POINT", "brocard"),
    ("method", "BROKARD THEOREM", "brokard-theorem"),
    ("subtopic", "ANGLE CHASING", "angle-chasing"),
])
def test_exact_aliases_follow_mathematical_identity_in_the_captured_role(kind, label, expected):
    assert concept_for(kind, label, topic="Geometry") == f"geo-{expected}"


@pytest.mark.parametrize("label", [
    "CEVA/MENELAUS", "CEVA WHEN APPLICABLE", "CEVA (AREA FORM)", "CEVA-STYLE CONCURRENCY",
    "CEVA, MENELAUS, AND CEVIANS", "SIMILARITY AND CONGRUENCE", "CIRCLE / ORTHOGONAL PROJECTIONS",
    "THALES", "THALES THEOREM", "EULER", "MINKOWSKI", "APOLLONIUS", "CARNOT THEOREM", "LEIBNIZ", "DIT",
    "PASCAL TRIANGLE MOD 2", "WITT VECTORS", "LATIN ORTHOGONALITY", "CYCLIC SUMS", "CYCLIC GROUPS",
    "POWER INTERPOLATION", "POWER/LIMITING POINTS", "CAUCHY FUNCTIONAL EQUATION", "JORDAN CURVE FLAVOR",
    "BROCARD", "NUMBER OF PRIME FACTORS", "ORTHOGONAL PROJECTIONS IN 4D",
])
def test_compounds_qualifiers_ambiguous_names_and_cross_topic_collisions_are_not_aliases(label):
    assert all(not concept_for(kind, label, topic="Geometry") for kind in (
        "technique", "method", "object", "lemma", "proof_role", "canonical_subtopic",
    ))


def test_context_only_candidates_have_no_automatic_aliases_or_assessments():
    held = [c for c in GEOMETRY_CONCEPTS.values() if c["evidence_status"] == "source_context_required"]
    assert len(held) == 4
    assert all(not c["aliases"] and not c["profiles"] and not c["preferred"] for c in held)


def test_subject_and_role_boundaries_preserve_existing_shared_profile_ownership():
    assert not concept_for("lemma", "CEVA", topic="Number Theory")
    assert not concept_for("lemma", "CEVA", topic="Algebra")
    assert not concept_for("object", "Ceva's theorem", topic="Geometry")
    assert concept_for_benchmark("object", "trigonometric-expression", topic="Geometry") == "geo-trigonometric-methods"
    assert concept_for_benchmark("object", "trigonometric-expression") == "trigonometric-expressions"
    assert concept_for_benchmark("method", "auxiliary-construction", topic="Geometry") == "geo-constructions"
    assert concept_for_benchmark("method", "auxiliary-construction") == "nt-construction"


def test_catalog_and_original_profile_gets_leave_every_database_value_unchanged(client, retained_geometry_profiles):
    client.force_login(UserFactory())
    TechniqueBenchmarkAlias.objects.create(
        kind="lemma", alias_label="MASS POINTS", alias_key="mass-points", benchmark_id=899,
    )
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    aliases_before = list(TechniqueBenchmarkAlias.objects.order_by("pk").values())
    for params, expected in [
        ({"area": "Geometry"}, 334),
        ({"area": "Geometry", "view": "profiles"}, 431),
        ({"row_key": "concept:geo-brokard-theorem"}, 1),
        ({"area": "Geometry", "q": "orthogonal projections"}, 1),
    ]:
        response = client.get(reverse("pages:technique_benchmark_list"), params)
        assert response.status_code == HTTPStatus.OK
        assert response.context["technique_benchmark_total"] == expected
    assert list(TechniqueBenchmark.objects.order_by("pk").values()) == before
    assert list(TechniqueBenchmarkAlias.objects.order_by("pk").values()) == aliases_before
    assert len(retained_geometry_profiles) == TechniqueBenchmark.objects.count() == 458


def test_every_profile_and_rating_is_retained_without_inventing_combined_assessments(retained_geometry_profiles):
    context = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(), catalog_filters={"topic": "Geometry"},
    )
    rows = context["technique_benchmark_rows"]
    assert len(rows) == 334
    captured = {p["id"]: p for p in retained_geometry_profiles}
    shown = [pid for row in rows for pid in row["profile_ids"]]
    assert len(shown) == len(set(shown)) == 364
    assert len(set(captured) - set(shown)) == 94
    for row in rows:
        definition = GEOMETRY_CONCEPTS[row["concept_id"]]
        assert row["benchmark_id"] == definition["canonical_benchmark_id"]
        if definition["profiles"] and not definition["preferred"]:
            assert row["profile_conflicts"]
            assert row["difficulty_score_number"] is None
            assert not row["chartable"]
        for profile in row["profiles"]:
            original = captured[profile["benchmark_id"]]
            assert profile["rating_signature"] == tuple(str(original[field]) for field in PROFILE_FIELDS)


def test_differing_profiles_and_live_drift_have_no_combined_rating_or_priority():
    first = geometry_benchmark("canonical_subtopic", "concurrence", load=2)
    second = geometry_benchmark("canonical_subtopic", "concurrency", load=4)
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    context = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(), catalog_filters={"topic": "Geometry"},
    )
    row = next(r for r in context["technique_benchmark_rows"] if r["concept_id"] == "geo-concurrency")
    assert set(row["profile_ids"]) == {first.pk, second.pk}
    assert row["benchmark_id"] is None
    assert row["profile_conflicts"]
    scored = _score_gap_rows(_enrich_gap_rows_with_benchmarks([
        {"concept_id": "geo-concurrency", "label": "Concurrency", "remaining": 5, "total": 5},
    ]), target_profile="national")[0]
    assert scored["benchmark_status"] == "needs_review"
    assert scored["priority_score"] is None
    geometry_benchmark("canonical_subtopic", "simson-line", load=2)
    geometry_benchmark("lemma", "simson-theorem", load=4)
    drifted = _enrich_gap_rows_with_benchmarks([
        {"concept_id": "geo-simson-line", "label": "Simson line theorem", "remaining": 2, "total": 2},
    ])[0]
    assert drifted["_benchmark"] is None
    assert drifted["concept_profile_conflict"]
    assert list(TechniqueBenchmark.objects.filter(pk__in=[first.pk, second.pk]).order_by("pk").values()) == before


def test_unfiltered_dashboard_retains_geometry_role_details_without_combining_ratings(client):
    client.force_login(UserFactory())
    first = geometry_benchmark("canonical_subtopic", "projective-geometry", load=4)
    second = geometry_benchmark("method", "projective-method", load=2)
    response = client.get(reverse("pages:technique_benchmark_list"))
    assert response.status_code == HTTPStatus.OK
    assert response.context["technique_benchmark_total"] == 1
    row = response.context["technique_benchmark_rows"][0]
    assert row["concept_id"] == "geo-projective-methods"
    assert set(row["profile_ids"]) == {first.pk, second.pk}
    assert row["benchmark_id"] is None
    assert row["difficulty_score_number"] is None
    assert {p["difficulty_score"] for p in row["profiles"]} == {
        str(first.difficulty_score), str(second.difficulty_score),
    }


@pytest.mark.parametrize("area", ["", "Geometry"])
def test_original_profile_deep_links_keep_their_rating_and_identity(client, area):
    client.force_login(UserFactory())
    original = geometry_benchmark("canonical_subtopic", "projective-geometry", load=4)
    response = client.get(reverse("pages:technique_benchmark_list"), {
        "row_key": "canonical_subtopic:projective-geometry", "area": area,
    })
    assert response.status_code == HTTPStatus.OK
    assert response.context["technique_benchmark_total"] == 1
    row = response.context["technique_benchmark_rows"][0]
    assert row["row_key"] == "canonical_subtopic:projective-geometry"
    assert row["benchmark_id"] == original.pk
    assert row["difficulty_score"] == str(original.difficulty_score)
    assert row["chartable"]


def test_missing_reference_and_unrated_identities_never_fall_back_to_legacy_aliases():
    wrong = geometry_benchmark("lemma", "ceva")
    geometry_benchmark("lemma", "simson-theorem")
    TechniqueBenchmarkAlias.objects.create(
        kind="technique", alias_label="Orthogonal projections", alias_key="orthogonal-projections", benchmark=wrong,
    )
    rows = _enrich_gap_rows_with_benchmarks([
        {"concept_id": "geo-simson-line", "label": "Simson line theorem", "remaining": 2, "total": 2},
        {"concept_id": "geo-orthogonal-projections", "label": "Orthogonal projections", "remaining": 2, "total": 2},
    ])
    assert all(row["_benchmark"] is None for row in rows)
    assert rows[0]["concept_profile_conflict"]


def test_gap_preview_and_practice_select_the_same_statement_union(client):
    user = UserFactory()
    client.force_login(user)
    both = geometry_statement(1, methods=["PYTHAGOREAN THEOREM"], lemmas=["PYTHAGOREAN THEOREM"])
    # Only the observed lemma role is an alias; arbitrary method captions stay separate.
    lemma = geometry_statement(2, lemmas=["PYTHAGORAS"])
    duplicate = geometry_statement(3, lemmas=["PYTHAGORAS", "PYTHAGOREAN THEOREM"])
    geometry_statement(4, lemmas=["PYTHAGORAS"], topic="A")
    rebuild_technique_progress_catalog()
    UserProblemCompletion.objects.create(user=user, statement=both, status=UserProblemCompletion.Status.SOLVED)
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(
        request_user=user, raw_kind="all", raw_topic="geometry",
    )
    matches = [r for r in rows if r.get("concept_id") == "geo-pythagoras"]
    assert len(matches) == 1
    row = matches[0]
    assert (row["total"], row["solved"], row["remaining"]) == (3, 1, 2)
    selected = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(), raw_kind="concepts", raw_tag="geo-pythagoras",
    )
    assert set(selected.values_list("pk", flat=True)) == {both.pk, lemma.pk, duplicate.pk}
    assert client.get(row["practice_url"]).status_code == HTTPStatus.OK
    preview = next(r for r in _scoped_subtopic_gap_rows(user=user, gap_topic="geometry")
                   if r["label"] == "Pythagorean theorem")
    assert (preview["total"], preview["remaining"]) == (3, 2)


def test_secondary_geometry_associations_and_role_union_match_practice():
    user = UserFactory()
    statement = geometry_statement(1, methods=["CYCLICITY"], objects=["CYCLIC QUADRILATERAL"], topic="A")
    tag = StatementTopicTechnique.objects.get(statement=statement)
    tag.domains = ["ALG", "GEO"]
    tag.save()
    rebuild_technique_progress_catalog()
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(
        request_user=user, raw_kind="all", raw_topic="geometry",
    )
    assert next(r for r in rows if r.get("concept_id") == "geo-cyclicity")["total"] == 1
    selected = TechniqueProgressFact.objects.filter(concept_fact_filter("geo-cyclicity"))
    assert set(selected.values_list("statement_id", flat=True)) == {statement.pk}


def test_navigation_search_and_target_links_preserve_geometry_scope(client):
    client.force_login(UserFactory())
    response = client.get(reverse("pages:technique_benchmark_list"), {
        "area": "Geometry", "q": "orthogonal projections", "sort": "name", "page": "2",
    })
    assert response.context["technique_benchmark_total"] == 1
    assert response.context["benchmark_scope_filters"] == {"area": "Geometry"}
    assert 'name="area" value="Geometry"' in response.content.decode()
    for option in response.context["technique_benchmark_target_profile_options"]:
        query = parse_qs(option["query"])
        assert query["area"] == ["Geometry"]
        assert query["q"] == ["orthogonal projections"]
        assert "page" not in query
    assert parse_qs(response.context["benchmark_reset_query"])["area"] == ["Geometry"]
    assert client.get(reverse("pages:technique_benchmark_list"), {"area": "Geometry", "page": "2"}).context[
        "page_obj"
    ].number == 2


def test_import_preview_and_write_keep_identical_role_classification():
    raw = "GEO - PYTHAGORAS; CYCLIC QUADRILATERAL"
    preview = prepare_topic_tag_entries(raw, topic="G", active=True, problem_uuid=None, canonicalize=False)
    write = prepare_topic_tag_entries(raw, topic="G", active=True, problem_uuid=None, canonicalize=True)
    assert preview == write
    assert concept_for("technique", "PYTHAGORAS", topic="Geometry") == "geo-pythagoras"
    assert concept_for("technique", "CYCLIC QUADRILATERAL", topic="Geometry") == "geo-cyclicity"


def test_geometry_catalog_remains_authenticated(client):
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Geometry"})
    assert response.status_code == HTTPStatus.FOUND
