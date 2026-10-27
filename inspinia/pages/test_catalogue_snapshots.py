# ruff: noqa: PLR2004
"""Published membership freshness, user-cache correctness and source preservation."""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.catalogue_models import CatalogueProblem
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.catalogue_models import ConceptLibrarySnapshot
from inspinia.pages.catalogue_models import UserConceptProgressSummary
from inspinia.pages.catalogue_snapshots import SnapshotChangedError
from inspinia.pages.catalogue_snapshots import current_snapshot
from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.catalogue_snapshots import scope_counts
from inspinia.pages.catalogue_snapshots import user_progress_summary
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ConceptAssignmentState
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.test_concept_progress import statement
from inspinia.pages.test_concept_progress import tag
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_cold_progress_does_not_scan_or_rebuild_sources(client):
    user = UserFactory()
    client.force_login(user)
    tag(statement())
    with patch(
        "inspinia.pages.catalogue_sources.iter_catalogue_sources",
        side_effect=AssertionError("Unexpected rebuild"),
    ):
        response = client.get(reverse("pages:technique_dashboard"))
    assert response.context["progress_unavailable"]
    assert "completion records are preserved" in response.content.decode()
    export = client.get(reverse("pages:technique_dashboard"), {"export": "csv"})
    assert export.status_code == 503


def test_completion_updates_bulk_changes_and_deletes_invalidate_only_personal_summary():
    user = UserFactory()
    row = statement()
    tag(row)
    snapshot = rebuild_library_snapshot()
    original_sources = list(ContestProblemStatement.objects.values())
    assert scope_counts(snapshot, user_progress_summary(user, snapshot), "c:am-gm")["solved"] == 0
    completion = UserProblemCompletion.objects.create(user=user, statement=row, status="solved")
    assert current_snapshot().pk == snapshot.pk
    assert scope_counts(snapshot, user_progress_summary(user, snapshot), "c:am-gm")["solved"] == 1
    # Fingerprints catch bulk updates which do not fire model signals or update timestamps.
    UserProblemCompletion.objects.filter(pk=completion.pk).update(status="attempted")
    assert scope_counts(snapshot, user_progress_summary(user, snapshot), "c:am-gm")["solved"] == 0
    completion.delete()
    assert scope_counts(snapshot, user_progress_summary(user, snapshot), "c:am-gm")["solved"] == 0
    assert list(ContestProblemStatement.objects.values()) == original_sources


def test_source_changes_hide_stale_progress_until_explicit_publication(client):
    user = UserFactory()
    client.force_login(user)
    row = statement()
    source = tag(row)
    before = rebuild_library_snapshot()
    UserProblemCompletion.objects.create(user=user, statement=row, status="solved")
    assert user_progress_summary(user, before)["c:am-gm"]["solved"] == 1
    source.normalization_status = "corrupt"
    source.save()
    assert current_snapshot() is None
    assert client.get(reverse("pages:technique_dashboard")).context["progress_unavailable"]
    after = rebuild_library_snapshot()
    assert after.pk != before.pk
    assert scope_counts(after, user_progress_summary(user, after), "c:am-gm")["total"] == 0
    assert UserProblemCompletion.objects.get(user=user).status == "solved"


def test_interrupted_and_changed_input_builds_keep_previous_pointer():
    tag(statement())
    before = rebuild_library_snapshot()
    total = ConceptLibrarySnapshot.objects.count()
    with (
        patch("inspinia.pages.catalogue_sources.iter_catalogue_sources", side_effect=ValueError("source unavailable")),
        pytest.raises(ValueError, match="source unavailable"),
    ):
        rebuild_library_snapshot(force=True)
    assert CatalogueState.objects.get(pk=1).snapshot_id == before.pk
    assert ConceptLibrarySnapshot.objects.count() == total
    from inspinia.pages.catalogue_signals import invalidate_catalogue_snapshot
    from inspinia.pages.catalogue_sources import iter_catalogue_sources

    def changed_sources():
        yield from iter_catalogue_sources()
        invalidate_catalogue_snapshot()

    with (
        patch("inspinia.pages.catalogue_sources.iter_catalogue_sources", side_effect=changed_sources),
        pytest.raises(SnapshotChangedError, match="sources changed"),
    ):
        rebuild_library_snapshot(force=True)
    assert CatalogueState.objects.get(pk=1).snapshot_id == before.pk
    assert ConceptLibrarySnapshot.objects.count() == total


