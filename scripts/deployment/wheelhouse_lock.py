"""Hash-lock built wheels while preserving the reviewed production versions."""

from __future__ import annotations

import argparse
import email.parser
import zipfile
from pathlib import Path

from scripts.deployment.check_production_lock import LOCK_ENTRY_RE
from scripts.deployment.check_production_lock import normalize_name
from scripts.deployment.check_production_lock import validate_locked_entries
from scripts.deployment.release_manifest import sha256_file


def render_wheelhouse_lock(wheelhouse: Path, source_lock: Path) -> str:
    lines = source_lock.read_text(encoding="utf-8").splitlines()
    validate_locked_entries(lines)
    expected = {
        normalize_name(match.group(1)): match.group(2)
        for line in lines
        if (match := LOCK_ENTRY_RE.match(line))
    }
    wheels = {}
    for path in sorted(wheelhouse.iterdir()):
        if path.name == "install.lock" and path.is_file() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
            msg = "wheelhouse must contain only regular wheel files"
            raise ValueError(msg)
        with zipfile.ZipFile(path) as wheel:
            metadata_paths = [
                name for name in wheel.namelist()
                if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                msg = f"wheel must contain exactly one top-level distribution metadata file: {path.name}"
                raise ValueError(msg)
            metadata = email.parser.BytesParser().parsebytes(wheel.read(metadata_paths[0]))
        name = normalize_name(metadata.get("Name", ""))
        version = metadata.get("Version", "")
        if name in wheels or name not in expected or expected[name] != version:
            msg = "wheelhouse distribution differs from reviewed production pins"
            raise ValueError(msg)
        wheels[name] = (version, sha256_file(path))
    if set(wheels) != set(expected):
        msg = "wheelhouse is missing reviewed production distributions"
        raise ValueError(msg)
    return "# Built wheel hashes; versions match requirements/production.lock\n" + "".join(
        f"{name}=={version} --hash=sha256:{digest}\n"
        for name, (version, digest) in sorted(wheels.items())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    args = parser.parse_args()
    content = render_wheelhouse_lock(args.wheelhouse, args.source_lock)
    (args.wheelhouse / "install.lock").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
