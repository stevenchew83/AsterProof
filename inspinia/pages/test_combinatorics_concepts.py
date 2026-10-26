"""Combinatorics identities preserve ratings, problem links, and exact practice unions."""
# ruff: noqa: PLR2004 -- fixed reviewed source counts and regression examples

import hashlib
import json
from http import HTTPStatus
from pathlib import Path

import pytest
from django.core.cache import cache
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.technique_benchmarking.dashboard import build_technique_benchmark_dashboard_context
from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS
from inspinia.pages.technique_concepts import CATALOG_PATH
from inspinia.pages.technique_concepts import CATALOG_SHA256
from inspinia.pages.technique_concepts import COMBINATORICS_CATALOG_PATH
from inspinia.pages.technique_concepts import COMBINATORICS_CONCEPTS
from inspinia.pages.technique_concepts import GEOMETRY_CATALOG_PATH
from inspinia.pages.technique_concepts import NUMBER_THEORY_CATALOG_PATH
from inspinia.pages.technique_concepts import catalog_concept_ids
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
    rows = json.loads((DATA / "combinatorics_concept_benchmarks_v1.json").read_text())
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row) for row in rows])
    return rows


def add_tag(statement, technique, *, family="Graph theory", methods=(), objects=(), lemmas=(), domains=None):  # noqa: PLR0913
    return StatementTopicTechnique.objects.create(
        statement=statement,
        technique=technique,
        domains=domains or ["COMB"],
        main_topic=(domains or ["COMB"])[0],
        canonical_subtopic=family,
        technique_tags=list(methods),
        object_tags=list(objects),
        lemma_theorem_tags=list(lemmas),
    )


def statement(number, *, technique=None, family="Graph theory", methods=(), objects=(), lemmas=(), topic="C"):  # noqa: PLR0913
    row = ContestProblemStatement.objects.create(
        contest_name="COMB CONCEPT TEST",
        contest_year=2026,
        problem_number=number,
        problem_code=f"C{number}",
        topic=topic,
        statement_latex="Count the configurations.",
        mohs=10,
    )
    add_tag(
        row,
        technique or f"SOURCE {number}",
        family=family,
        methods=methods,
        objects=objects,
        lemmas=lemmas,
        domains=["COMB"] if topic == "C" else ["ALG"],
    )
    return row


def selected(cid):
    return set(
        _completion_quick_update_apply_layer_filter(
            ContestProblemStatement.objects.all(),
            raw_kind="concepts",
            raw_tag=cid,
        ).values_list("pk", flat=True),
    )


def gaps(user):
    cache.clear()
    return technique_progress_gap_rows_for_benchmark_export(
        request_user=user,
        raw_kind="all",
        raw_topic="combinatorics",
    )


def test_complete_namespaced_catalog_and_cache_hash():
    assert len(catalog_concept_ids("Combinatorics")) == len(COMBINATORICS_CONCEPTS) == 358
    assert len(catalog_concept_ids("COMB", scope="all")) == 358
    assert len(ALGEBRA_CONCEPTS) == 180
    assert not set(ALGEBRA_CONCEPTS) & set(COMBINATORICS_CONCEPTS)
    assert all(cid.startswith("comb-") for cid in COMBINATORICS_CONCEPTS)
    assert (
        hashlib.sha256(
            b"".join(
                path.read_bytes()
                for path in (
                    CATALOG_PATH,
                    NUMBER_THEORY_CATALOG_PATH,
                    GEOMETRY_CATALOG_PATH,
                    COMBINATORICS_CATALOG_PATH,
                )
            ),
        ).hexdigest()
        == CATALOG_SHA256
    )
    keys = [(p["kind"], p["label_key"]) for c in COMBINATORICS_CONCEPTS.values() for p in c["profiles"]]
    assert len(keys) == len(set(keys)) == 386


@pytest.mark.parametrize(
    ("kind", "label", "expected"),
    [
        ("method", "AM-GM", "comb-am-gm"),
        ("lemma", "Hall's theorem", "comb-hall-theorem"),
        ("method", "HALL CONDITION", "comb-hall-theorem"),
        ("technique", "Orbit counting", "comb-burnside-lemma"),
        ("canonical_subtopic", "Variance", "comb-second-moment"),
        ("canonical_subtopic", "Binomial coefficients", "comb-binomial-coefficients"),
        ("method", "F_2 LINEAR ALGEBRA", "comb-f2-linear-algebra"),
        ("method", "EXTREMAL METHOD", "comb-extremal-principle"),
    ],
)
def test_reviewed_exact_role_aliases(kind, label, expected):
    assert concept_for(kind, label, topic="Combinatorics") == expected
    assert not concept_for(kind, label + " UNREVIEWED", topic="Combinatorics")
    assert concept_for("method", "AM-GM") == "am-gm"


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        ("lemma", "Hall"),
        ("lemma", "Hall subgroup"),
        ("lemma", "Orientation theorem"),
        ("lemma", "Fixed point theorem"),
        ("lemma", "Gallai theorem"),
        ("lemma", "Zykov"),
        ("method", "cycle decomposition"),
        ("object", "transversals"),
        ("object", "ordered partitions/compositions"),
        ("technique", "partition counting"),
    ],
)
def test_ambiguous_or_excluded_names_are_not_global_aliases(kind, label):
    assert not concept_for(kind, label, topic="Combinatorics")


