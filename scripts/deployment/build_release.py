# ruff: noqa: EM101, EM102, PLR0913, RET504, S603, S607, T201, TRY003
from __future__ import annotations

import argparse
import io
import json
import stat
import subprocess
import tarfile
import tempfile
from datetime import UTC
from datetime import datetime
from pathlib import Path

from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_manifest import sha256_file

EXCLUDED_PARTS = {".git", ".venv", "node_modules", "__pycache__", "media"}
EXCLUDED_NAMES = {".env"}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _tracked_files(root: Path, release_sha: str) -> list[Path]:
    if _git(root, "rev-parse", "HEAD") != release_sha:
        raise ValueError("checked-out commit does not match requested release SHA")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=root, check=False).returncode:
        raise ValueError("tracked worktree changes are not allowed in a release")
    values = _git(root, "ls-files", "-z").split("\x00")
    paths = [Path(value) for value in values if value]
    for path in paths:
        absolute = root / path
        if not absolute.is_file() or absolute.is_symlink():
            raise ValueError(f"tracked release entry must be a regular file: {path}")
        if path.name in EXCLUDED_NAMES or EXCLUDED_PARTS.intersection(path.parts):
            raise ValueError(f"tracked release entry is prohibited: {path}")
    return sorted(paths, key=lambda value: value.as_posix())


def _add_tree(entries: dict[str, Path], prefix: str, root: Path) -> None:
    if not root.is_dir():
        raise ValueError(f"required release tree is missing: {root}")
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"release tree contains a prohibited entry: {path}")
        relative = path.relative_to(root).as_posix()
        entries[f"{prefix}/{relative}"] = path


def build_release(
    *,
    repository_root: Path,
    static_root: Path,
    wheelhouse: Path,
    output: Path,
    repository: str,
    repository_id: str,
    release_sha: str,
    run_id: str,
    target_platform: str,
    python_abi: str,
    built_at: str,
    source_date_epoch: int,
) -> dict[str, object]:
    entries = {path.as_posix(): repository_root / path for path in _tracked_files(repository_root, release_sha)}
    _add_tree(entries, "staticfiles", static_root)
    _add_tree(entries, "wheelhouse", wheelhouse)

    files = tuple(
        {
            "path": relative,
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
        for relative, path in sorted(entries.items())
    )
    manifest = ReleaseManifest(
        repository=repository,
        repository_id=repository_id,
        release_sha=release_sha,
        run_id=run_id,
        built_at=built_at,
        target_platform=target_platform,
        python_abi=python_abi,
        files=files,
    )
    manifest_bytes = manifest.to_json_bytes()

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with tarfile.open(temporary_path, "w", format=tarfile.PAX_FORMAT) as archive:
            for relative, path in sorted(entries.items()):
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = source_date_epoch
                info.mode = 0o755 if stat.S_IMODE(path.stat().st_mode) & 0o111 else 0o644
                info.pax_headers = {}
                with path.open("rb") as source:
                    archive.addfile(info, source)
            metadata = tarfile.TarInfo("release-metadata.json")
            metadata.size = len(manifest_bytes)
            metadata.mode = 0o644
            metadata.uid = metadata.gid = 0
            metadata.mtime = source_date_epoch
            archive.addfile(metadata, fileobj=io.BytesIO(manifest_bytes))
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)

    envelope = {
        "archive_sha256": sha256_file(output),
        "archive_size": output.stat().st_size,
        "release_sha": release_sha,
        "repository": repository,
        "repository_id": repository_id,
        "run_id": run_id,
    }
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-platform", required=True)
    parser.add_argument("--python-abi", default="cp312")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    epoch = int(_git(root, "show", "-s", "--format=%ct", args.release_sha))
    built_at = datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")
    envelope = build_release(
        repository_root=root,
        static_root=args.static_root.resolve(),
        wheelhouse=args.wheelhouse.resolve(),
        output=args.output.resolve(),
        repository=args.repository,
        repository_id=args.repository_id,
        release_sha=args.release_sha,
        run_id=args.run_id,
        target_platform=args.target_platform,
        python_abi=args.python_abi,
        built_at=built_at,
        source_date_epoch=epoch,
    )
    args.envelope.write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n")
    print(json.dumps(envelope, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
