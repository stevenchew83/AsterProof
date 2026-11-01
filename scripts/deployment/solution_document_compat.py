"""A frozen reader capability, verified without executing release-controlled code."""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

READER_VERSION = 1
# These exact reviewed reader bytes are frozen after integration verification.
# Changing a critical reader requires a newly reviewed installed allowance.
READER_SOURCES = {
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/views.py": "8e24c6e8d2edc24bcdd64ca3314462ab51fa8aa4d5e06066f1f59cc659cf701f",
    "inspinia/solutions/pdf_latex.py": "264acea2cb7755a5dac6f453a56d58108b0abef189f120df8962f1ab860f5c84",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "cd89f468803f1f781db831e2cbefa90dd859da922deafd66b864b7d322033beb"
    ),
}


def reader_sources_match(files):
    entries = {item["path"]: item["sha256"] for item in files}
    return all(entries.get(path) == digest for path, digest in READER_SOURCES.items())


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
        root = release.resolve(strict=True)
        for relative, expected in READER_SOURCES.items():
            path = release / relative
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
    except (OSError, ValueError, ManifestError):
        return False
    return True