def test_shared_profiles_preserve_established_subject_ownership():
    assert concept_for_benchmark("lemma", "am-gm") == "am-gm"
    assert concept_for_benchmark("lemma", "am-gm", topic="Combinatorics") == "comb-am-gm"
    assert concept_for_benchmark("lemma", "hall", topic="Combinatorics") == "comb-hall-theorem"
    assert not concept_for_benchmark("object", "transversals", topic="Combinatorics")
    assert not concept_for_benchmark("object", "cycle-decomposition", topic="Combinatorics")


def test_catalog_and_profile_gets_preserve_every_original_benchmark_value(client, retained_profiles):
    client.force_login(UserFactory())
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    aliases = list(TechniqueBenchmarkAlias.objects.values())
    for params, expected in [
        ({"area": "Combinatorics"}, 358),
        ({"area": "Combinatorics", "view": "profiles"}, 470),
        ({"area": "Combinatorics", "q": "Hall's marriage"}, 1),
        ({"row_key": "concept:comb-orbit-counting"}, 1),
    ]:
        response = client.get(reverse("pages:technique_benchmark_list"), params)
        assert response.status_code == HTTPStatus.OK
        assert response.context["technique_benchmark_total"] == expected
    response = client.get(reverse("pages:technique_benchmark_list"), {"area": "Combinatorics", "page": 2})
    assert response.context["page_obj"].number == 2
    assert list(TechniqueBenchmark.objects.order_by("pk").values()) == before
    assert list(TechniqueBenchmarkAlias.objects.values()) == aliases
    assert TechniqueBenchmark.objects.count() == len(retained_profiles) == 507


def test_all_profiles_remain_available_and_missing_assessments_stay_unrated(retained_profiles):
    rows = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(),
        catalog_filters={"topic": "Combinatorics"},
    )["technique_benchmark_rows"]
    assert len(rows) == 358
    displayed = [pid for row in rows for pid in row["profile_ids"]]
    assert len(displayed) == len(set(displayed)) == 386
    assert TechniqueBenchmark.objects.exclude(pk__in=displayed).count() == 121
    no_profiles = [row for row in rows if not row["profile_ids"]]
    assert len(no_profiles) == 145
    assert all(not row["chartable"] and row["benchmark_id"] is None for row in no_profiles)
    assert all(row["benchmark_id"] is None for row in rows if row["profile_conflicts"])


def test_runtime_rating_drift_fails_closed_without_rewriting_profiles(retained_profiles):
    assert COMBINATORICS_CONCEPTS["comb-am-gm"]["preferred"]
    member = TechniqueBenchmark.objects.get(pk=140)
    member.concept_load = (member.concept_load % 5) + 1
    member.save()
    before = list(TechniqueBenchmark.objects.order_by("pk").values())
    rows = build_technique_benchmark_dashboard_context(
        TechniqueBenchmark.objects.all(),
        catalog_filters={"topic": "Combinatorics"},
    )["technique_benchmark_rows"]
    row = next(r for r in rows if r["concept_id"] == "comb-am-gm")
    assert row["benchmark_id"] is None
    assert not row["chartable"]
    scored = _score_gap_rows(
        _enrich_gap_rows_with_benchmarks(
            [
                {"concept_id": "comb-am-gm", "label": "AM-GM", "remaining": 3, "total": 3},
            ],
        ),
        target_profile="national",
    )[0]
    assert scored["priority_score"] is None
    assert list(TechniqueBenchmark.objects.order_by("pk").values()) == before


def test_missing_reference_does_not_fall_back_to_another_role(retained_profiles):
    TechniqueBenchmark.objects.filter(pk=COMBINATORICS_CONCEPTS["comb-am-gm"]["canonical_benchmark_id"]).delete()
    row = _enrich_gap_rows_with_benchmarks(
        [
            {"concept_id": "comb-am-gm", "label": "AM-GM", "remaining": 2, "total": 2},
        ],
    )[0]
    assert row["_benchmark"] is None
    assert row["concept_profile_conflict"]


