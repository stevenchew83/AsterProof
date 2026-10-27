"""Reviewed algebra cleanup: read-only planning, transactional apply, and import parity."""

import hashlib
import json
from copy import deepcopy
from io import StringIO

import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_aliases import load_policy
from inspinia.pages.algebra_tag_aliases import normalize_tag_fields
from inspinia.pages.algebra_tag_cleanup import build_cleanup_report
from inspinia.pages.algebra_tag_cleanup import projected_snapshot
from inspinia.pages.algebra_tag_cleanup_db import apply_reviewed_report
from inspinia.pages.algebra_tag_cleanup_db import capture_snapshot
from inspinia.pages.algebra_tag_imports import normalization_active
from inspinia.pages.algebra_tag_search import tag_token_query
from inspinia.pages.management.commands.cleanup_algebra_tags import DEFAULT_PLAN
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.models import TechniqueProgressCatalogState
from inspinia.pages.problem_import import build_parsed_preview_payload
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.pages.problem_import import sync_problem_topic_techniques
from inspinia.pages.statement_metadata_backfill import sync_statement_topic_techniques
from inspinia.pages.subtopic_cleanup import apply_subtopic_cleanup
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.pages.topic_tag_analytics import topic_tag_analytics_data

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def reviewed_plan():
    return json.loads(DEFAULT_PLAN.read_bytes())


@pytest.fixture
def benchmark_metadata(reviewed_plan):
    activation = {(r["kind"], r["alias_key"]): r["target_label_key"] for r in load_policy()["activation_aliases"]}
    records = {}
    for action in reviewed_plan["benchmark_alias_actions"]:
        target = action["candidate_after"]
        key = activation.get((target["kind"], target["alias_key"]), target["alias_key"])
        records[target["benchmark_id"]] = {"kind": target["kind"], "label_key": key}
    for action in reviewed_plan["benchmark_alias_actions"]:
        if action["before"]:
            old = action["before"]
            records.setdefault(
                old["benchmark_id"],
                {"kind": old["kind"], "label_key": f"legacy-{old['benchmark_id']}"},
            )
    TechniqueBenchmark.objects.bulk_create(
        [TechniqueBenchmark(id=rid, label=fields["label_key"], **fields) for rid, fields in records.items()],
    )
    TechniqueBenchmarkAlias.objects.bulk_create(
        [
            TechniqueBenchmarkAlias(**action["before"])
            for action in reviewed_plan["benchmark_alias_actions"]
            if action["before"]
        ],
    )
    return records


def activate(reviewed_plan):
    for action in reviewed_plan["benchmark_alias_actions"]:
        after = {key: value for key, value in action["candidate_after"].items() if key != "id"}
        if action["action"] == "insert":
            TechniqueBenchmarkAlias.objects.create(**after)
        else:
            TechniqueBenchmarkAlias.objects.filter(id=action["alias_id"]).update(**after)


@pytest.fixture
def algebra_problem():
    return ProblemSolveRecord.objects.create(year=2025, contest="TEST", problem="P1", topic="A", mohs=10)


def statement_for(problem):
    return ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2025,
        contest_name="TEST",
        problem_number=1,
        problem_code="P1",
        topic="A",
        statement_latex="Find x.",
    )


def tag(problem, technique="SUBSTITUTIONS", **extra):
    fields = {
        "record": problem,
        "technique": technique,
        "raw_tag": technique,
        "domains": ["ALG"],
        "normalization_status": "alias",
        "normalization_confidence": "high",
        **extra,
    }
    return ProblemTopicTechnique.objects.create(**fields)


def report_for(plan):
    return build_cleanup_report(
        capture_snapshot(plan),
        plan,
        policy=load_policy(),
        plan_sha256=hashlib.sha256(DEFAULT_PLAN.read_bytes()).hexdigest(),
    )


def apply_report(report, plan, tmp_path):
    return apply_reviewed_report(
        report,
        plan,
        policy=load_policy(),
        plan_sha256=load_policy()["reviewed_plan_sha256"],
        audit_directory=tmp_path / "audit",
    )


