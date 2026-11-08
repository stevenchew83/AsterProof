"""Preserve the exact Training identity CHECK through PG17.9 dump and restore.

Only the observed public.learning_contentdocument CHECK representations are
equivalent; every unreviewed identity or definition must remain distinct.
"""
from copy import deepcopy

import pytest

from scripts.deployment.database_recovery import logical_backup_schema

SOURCE_DEFINITION = (
    "CHECK (canonical_area_id IS NOT NULL AND canonical_concept_id IS NULL AND kind::text = "
    "'overview'::text OR canonical_area_id IS NULL AND canonical_concept_id IS NOT NULL AND kind::text "
    "= 'concept'::text OR (kind::text = ANY (ARRAY['lecture'::character varying, 'technique'::character"
    " varying, 'standalone'::character varying]::text[])))"
)
RESTORED_DEFINITION = (
    "CHECK (canonical_area_id IS NOT NULL AND canonical_concept_id IS NULL AND kind::text = "
    "'overview'::text OR canonical_area_id IS NULL AND canonical_concept_id IS NOT NULL AND kind::text "
    "= 'concept'::text OR (kind::text = ANY (ARRAY['lecture'::character varying::text, "
    "'technique'::character varying::text, 'standalone'::character varying::text])))"
)

IDENTITY = {
    "schema": "public",
    "table": "learning_contentdocument",
    "name": "learning_document_canonical_identity",
    "type": "c",
}


def snapshot(definition, **identity_changes):
    return {
        "tables": [],
        "columns": [],
        "constraints": [{**IDENTITY, **identity_changes, "definition": definition}],
        "indexes": [],
        "extensions": [],
    }


def test_exact_observed_training_check_cast_pair_is_equivalent():
    assert logical_backup_schema(snapshot(SOURCE_DEFINITION)) == logical_backup_schema(snapshot(RESTORED_DEFINITION))


@pytest.mark.parametrize("definition", [SOURCE_DEFINITION, RESTORED_DEFINITION], ids=["source", "restored"])
def test_training_check_normalization_is_idempotent_and_does_not_mutate_input(definition):
    original = snapshot(definition)
    unchanged = deepcopy(original)
    normalized = logical_backup_schema(original)
    normalized_before = deepcopy(normalized)
    assert logical_backup_schema(normalized) == normalized
    assert original == unchanged
    assert normalized == normalized_before
    assert normalized is not original
    assert normalized["constraints"][0] is not original["constraints"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "private"),
        ("table", "learning_otherdocument"),
        ("name", "other_document_canonical_identity"),
        ("type", "u"),
    ],
)
def test_training_check_cast_pair_is_not_normalized_for_other_identity(field, value):
    source = snapshot(SOURCE_DEFINITION, **{field: value})
    restored = snapshot(RESTORED_DEFINITION, **{field: value})
    assert logical_backup_schema(source) == source
    assert logical_backup_schema(restored) == restored
    assert logical_backup_schema(source) != logical_backup_schema(restored)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("'overview'::text", "'different'::text"),
        ("'lecture'::character varying", "'proof'::character varying"),
        ("kind::text = ANY", "kind::text <> ANY"),
        ("canonical_area_id IS NOT NULL", "canonical_area_id IS NULL"),
        ("canonical_concept_id IS NULL", "canonical_concept_id IS NOT NULL"),
        ("'overview'::text OR canonical_area_id", "'overview'::text AND canonical_area_id"),
    ],
    ids=["overview_literal", "array_literal", "comparison_operator", "area_null", "concept_null", "boolean_operator"],
)
def test_changed_training_check_cast_pairs_remain_distinct(old, new):
    # Change both definitions identically. A broad cast/SQL normalization would
    # incorrectly equate these unreviewed pairs despite their matching changes.
    assert SOURCE_DEFINITION.count(old) == RESTORED_DEFINITION.count(old) == 1
    source_definition = SOURCE_DEFINITION.replace(old, new, 1)
    restored_definition = RESTORED_DEFINITION.replace(old, new, 1)
    source = snapshot(source_definition)
    restored = snapshot(restored_definition)
    assert logical_backup_schema(source) == source
    assert logical_backup_schema(restored) == restored
    assert logical_backup_schema(source) != logical_backup_schema(restored)
