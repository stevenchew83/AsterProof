"""Second-batch safeguards and the role-preserving canonical concept registry."""
# ruff: noqa: F811 -- pytest fixtures are intentionally imported and injected by name

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_cleanup import projected_snapshot
from inspinia.pages.algebra_tag_cleanup_db import apply_reviewed_report
from inspinia.pages.algebra_tag_cleanup_db import capture_snapshot
from inspinia.pages.algebra_tag_imports import vocabulary_active
from inspinia.pages.algebra_vocabulary import build_vocabulary_report
from inspinia.pages.algebra_vocabulary import load_vocabulary_plan
from inspinia.pages.algebra_vocabulary import vocabulary_operation_plan
from inspinia.pages.algebra_vocabulary import vocabulary_sha256
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.test_algebra_tag_cleanup import activate
from inspinia.pages.test_algebra_tag_cleanup import algebra_problem  # noqa: F401 -- shared pytest fixture
from inspinia.pages.test_algebra_tag_cleanup import benchmark_metadata  # noqa: F401 -- shared pytest fixture
from inspinia.pages.test_algebra_tag_cleanup import reviewed_plan  # noqa: F401 -- shared pytest fixture
from inspinia.pages.test_algebra_tag_cleanup import statement_for
from inspinia.pages.test_algebra_tag_cleanup import tag

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def vocabulary_metadata(benchmark_metadata, reviewed_plan):
    path = Path(__file__).parent / "testdata" / "algebra_vocabulary_benchmarks_v2.json"
    for row in json.loads(path.read_text()):
        if TechniqueBenchmark.objects.filter(pk=row["id"]).exists():
            TechniqueBenchmark.objects.filter(pk=row["id"]).update(**row)
        else:
            TechniqueBenchmark.objects.bulk_create([TechniqueBenchmark(**row)])
    activate(reviewed_plan)


def vocabulary_report():
    policy = load_vocabulary_plan()
    plan = vocabulary_operation_plan(policy)
    return build_vocabulary_report(capture_snapshot(plan), plan, policy=policy, plan_sha256=vocabulary_sha256())


def apply_vocabulary(report, tmp_path):
    return apply_reviewed_report(
        report,
        vocabulary_operation_plan(load_vocabulary_plan()),
        policy=load_vocabulary_plan(),
        plan_sha256=vocabulary_sha256(),
        audit_directory=tmp_path / "audit",
        report_builder=build_vocabulary_report,
    )


def install_vocabulary_aliases():
    for rule in load_vocabulary_plan()["activation_aliases"]:
        TechniqueBenchmarkAlias.objects.create(
            **{key: rule[key] for key in ("kind", "alias_label", "alias_key", "benchmark_id", "reason")},
        )


def test_vocabulary_default_command_is_read_only(vocabulary_metadata, algebra_problem):
    original = tag(algebra_problem, "TRIG SUBSTITUTION", technique_tags=["TRIG SUBSTITUTION"])
    before = list(TechniqueBenchmarkAlias.objects.values())
    call_command("consolidate_algebra_tags", stdout=StringIO())
    original.refresh_from_db()
    assert original.technique == "TRIG SUBSTITUTION"
    assert list(TechniqueBenchmarkAlias.objects.values()) == before
    assert not vocabulary_active()


def test_vocabulary_apply_requires_immutable_review():
    with pytest.raises(CommandError, match="Apply requires"):
        call_command("consolidate_algebra_tags", apply=True)


def test_vocabulary_apply_updates_mirrors_preserves_sources_and_is_idempotent(
    vocabulary_metadata,
    algebra_problem,
    tmp_path,
):
    row = tag(
        algebra_problem,
        "COEFFICIENT MATCH",
        technique_tags=["COEFFICIENT MATCH", "COEFFICIENT COMPARISON"],
        canonical_subtopic="Combinatorial and discrete geometry",
    )
    statement = statement_for(algebra_problem)
    mirror = StatementTopicTechnique.objects.create(
        statement=statement,
        **{
            key: getattr(row, key)
            for key in (
                "technique",
                "technique_tags",
                "canonical_subtopic",
                "domains",
                "raw_tag",
                "normalization_status",
                "normalization_confidence",
            )
        },
    )
    before_definitions = list(TechniqueBenchmark.objects.values())
    report = vocabulary_report()
    assert not report["conflicts"]
    assert report["benchmark_equivalences"][0]["rating_values_equal"]
    assert len(report["tag_actions"]) == len((row, mirror))
    assert apply_vocabulary(report, tmp_path)["status"] == "committed"
    for item in (row, mirror):
        item.refresh_from_db()
        assert item.technique_tags == ["COEFFICIENT COMPARISON"]
        assert item.canonical_subtopic == "Discrete and combinatorial geometry"
        assert item.raw_tag == "COEFFICIENT MATCH"
    assert list(TechniqueBenchmark.objects.values()) == before_definitions
    assert vocabulary_active()
    again = vocabulary_report()
    assert not again["conflicts"]
    assert again["tag_actions"] == again["alias_actions"] == []