def test_gap_union_practice_and_preview_agree_and_problem_links_are_unchanged(client):
    user = UserFactory()
    client.force_login(user)
    both = statement(1, technique="GRAPH MATCHING", methods=["HALL CONDITION"], lemmas=["HALL"])
    method = statement(2, methods=["HALL CONDITION"])
    lemma = statement(3, lemmas=["HALL'S THEOREM"])
    statement(4, methods=["HALL CONDITION"], topic="A")
    statement(5, lemmas=["HALL"])
    rebuild_technique_progress_catalog()
    UserProblemCompletion.objects.create(user=user, statement=both, status=UserProblemCompletion.Status.SOLVED)
    before = {
        model: list(model.objects.order_by("pk").values())
        for model in (
            ContestProblemStatement,
            StatementTopicTechnique,
            UserProblemCompletion,
        )
    }
    row = next(r for r in gaps(user) if r.get("concept_id") == "comb-hall-theorem")
    assert (row["total"], row["solved"], row["remaining"]) == (3, 1, 2)
    assert selected("comb-hall-theorem") == {both.pk, method.pk, lemma.pk}
    assert client.get(row["practice_url"]).status_code == HTTPStatus.OK
    preview = next(
        r
        for r in _scoped_subtopic_gap_rows(user=user, gap_topic="combinatorics")
        if r["label"] == "Hall's marriage theorem"
    )
    assert (preview["total"], preview["remaining"]) == (3, 2)
    assert all(list(model.objects.order_by("pk").values()) == values for model, values in before.items())


def test_graph_and_permutation_cycle_contexts_stay_separate_on_one_problem():
    user = UserFactory()
    graph = statement(1, technique="CYCLE DECOMPOSITION", methods=["CYCLE DECOMPOSITION"])
    permutation = statement(
        2,
        technique="PERMUTATION CODES",
        family="Combinatorial algebra and counting",
        methods=["CYCLE DECOMPOSITION"],
    )
    both = statement(3, technique="CYCLE DECOMPOSITION", methods=["CYCLE DECOMPOSITION"])
    add_tag(both, "PERMUTATION CODES", family="Combinatorial algebra and counting", methods=["CYCLE DECOMPOSITION"])
    rebuild_technique_progress_catalog()
    rows = {r.get("concept_id"): r for r in gaps(user) if r.get("concept_id")}
    assert rows["comb-cycle-decomposition"]["total"] == 2
    assert rows["comb-permutation-cycle-decomposition"]["total"] == 2
    assert selected("comb-cycle-decomposition") == {graph.pk, both.pk}
    assert selected("comb-permutation-cycle-decomposition") == {permutation.pk, both.pk}
    previews = _scoped_subtopic_gap_rows(user=user, gap_topic="combinatorics")
    assert not any(
        r["label"] == "Permutation cycle decomposition" and r["canonical_subtopic_labels"] == ["Graph theory"]
        for r in previews
    )


def test_transversal_meanings_use_their_exact_source_context():
    user = UserFactory()
    hitting = statement(
        1,
        technique="TRANSVERSALS",
        family="Set systems, posets, and order theory",
        objects=["TRANSVERSALS"],
    )
    sdr = statement(
        2,
        technique="HALL-TYPE REASONING",
        family="Combinatorial algebra and counting",
        objects=["TRANSVERSALS"],
    )
    geometric = statement(
        3,
        technique="GEOMETRIC TRANSVERSALS",
        family="Combinatorial and discrete geometry",
        objects=["TRANSVERSALS"],
    )
    statement(4, objects=["TRANSVERSALS"])
    rebuild_technique_progress_catalog()
    rows = {r.get("concept_id"): r for r in gaps(user) if r.get("concept_id")}
    for cid, row in [("comb-hitting-sets", hitting), ("comb-sdr", sdr), ("comb-stabbing", geometric)]:
        assert rows[cid]["total"] == 1
        assert selected(cid) == {row.pk}


def test_context_does_not_leak_between_two_unrelated_tags_on_the_same_problem():
    user = UserFactory()
    row = statement(1, technique="GRAPH MATCHING")
    add_tag(row, "OTHER SOURCE", lemmas=["HALL"])
    rebuild_technique_progress_catalog()
    assert not selected("comb-hall-theorem")
    assert not any(r.get("concept_id") == "comb-hall-theorem" for r in gaps(user))


def test_secondary_subjects_and_retired_deep_links_keep_problem_membership(client):
    client.force_login(UserFactory())
    row = statement(1, methods=["VARIANCE METHOD"], topic="A")
    tag = row.statement_topic_techniques.get()
    tag.domains = ["ALG", "COMB"]
    tag.save()
    rebuild_technique_progress_catalog()
    assert selected("comb-variance") == selected("comb-second-moment") == {row.pk}
    response = client.get(reverse("pages:technique_benchmark_list"), {"row_key": "concept:comb-variance"})
    assert response.context["technique_benchmark_rows"][0]["concept_id"] == "comb-second-moment"
    assert not selected("comb-transversals")


