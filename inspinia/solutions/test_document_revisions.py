# ruff: noqa: PLR2004 - Revision sequences and snapshot format versions are explicit contract assertions.
"""Continuous source conversion, immutable saves, and canonical output consumers."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from inspinia.pages.concept_assignment_service import published_solution_evidence
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.document_source import convert_legacy_block
from inspinia.solutions.document_source import solution_blocks
from inspinia.solutions.document_source import solution_source
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.models import SolutionRevision
from inspinia.solutions.pdf_latex import build_solution_tex_source
from inspinia.solutions.revisions import DOCUMENT_SOURCE_LIMIT
from inspinia.solutions.revisions import InvalidDocument
from inspinia.solutions.revisions import InvalidEditorContext
from inspinia.solutions.revisions import StaleSolutionVersion
from inspinia.solutions.revisions import editor_context
from inspinia.solutions.revisions import save_document
from inspinia.solutions.sharing import build_public_snapshot
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
OPTIONS = {"pdf_show_author": True, "pdf_show_date": True, "pdf_show_footer": False}
CONFORMANCE = json.loads((
    Path(__file__).resolve().parents[2] / "scripts/tests/fixtures/solution-document-conformance.json"
).read_text())


@pytest.fixture
def document():
    user = UserFactory()
    problem = ProblemSolveRecord.objects.create(contest="DOCUMENT", year=2026, problem="P1", topic="ALG")
    return user, problem, ProblemSolution(problem=problem, author=user)


def save(solution, user, **changes):
    values = {
        "solution": solution, "user": user, "source": "Use $(a-b)^2\\geq0$.", "title": "My proof",
        "summary": "A square is nonnegative.", "pdf_options": OPTIONS,
        "base_version": solution.edit_version,
        "context": editor_context(user, solution.problem.problem_uuid, solution=solution),
    }
    return save_document(**{**values, **changes})


def test_legacy_claim_statement_and_proof_are_separate():
    block = SimpleNamespace(
        block_type=SimpleNamespace(slug="claim", label="Claim"), title="$x=y$", body_source="By symmetry.",
        body_format="latex",
    )
    assert convert_legacy_block(block) == (
        "\\begin{claim}\n$x=y$\n\\end{claim}\n\n\\begin{proof}\nBy symmetry.\n\\end{proof}"
    )


@pytest.mark.parametrize("fixture", CONFORMANCE, ids=lambda fixture: fixture["name"])
def test_legacy_conversion_matches_the_shared_browser_conformance_fixture(fixture):
    value = fixture["block"]
    block = SimpleNamespace(
        block_type=SimpleNamespace(slug=value["slug"], label=value["label"]),
        title=value["title"], body_source=value["body_source"], body_format=value["body_format"],
    )
    assert convert_legacy_block(block) == fixture["source"]


def test_legacy_plaintext_never_becomes_executable_latex():
    block = SimpleNamespace(
        block_type=None, title="Literal", body_source=r"$x$ \input{secret} costs 5% & a_b.",
        body_format="plain_text",
    )
    source = convert_legacy_block(block)
    assert r"\$x\$" in source
    assert r"\textbackslash{}input\{secret\}" in source
    assert r"5\% \& a\_b" in source


def test_legacy_unknown_type_keeps_heading_and_body():
    block = SimpleNamespace(
        block_type=SimpleNamespace(slug="future-type", label="Future"), title="Unusual #1",
        body_source=r"Keep \unknownmacro{x} intact.", body_format="latex",
    )
    source = convert_legacy_block(block)
    assert r"\paragraph{Future — Unusual \#1}" in source
    assert block.body_source in source


def test_reading_legacy_document_does_not_create_revisions_or_reorder_blocks(document):
    user, _problem, solution = document
    solution.save()
    claim = SolutionBlockType.objects.get(slug="claim")
    last = solution.blocks.create(position=8, body_source="Last.")
    first = solution.blocks.create(position=2, block_type=claim, title="Statement.", body_source="Proof.")
    source = solution_source(solution)
    assert source.index("Statement.") < source.index("Last.")
    assert not SolutionRevision.objects.exists()
    assert list(solution.blocks.values_list("pk", flat=True)) == [first.pk, last.pk]
    assert solution.edit_version == 0
    assert editor_context(user, solution.problem.problem_uuid)


def test_first_document_save_preserves_frozen_blocks_and_problem_completion(document):
    user, problem, solution = document
    solution.save()
    block = solution.blocks.create(position=1, body_source="Original legacy content.")
    result = save(solution, user, source="New continuous source.")
    block.refresh_from_db()
    assert block.body_source == "Original legacy content."
    assert result.solution.current_revision == result.revision
    assert result.solution.edit_version == 1
    assert result.revision.sequence == 1
    assert result.revision.conversion_version == 1
    assert solution_source(result.solution) == "New continuous source."
    assert not problem.user_completions.exists()


def test_unchanged_save_reuses_revision_and_timestamp(document):
    user, _problem, solution = document
    first = save(solution, user)
    second = save(first.solution, user)
    assert not second.changed
    assert second.revision.pk == first.revision.pk
    assert second.solution.updated_at == first.solution.updated_at
    assert second.solution.edit_version == 1
    assert SolutionRevision.objects.count() == 1


def test_unchanged_legacy_draft_autosave_does_not_create_a_revision(document):
    user, _problem, solution = document
    solution.save()
    solution.blocks.create(position=1, body_source="Original legacy content.")
    result = save(
        solution, user, action="autosave", source=solution_source(solution),
        title=solution.title, summary=solution.summary, pdf_options={**OPTIONS, "pdf_show_footer": True},
    )
    assert not result.changed
    assert result.solution.edit_version == 0
    assert not solution.revisions.exists()


def test_changed_document_creates_new_revision_and_status_only_save_reuses_it(document):
    user, _problem, solution = document
    first = save(solution, user)
    second = save(first.solution, user, source="A better argument.")
    assert second.revision.sequence == 2
    assert first.revision.body_source != second.revision.body_source
    published = save(second.solution, user, source="A better argument.", action="publish")
    assert published.solution.status == "published"
    assert published.revision.pk == second.revision.pk
    assert published.solution.edit_version == 3
    drafted = save(published.solution, user, source="A better argument.", action="save_draft")
    assert drafted.solution.status == "draft"
    assert drafted.solution.published_at is drafted.solution.submitted_at is None
    assert SolutionRevision.objects.count() == 2


def test_pdf_option_change_is_an_immutable_revision_change(document):
    user, _problem, solution = document
    first = save(solution, user)
    changed = save(first.solution, user, pdf_options={**OPTIONS, "pdf_show_author": False})
    assert first.revision.pdf_show_author
    assert not changed.revision.pdf_show_author
    assert changed.revision.source_digest != first.revision.source_digest


def test_stale_editor_cannot_overwrite_new_document(document):
    user, problem, solution = document
    token = editor_context(user, problem.problem_uuid)
    first = save(solution, user, context=token)
    with pytest.raises(StaleSolutionVersion):
        save(solution, user, source="Stale replacement.", context=token, base_version=0)
    assert SolutionRevision.objects.count() == 1
    assert solution_source(first.solution) != "Stale replacement."


def test_context_is_bound_to_author_problem_and_signed_version(document):
    user, problem, solution = document
    token = editor_context(user, problem.problem_uuid)
    with pytest.raises(InvalidEditorContext):
        save(solution, UserFactory(), context=token)
    with pytest.raises(InvalidEditorContext):
        save(solution, user, context=token + "tampered")
    with pytest.raises(StaleSolutionVersion):
        save(solution, user, context=token, base_version=99)
    assert not ProblemSolution.objects.exists()


def test_expired_editor_context_cannot_save(document):
    user, problem, solution = document
    with patch("django.core.signing.time.time", return_value=0):
        token = editor_context(user, problem.problem_uuid)
    with pytest.raises(InvalidEditorContext, match="expired"):
        save(solution, user, context=token)
    assert not ProblemSolution.objects.exists()


def test_initial_context_can_adopt_only_an_empty_upload_placeholder(document):
    user, problem, solution = document
    token = editor_context(user, problem.problem_uuid)
    placeholder = ProblemSolution.objects.create(problem=problem, author=user)
    result = save(solution, user, context=token)
    assert result.solution.pk == placeholder.pk
    assert ProblemSolution.objects.count() == 1


def test_initial_context_cannot_replace_a_newly_created_legacy_document(document):
    user, problem, solution = document
    token = editor_context(user, problem.problem_uuid)
    created = ProblemSolution.objects.create(problem=problem, author=user)
    created.blocks.create(position=1, body_source="Written in another tab.")
    with pytest.raises(StaleSolutionVersion):
        save(solution, user, context=token)
    assert not SolutionRevision.objects.exists()


def test_empty_draft_can_be_saved_but_not_published(document):
    user, _problem, solution = document
    saved = save(solution, user, source="")
    assert saved.solution.status == "draft"
    with pytest.raises(InvalidDocument, match="before publishing"):
        save(saved.solution, user, source=" \n", action="publish")


def test_large_legacy_source_remains_savable_without_truncation(document):
    user, _problem, solution = document
    solution.save()
    source = "x" * (DOCUMENT_SOURCE_LIMIT + 1)
    solution.blocks.create(position=1, body_source=source)
    saved = save(solution, user, source=solution_source(solution))
    assert saved.revision.body_source == source


def test_wrong_solution_current_revision_fails_closed(document):
    user, problem, solution = document
    original = save(solution, user)
    foreign = ProblemSolution.objects.create(problem=problem, author=UserFactory())
    foreign.current_revision = original.revision
    with pytest.raises(ValidationError, match="must belong"):
        foreign.clean()
    with pytest.raises(ValidationError, match="does not belong"):
        solution_source(foreign)


@pytest.mark.parametrize("changes", [
    {"source": "x" * (DOCUMENT_SOURCE_LIMIT + 1)}, {"source": "bad\x00text"},
    {"title": "x" * 161}, {"pdf_options": {"pdf_show_author": "yes"}},
])
def test_invalid_document_does_not_create_a_solution(document, changes):
    user, _problem, solution = document
    with pytest.raises(InvalidDocument):
        save(solution, user, **changes)
    assert not ProblemSolution.objects.exists()


def test_revision_cannot_be_modified_through_model_queryset_or_duplicate_uuid(document):
    user, _problem, solution = document
    revision = save(solution, user).revision
    revision.body_source = "Mutation."
    with pytest.raises(ValidationError, match="cannot be changed"):
        revision.save()
    with pytest.raises(ValidationError):
        SolutionRevision.objects.filter(pk=revision.pk).update(body_source="Mutation.")
    with pytest.raises(ValidationError):
        SolutionRevision.objects.bulk_update([revision], ["body_source"])
    duplicate = SolutionRevision(
        pk=revision.pk, solution=revision.solution, sequence=9, body_source="Mutation.", source_digest="a" * 64,
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        duplicate.save()
    revision.refresh_from_db()
    assert revision.body_source != "Mutation."


def test_canonical_pdf_has_raw_document_without_spurious_block_heading(document, tmp_path):
    user, _problem, solution = document
    result = save(solution, user, source="\\begin{proof}\nDone.\n\\end{proof}")
    tex = build_solution_tex_source(
        solution=result.solution, blocks=solution_blocks(result.solution), media_root=tmp_path, problem_label="P1",
    )
    assert result.revision.body_source in tex
    assert r"\paragraph{Block}" not in tex


def test_new_snapshot_is_v2_and_existing_public_copy_stays_unchanged(document):
    user, problem, solution = document
    result = save(solution, user)
    old_snapshot = {"version": 1, "blocks": [{"source": "Earlier explicitly shared proof."}]}
    share = SolutionPublicShare.objects.create(
        solution=result.solution, snapshot=old_snapshot, source_updated_at=result.solution.updated_at,
    )
    snapshot = build_public_snapshot(result.solution, {
        "statement_render_segments": [], "problem_label": "P1", "problem_mohs": 5,
    }, {"concept_areas": [], "concept_coverage": []})
    assert snapshot["version"] == 2
    assert snapshot["document"]["source"] == result.revision.body_source
    assert "blocks" not in snapshot
    share.refresh_from_db()
    assert share.snapshot == old_snapshot
    assert result.solution.problem_id == problem.pk


def test_published_concept_evidence_uses_current_revision_and_preserves_private_boundary(document, settings):
    user, problem, solution = document
    solution.save()
    solution.blocks.create(position=1, body_source="Stale legacy evidence.")
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    with patch("inspinia.pages.concept_assignment_service.invalidate_assignments") as invalidate:
        published = save(solution, user, source="Exact published argument.", action="publish")
        assert invalidate.called
    evidence = published_solution_evidence([problem.problem_uuid])
    first_hash = evidence[published.solution.pk]["content_hash"]
    assert "Exact published argument." in evidence[published.solution.pk]["text"]
    assert "Stale legacy evidence." not in evidence[published.solution.pk]["text"]
    with patch("inspinia.pages.concept_assignment_service.invalidate_assignments") as invalidate:
        changed = save(published.solution, user, source="Revised published argument.")
        assert invalidate.called
    assert published_solution_evidence([problem.problem_uuid])[changed.solution.pk]["content_hash"] != first_hash
    save(changed.solution, user, source="Revised published argument.", action="save_draft")
    assert published_solution_evidence([problem.problem_uuid]) == {}


def test_solution_deletion_cascades_revision_without_immutable_update_failure(document):
    user, _problem, solution = document
    saved = save(solution, user)
    saved.solution.delete()
    assert not SolutionRevision.objects.exists()