def test_vocabulary_benchmark_drift_blocks_equivalence(vocabulary_metadata, algebra_problem):
    tag(algebra_problem, canonical_subtopic="Combinatorial and discrete geometry")
    TechniqueBenchmark.objects.filter(pk=457).update(concept_load=1)
    report = vocabulary_report()
    assert any(item["type"] == "EQUIVALENT_BENCHMARK_CHANGED" for item in report["conflicts"])


def test_vocabulary_outside_alias_use_blocks_apply(vocabulary_metadata):
    outside = ProblemSolveRecord.objects.create(year=2025, contest="OTHER", problem="P2", topic="G", mohs=10)
    tag(outside, technique_tags=["SIMPLE FACTORIZATION"])
    assert vocabulary_report()["conflicts"]


def test_vocabulary_rollback_does_not_activate_imports(vocabulary_metadata, algebra_problem, tmp_path):
    original = tag(algebra_problem, "TRIG SUBSTITUTION", technique_tags=["TRIG SUBSTITUTION"])
    report = vocabulary_report()
    with (
        patch(
            "inspinia.pages.algebra_tag_cleanup_db.queue_technique_progress_catalog_refresh", side_effect=RuntimeError,
        ),
        pytest.raises(RuntimeError),
    ):
        apply_vocabulary(report, tmp_path)
    original.refresh_from_db()
    assert original.technique == "TRIG SUBSTITUTION"
    assert not vocabulary_active()


def test_vocabulary_partial_activation_fails_closed_only_for_algebra(vocabulary_metadata):
    rule = load_vocabulary_plan()["activation_aliases"][0]
    TechniqueBenchmarkAlias.objects.create(
        **{key: rule[key] for key in ("kind", "alias_label", "alias_key", "benchmark_id", "reason")},
    )
    with pytest.raises(AlgebraAliasError, match="incomplete or changed"):
        prepare_topic_tag_entries(
            "ALG - TRIG SUBSTITUTION", topic="A", active=True, problem_uuid=None, canonicalize=True,
        )
    assert prepare_topic_tag_entries(
        "GEO - POWER OF A POINT",
        topic="G",
        active=True,
        problem_uuid=None,
        canonicalize=True,
    )


@pytest.mark.parametrize("raw", ["TRIG SUBSTITUTION", "TRIGONOMETRIC SUBSTITUTION"])
def test_vocabulary_import_accepts_old_and_canonical_names(vocabulary_metadata, raw):
    install_vocabulary_aliases()
    entries = prepare_topic_tag_entries(
        f"ALG - {raw}",
        topic="A",
        active=True,
        problem_uuid=None,
        canonicalize=True,
    )
    assert {item["technique"] for item in entries} == {"TRIGONOMETRIC SUBSTITUTION"}
    assert all("TRIGONOMETRIC SUBSTITUTION" in item["technique_tags"] for item in entries)


def test_vocabulary_excludes_invalid_inactive_and_outside_records(vocabulary_metadata, algebra_problem):
    invalid = tag(algebra_problem, "TRIG SUBSTITUTION", normalization_status="invalid")
    outside = ProblemSolveRecord.objects.create(year=2025, contest="OUTSIDE", problem="P1", topic="N", mohs=10)
    tag(outside, "TRIG SUBSTITUTION")
    inactive = ProblemSolveRecord.objects.create(
        year=2025,
        contest="INACTIVE",
        problem="P1",
        topic="A",
        mohs=10,
        is_active=False,
    )
    tag(inactive, "TRIG SUBSTITUTION")
    assert not vocabulary_report()["tag_actions"]
    invalid.refresh_from_db()
    assert invalid.normalization_status == "invalid"


def test_vocabulary_second_pass_projection_has_no_additional_actions(vocabulary_metadata, algebra_problem):
    tag(algebra_problem, "FACTOR TRICK", technique_tags=["FACTOR TRICK"])
    policy = load_vocabulary_plan()
    plan = vocabulary_operation_plan(policy)
    before = capture_snapshot(plan)
    report = build_vocabulary_report(before, plan, policy=policy, plan_sha256=vocabulary_sha256())
    after = projected_snapshot(before, report["tag_actions"], report["alias_actions"])
    again = build_vocabulary_report(after, plan, policy=policy, plan_sha256=vocabulary_sha256())
    assert not again["conflicts"]
    assert not again["tag_actions"]
    assert not again["alias_actions"]
