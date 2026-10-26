"""Number Theory identities preserve source assessments and exact practice unions."""

# ruff: noqa: PLR2004 -- frozen catalog/fixture sizes and regression examples

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
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.technique_benchmarking.dashboard import build_technique_benchmark_dashboard_context
from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS
from inspinia.pages.technique_concepts import NUMBER_THEORY_CONCEPTS
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
def retained_profiles():
    rows = json.loads((DATA / "number_theory_concept_benchmarks_v1.json").read_text())
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row) for row in rows])
    return rows


def nt_statement(number, *, methods=(), lemmas=(), topic="N", family="Congruences and modular arithmetic"):
    statement = ContestProblemStatement.objects.create(
        contest_name="NT CONCEPT TEST", contest_year=2026, problem_number=number,
        problem_code=f"N{number}", topic=topic, statement_latex="Find n.", mohs=10,
    )
    StatementTopicTechnique.objects.create(
        statement=statement, technique=f"SOURCE {number}", domains=["NT" if topic == "N" else "ALG"],
        main_topic="NT" if topic == "N" else "ALG", canonical_subtopic=family,
        technique_tags=list(methods), lemma_theorem_tags=list(lemmas),
    )
    return statement


def nt_benchmark(kind, key, *, load=2):
    return TechniqueBenchmark.objects.create(
        kind=kind, label=key, label_key=key, primary_area="Number Theory",
        syllabus_core=5, contest_frequency=5, transfer_value=5, prerequisite_value=5,
        concept_load=load, recognition_burden=2, execution_load=2, proof_fragility=2,
        cross_topic_dependency=2, training_type="Drill", target_level="National",
        typical_mohs_min=0, typical_mohs_max=35, benchmark_confidence=94,
    )


def test_catalog_sizes_and_subject_namespaces_preserve_the_algebra_contract():
    assert len(catalog_concept_ids("Number Theory")) == 236
    assert len(catalog_concept_ids("Number Theory", scope="shared")) == 32
    assert len(NUMBER_THEORY_CONCEPTS) == 268
    assert len(ALGEBRA_CONCEPTS) == 180
    assert not set(ALGEBRA_CONCEPTS) & set(NUMBER_THEORY_CONCEPTS)
    assert all(cid.startswith("nt-") for cid in NUMBER_THEORY_CONCEPTS)
    assert concept_for("method", "CAUCHY EQUATION ON Q+") == "additive-functions"
    assert concept_for("technique", "Additive arithmetic functions", topic="Number Theory") == "nt-additive-functions"
    assert not concept_for("method", "CAUCHY EQUATION ON Q+", topic="Number Theory")


@pytest.mark.parametrize(("kind", "label", "expected"), [
    ("lemma", "Chinese remainder theorem", "nt-crt"),
    ("method", "CRT", "nt-crt"),
    ("technique", "MOD 3", "nt-modular-arithmetic"),
    ("technique", "MODULO 3", "nt-modular-arithmetic"),
    ("method", "2-ADIC VALUATION", "nt-p-adic-valuation"),
    ("technique", "popcount", "nt-digit-sums"),
    ("technique", "binary weight", "nt-digit-sums"),
    ("technique", "HENSEL-STYLE LIFTING", "nt-lifting"),
    ("lemma", "Hensel's lemma", "nt-hensel"),
    ("method", "finite logarithm", "nt-discrete-logarithms"),
    ("lemma", "sum of two squares", "nt-fermat-two-squares"),
    ("technique", "sum of two squares", "nt-sum-two-squares"),
])
def test_exact_aliases_preserve_role_and_subject(kind, label, expected):
    assert concept_for(kind, label, topic="Number Theory") == expected
    assert not concept_for(kind, label, topic="Geometry")


@pytest.mark.parametrize("label", [
    "number of prime factors", "Schur/Rado flavor", "AP/GP avoidance",
    "Ljunggren / Nagell flavor", "p-adic density / local-global flavor",
    "inverse phi / inverse sigma flavor", "phi/tau/sigma constraints",
])
def test_ambiguous_and_compound_labels_never_become_single_identity_aliases(label):
    assert not concept_for("technique", label, topic="Number Theory")


def test_all_profile_members_have_one_owner_per_subject():
    for registry in (ALGEBRA_CONCEPTS, NUMBER_THEORY_CONCEPTS):
        keys = [(p["kind"], p["label_key"]) for c in registry.values() for p in c["profiles"]]
        assert len(keys) == len(set(keys))
    assert concept_for_benchmark("method", "descent", topic="Algebra") == "descent"
    assert concept_for_benchmark("method", "descent", topic="Number Theory") == "nt-infinite-descent"
    assert not concept_for_benchmark("object", "prime-and-primitive-objects", topic="Number Theory")


