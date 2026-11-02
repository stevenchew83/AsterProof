# ruff: noqa: EM101, TRY003, PLR0911
"""Frozen image-reader capability and a separately installed root-owned privacy floor."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path  # noqa: TC003

READER_VERSION = 1
MARKER_NAME = "solution-image-reader-required.json"
ROOT_UID = 0
MAX_MARKER_BYTES = 1024
# Frozen after integration. The build refuses to advertise this capability when
# any required reader or consumer differs; the trusted worker verifies disk bytes.
READER_SOURCES = {
    "config/urls.py": "ba15614ec72f02720d15d28a5c5fe9a0c08a8707dd9f977b6910ef77878db448",
    "inspinia/solutions/models.py": "1db394d5c101807e9caf695f5083ea5c763f386911bb171b10b4b564407d02af",
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/forum_access.py": "e90d1cb44c14c89368f68be47b8fd47c7a7da54f1496ff94aa8721a06658fe0d",
    "inspinia/solutions/image_access.py": "abb7dd9e978e63f54d29a1e1a5c642cf8d4079a75eba1a0cc251b994c9b52cf1",
    "inspinia/solutions/image_urls.py": "81485468f8900ee2ab92d3f8c19f4db86913ebb9497adbc9da31aa58880401cf",
    "inspinia/solutions/views.py": "aa01392c8d7be9590b2af9c5e218705174f003d96e0ba6d7667082d4125d0098",
    "inspinia/solutions/urls.py": "ba712627be151db4d6f25475955f3374129a8075c99e176c7f56f754c3b35dd9",
    "inspinia/solutions/public_views.py": "0b111d152ab9a71fdb9d601215c4ec42c7671f27cd49ddf8870387c79135245c",
    "inspinia/solutions/collection_views.py": "6c28fcc098b0e04e089c692690421a32305d21b8693021b22555c7cf49694da2",
    "inspinia/solutions/admin_collections.py": "be9e018e5164f8639e160dcd74e003cb8c8c9737ff8f247a0744750250bb98ec",
    "inspinia/static/js/solution-document-preview-entry.js": (
        "ee59e60a26b3cf04caca6033b2c0f66cfcec3c6b92543bbf56bad9fea81c59fb"
    ),
    "inspinia/static/js/solution-document-preview.bundle.js": (
        "6dd2a3a315ef370de03bf41e5d8e11aa9f8146a42232e75f2d605014c49c9c11"
    ),
    "inspinia/static/js/solution-latex-hybrid.js": "9177afbcd73eee9265aaa1348e40ab08ebfae0d9fc8a78bc594cd910033a57b9",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "22b8d280a452757a0eb522b03c607e27d31bef8f7eb918109432537bfc64e58b"
    ),
    "inspinia/templates/solutions/problem-solution-editor.html": (
        "52410bb0a156cdc582f8b2a808f9a7d5515dcc9bbad94e9d6f998718d2888396"
    ),
    "inspinia/templates/solutions/problem-solution-list.html": (
        "6be38882eb762a50f55281668e36f0ca57ffccf367c80b95d1006525366ed216"
    ),
    "inspinia/templates/solutions/collection-edit.html": (
        "4ec13b81be8393fff83d10636d667a6340a1138ea36823cb7d30a5f30c411e2b"
    ),
    "inspinia/templates/solutions/admin-collection-edit.html": (
        "bb0e3f64248b21a30478c1bf5dac242fc207dacb73d3e376f293b2d83dc6ff1e"
    ),
    "inspinia/templates/website/shared_collection.html": (
        "409b530d40be0f2ddcd906a1526a503b7e1e5adb98b42d3a97106ee1b6380f41"
    ),
    "inspinia/solutions/forum.py": "3c0aa934fab6a1aff7fe2e348eb88248f08a3f0382bcf9d6281146a51eaaefc6",
    "inspinia/solutions/forum_models.py": "433beebf0ad304cad730510a073d02d98ef12660556d1d579778555b7f0e5505",
}
COMPATIBILITY_SOURCES = {
    "config/urls.py": "ba15614ec72f02720d15d28a5c5fe9a0c08a8707dd9f977b6910ef77878db448",
    "inspinia/solutions/models.py": "168ed26239f23ad27e6b2a8fab8e80e59f16254d05158176c4b76883cad6d8e7",
    "inspinia/solutions/document_source.py": "91d758d4940fba4cba4dae3a19876349029f9991f814438fce84299adc3a0da3",
    "inspinia/solutions/forum_access.py": "e90d1cb44c14c89368f68be47b8fd47c7a7da54f1496ff94aa8721a06658fe0d",
    "inspinia/solutions/image_access.py": "abb7dd9e978e63f54d29a1e1a5c642cf8d4079a75eba1a0cc251b994c9b52cf1",
    "inspinia/solutions/image_urls.py": "81485468f8900ee2ab92d3f8c19f4db86913ebb9497adbc9da31aa58880401cf",
    "inspinia/solutions/views.py": "2dae12f4d3a22724979c36a4eb57f439724e533519c3a6145d47374b1a977c69",
    "inspinia/solutions/urls.py": "c99e395572978806ec076072e0a229b678b5886ecd3a21119d6c86f5ebd310f2",
    "inspinia/solutions/public_views.py": "0b111d152ab9a71fdb9d601215c4ec42c7671f27cd49ddf8870387c79135245c",
    "inspinia/solutions/collection_views.py": "6c28fcc098b0e04e089c692690421a32305d21b8693021b22555c7cf49694da2",
    "inspinia/solutions/admin_collections.py": "be9e018e5164f8639e160dcd74e003cb8c8c9737ff8f247a0744750250bb98ec",
    "inspinia/static/js/solution-document-preview-entry.js": (
        "ee59e60a26b3cf04caca6033b2c0f66cfcec3c6b92543bbf56bad9fea81c59fb"
    ),
    "inspinia/static/js/solution-document-preview.bundle.js": (
        "6dd2a3a315ef370de03bf41e5d8e11aa9f8146a42232e75f2d605014c49c9c11"
    ),
    "inspinia/static/js/solution-latex-hybrid.js": "9177afbcd73eee9265aaa1348e40ab08ebfae0d9fc8a78bc594cd910033a57b9",
    "inspinia/templates/solutions/partials/shared-solution-content.html": (
        "22b8d280a452757a0eb522b03c607e27d31bef8f7eb918109432537bfc64e58b"
    ),
    "inspinia/templates/solutions/problem-solution-editor.html": (
        "52410bb0a156cdc582f8b2a808f9a7d5515dcc9bbad94e9d6f998718d2888396"
    ),
    "inspinia/templates/solutions/problem-solution-list.html": (
        "cf113cec294843904c47032d84274c4408349bc56fb5484c6a96126ad4596cde"
    ),
    "inspinia/templates/solutions/collection-edit.html": (
        "4ec13b81be8393fff83d10636d667a6340a1138ea36823cb7d30a5f30c411e2b"
    ),
    "inspinia/templates/solutions/admin-collection-edit.html": (
        "bb0e3f64248b21a30478c1bf5dac242fc207dacb73d3e376f293b2d83dc6ff1e"
    ),
    "inspinia/templates/website/shared_collection.html": (
        "409b530d40be0f2ddcd906a1526a503b7e1e5adb98b42d3a97106ee1b6380f41"
    ),
}


def reader_sources_match(files):
    entries = {item["path"]: item["sha256"] for item in files}
    return any(
        sources and all(entries.get(path) == digest for path, digest in sources.items())
        for sources in (READER_SOURCES, COMPATIBILITY_SOURCES)
    )


def reader_required(registry: Path) -> bool:
    """Absent preserves pre-cutover behavior; malformed/untrusted markers fail closed."""
    marker = registry / MARKER_NAME
    try:
        descriptor = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != ROOT_UID
            or metadata.st_mode & 0o022
            or metadata.st_size > MAX_MARKER_BYTES
        ):
            raise ValueError("Image privacy floor must be a bounded root-owned protected regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            value = json.loads(stream.read(MAX_MARKER_BYTES + 1))
        if (
            not isinstance(value, dict)
            or set(value) != {"format_version", "image_reader_required"}
            or type(value["format_version"]) is not int
            or value["format_version"] != 1
            or value["image_reader_required"] is not True
        ):
            raise ValueError("Image privacy floor has an invalid contract")
        return True
    finally:
        os.close(descriptor)


def verified_reader_release(release: Path) -> bool:
    from scripts.deployment.release_manifest import ManifestError
    from scripts.deployment.release_manifest import ReleaseManifest

    try:
        metadata = release / "release-metadata.json"
        if metadata.is_symlink() or metadata.stat().st_size > 2 * 1024 * 1024:
            return False
        manifest = ReleaseManifest.from_bytes(metadata.read_bytes())
        if manifest.solution_image_reader != READER_VERSION or manifest.release_sha != release.name:
            return False
        entries = {item["path"]: item["sha256"] for item in manifest.files}
        sources = next(
            (
                sources
                for sources in (READER_SOURCES, COMPATIBILITY_SOURCES)
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
