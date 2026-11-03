"""Only the observed ranking evidence CHECK cast pair is equivalent after restore."""
from copy import deepcopy

import pytest

from scripts.deployment.database_recovery import logical_backup_schema
from scripts.deployment.schema_fingerprint import schema_state

SOURCE_DEFINITION = (
        "CHECK (NOT active OR NOT verification_status::text = 'verified'::text OR NOT evidence = ''::text AND"
        " (source_type::text = ANY (ARRAY['organizer'::character varying, 'news'::character varying, "
        "'other'::character varying]::text[])) AND (NOT source_label::text = ''::text OR NOT source_url::text"
        " = ''::text))"
)
RESTORED_DEFINITION = (
        "CHECK (NOT active OR NOT verification_status::text = 'verified'::text OR NOT evidence = ''::text AND"
        " (source_type::text = ANY (ARRAY['organizer'::character varying::text, 'news'::character "
        "varying::text, 'other'::character varying::text])) AND (NOT source_label::text = ''::text OR NOT "
        "source_url::text = ''::text))"
)


def snapshot(definition, **identity):
    return {"tables": [], "columns": [], "indexes": [], "extensions": [], "constraints": [{
        "schema": "public", "table": "rankings_resultclaim", "name": "rank_claim_verified_evidence", "type": "c",
        **identity, "definition": definition,
    }]}


def test_observed_restore_cast_pair_is_equivalent_without_relaxing_live_audit():
    source, restored = snapshot(SOURCE_DEFINITION), snapshot(RESTORED_DEFINITION)
    unchanged = deepcopy(source)
    assert logical_backup_schema(source) == logical_backup_schema(restored)
    assert logical_backup_schema(logical_backup_schema(source)) == logical_backup_schema(source)
    assert source == unchanged
    assert schema_state(source) != schema_state(restored)


@pytest.mark.parametrize("field", ["schema", "table", "name", "type"])
def test_other_object_identity_does_not_receive_the_equivalence(field):
    source = snapshot(SOURCE_DEFINITION, **{field: "changed"})
    restored = snapshot(RESTORED_DEFINITION, **{field: "changed"})
    assert logical_backup_schema(source) == source
    assert logical_backup_schema(restored) == restored
    assert logical_backup_schema(source) != logical_backup_schema(restored)


@pytest.mark.parametrize(("old", "new"), [
    ("NOT active OR", "active OR"), ("'verified'", "'pending'"),
    ("NOT evidence =", "evidence ="), ("'organizer'", "'family'"),
    ("source_type::text = ANY", "source_type::text <> ANY"),
    ("source_label::text", "other_label::text"),
    ("OR NOT source_url", "AND NOT source_url"),
    ("::character varying", "::varchar"),
])
def test_changed_verification_logic_is_never_normalized(old, new):
    source = snapshot(SOURCE_DEFINITION.replace(old, new))
    restored = snapshot(RESTORED_DEFINITION.replace(old, new))
    assert logical_backup_schema(source) == source
    assert logical_backup_schema(restored) == restored
    assert logical_backup_schema(source) != logical_backup_schema(restored)