def test_entire_catalog_and_raw_profile_views_preserve_every_database_value(client, retained_profiles):
    client.force_login(UserFactory())
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    aliases_before = list(TechniqueBenchmarkAlias.objects.values())
    for params, expected in [
        ({"area": "Number Theory"}, 236),
        ({"area": "Number Theory", "scope": "shared"}, 32),
        ({"area": "Number Theory", "view": "profiles"}, 307),
        ({"area": "Number Theory", "q": "big omega"}, 1),
    ]:
        response = client.get(reverse("pages:technique_benchmark_list"), params)
        assert response.status_code == HTTPStatus.OK
        assert response.context["technique_benchmark_total"] == expected
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Number Theory", "page": "2"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["page_obj"].number == 2
    assert list(TechniqueBenchmark.objects.order_by("pk").values()) == before
    assert list(TechniqueBenchmarkAlias.objects.values()) == aliases_before
    assert TechniqueBenchmark.objects.count() == len(retained_profiles)


def test_all_source_profiles_survive_combining_and_excluded_profiles_remain_accessible(retained_profiles):
    context = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(), catalog_filters={"topic": "Number Theory", "scope": "all"},
    )
    assert len(context["technique_benchmark_rows"]) == 268
    captured = {p["id"] for p in retained_profiles}
    displayed = [pid for row in context["technique_benchmark_rows"] for pid in row["profile_ids"]]
    assert len(displayed) == len(set(displayed)) == 266
    assert set(displayed) <= captured
    assert TechniqueBenchmark.objects.filter(pk__in=captured - set(displayed)).count() == 41
    assert all(row["benchmark_id"] is None for row in context["technique_benchmark_rows"] if row["profile_conflicts"])


def test_search_sort_targets_and_reset_preserve_number_theory_scope(client):
    client.force_login(UserFactory())
    response = client.get(reverse("pages:technique_benchmark_list"), {
        "area": "Number Theory", "q": "big omega", "scope": "core", "page": "2", "sort": "name",
    })
    assert response.context["technique_benchmark_total"] == 1
    assert response.context["benchmark_scope_filters"] == {"area": "Number Theory", "scope": "core"}
    assert 'name="area" value="Number Theory"' in response.content.decode()
    for option in response.context["technique_benchmark_target_profile_options"]:
        query = parse_qs(option["query"])
        assert query["area"] == ["Number Theory"]
        assert query["q"] == ["big omega"]
        assert query["scope"] == ["core"]
        assert "page" not in query
    reset = parse_qs(response.context["benchmark_reset_query"])
    assert reset["area"] == ["Number Theory"]
    assert "q" not in reset


def test_existing_algebra_profiles_and_references_are_unchanged(retained_profiles):
    existing = set(TechniqueBenchmark.objects.values_list("pk", flat=True))
    algebra = json.loads((DATA / "algebra_concept_benchmarks_v1.json").read_text())
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**r) for r in algebra if r["id"] not in existing])
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    context = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(), catalog_filters={"topic": "Algebra"},
    )
    assert len(context["technique_benchmark_rows"]) == 180
    for row in context["technique_benchmark_rows"]:
        assert row["benchmark_id"] == ALGEBRA_CONCEPTS[row["concept_id"]]["canonical_benchmark_id"]
    assert list(TechniqueBenchmark.objects.order_by("pk").values()) == before


def test_differing_profiles_are_retained_without_a_combined_rating_or_priority():
    first = nt_benchmark("object", "p-adic-valuation", load=2)
    second = nt_benchmark("method", "2-adic-valuation", load=4)
    before = list(TechniqueBenchmark.objects.values())
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all())
    row = context["technique_benchmark_rows"][0]
    assert row["concept_id"] == "nt-p-adic-valuation"
    assert set(row["profile_ids"]) == {first.pk, second.pk}
    assert row["profile_conflicts"]
    assert not row["chartable"]
    assert row["difficulty_score_number"] is None
    assert row["benchmark_id"] is None
    scored = _score_gap_rows(_enrich_gap_rows_with_benchmarks([
        {"concept_id": "nt-p-adic-valuation", "label": "p-adic valuations", "remaining": 5, "total": 5},
    ]), target_profile="national")[0]
    assert scored["benchmark_status"] == "needs_review"
    assert scored["priority_score"] is None
    assert list(TechniqueBenchmark.objects.values()) == before


