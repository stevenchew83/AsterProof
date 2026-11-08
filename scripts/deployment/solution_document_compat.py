# ruff: noqa: PLR0911
"""A frozen reader capability, verified without executing release-controlled code."""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

READER_VERSION = 1
# These exact reviewed reader bytes are frozen after integration verification.
# Changing a critical reader requires a newly reviewed installed allowance.
READER_SOURCES = {
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/views.py": "aa01392c8d7be9590b2af9c5e218705174f003d96e0ba6d7667082d4125d0098",
    "inspinia/solutions/pdf_latex.py": "264acea2cb7755a5dac6f453a56d58108b0abef189f120df8962f1ab860f5c84",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "22b8d280a452757a0eb522b03c607e27d31bef8f7eb918109432537bfc64e58b"
    ),
}
# Keep the previously reviewed reader eligible where the separate image floor
# permits it. New stage-one and forum readers are frozen after integration.
LEGACY_READER_SOURCES = {
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/views.py": "8e24c6e8d2edc24bcdd64ca3314462ab51fa8aa4d5e06066f1f59cc659cf701f",
    "inspinia/solutions/pdf_latex.py": "264acea2cb7755a5dac6f453a56d58108b0abef189f120df8962f1ab860f5c84",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "cd89f468803f1f781db831e2cbefa90dd859da922deafd66b864b7d322033beb"
    ),
}
IMAGE_COMPATIBILITY_SOURCES = {
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/views.py": "2dae12f4d3a22724979c36a4eb57f439724e533519c3a6145d47374b1a977c69",
    "inspinia/solutions/pdf_latex.py": "264acea2cb7755a5dac6f453a56d58108b0abef189f120df8962f1ab860f5c84",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "22b8d280a452757a0eb522b03c607e27d31bef8f7eb918109432537bfc64e58b"
    ),
}


MULTIPLE_SOLUTION_READER_SOURCES = {
    **READER_SOURCES,
    "inspinia/solutions/draft_autosave.py": "f8606e12261448065bd566adf528df71e8b3d14b810c8c1bd5489d48002153bb",
    "inspinia/solutions/revisions.py": "357f3e90c99f47c96f097fa346bbf26fe8a3616063853fdadb8f17cc53551aed",
    "inspinia/solutions/views.py": "bee9fdc1949600739775d412e28a5131c9f8338f16199e59d06ca399418b3905",
    "inspinia/templates/solutions/partials/solution-editor-workspace.html": (
        "aaba9a1ce17c5fcfa23d21c13e3f3f00c5e291f914afaa7cfac6045cc92a2df2"
    ),
}


def _reader_profiles():
    return (
        READER_SOURCES,
        LEGACY_READER_SOURCES,
        IMAGE_COMPATIBILITY_SOURCES,
        MULTIPLE_SOLUTION_READER_SOURCES,
    )


def reader_sources_match(files):
    entries = {item["path"]: item["sha256"] for item in files}
    return any(
        sources and all(entries.get(path) == digest for path, digest in sources.items())
        for sources in _reader_profiles()
    )


def verified_reader_release(release: Path):
    from scripts.deployment.release_manifest import ManifestError
    from scripts.deployment.release_manifest import ReleaseManifest

    try:
        metadata = release / "release-metadata.json"
        if metadata.is_symlink() or metadata.stat().st_size > 2 * 1024 * 1024:
            return False
        manifest = ReleaseManifest.from_bytes(metadata.read_bytes())
        if manifest.solution_document_reader != READER_VERSION or manifest.release_sha != release.name:
            return False
        entries = {item["path"]: item["sha256"] for item in manifest.files}
        sources = next(
            (
                sources
                for sources in _reader_profiles()
                if sources and all(entries.get(path) == digest for path, digest in sources.items())
            ),
            None,
        )
        if not sources:
            return False
        root = release.resolve(strict=True)
        for relative, expected in sources.items():
            path = release / relative
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
    except (OSError, ValueError, ManifestError):
        return False
    return True
