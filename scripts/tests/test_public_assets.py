"""Public asset contracts that preserve typography and optional UI states."""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "inspinia" / "static"


def test_public_fonts_preserve_every_existing_open_sans_style_and_unicode_range():
    canonical = (STATIC / "scss/config/_fonts.scss").read_text()
    public = (STATIC / "scss/config/_public-fonts.scss").read_text()
    pattern = r"@font-face\s*\{[^}]+\}"
    expected = [face for face in re.findall(pattern, canonical) if "font-family: 'Open Sans';" in face]
    assert expected
    assert re.findall(pattern, public) == expected
    assert all("font-display: swap;" in face for face in expected)


@pytest.mark.parametrize("name", ["site", "writer", "solving", "shared"])
def test_public_stylesheets_keep_shared_controls_and_exclude_unused_assets(name):
    css = (STATIC / f"css/public-{name}.css").read_text()
    assert 'font-family: "Open Sans"' in css or "font-family: 'Open Sans'" in css
    for control in (".form-control", ".form-check-input", ".form-select", ".website-tools-menu > div"):
        assert control in css
    # Validation references these widgets, but their component styles are absent.
    for unused in (
        "[data-bs-theme=dark]", ".form-range", ".form-floating > .form-control",
        ".input-group-text", 'font-family: "Poppins"',
    ):
        assert unused not in css
    assert (".public-tool-grid" in css) == (name == "writer")
    assert (".solving-hero" in css) == (name == "solving")
    assert (".public-shared-paper" in css) == (name == "shared")
