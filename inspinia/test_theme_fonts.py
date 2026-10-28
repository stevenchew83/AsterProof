"""Keep theme typography available without third-party rendering dependencies."""

import hashlib
import json
import re
from pathlib import Path

STATIC_ROOT = Path(__file__).parent / "static"
FONT_ROOT = STATIC_ROOT / "fonts" / "theme"
FONT_SOURCE = STATIC_ROOT / "scss" / "config" / "_fonts.scss"
FAMILIES = {"Open Sans", "Roboto", "Inter", "Poppins", "IBM Plex Sans", "Nunito"}


def test_theme_font_declarations_preserve_all_families_styles_and_subsets():
    source = FONT_SOURCE.read_text()
    faces = re.findall(r"@font-face\s*\{[^}]+\}", source)
    assert {re.search(r"font-family: '([^']+)'", face)[1] for face in faces} == FAMILIES
    manifest = json.loads((FONT_ROOT / "provenance.json").read_text())
    for family in manifest["families"]:
        matching = [face for face in faces if f"font-family: '{family['family']}';" in face]
        assert len(matching) == family["faces"]
        assert {re.search(r"font-style: (\w+)", face)[1] for face in matching} == {"normal", "italic"}
    for face in faces:
        assert "font-display: swap;" in face
        assert "unicode-range:" in face
        assert re.search(r"font-weight: [\d ]+;", face)
    referenced = set(re.findall(r"url\(\.\./fonts/theme/([^)]*)\)", source))
    assert referenced == {entry["path"] for entry in manifest["files"]}


def test_theme_font_assets_match_original_bytes_and_include_licenses():
    manifest = json.loads((FONT_ROOT / "provenance.json").read_text())
    for entry in manifest["files"]:
        path = FONT_ROOT / entry["path"]
        assert path.resolve().is_relative_to(FONT_ROOT.resolve())
        body = path.read_bytes()
        assert body.startswith(b"wOF2")
        assert len(body) == entry["bytes"]
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]
        assert "SIL OPEN FONT LICENSE" in (path.parent / "OFL.txt").read_text()


def test_theme_css_has_no_external_font_imports_or_requests():
    for relative in ("css/app.css", "css/app.min.css"):
        css = (STATIC_ROOT / relative).read_text()
        assert "fonts.googleapis.com" not in css
        assert "fonts.gstatic.com" not in css
        assert "@font-face" in css
        urls = re.findall(r"url\(['\"]?(\.\./fonts/theme/[^)'\"]+)", css)
        assert urls
        for url in urls:
            assert (STATIC_ROOT / "css" / url).is_file()
    for path in (STATIC_ROOT / "scss" / "config").glob("*.scss"):
        assert "fonts.googleapis.com" not in path.read_text()
