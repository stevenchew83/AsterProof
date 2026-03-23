from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORS_BUNDLE = REPO_ROOT / "inspinia" / "static" / "js" / "vendors.min.js"


def _read_vendor_bundle() -> str:
    assert VENDORS_BUNDLE.is_file(), (
        "Expected built vendor bundle at "
        f"{VENDORS_BUNDLE}. Run `npm run build` and commit the generated file."
    )
    return VENDORS_BUNDLE.read_text(encoding="utf-8")


def test_inspinia_vendor_bundle_exists():
    assert VENDORS_BUNDLE.is_file(), (
        "Expected built vendor bundle at "
        f"{VENDORS_BUNDLE}. Run `npm run build` and commit the generated file."
    )


def test_inspinia_vendor_bundle_contains_expected_vendor_markers():
    bundle_lower = _read_vendor_bundle().lower()

    for marker in ("jquery", "bootstrap", "lucide", "simplebar"):
        assert marker in bundle_lower
