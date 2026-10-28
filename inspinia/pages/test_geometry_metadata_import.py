"""Atomic Geometry imports retain catalog identities and statement coverage."""

import json
from pathlib import Path

import pytest

from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.statement_metadata_backfill import import_statement_metadata_dataframe
from inspinia.pages.statement_metadata_backfill import statement_metadata_dataframe_from_rows

CASES = json.loads((Path(__file__).parent / "testdata" / "igo_geometry_import_regressions.json").read_text())
IMPORT_MOHS = 20
TAG_FIELDS = (
    "technique", "domains", "main_topic", "canonical_subtopic", "normalization_status",
    "normalization_confidence", "object_tags", "technique_tags", "lemma_theorem_tags", "proof_roles",
)


@pytest.mark.parametrize(("caption", "stored", "concept_id"), [
    ("Radical axis", "RADICAL AXIS", "geo-radical-axis"),
    ("Radical axes", "RADICAL AXIS", "geo-radical-axis"),
    ("Radical axis method", "RADICAL AXIS", "geo-radical-axis"),
    ("Radical axis theorem", "RADICAL AXIS", "geo-radical-axis"),
    ("Arc midpoint", "ARC-MIDPOINT GEOMETRY", "geo-arc-midpoints"),
    ("Arc midpoints", "ARC-MIDPOINT GEOMETRY", "geo-arc-midpoints"),
    ("Arc midpoint geometry", "ARC-MIDPOINT GEOMETRY", "geo-arc-midpoints"),
    ("Arc-midpoint geometry", "ARC-MIDPOINT GEOMETRY", "geo-arc-midpoints"),
    ("Trapezoid", "TRAPEZOIDS", "geo-trapezoids"),
    ("Trapezoids", "TRAPEZOIDS", "geo-trapezoids"),
])
def test_atomic_geometry_caption_survives_preview_and_write(caption, stored, concept_id):
    raw = f"GEO - {caption}"
    preview = prepare_topic_tag_entries(raw, topic="GEO", active=True, problem_uuid=None, canonicalize=False)
    write = prepare_topic_tag_entries(raw, topic="GEO", active=True, problem_uuid=None, canonicalize=True)
    assert preview == write
    assert len(preview) == 1
    tag = preview[0]
    assert tag["technique"] == stored
    assert tag["domains"] == ["GEO"]
    assert tag["main_topic"] == "GEO"
    assert tag["normalization_status"] == "canonical"
    assert tag["normalization_confidence"] == "high"
    assert tag["raw_tag"] == caption
    assert REGISTRY.resolve("Geometry", "technique", stored, tag)["ids"] == [concept_id]


def test_compound_geometry_captions_are_not_relabelled_as_atomic_concepts():
    tags = prepare_topic_tag_entries(
        "GEO - MIQUEL/RADICAL AXIS", topic="GEO", active=True, problem_uuid=None, canonicalize=False,
    )
    assert {tag["technique"] for tag in tags} == {
        "MIQUEL AND SPIRAL SIMILARITY", "RADICAL AXIS AND COAXALITY",
    }