def test_linked_problem_fallback_and_statement_completion_precedence():
    user = UserFactory()
    problem = ProblemSolveRecord.objects.create(year=2026, topic="C", mohs=10, contest="COMB", problem="P1")
    ProblemTopicTechnique.objects.create(
        record=problem,
        technique="GRAPH MATCHING",
        main_topic="COMB",
        domains=["COMB"],
        canonical_subtopic="Graph theory",
        lemma_theorem_tags=["HALL"],
    )
    row = ContestProblemStatement.objects.create(
        contest_name="FALLBACK",
        contest_year=2026,
        problem_number=1,
        problem_code="C1",
        topic="C",
        statement_latex="Find a matching.",
        linked_problem=problem,
        problem_uuid=problem.problem_uuid,
    )
    UserProblemCompletion.objects.create(user=user, problem=problem, status=UserProblemCompletion.Status.SOLVED)
    open_problem = statement(2, lemmas=["HALL'S THEOREM"])
    rebuild_technique_progress_catalog()
    assert selected("comb-hall-theorem") == {row.pk, open_problem.pk}
    assert next(r for r in gaps(user) if r.get("concept_id") == "comb-hall-theorem")["solved"] == 1
    UserProblemCompletion.objects.create(user=user, statement=row, status=UserProblemCompletion.Status.ATTEMPTED)
    assert next(r for r in gaps(user) if r.get("concept_id") == "comb-hall-theorem")["solved"] == 0
    add_tag(row, "OTHER SOURCE", lemmas=["HALL"])
    rebuild_technique_progress_catalog()
    assert selected("comb-hall-theorem") == {open_problem.pk}
    row.refresh_from_db()
    assert row.linked_problem_id == problem.pk
    assert row.problem_uuid == problem.problem_uuid


def test_import_preview_and_write_feed_the_same_concept_members():
    raw = "COMB - HALL; VARIANCE"
    preview = prepare_topic_tag_entries(raw, topic="C", active=True, problem_uuid=None, canonicalize=False)
    write = prepare_topic_tag_entries(raw, topic="C", active=True, problem_uuid=None, canonicalize=True)
    assert preview == write
    ids = {
        concept_for(kind, label, topic="Combinatorics")
        for row in preview
        for kind, labels in (
            ("technique", [row["technique"]]),
            ("method", row["technique_tags"]),
        )
        for label in labels
    }
    assert {"comb-matching", "comb-second-moment"} <= ids


@pytest.mark.parametrize(("primary", "linked", "expected"), [("C", "A", True), ("A", "C", False)])
def test_blank_domain_fallback_uses_statement_topic_before_linked_problem_topic(primary, linked, expected):
    user = UserFactory()
    problem = ProblemSolveRecord.objects.create(year=2026, topic=linked, mohs=10, contest="SOURCE", problem="P1")
    ProblemTopicTechnique.objects.create(
        record=problem,
        technique="GRAPH MATCHING",
        main_topic="",
        domains=[],
        canonical_subtopic="Graph theory",
        lemma_theorem_tags=["HALL"],
    )
    row = ContestProblemStatement.objects.create(
        contest_name="TOPIC PRECEDENCE",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        topic=primary,
        statement_latex="Find the matching.",
        linked_problem=problem,
    )
    rebuild_technique_progress_catalog()
    assert selected("comb-hall-theorem") == ({row.pk} if expected else set())
    assert any(r.get("concept_id") == "comb-hall-theorem" for r in gaps(user)) == expected


def test_catalog_is_authenticated_and_navigation_exposes_both_views(client):
    url = reverse("pages:technique_benchmark_list")
    assert client.get(url, {"area": "Combinatorics"}).status_code == HTTPStatus.FOUND
    client.force_login(UserFactory())
    html = client.get(url, {"area": "Combinatorics"}).content.decode()
    assert "Combinatorics concept catalog" in html
    assert "Combinatorics role profiles" in html


def test_unfiltered_map_preserves_every_profile_across_all_subject_catalogs():
    profiles = {}
    for name in ["algebra", "number_theory", "geometry", "combinatorics"]:
        for row in json.loads((DATA / f"{name}_concept_benchmarks_v1.json").read_text()):
            profiles[row["id"]] = row
    TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row) for row in profiles.values()])
    context = build_technique_benchmark_dashboard_context(TechniqueBenchmark.objects.all())
    displayed = [pid for row in context["technique_benchmark_rows"] for pid in row["profile_ids"]]
    assert len(displayed) == len(set(displayed)) == len(profiles)
    assert set(displayed) == set(profiles)
