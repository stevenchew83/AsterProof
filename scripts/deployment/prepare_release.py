# ruff: noqa: EM101, PLR0913, S603, S607, TRY003
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
from pathlib import Path

from scripts.deployment.archive_safety import safe_extract


def _materialize_internal_symlinks(destination: Path) -> None:
    root = destination.resolve(strict=True)
    for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink():
            continue
        target_text = path.readlink()
        if Path(target_text).is_absolute():
            raise ValueError("prepared release contains an absolute symlink")
        target = path.resolve(strict=True)
        if target != root and root not in target.parents:
            raise ValueError("prepared release symlink escapes the release")
        path.unlink()
        if target.is_dir():
            shutil.copytree(target, path, symlinks=False)
        elif target.is_file():
            shutil.copy2(target, path)
        else:
            raise ValueError("prepared release symlink target is invalid")


def _rewrite_venv_shebangs(venv: Path, *, staging: Path, final: Path) -> None:
    staging_prefix = f"#!{staging}".encode()
    final_prefix = f"#!{final}".encode()
    for path in (venv / "bin").iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        content = path.read_bytes()
        first_line, separator, remainder = content.partition(b"\n")
        if first_line.startswith(staging_prefix):
            path.write_bytes(first_line.replace(staging_prefix, final_prefix, 1) + separator + remainder)


def _freeze_release(destination: Path) -> None:
    for root, directories, files in os.walk(destination, topdown=False, followlinks=False):
        for name in files + directories:
            path = Path(root) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if stat.S_ISDIR(mode):
                path.chmod(0o555)
            elif stat.S_ISREG(mode):
                path.chmod(0o555 if mode & 0o111 else 0o444)
            else:
                raise ValueError("prepared release contains a prohibited member type")
    destination.chmod(0o555)


def prepare_release(
    *,
    archive: Path,
    destination: Path,
    final_destination: Path,
    digest: str,
    python_executable: Path,
    repository: str,
    repository_id: str,
    python_abi: str,
    target_platform: str,
) -> None:
    if not final_destination.is_absolute() or final_destination.name != destination.name:
        raise ValueError("final release destination is invalid")
    manifest = safe_extract(archive, destination, expected_digest=digest)
    if destination.name != manifest.release_sha:
        raise ValueError("release directory does not match manifest SHA")
    if (
        manifest.repository != repository
        or manifest.repository_id != repository_id
        or manifest.python_abi != python_abi
        or manifest.target_platform != target_platform
    ):
        raise ValueError("release metadata does not match the target contract")
    venv = destination / ".venv"
    subprocess.run([str(python_executable), "-m", "venv", "--copies", str(venv)], check=True)
    env = os.environ.copy()
    env["PIP_NO_INDEX"] = "1"
    env["PIP_FIND_LINKS"] = str(destination / "wheelhouse")
    subprocess.run(
        [
            str(venv / "bin/python"),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--require-hashes",
            "--find-links",
            str(destination / "wheelhouse"),
            "-r",
            str(destination / "requirements/production.lock"),
        ],
        check=True,
        env=env,
    )
    _rewrite_venv_shebangs(venv, staging=destination, final=final_destination)
    _materialize_internal_symlinks(destination)
    _freeze_release(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--final-destination", type=Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--python-abi", required=True)
    parser.add_argument("--target-platform", required=True)
    args = parser.parse_args()
    prepare_release(
        archive=args.archive,
        destination=args.destination,
        final_destination=args.final_destination,
        digest=args.digest,
        python_executable=args.python,
        repository=args.repository,
        repository_id=args.repository_id,
        python_abi=args.python_abi,
        target_platform=args.target_platform,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