def _assert_imported_coverage(statement, case):
    statement.refresh_from_db()
    payload = statement_coverage_payloads([statement])[statement.pk]
    actual_ids = {REGISTRY.canonical(c["id"]) for c in payload["concept_coverage"]}
    assert set(case["concept_ids"]) <= actual_ids
    assert payload["concept_areas"] == case["areas"]
    assert statement.topic == "GEO"
    assert statement.mohs == IMPORT_MOHS
    assert statement.linked_problem.problem_uuid == statement.problem_uuid
    for parent, relation in [(statement, "statement"), (statement.linked_problem, "record")]:
        model = StatementTopicTechnique if relation == "statement" else ProblemTopicTechnique
        tags = list(model.objects.filter(**{relation: parent}).values(*TAG_FIELDS))
        assert all(tag["technique"] == tag["technique"].upper() for tag in tags)
        for tag in tags:
            if tag["technique"] in {"RADICAL AXIS", "ARC-MIDPOINT GEOMETRY", "TRAPEZOIDS"}:
                assert tag["normalization_status"] == "canonical"


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=[case["problem"] for case in CASES])
def test_metadata_import_creates_merges_replaces_and_reimports_geometry_coverage(case, settings):
    settings.CONCEPT_ASSIGNMENTS_ENABLED = False
    year, code = case["problem"].split()
    statement = ContestProblemStatement.objects.create(
        contest_year=int(year), contest_name="Iranian Geometry Olympiad",
        day_label="Advanced Level" if code[0] == "A" else "Intermediate Level",
        problem_number=int(code[1:]), problem_code=f"P{code[1:]}", statement_latex="Prove the claim.",
    )
    identity = statement.problem_uuid
    frame = statement_metadata_dataframe_from_rows([{
        "STATEMENT UUID": str(statement.statement_uuid),
        "PROBLEM UUID": str(identity), "TOPIC": "GEO", "MOHS": IMPORT_MOHS,
        "Topic tags": case["topic_tags"],
    }])
    result = import_statement_metadata_dataframe(frame, replace_tags=False)
    assert result.created_count == 1
    assert result.processed_count == 1
    _assert_imported_coverage(statement, case)

    # An existing statement source must be updated rather than masking the newly
    # imported archive tags. Merge and replacement retain their distinct semantics.
    for model, relation in [(StatementTopicTechnique, "statement"), (ProblemTopicTechnique, "record")]:
        parent = statement if relation == "statement" else statement.linked_problem
        model.objects.filter(**{relation: parent}).delete()
        model.objects.create(**{relation: parent}, technique="RETAINED SOURCE TAG", domains=["GEO"])
    import_statement_metadata_dataframe(frame, replace_tags=False)
    _assert_imported_coverage(statement, case)
    assert StatementTopicTechnique.objects.filter(statement=statement, technique="RETAINED SOURCE TAG").exists()
    assert ProblemTopicTechnique.objects.filter(
        record=statement.linked_problem, technique="RETAINED SOURCE TAG",
    ).exists()

    import_statement_metadata_dataframe(frame, replace_tags=True)
    _assert_imported_coverage(statement, case)
    assert not StatementTopicTechnique.objects.filter(statement=statement, technique="RETAINED SOURCE TAG").exists()
    assert not ProblemTopicTechnique.objects.filter(
        record=statement.linked_problem, technique="RETAINED SOURCE TAG",
    ).exists()
    before = list(statement.statement_topic_techniques.order_by("technique").values(*TAG_FIELDS))
    import_statement_metadata_dataframe(frame, replace_tags=True)
    assert list(statement.statement_topic_techniques.order_by("technique").values(*TAG_FIELDS)) == before
    assert ProblemSolveRecord.objects.count() == 1
    statement.refresh_from_db()
    assert statement.problem_uuid == identity


@pytest.mark.django_db
def test_reimport_preserves_provenance_when_source_tags_share_a_stored_caption():
    statement = ContestProblemStatement.objects.create(
        contest_year=2024, contest_name="Iranian Geometry Olympiad", day_label="Elementary Level",
        problem_number=5, problem_code="P5", statement_latex="Prove the circle intersection is collinear.",
    )
    frame = statement_metadata_dataframe_from_rows([{
        "STATEMENT UUID": str(statement.statement_uuid), "TOPIC": "GEO", "MOHS": IMPORT_MOHS,
        "Topic tags": "GEO - MIQUEL, SPIRAL SIMILARITIES",
    }])
    import_statement_metadata_dataframe(frame, replace_tags=False)
    statement.refresh_from_db()
    for _ in range(2):
        import_statement_metadata_dataframe(frame, replace_tags=False)
        for model, relation, parent in [
            (StatementTopicTechnique, "statement", statement),
            (ProblemTopicTechnique, "record", statement.linked_problem),
        ]:
            tag = model.objects.get(**{relation: parent}, technique="MIQUEL AND SPIRAL SIMILARITY")
            assert tag.raw_tag == "MIQUEL; SPIRAL SIMILARITIES"
