from collections import Counter
from pathlib import Path

import pytest

from scripts.check_application_lint import check_baseline
from scripts.check_application_lint import finding_keys


def test_application_lint_rejects_new_and_duplicate_findings():
    baseline = {"format_version": 1, "findings": {"existing": 1}}
    assert check_baseline(Counter(existing=1), baseline) == Counter()
    assert check_baseline(Counter(), baseline) == Counter()
    assert check_baseline(Counter(existing=2, added=1), baseline) == Counter(existing=1, added=1)


@pytest.mark.parametrize("count", [0, -1, True, "1"])
def test_application_lint_rejects_invalid_baseline_counts(count):
    with pytest.raises(ValueError, match="invalid findings"):
        check_baseline(Counter(), {"format_version": 1, "findings": {"key": count}})


def test_application_lint_survives_line_shifts_but_detects_changed_source(tmp_path):
    source = tmp_path / "example.py"
    source.write_text("unused = 1\n")
    finding = {"filename": str(source), "code": "F841", "message": "unused", "location": {"row": 1}}
    original = finding_keys([finding], tmp_path)
    source.write_text("\nunused = 1\n")
    finding["location"]["row"] = 2
    assert finding_keys([finding], tmp_path) == original
    source.write_text("\nother_unused = 1\n")
    assert finding_keys([finding], tmp_path) != original


def test_ci_and_production_enforce_the_same_application_lint_baseline():
    root = Path(__file__).resolve().parents[3]
    for name in ("ci.yml", "production-deploy.yml"):
        workflow = (root / ".github/workflows" / name).read_text()
        assert "python scripts/check_application_lint.py" in workflow
        assert "ruff check config scripts" in workflow
