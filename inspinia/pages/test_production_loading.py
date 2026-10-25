# ruff: noqa: PLR2004, SLF001
"""Production-size loading safeguards and preservation of archive semantics."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages import statement_duplicate_snapshot as snapshots
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueProgressCatalogState
from inspinia.pages.statement_duplicates import build_statement_duplicate_report
from inspinia.pages.views import _statement_linker_payload
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_report_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    return client


def statement(number, text, *, year=2026, contest="Test", day="Day 1"):
    return ContestProblemStatement.objects.create(
        contest_year=year,
        contest_name=contest,
        problem_number=number,
        problem_code=f"P{number}",
        day_label=day,
        statement_latex=text,
    )


def test_duplicate_cold_get_never_reads_statement_bodies_or_rebuilds(admin_client):
    statement(1, "a large statement " * 1000)
    with (
        patch.object(snapshots, "refresh_statement_duplicate_snapshot", side_effect=AssertionError("GET rebuilt")),
        CaptureQueriesContext(connection) as queries,
    ):
        response = admin_client.get(reverse("pages:problem_statement_duplicates"))
    assert response.status_code == 200
    assert response.context["statement_duplicate_pending"] is True
    assert "does not mean there are no duplicates" in response.content.decode()
    assert not any('"statement_latex"' in q["sql"] for q in queries)


@pytest.mark.parametrize("popular_bucket_size", [2, 24, 25])
def test_disk_index_preserves_original_exact_and_similarity_results(popular_bucket_size):
    common = (
        "Let ABC be a triangle with circumcenter O. Prove that reflections across its sides lie on a common circle. "
    )
    for number in range(popular_bucket_size):
        statement(number + 1, common + f"Consider the particular configuration number {number}.")
    statement(100, "Determine all integers n such that n squared plus n plus one is prime.", year=2024)
    statement(101, "  DETERMINE all integers n such that n squared plus n plus one is prime.  ", year=2025)
    reference = build_statement_duplicate_report(
        list(ContestProblemStatement.objects.select_related("linked_problem")),
    )
    assert snapshots.refresh_statement_duplicate_snapshot(force=True)
    actual = snapshots.snapshot_context()
    assert actual["statement_duplicate_available"] is True
    assert actual["statement_duplicate_stats"] == {
        key: reference[key]
        for key in (
            "statement_total",
            "exact_duplicate_group_total",
            "exact_duplicate_row_total",
            "similar_pair_total",
        )
    }
    assert actual["statement_duplicate_similar_rows"] == reference["similar_pair_rows"]
    actual_groups = {row["problem_labels"]: row for row in actual["statement_duplicate_exact_rows"]}
    for expected in reference["exact_duplicate_rows"]:
        row = actual_groups[expected["problem_labels"]]
        for key in ("duplicate_count", "statement_length", "year_span_label", "preview", "problem_items"):
            assert row[key] == expected[key]


def test_duplicate_groups_and_large_group_members_remain_reachable():
    for number in range(27):
        statement(number + 1, f"Exact text for group {number}", year=2024)
        statement(number + 1, f"Exact text for group {number}", year=2025)
    for number in range(30):
        statement(number + 100, "One large exact group")
    assert snapshots.refresh_statement_duplicate_snapshot(force=True)
    first = snapshots.snapshot_context()
    second = snapshots.snapshot_context(page_number=2)
    assert len(first["statement_duplicate_exact_rows"]) == 25
    assert len(second["statement_duplicate_exact_rows"]) == 3
    assert first["statement_duplicate_stats"]["exact_duplicate_group_total"] == 28
    large = next(row for row in first["statement_duplicate_exact_rows"] if row["duplicate_count"] == 30)
    assert len(large["problem_items"]) == 25
    tail = snapshots.snapshot_context(group=large["group_key"], member_page=2)
    assert len(tail["statement_duplicate_exact_rows"][0]["problem_items"]) == 5
    assert tail["statement_duplicate_member_pages"] == 2


def test_duplicate_stale_report_is_served_without_recomputation():
    statement(1, "Repeated statement")
    statement(2, "Repeated statement")
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    statement(3, "New source data")
    with CaptureQueriesContext(connection) as queries:
        context = snapshots.snapshot_context()
    assert context["statement_duplicate_available"] is True
    assert context["statement_duplicate_stale"] is True
    assert context["statement_duplicate_stats"]["statement_total"] == 2
    assert len(queries) == 1


def test_duplicate_member_label_preserves_first_nonempty_link_from_reference():
    first_problem = ProblemSolveRecord.objects.create(year=2026, contest="A", problem="P1", topic="ALG", mohs=5)
    other_problem = ProblemSolveRecord.objects.create(year=2025, contest="Z", problem="P1", topic="ALG", mohs=5)
    first = statement(1, "Same text", year=2026, contest="A")
    other = statement(1, "Same text", year=2025, contest="Z")
    ContestProblemStatement.objects.filter(pk=first.pk).update(
        linked_problem=first_problem,
        contest_year_problem="Shared label",
    )
    ContestProblemStatement.objects.filter(pk=other.pk).update(
        linked_problem=other_problem,
        contest_year_problem="Shared label",
    )
    reference = build_statement_duplicate_report(
        list(ContestProblemStatement.objects.select_related("linked_problem")),
    )
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    result = snapshots.snapshot_context()
    assert (
        result["statement_duplicate_exact_rows"][0]["problem_items"]
        == reference["exact_duplicate_rows"][0]["problem_items"]
    )


def test_duplicate_cache_failure_preserves_last_published_generation(monkeypatch):
    statement(1, "Previous snapshot")
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    previous = cache.get(snapshots.MANIFEST_KEY)
    monkeypatch.setattr(snapshots.cache, "set", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="cache publication failed"):
        snapshots.refresh_statement_duplicate_snapshot(force=True)
    assert cache.get(snapshots.MANIFEST_KEY) == previous


def test_duplicate_source_change_during_refresh_does_not_publish(monkeypatch):
    statement(1, "Previous snapshot")
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    previous = cache.get(snapshots.MANIFEST_KEY)
    original = snapshots._similar_pairs

    def change_source(db, **kwargs):
        result = original(db, **kwargs)
        statement(2, "Changed while rebuilding")
        return result

    monkeypatch.setattr(snapshots, "_similar_pairs", change_source)
    assert snapshots.refresh_statement_duplicate_snapshot(force=True) is False
    assert cache.get(snapshots.MANIFEST_KEY) == previous


def test_duplicate_refresh_lock_cannot_be_stolen_by_second_invocation():
    with snapshots._refresh_lock() as acquired:
        assert acquired
        assert snapshots.refresh_statement_duplicate_snapshot(force=True) is False


def test_duplicate_scratch_recovers_files_left_by_an_interrupted_build(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots.tempfile, "gettempdir", lambda: str(tmp_path))
    with snapshots._scratch_index() as directory:
        pass
    # Simulate a file left after SIGKILL, which bypasses context-manager cleanup.
    (directory / "index.sqlite3").write_text("interrupted scratch data")
    with snapshots._scratch_index() as directory:
        assert not (directory / "index.sqlite3").exists()


def test_duplicate_time_budget_failure_preserves_completed_manifest():
    statement(1, "Previous snapshot")
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    previous = cache.get(snapshots.MANIFEST_KEY)
    with pytest.raises(RuntimeError, match="time budget"):
        snapshots.refresh_statement_duplicate_snapshot(force=True, max_seconds=-1)
    assert cache.get(snapshots.MANIFEST_KEY) == previous


@pytest.mark.parametrize("missing", ["exact:1", "similar", "members"])
def test_duplicate_scheduled_refresh_repairs_evicted_generation_chunks(missing):
    statement(1, "A repeated statement")
    statement(2, "A repeated statement")
    if missing == "members":
        for number in range(3, 30):
            statement(number, "A repeated statement")
    snapshots.refresh_statement_duplicate_snapshot(force=True)
    manifest = cache.get(snapshots.MANIFEST_KEY)
    if missing == "members":
        group = snapshots.snapshot_context()["statement_duplicate_exact_rows"][0]["group_key"]
        missing = f"members:{group}:1"
    cache.delete(snapshots._key(manifest["generation"], missing))
    assert snapshots.refresh_statement_duplicate_snapshot() is True
    assert cache.get(snapshots.MANIFEST_KEY)["generation"] != manifest["generation"]
    assert snapshots.snapshot_context()["statement_duplicate_available"] is True


def test_duplicate_refresh_runs_when_scheduled_catalog_has_no_queued_work():
    statement(1, "Scheduled snapshot")
    TechniqueProgressCatalogState.objects.update_or_create(singleton_key=1, defaults={"needs_rebuild": False})
    output = StringIO()
    call_command("recompute_technique_progress_catalog", queued_only=True, stdout=output)
    assert "No queued rebuild" in output.getvalue()
    assert snapshots.snapshot_context()["statement_duplicate_available"] is True


def test_linker_checks_hidden_claimants_and_duplicate_codes_without_loading_archive_bodies():
    problem = ProblemSolveRecord.objects.create(
        year=2025,
        contest="Visible",
        problem="P1",
        topic="ALG",
        mohs=10,
        contest_year_problem="Visible 2025 P1",
        rationale="large archive prose " * 1000,
    )
    claimed = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2024,
        contest_name="Hidden claimant",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Claimed",
    )
    statement(1, "Hidden duplicate code", year=2025, contest="Visible", day="Old section")
    for number in range(102):
        statement(number + 2, "Visible statement", year=2025, contest="Visible")
    statement(1, "Visible duplicate code", year=2025, contest="Visible", day="New section")
    with CaptureQueriesContext(connection) as queries:
        payload = _statement_linker_payload()
    assert len(payload["rows"]) == 100
    row = next(item for item in payload["rows"] if item["problem_code"] == "P1")
    assert row["suggested_problem_id"] is None
    candidate = payload["candidate_groups"][row["candidate_group_key"]][0]
    assert candidate["is_claimed"] is True
    assert claimed.contest_year_problem in candidate["claimed_statement_label"]
    archive_selects = [q["sql"] for q in queries if 'FROM "pages_problemsolverecord"' in q["sql"]]
    assert archive_selects
    assert all('"rationale"' not in sql for sql in archive_selects)


def test_topic_directory_payload_and_scatter_are_bounded_with_full_totals(admin_client):
    problem = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=25)
    ProblemTopicTechnique.objects.bulk_create(
        [
            ProblemTopicTechnique(record=problem, technique=f"METHOD-{number:04}", domains=["ALG", "NT"])
            for number in range(230)
        ],
    )
    response = admin_client.get(reverse("pages:topic_tag_dashboard"))
    assert response.context["technique_row_total"] == 230
    assert response.context["technique_total"] == 230
    assert response.context["technique_stats"]["domain_total"] == 2
    assert len(response.context["technique_rows"]) == 25
    assert len(response.context["charts_payload"]["byAvgMohsScatter"]["series"][0]["data"]) == 200
    assert len(response.content) < 150_000
    filtered = admin_client.get(reverse("pages:topic_tag_dashboard"), {"domain": "NT", "q": "METHOD-0229"})
    assert filtered.context["technique_total"] == 1
    assert filtered.context["technique_rows"][0]["technique"] == "METHOD-0229"


def test_benchmark_payload_pages_details_and_searches_beyond_first_page(admin_client):
    TechniqueBenchmark.objects.bulk_create(
        [
            TechniqueBenchmark(
                kind="method",
                label=f"Method {number:04}",
                label_key=f"method-{number:04}",
                normalized_label=f"Method {number:04}",
                rationale="Long rationale " * 2000,
            )
            for number in range(230)
        ],
    )
    response = admin_client.get(reverse("pages:technique_benchmark_list"))
    assert response.context["technique_benchmark_total"] == 230
    assert len(response.context["technique_benchmark_rows"]) == 25
    assert response.context["technique_benchmark_chart_is_capped"] is True
    scoped = admin_client.get(reverse("pages:technique_benchmark_list"), {"q": "0229"})
    assert scoped.context["technique_benchmark_total"] == 1
    assert scoped.context["technique_benchmark_rows"][0]["label"] == "Method 0229"


def test_benchmark_ranks_selected_target_globally_before_pagination(admin_client):
    fields = {
        "kind": "method",
        "syllabus_core": 3,
        "contest_frequency": 3,
        "transfer_value": 3,
        "prerequisite_value": 3,
        "concept_load": 2,
        "recognition_burden": 2,
        "execution_load": 2,
        "proof_fragility": 2,
        "cross_topic_dependency": 2,
    }
    TechniqueBenchmark.objects.bulk_create(
        [
            TechniqueBenchmark(
                **fields,
                label=f"National {n}",
                label_key=f"national-{n}",
                national_weight=5,
                jbmo_weight=1,
            )
            for n in range(30)
        ],
    )
    TechniqueBenchmark.objects.create(
        **fields,
        label="Z JBMO leader",
        label_key="jbmo-leader",
        national_weight=1,
        jbmo_weight=5,
    )
    result = admin_client.get(reverse("pages:technique_benchmark_list"), {"target_profile": "jbmo"})
    assert result.context["technique_benchmark_rows"][0]["label"] == "Z JBMO leader"


def test_benchmark_matrix_limit_applies_after_chartability_filter(admin_client):
    fields = {
        "kind": "method",
        "syllabus_core": 5,
        "contest_frequency": 5,
        "transfer_value": 5,
        "prerequisite_value": 5,
    }
    TechniqueBenchmark.objects.bulk_create(
        [TechniqueBenchmark(**fields, label=f"Incomplete {n}", label_key=f"incomplete-{n}") for n in range(201)],
    )
    TechniqueBenchmark.objects.create(
        kind="method",
        label="Complete lower-value row",
        label_key="complete",
        syllabus_core=2,
        contest_frequency=2,
        transfer_value=2,
        prerequisite_value=2,
        concept_load=2,
        recognition_burden=2,
        execution_load=2,
        proof_fragility=2,
        cross_topic_dependency=2,
    )
    result = admin_client.get(reverse("pages:technique_benchmark_list"))
    points = [
        point for series in result.context["technique_benchmark_matrix_payload"]["series"] for point in series["data"]
    ]
    assert [point["row_key"] for point in points] == ["method:complete"]


def test_topic_sort_applies_to_all_matches_before_pagination(admin_client):
    ordinary = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=5)
    hard = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P2", topic="Algebra", mohs=59)
    ProblemTopicTechnique.objects.bulk_create(
        [ProblemTopicTechnique(record=ordinary, technique=f"A-{n:03}", domains=["ALG"]) for n in range(30)],
    )
    ProblemTopicTechnique.objects.create(record=hard, technique="Z-HARD", domains=["ALG"])
    result = admin_client.get(reverse("pages:topic_tag_dashboard"), {"sort": "mohs", "topic": "Algebra"})
    assert result.context["technique_rows"][0]["technique"] == "Z-HARD"
    assert result.context["technique_total"] == 31