def test_runtime_rating_drift_does_not_silently_choose_a_preferred_profile():
    nt_benchmark("method", "crt", load=2)
    nt_benchmark("lemma", "chinese-remainder-theorem", load=4)
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all())
    assert not context["technique_benchmark_rows"][0]["chartable"]
    enriched = _enrich_gap_rows_with_benchmarks([
        {"concept_id": "nt-crt", "label": "Chinese remainder theorem", "remaining": 2, "total": 2},
    ])[0]
    assert enriched["_benchmark"] is None
    assert enriched["concept_profile_conflict"]


def test_missing_reference_does_not_fall_back_to_another_role():
    nt_benchmark("lemma", "chinese-remainder-theorem")
    row = _enrich_gap_rows_with_benchmarks([
        {"concept_id": "nt-crt", "label": "Chinese remainder theorem", "remaining": 2, "total": 2},
    ])[0]
    assert row["_benchmark"] is None
    assert row["concept_profile_conflict"]


def test_gap_and_practice_count_the_same_subject_scoped_statement_union(client):
    user = UserFactory()
    client.force_login(user)
    both = nt_statement(1, methods=["CRT"], lemmas=["CHINESE REMAINDER THEOREM"])
    method = nt_statement(2, methods=["CRT"])
    lemma = nt_statement(3, lemmas=["CHINESE REMAINDER THEOREM"])
    nt_statement(4, methods=["CRT"], topic="A")
    rebuild_technique_progress_catalog()
    UserProblemCompletion.objects.create(user=user, statement=both, status=UserProblemCompletion.Status.SOLVED)
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(
        request_user=user, raw_kind="all", raw_topic="number-theory",
    )
    matching = [r for r in rows if r.get("concept_id") == "nt-crt"]
    assert len(matching) == 1
    row = matching[0]
    assert (row["total"], row["solved"], row["remaining"]) == (3, 1, 2)
    selected = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(), raw_kind="concepts", raw_tag="nt-crt",
    )
    assert set(selected.values_list("pk", flat=True)) == {both.pk, method.pk, lemma.pk}
    assert client.get(row["practice_url"]).status_code == HTTPStatus.OK
    previews = _scoped_subtopic_gap_rows(user=user, gap_topic="number-theory")
    preview = next(r for r in previews if r["label"] == "Chinese remainder theorem")
    assert (preview["total"], preview["remaining"]) == (3, 2)


def test_secondary_subject_associations_are_included_in_counts_and_practice():
    user = UserFactory()
    row = nt_statement(1, methods=["CRT"], topic="A")
    tag = StatementTopicTechnique.objects.get(statement=row)
    tag.domains = ["ALG", "NT"]
    tag.save()
    rebuild_technique_progress_catalog()
    cache.clear()
    rows = technique_progress_gap_rows_for_benchmark_export(
        request_user=user, raw_kind="all", raw_topic="number-theory",
    )
    assert next(r for r in rows if r.get("concept_id") == "nt-crt")["total"] == 1
    from inspinia.pages.models import TechniqueProgressFact

    selected = TechniqueProgressFact.objects.filter(concept_fact_filter("nt-crt"))
    assert set(selected.values_list("statement_id", flat=True)) == {row.pk}


def test_retired_variant_deep_links_and_practice_filters_use_surviving_identity(client):
    client.force_login(UserFactory())
    row = nt_statement(1, methods=["2-ADIC VALUATION"])
    rebuild_technique_progress_catalog()
    selected = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(), raw_kind="concepts", raw_tag="nt-two-adic-valuation",
    )
    assert list(selected.values_list("pk", flat=True)) == [row.pk]
    response = client.get(reverse("pages:technique_benchmark_list"), {"row_key": "concept:nt-two-adic-valuation"})
    assert response.context["technique_benchmark_total"] == 1
    assert response.context["technique_benchmark_rows"][0]["concept_id"] == "nt-p-adic-valuation"


def test_import_preview_and_write_classification_feed_the_same_identity_members():
    raw = "NT - MOD 3; FINITE LOGARITHM"
    preview = prepare_topic_tag_entries(raw, topic="N", active=True, problem_uuid=None, canonicalize=False)
    write = prepare_topic_tag_entries(raw, topic="N", active=True, problem_uuid=None, canonicalize=True)
    assert preview == write
    concepts = {
        concept_for(kind, label, topic="Number Theory")
        for entry in preview
        for kind, labels in (
            ("technique", [entry["technique"]]), ("object", entry["object_tags"]),
            ("method", entry["technique_tags"]),
        )
        for label in labels
    }
    assert {"nt-modular-arithmetic", "nt-discrete-logarithms"} <= concepts


def test_number_theory_catalog_remains_authenticated(client):
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Number Theory"})
    assert response.status_code == HTTPStatus.FOUND
