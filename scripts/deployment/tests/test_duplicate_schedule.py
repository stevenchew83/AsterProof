from pathlib import Path

import pytest

from scripts.deployment.duplicate_schedule import check_destinations


def test_existing_unit_is_never_overwritten(tmp_path):
    target = tmp_path / "duplicate.service"
    target.write_text("Existing operator configuration")
    with pytest.raises(ValueError, match="Refusing to replace"):
        check_destinations(tmp_path, {target.name: "Different configuration"})
    assert target.read_text() == "Existing operator configuration"


def test_symlink_is_rejected_even_when_target_bytes_match(tmp_path):
    original = tmp_path / "original"
    original.write_text("expected")
    target = tmp_path / "duplicate.service"
    target.symlink_to(original)
    with pytest.raises(ValueError, match="Refusing to replace"):
        check_destinations(tmp_path, {target.name: "expected"})
    assert Path(target.readlink()) == original