def test_warm_personal_summary_never_fetches_all_library_problems():
    user, other = UserFactory(), UserFactory()
    for number in range(1, 42):
        row = statement(number)
        tag(row)
        if number == 1:
            UserProblemCompletion.objects.create(user=user, statement=row, status="checked")
        else:
            UserProblemCompletion.objects.create(user=other, statement=row, status="solved")
    snapshot = rebuild_library_snapshot()
    cold = user_progress_summary(user, snapshot)
    assert cold["c:am-gm"]["solved"] == 1
    with CaptureQueriesContext(connection) as queries:
        assert user_progress_summary(user, snapshot) == cold
    assert len(queries) == 2
    sql = "\n".join(q["sql"] for q in queries)
    assert "pages_catalogueproblem" not in sql
    assert "pages_statementtopictechnique" not in sql
    assert UserConceptProgressSummary.objects.filter(user=user).count() == 1


def test_enabled_projection_uses_reviewed_assignments_and_preserves_rows(settings):
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    row = statement()
    tag(row)
    source = load_sources([row.problem_uuid])[str(row.problem_uuid)]
    assignment = ProblemConceptAssignment.objects.create(
        problem_uuid=row.problem_uuid,
        concept_id="am-gm",
        disposition="accepted",
        roles=["lemma"],
        source_fingerprint=source["source_fingerprint"],
        concept_signature=REGISTRY.signature("am-gm"),
    )
    ConceptAssignmentState.objects.create(
        enabled=True,
        initial_seed_complete=True,
        registry_fingerprint=REGISTRY.fingerprint,
    )
    before = list(ProblemConceptAssignment.objects.values())
    snapshot = rebuild_library_snapshot()
    assert snapshot.totals["c:am-gm"]["total"] == 1
    assert list(ProblemConceptAssignment.objects.values()) == before
    assignment.disposition = "rejected"
    assignment.decision_origin = "reviewed"
    assignment.save()
    assert current_snapshot() is None
    refreshed = rebuild_library_snapshot()
    assert refreshed.totals.get("c:am-gm", {}).get("total", 0) == 0
    assert CatalogueProblem.objects.filter(snapshot=refreshed).count() == 1


def test_bulk_assignment_revision_and_mode_changes_invalidate_shared_snapshot(settings):
    tag(statement())
    ConceptAssignmentState.objects.create(revision=2)
    before = rebuild_library_snapshot()
    assert current_snapshot().pk == before.pk
    ConceptAssignmentState.objects.filter(singleton_key=1).update(revision=3)
    assert current_snapshot() is None
    refreshed = rebuild_library_snapshot()
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    assert current_snapshot() is None
    assert refreshed.pk != before.pk


def test_concept_and_area_must_match_the_same_membership():
    from inspinia.pages.catalogue_progress import progress_problem_query

    user = UserFactory()
    row = statement()
    tag(row)
    tag(row, "vieta")
    snapshot = rebuild_library_snapshot()
    assert progress_problem_query(user, snapshot, "am-gm", area="Algebra:inequalities").count() == 1
    assert progress_problem_query(user, snapshot, "am-gm", area="Algebra:polynomials").count() == 0


def test_bulk_and_direct_tag_updates_invalidate_without_model_signals():
    row = statement()
    source = tag(row)
    rebuild_library_snapshot()
    type(source).objects.filter(pk=source.pk).update(normalization_status="corrupt")
    assert current_snapshot() is None
    rebuild_library_snapshot()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE pages_statementtopictechnique SET normalization_status = %s WHERE id = %s", ["", source.pk],
        )
    assert current_snapshot() is None


def test_private_solution_edits_do_not_invalidate_but_published_bulk_edits_do():
    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.solutions.models import ProblemSolution

    user = UserFactory()
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=20)
    solution = ProblemSolution.objects.create(problem=archive, author=user, status="draft")
    snapshot = rebuild_library_snapshot()
    ProblemSolution.objects.filter(pk=solution.pk).update(title="Private draft update")
    assert current_snapshot().pk == snapshot.pk
    ProblemSolution.objects.filter(pk=solution.pk).update(status="published")
    assert current_snapshot() is None


def test_progress_area_options_retain_subject_names(client):
    user = UserFactory()
    client.force_login(user)
    tag(statement())
    rebuild_library_snapshot()
    response = client.get(reverse("pages:technique_dashboard"), {"mode": "areas"})
    assert response.status_code == 200
    options = {area["id"]: area for area in response.context["scope_areas"]}
    assert options["Algebra:inequalities"]["subject"] == "Algebra"
    assert options["Geometry:circles"]["subject"] == "Geometry"
    content = response.content.decode()
    assert "Algebra · Inequalities and optimization" in content
    assert "Geometry · Circles, tangency, and cyclicity" in content