def test_default_dry_run_never_writes(benchmark_metadata, algebra_problem, reviewed_plan):
    original = tag(algebra_problem)
    before = list(TechniqueBenchmarkAlias.objects.values())
    call_command("cleanup_algebra_tags", stdout=StringIO())
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTIONS"
    assert list(TechniqueBenchmarkAlias.objects.values()) == before
    assert not normalization_active()


def test_apply_requires_review_hash_and_audit_path():
    with pytest.raises(CommandError, match="Apply requires"):
        call_command("cleanup_algebra_tags", apply=True)


def test_captured_snapshot_cannot_be_applied(tmp_path):
    with pytest.raises(CommandError, match="Captured snapshots"):
        call_command("cleanup_algebra_tags", apply=True, snapshot_input=tmp_path / "anything.json")


def test_modified_policy_file_is_rejected(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{}")
    with pytest.raises(CommandError, match="plan hash"):
        call_command("cleanup_algebra_tags", plan=path)


def test_report_path_never_overwrites_existing_file(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("reviewed")
    with pytest.raises(CommandError):
        call_command("cleanup_algebra_tags", report=path)
    assert path.read_text() == "reviewed"


def test_atomic_apply_is_lossless_and_idempotent(benchmark_metadata, algebra_problem, reviewed_plan, tmp_path):
    first = tag(algebra_problem, object_tags=["SUBSTITUTION"])
    second = tag(algebra_problem, "SUBSTITUTION TRICKS", proof_roles=["REDUCTION"])
    linked = statement_for(algebra_problem)
    report = report_for(reviewed_plan)
    assert not report["conflicts"]
    receipt = apply_report(report, reviewed_plan, tmp_path)
    assert receipt["status"] == "committed"
    first.refresh_from_db()
    assert first.technique == "SUBSTITUTION"
    assert first.raw_tag == "SUBSTITUTIONS; SUBSTITUTION TRICKS"
    assert first.proof_roles == ["REDUCTION"]
    assert not ProblemTopicTechnique.objects.filter(id=second.id).exists()
    assert linked.problem_uuid == algebra_problem.problem_uuid
    assert normalization_active()
    again = report_for(reviewed_plan)
    assert not again["tag_actions"]
    assert not again["alias_actions"]
    assert again["identity"]["guard_fingerprints"] == report["identity"]["guard_fingerprints"]
    audit = json.loads((tmp_path / "audit" / "before-and-after.json").read_text())
    assert {a["row_id"] for a in audit["tag_actions"]} == {first.id, second.id}


def test_stale_before_image_refuses_all_writes(benchmark_metadata, algebra_problem, reviewed_plan, tmp_path):
    original = tag(algebra_problem)
    report = report_for(reviewed_plan)
    ProblemTopicTechnique.objects.filter(id=original.id).update(raw_tag="changed after review")
    with pytest.raises(AlgebraAliasError, match="before-values changed"):
        apply_report(report, reviewed_plan, tmp_path)
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTIONS"
    assert not normalization_active()


def test_apply_rolls_back_aliases_and_merge_on_write_failure(
    benchmark_metadata,
    algebra_problem,
    reviewed_plan,
    tmp_path,
    monkeypatch,
):
    first = tag(algebra_problem)
    second = tag(algebra_problem, "SUBSTITUTION TRICKS")
    report = report_for(reviewed_plan)

    def fail(*args, **kwargs):
        message = "injected write failure"
        raise RuntimeError(message)

    monkeypatch.setattr(ProblemTopicTechnique.objects, "bulk_update", fail)
    with pytest.raises(RuntimeError, match="injected"):
        apply_report(report, reviewed_plan, tmp_path)
    assert set(ProblemTopicTechnique.objects.filter(id__in=[first.id, second.id]).values_list("id", flat=True)) == {
        first.id,
        second.id,
    }
    assert not normalization_active()
    assert json.loads((tmp_path / "audit" / "receipt.json").read_text())["status"] == "failed_before_commit"


def test_post_commit_receipt_failure_is_not_reported_as_rollback(
    benchmark_metadata,
    algebra_problem,
    reviewed_plan,
    tmp_path,
    monkeypatch,
):
    from inspinia.pages import algebra_tag_cleanup_db as boundary

    original = tag(algebra_problem)
    report = report_for(reviewed_plan)
    write = boundary._write_audit  # noqa: SLF001 -- inject a post-commit filesystem failure

    def fail_committed(path, value, **kwargs):
        if value.get("status") == "committed":
            message = "injected receipt failure"
            raise OSError(message)
        write(path, value, **kwargs)

    monkeypatch.setattr(boundary, "_write_audit", fail_committed)
    with pytest.raises(AlgebraAliasError, match="reconcile"):
        apply_report(report, reviewed_plan, tmp_path)
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTION"
    assert normalization_active()
    assert json.loads((tmp_path / "audit" / "receipt.json").read_text())["status"] == "prepared"


def test_invalid_inactive_and_other_topics_are_excluded(benchmark_metadata, algebra_problem, reviewed_plan):
    invalid = tag(algebra_problem, normalization_status="invalid")
    algebra_problem.is_active = False
    algebra_problem.save(update_fields=["is_active"])
    other = ProblemSolveRecord.objects.create(year=2025, contest="TEST", problem="P2", topic="C", mohs=10)
    tag(other)
    report = report_for(reviewed_plan)
    assert not report["tag_actions"]
    invalid.refresh_from_db()
    assert invalid.technique == "SUBSTITUTIONS"


def test_outside_alias_usage_blocks_application(benchmark_metadata, reviewed_plan):
    outside = ProblemSolveRecord.objects.create(year=2025, contest="OTHER", problem="P1", topic="C", mohs=10)
    tag(outside, "INVARIANT")
    assert any(c["type"] == "OUTSIDE_TOPIC_BENCHMARK_COVERAGE" for c in report_for(reviewed_plan)["conflicts"])


def test_policy_is_inactive_before_maintenance_metadata(benchmark_metadata, algebra_problem):
    sync_problem_topic_techniques(
        record=algebra_problem,
        raw_topic_tags="ALG - SUBSTITUTION TRICKS",
        replace_tags=True,
    )
    assert not normalization_active()
    assert not algebra_problem.topic_techniques.filter(technique="SUBSTITUTION").exists()


def test_partial_activation_fails_closed(benchmark_metadata, reviewed_plan):
    target = next(a["candidate_after"] for a in reviewed_plan["benchmark_alias_actions"] if a["action"] == "insert")
    TechniqueBenchmarkAlias.objects.create(**target)
    with pytest.raises(AlgebraAliasError, match="metadata is incomplete"):
        normalization_active()


@pytest.mark.parametrize("replace", [True, False])
def test_import_reuses_canonical_row_and_retains_both_sources(
    benchmark_metadata,
    algebra_problem,
    reviewed_plan,
    replace,
):
    activate(reviewed_plan)
    sync_problem_topic_techniques(
        record=algebra_problem,
        raw_topic_tags="ALG - SUBSTITUTIONS, SUBSTITUTION TRICKS",
        replace_tags=replace,
    )
    assert algebra_problem.topic_techniques.count() == 1
    row = algebra_problem.topic_techniques.get()
    assert row.technique == "SUBSTITUTION"
    assert "SUBSTITUTIONS" in row.raw_tag
    assert "SUBSTITUTION TRICKS" in row.raw_tag
    sync_problem_topic_techniques(record=algebra_problem, raw_topic_tags="ALG - SUBSTITUTION", replace_tags=False)
    assert algebra_problem.topic_techniques.count() == 1


def test_statement_import_uses_linked_topic_fallback(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    statement = statement_for(algebra_problem)
    statement.topic = ""
    statement.save(update_fields=["topic"])
    sync_statement_topic_techniques(statement=statement, raw_topic_tags="ALG - SUBSTITUTION TRICKS", replace_tags=True)
    assert statement.statement_topic_techniques.get().technique == "SUBSTITUTION"


def test_preview_and_import_show_same_canonical_technique(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    frame = pd.DataFrame(
        [
            {
                "YEAR": 2025,
                "TOPIC": "A",
                "MOHS": 10,
                "CONTEST": "TEST",
                "PROBLEM": "P1",
                "CONTEST PROBLEM": "TEST 2025 P1",
                "Topic tags": "ALG - SUBSTITUTIONS, SUBSTITUTION TRICKS",
                "PROBLEM UUID": str(algebra_problem.problem_uuid),
            },
        ],
    )
    preview = build_parsed_preview_payload(frame, algebra_aliases_active=True)
    import_problem_dataframe(frame, replace_tags=True)
    assert preview["total_parsed_techniques"] == 1
    assert {r["technique"] for r in preview["techniques"]} == set(
        algebra_problem.topic_techniques.values_list("technique", flat=True),
    )


def test_search_aliases_do_not_create_extra_coverage_facts(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    statement = statement_for(algebra_problem)
    StatementTopicTechnique.objects.create(
        statement=statement,
        technique="SUBSTITUTION",
        domains=["ALG"],
        raw_tag="SUBSTITUTIONS; SUBSTITUTION TRICKS",
    )
    rebuild_technique_progress_catalog(statement_ids=[statement.id])
    facts = statement.technique_progress_facts.filter(layer="technique")
    assert facts.count() == 1
    assert facts.get().label == "SUBSTITUTION"
    assert "SUBSTITUTION TRICKS" in facts.get().search_text
    assert "SUBSTITUTIONS" in facts.get().search_text


def test_legacy_cleanup_and_backfill_cannot_undo_canonical_algebra(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    canonical = tag(algebra_problem, "SUBSTITUTION", technique_tags=["SUBSTITUTION"])
    apply_subtopic_cleanup()
    call_command("backfill_topic_tag_layers", stdout=StringIO())
    canonical.refresh_from_db()
    assert canonical.technique == "SUBSTITUTION"
    assert canonical.technique_tags == ["SUBSTITUTION"]


def test_source_overflow_aborts_import_without_truncating(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    original = tag(algebra_problem, "SUBSTITUTION")
    original.raw_tag = "A" * 510
    original.save(update_fields=["raw_tag"])
    with pytest.raises(AlgebraAliasError, match="512"):
        sync_problem_topic_techniques(
            record=algebra_problem,
            raw_topic_tags="ALG - SUBSTITUTION TRICKS",
            replace_tags=False,
        )
    original.refresh_from_db()
    assert original.raw_tag == "A" * 510


def test_apply_requires_standalone_transaction(reviewed_plan, tmp_path):
    with transaction.atomic(), pytest.raises(AlgebraAliasError, match="standalone"):
        apply_report({"conflicts": []}, reviewed_plan, tmp_path)


def test_apmo_normalization_is_stable_uuid_guarded():
    policy = load_policy()
    fields = {"technique": "INJECTIVITY TRICKS", "normalization_status": "needs_review", "technique_tags": []}
    specific = normalize_tag_fields(fields, topic="A", problem_uuid=policy["specificity"]["problem_uuid"])
    assert specific["technique"] == "INJECTIVITY UP TO SIGN"
    assert specific["technique_tags"] == ["INJECTIVITY UP TO SIGN"]
    other = normalize_tag_fields(fields, topic="A", problem_uuid="different")
    assert other["technique"] == "INJECTIVITY"


def test_canonicalization_is_pure_and_idempotent():
    fields = {
        "technique": "SUBSTITUTIONS",
        "normalization_status": "alias",
        "domains": ["ALGEBRA"],
        "technique_tags": ["SUBSTITUTION TRICK", "SUBSTITUTION"],
    }
    before = deepcopy(fields)
    after = normalize_tag_fields(fields, topic="A")
    assert fields == before
    assert normalize_tag_fields(after, topic="A") == after


def test_catalog_is_marked_stale_on_apply(benchmark_metadata, algebra_problem, reviewed_plan, tmp_path):
    tag(algebra_problem)
    statement_for(algebra_problem)
    state, _ = TechniqueProgressCatalogState.objects.get_or_create(singleton_key=1)
    state.needs_rebuild = False
    state.last_refreshed_at = timezone.now()
    state.save()
    apply_report(report_for(reviewed_plan), reviewed_plan, tmp_path)
    state.refresh_from_db()
    assert state.needs_rebuild


def test_projected_report_keeps_all_benchmark_numeric_fields(benchmark_metadata, algebra_problem, reviewed_plan):
    tag(algebra_problem)
    snapshot = capture_snapshot(reviewed_plan)
    report = report_for(reviewed_plan)
    projected = projected_snapshot(snapshot, report["tag_actions"], report["alias_actions"])
    assert projected["benchmarks"] == snapshot["benchmarks"]


def test_repeated_merge_import_keeps_provenance_identical(benchmark_metadata, algebra_problem, reviewed_plan):
    activate(reviewed_plan)
    sync_problem_topic_techniques(
        record=algebra_problem, raw_topic_tags="ALG - SUBSTITUTIONS, SUBSTITUTION TRICKS", replace_tags=True,
    )
    before = algebra_problem.topic_techniques.get().raw_tag
    for _ in range(3):
        sync_problem_topic_techniques(
            record=algebra_problem, raw_topic_tags="ALG - SUBSTITUTIONS, SUBSTITUTION TRICKS", replace_tags=False,
        )
    assert algebra_problem.topic_techniques.get().raw_tag == before


@pytest.mark.parametrize("source", ["INJECTIVITY TRICKS", "INJECTIVITY UP TO SIGN"])
def test_apmo_reimport_does_not_restore_umbrella_name(
    benchmark_metadata, algebra_problem, reviewed_plan, source,
):
    activate(reviewed_plan)
    algebra_problem.problem_uuid = load_policy()["specificity"]["problem_uuid"]
    algebra_problem.save(update_fields=["problem_uuid"])
    statement = statement_for(algebra_problem)
    sync_problem_topic_techniques(record=algebra_problem, raw_topic_tags=f"ALG - {source}", replace_tags=True)
    sync_statement_topic_techniques(statement=statement, raw_topic_tags=f"ALG - {source}", replace_tags=True)
    assert set(algebra_problem.topic_techniques.values_list("technique", flat=True)) == {"INJECTIVITY UP TO SIGN"}
    assert set(statement.statement_topic_techniques.values_list("technique", flat=True)) == {"INJECTIVITY UP TO SIGN"}


def test_precommit_audit_failure_causes_no_database_changes(
    benchmark_metadata, algebra_problem, reviewed_plan, tmp_path, monkeypatch,
):
    from inspinia.pages import algebra_tag_cleanup_db as boundary

    original = tag(algebra_problem)
    report = report_for(reviewed_plan)
    write = boundary._write_audit  # noqa: SLF001 -- inject an audit-disk failure before DML

    def fail_before_image(path, value, **kwargs):
        if path.name == "before-and-after.json":
            message = "injected audit failure"
            raise OSError(message)
        write(path, value, **kwargs)

    monkeypatch.setattr(boundary, "_write_audit", fail_before_image)
    with pytest.raises(OSError, match="injected audit"):
        apply_report(report, reviewed_plan, tmp_path)
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTIONS"
    assert not normalization_active()


def test_command_applies_only_the_exact_reviewed_report(
    benchmark_metadata, algebra_problem, reviewed_plan, tmp_path,
):
    original = tag(algebra_problem)
    report_path = tmp_path / "review.json"
    call_command("cleanup_algebra_tags", report=report_path, stdout=StringIO())
    with pytest.raises(CommandError, match="SHA-256"):
        call_command(
            "cleanup_algebra_tags", apply=True, review_report=report_path, expected_report_sha256="wrong",
            audit_directory=tmp_path / "unapproved-audit", stdout=StringIO(),
        )
    assert not (tmp_path / "unapproved-audit").exists()
    call_command(
        "cleanup_algebra_tags", apply=True, review_report=report_path,
        expected_report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
        audit_directory=tmp_path / "audit", stdout=StringIO(),
    )
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTION"


def test_database_search_accepts_old_alias_without_touching_other_topics(algebra_problem):
    canonical = tag(algebra_problem, "SUBSTITUTION", raw_tag="")
    outside = ProblemSolveRecord.objects.create(year=2025, contest="TEST", problem="P2", topic="C", mohs=10)
    tag(outside, "SUBSTITUTION", raw_tag="")
    assert list(ProblemTopicTechnique.objects.filter(tag_token_query("TRICKS", source="problem"))) == [canonical]
    statement = statement_for(algebra_problem)
    statement.topic = " "
    statement.save(update_fields=["topic"])
    mirror = StatementTopicTechnique.objects.create(statement=statement, technique="SUBSTITUTION")
    assert list(StatementTopicTechnique.objects.filter(tag_token_query("TRICKS", source="statement"))) == [mirror]


def test_merge_cannot_remove_a_differently_rated_source(benchmark_metadata, algebra_problem, reviewed_plan):
    TechniqueBenchmark.objects.create(kind="technique", label="Substitutions", label_key="substitutions")
    TechniqueBenchmark.objects.create(kind="technique", label="Substitution", label_key="substitution")
    tag(algebra_problem)
    tag(algebra_problem, "SUBSTITUTION")
    report = report_for(reviewed_plan)
    assert any(c["type"] == "BENCHMARK_BINDING_CHANGED" for c in report["conflicts"])


def test_alias_target_identity_is_verified_beyond_its_numeric_id(benchmark_metadata, reviewed_plan):
    rule = load_policy()["activation_aliases"][0]
    TechniqueBenchmark.objects.filter(kind=rule["target_kind"], label_key=rule["target_label_key"]).update(
        label_key="unrelated-concept",
    )
    report = report_for(reviewed_plan)
    assert any(c["type"] == "ACTIVATION_BENCHMARK_CHANGED" for c in report["conflicts"])


def test_report_for_another_database_cannot_be_applied(benchmark_metadata, algebra_problem, reviewed_plan, tmp_path):
    original = tag(algebra_problem)
    report = report_for(reviewed_plan)
    report["identity"]["target"]["database"] = "another-database"
    with pytest.raises(AlgebraAliasError, match="database target differs"):
        apply_report(report, reviewed_plan, tmp_path)
    original.refresh_from_db()
    assert original.technique == "SUBSTITUTIONS"


def test_grouped_analytics_search_retains_old_names(algebra_problem):
    tag(algebra_problem, "SUBSTITUTION", raw_tag="")
    data = topic_tag_analytics_data({"q": "SUBSTITUTION TRICKS", "contest": "", "topic": "", "year": "", "domain": ""})
    assert {row["technique"] for row in data["directory"]} == {"SUBSTITUTION"}


def test_catalog_only_rebuild_skips_independent_duplicate_report(algebra_problem, monkeypatch):
    statement_for(algebra_problem)
    tag(algebra_problem, "SUBSTITUTION")

    def fail_duplicate_refresh(**kwargs):
        pytest.fail("Catalog-only maintenance must not refresh the duplicate report")

    monkeypatch.setattr(
        "inspinia.pages.statement_duplicate_snapshot.refresh_statement_duplicate_snapshot",
        fail_duplicate_refresh,
    )
    call_command("recompute_technique_progress_catalog", catalog_only=True, stdout=StringIO())
    assert not TechniqueProgressCatalogState.objects.get(singleton_key=1).needs_rebuild
