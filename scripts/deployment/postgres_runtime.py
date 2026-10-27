# ruff: noqa: C901, EM101, EM102, PLR0912, PLR0913, PLR0915, PLR2004, S603, S607, T201, TRY003
"""Package and verify a private PostgreSQL runtime from the pinned rehearsal image.

Installation copies verified regular files only. Native database programs run
only in the explicit unprivileged smoke test or the recovery helper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO

IMAGE = "postgres:17.9-bookworm@sha256:47f917f7409eacd22fc5dfb1dee634e1b55cf0c01d1a7eb701be2227a03e0641"
INSTALL_ROOT = Path("/usr/local/libexec/asterproof-recovery-tools/pg17-170009")
BIN = PurePosixPath("usr/lib/postgresql/17/bin")
PLUGIN = PurePosixPath("usr/lib/postgresql/17/lib")
SHARE = PurePosixPath("usr/share/postgresql/17")
LOCALE = PurePosixPath("usr/lib/locale/en_US.utf8")
PROGRAMS = ("pg_dump", "pg_restore", "psql", "initdb", "postgres", "pg_ctl", "createdb")
MANIFEST = "runtime-manifest.json"
LOADER = "ld-linux-x86-64.so.2"
MAX_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILES = 10000
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PostgresRuntimeError(ValueError):
    """The runtime artifact or isolated test did not satisfy its fixed contract."""


def _command(args: list[str], **kwargs) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=180, **kwargs).stdout.strip()


def _hash_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _hash_file(path: Path) -> str:
    with path.open("rb") as handle:
        return _hash_stream(handle)


def program_path(name: str) -> Path:
    if name not in PROGRAMS:
        raise PostgresRuntimeError("Unsupported recovery runtime program")
    return INSTALL_ROOT / str(BIN) / name


def wrapper(name: str) -> bytes:
    if name not in PROGRAMS:
        raise PostgresRuntimeError("Unsupported recovery runtime program")
    return (
        "#!/bin/sh\nexport LOCPATH=" + shlex.quote(str(INSTALL_ROOT / "usr/lib/locale"))
        + "\nexec " + shlex.quote(str(INSTALL_ROOT / "lib" / LOADER))
        + " --library-path " + shlex.quote(str(INSTALL_ROOT / "lib"))
        + " " + shlex.quote(str(program_path(name)) + ".real") + ' "$@"\n'
    ).encode()


def _safe_name(name: str) -> PurePosixPath:
    value = PurePosixPath(name)
    if (
        not name or value.is_absolute() or ".." in value.parts or "\\" in name
        or value.as_posix() != name or any(ord(c) < 32 for c in name)
    ):
        raise PostgresRuntimeError("Unsafe PostgreSQL runtime member path")
    return value


def _allowed(name: str) -> bool:
    path = _safe_name(name)
    if path.parent == BIN:
        return path.name in {*PROGRAMS, *(p + ".real" for p in PROGRAMS)}
    if path.parent == PLUGIN:
        return path.suffix == ".so" and not path.name.startswith("llvmjit")
    if SHARE in path.parents:
        return True
    if LOCALE in path.parents:
        return True
    return path.parent == PurePosixPath("lib") and (
        path.name == LOADER or bool(re.fullmatch(r"lib[A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*", path.name))
    )


def _mode(name: str) -> int:
    return 0o555 if PurePosixPath(name).parent == BIN or name == "lib/" + LOADER else 0o444


def _copy_container(container: str, source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker", "cp", "-L", f"{container}:{source}", str(destination)], check=True, timeout=180)
    if not destination.is_file() or destination.is_symlink():
        raise PostgresRuntimeError("Container runtime member was not copied as a regular file")


def build_runtime(container: str, *, output: Path, source_sha: str) -> dict:
    """Copy public software from the exact existing service image, never DB data."""
    if not re.fullmatch(r"[0-9a-f]{12,64}", container) or not SHA.fullmatch(source_sha):
        raise PostgresRuntimeError("Invalid runtime producer identity")
    if _command(["docker", "inspect", "--format", "{{.Config.Image}}", container]) != IMAGE:
        raise PostgresRuntimeError("Recovery runtime producer is not the pinned PostgreSQL image")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pg17-package-", dir=output.parent) as temporary:
        root = Path(temporary)
        files = _command([
            "docker", "exec", container, "find", "-L", "/usr/share/postgresql/17", "-type", "f", "-print",
        ]).splitlines()
        locale_root = _command(["docker", "exec", container, "mktemp", "-d"])
        if not re.fullmatch(r"/tmp/[A-Za-z0-9_.-]+", locale_root):  # noqa: S108 - validates container mktemp output.
            raise PostgresRuntimeError("Container did not allocate a private locale directory")
        _command([
            "docker", "exec", container, "localedef", "--no-archive", "-i", "en_US", "-f", "UTF-8",
            locale_root + "/en_US.utf8",
        ])
        locale_files = _command([
            "docker", "exec", container, "find", locale_root + "/en_US.utf8", "-type", "f", "-print",
        ]).splitlines()
        plugins = _command([
            "docker", "exec", container, "find", "-L", "/usr/lib/postgresql/17/lib", "-maxdepth", "1",
            "-name", "*.so", "!", "-name", "llvmjit*", "-print",
        ]).splitlines()
        sources = [*("/" + str(BIN / p) for p in PROGRAMS), *plugins]
        dependency_output = _command(["docker", "exec", container, "ldd", *sources])
        libraries: dict[str, str] = {}
        if "not found" in dependency_output:
            raise PostgresRuntimeError("Pinned runtime has unresolved native dependencies")
        for line in dependency_output.splitlines():
            if line.rstrip().endswith(":"):
                continue
            match = re.search(r"(/[^\s()]+)", line)
            if match:
                source = match.group(1)
                name = PurePosixPath(source).name
                if name in libraries and libraries[name] != source:
                    old = _command(["docker", "exec", container, "readlink", "-f", libraries[name]])
                    new = _command(["docker", "exec", container, "readlink", "-f", source])
                    if old != new:
                        raise PostgresRuntimeError("Native dependencies have conflicting library names")
                libraries[name] = source
        if LOADER not in libraries:
            raise PostgresRuntimeError("Pinned native loader was not discovered")
        # Share files and modules retain the compiled relative directory layout.
        for source in [*files, *plugins]:
            relative = source.removeprefix("/")
            if not _allowed(relative):
                raise PostgresRuntimeError("Pinned runtime contains an unexpected share or module path")
            _copy_container(container, source, root / relative)
        for source in locale_files:
            relative = source.replace(locale_root + "/", "usr/lib/locale/", 1)
            if not _allowed(relative):
                raise PostgresRuntimeError("Generated locale has an unexpected path")
            _copy_container(container, source, root / relative)
        for name in PROGRAMS:
            _copy_container(container, "/" + str(BIN / name), root / str(BIN / (name + ".real")))
            (root / str(BIN / name)).write_bytes(wrapper(name))
        for name, source in libraries.items():
            relative = "lib/" + name
            if not _allowed(relative):
                raise PostgresRuntimeError("Pinned runtime contains an unexpected library path")
            _copy_container(container, source, root / relative)
        records = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            name = path.relative_to(root).as_posix()
            records.append({
                "path": name, "sha256": _hash_file(path), "size": path.stat().st_size, "mode": _mode(name),
            })
        manifest = {
            "format_version": 1, "postgres_version": 170009, "image": IMAGE,
            "install_root": str(INSTALL_ROOT), "source_sha": source_sha, "files": records,
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (root / MANIFEST).write_bytes(manifest_bytes)
        with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name in [MANIFEST, *(r["path"] for r in records)]:
                path = root / name
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.mtime = path.stat().st_size, 0o444 if name == MANIFEST else _mode(name), 0
                with path.open("rb") as handle:
                    archive.addfile(item, handle)
        digest = _hash_file(output)
        validate_runtime_archive(output, expected_sha256=digest, expected_source_sha=source_sha)
        summary = {"archive_sha256": digest, "archive_size": output.stat().st_size, **manifest}
        output.with_suffix(".manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary


def _validate(handle: BinaryIO, *, expected_sha256: str, expected_source_sha: str) -> dict:
    if not DIGEST.fullmatch(expected_sha256) or not SHA.fullmatch(expected_source_sha):
        raise PostgresRuntimeError("Invalid expected recovery runtime identity")
    if os.fstat(handle.fileno()).st_size > MAX_BYTES or _hash_stream(handle) != expected_sha256:
        raise PostgresRuntimeError("PostgreSQL runtime archive digest or size mismatch")
    handle.seek(0)
    with tarfile.open(fileobj=handle, mode="r:") as archive:
        members = archive.getmembers()
        if len(members) > MAX_FILES:
            raise PostgresRuntimeError("PostgreSQL runtime archive has too many files")
        names = set()
        for item in members:
            _safe_name(item.name)
            if not item.isfile() or item.name in names or item.size < 0:
                raise PostgresRuntimeError("Runtime archive requires unique regular files only")
            names.add(item.name)
        if MANIFEST not in names or archive.getmember(MANIFEST).size > MAX_MANIFEST_BYTES:
            raise PostgresRuntimeError("Recovery runtime manifest is missing or oversized")
        if any(parent.as_posix() in names for name in names for parent in PurePosixPath(name).parents):
            raise PostgresRuntimeError("Runtime file collides with an ancestor directory")
        stream = archive.extractfile(MANIFEST)
        if stream is None:
            raise PostgresRuntimeError("Recovery runtime manifest cannot be read")
        manifest = json.load(stream)
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"format_version", "postgres_version", "image", "install_root", "source_sha", "files"}
            or type(manifest["format_version"]) is not int or manifest["format_version"] != 1
            or manifest["postgres_version"] != 170009 or manifest["image"] != IMAGE
            or manifest["install_root"] != str(INSTALL_ROOT) or manifest["source_sha"] != expected_source_sha
            or not isinstance(manifest["files"], list)
        ):
            raise PostgresRuntimeError("Recovery runtime manifest identity mismatch")
        records = manifest["files"]
        paths = [r.get("path") for r in records if isinstance(r, dict)]
        if (
            len(paths) != len(records) or any(not isinstance(p, str) for p in paths)
            or paths != sorted(set(paths)) or names != {MANIFEST, *paths}
        ):
            raise PostgresRuntimeError("Recovery runtime manifest membership mismatch")
        required = {str(BIN / n) for n in PROGRAMS} | {str(BIN / (n + ".real")) for n in PROGRAMS}
        required |= {
            "lib/" + LOADER, str(PLUGIN / "plpgsql.so"), str(SHARE / "postgresql.conf.sample"),
            str(LOCALE / "LC_CTYPE"),
        }
        if not required <= set(paths):
            missing = ",".join(sorted(required - set(paths)))
            raise PostgresRuntimeError("Recovery runtime is missing required programs or server support: " + missing)
        total = 0
        for record in records:
            name = record["path"]
            if (
                set(record) != {"path", "sha256", "size", "mode"} or not _allowed(name)
                or type(record["size"]) is not int or record["size"] < 0
                or not isinstance(record["sha256"], str) or not DIGEST.fullmatch(record["sha256"])
                or type(record["mode"]) is not int or record["mode"] != _mode(name)
            ):
                raise PostgresRuntimeError("Invalid recovery runtime manifest file")
            item = archive.getmember(name)
            if item.size != record["size"] or item.mode != record["mode"]:
                raise PostgresRuntimeError("Recovery runtime member size or mode mismatch")
            total += item.size
            if total > MAX_BYTES:
                raise PostgresRuntimeError("Recovery runtime expands beyond its size bound")
            member = archive.extractfile(item)
            if member is None or _hash_stream(member) != record["sha256"]:
                raise PostgresRuntimeError("Recovery runtime member digest mismatch")
            if name in {str(BIN / p) for p in PROGRAMS}:
                member = archive.extractfile(item)
                if member is None or member.read() != wrapper(PurePosixPath(name).name):
                    raise PostgresRuntimeError("Recovery runtime wrapper differs from the fixed launcher")
        if archive.getmember(MANIFEST).mode != 0o444:
            raise PostgresRuntimeError("Recovery runtime manifest has unexpected permissions")
    handle.seek(0)
    return manifest


def validate_runtime_archive(archive: Path, *, expected_sha256: str, expected_source_sha: str) -> dict:
    if archive.is_symlink() or not archive.is_file():
        raise PostgresRuntimeError("Recovery runtime archive must be a regular file")
    with archive.open("rb") as handle:
        return _validate(handle, expected_sha256=expected_sha256, expected_source_sha=expected_source_sha)


def _verify_tree(root: Path, manifest: dict) -> None:
    if root.is_symlink() or not root.is_dir():
        raise PostgresRuntimeError("Installed recovery runtime path is unsafe")
    if root.stat().st_uid != 0 or root.stat().st_mode & 0o222:
        raise PostgresRuntimeError("Installed recovery runtime root ownership or permissions drifted")
    expected = {MANIFEST, *(r["path"] for r in manifest["files"])}
    found = set()
    for path in root.rglob("*"):
        info = path.lstat()
        if info.st_uid != 0 or path.is_symlink() or info.st_mode & 0o222:
            raise PostgresRuntimeError("Installed recovery runtime ownership or permissions drifted")
        if path.is_file():
            if info.st_nlink != 1:
                raise PostgresRuntimeError("Installed recovery runtime contains a hardlink")
            found.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise PostgresRuntimeError("Installed recovery runtime contains a special file")
    if found != expected:
        raise PostgresRuntimeError("Installed recovery runtime contains missing or additional files")
    for record in manifest["files"]:
        path = root / record["path"]
        if (
            path.stat().st_size != record["size"] or stat.S_IMODE(path.stat().st_mode) != record["mode"]
            or _hash_file(path) != record["sha256"]
        ):
            raise PostgresRuntimeError("Installed recovery runtime bytes differ from its manifest")


def verify_installed_runtime(*, source_sha: str | None = None) -> dict:
    path = INSTALL_ROOT / MANIFEST
    if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise PostgresRuntimeError("Installed recovery runtime manifest is unsafe")
    manifest = json.loads(path.read_text())
    if (
        manifest.get("image") != IMAGE or manifest.get("postgres_version") != 170009
        or manifest.get("install_root") != str(INSTALL_ROOT)
        or (source_sha is not None and manifest.get("source_sha") != source_sha)
    ):
        raise PostgresRuntimeError("Installed recovery runtime identity differs")
    _verify_tree(INSTALL_ROOT, manifest)
    return manifest


def validate_installed_runtime(*, expected_source_sha: str) -> dict:
    """Non-mutating preflight; verifies root control, bytes, modes and source."""
    if not SHA.fullmatch(expected_source_sha):
        raise PostgresRuntimeError("Expected runtime source revision is invalid")
    return verify_installed_runtime(source_sha=expected_source_sha)


def validate_and_install_archive(archive: Path, *, expected_sha256: str, expected_source_sha: str) -> dict:
    if os.geteuid() != 0:
        raise PostgresRuntimeError("Recovery runtime installation requires the authorized host administrator")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(archive, flags)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise PostgresRuntimeError("Recovery runtime archive is not stabilized under root control")
        manifest = _validate(handle, expected_sha256=expected_sha256, expected_source_sha=expected_source_sha)
        INSTALL_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        for path in [INSTALL_ROOT.parent, *INSTALL_ROOT.parent.parents]:
            info = path.lstat()
            if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise PostgresRuntimeError("Recovery runtime destination parent is unsafe")
        if INSTALL_ROOT.exists() or INSTALL_ROOT.is_symlink():
            installed = verify_installed_runtime(source_sha=expected_source_sha)
            if installed != manifest:
                raise PostgresRuntimeError("Existing recovery runtime differs; reconcile instead of replacing it")
            return {"state": "already_installed", "source_sha": expected_source_sha, "archive_sha256": expected_sha256}
        staged = INSTALL_ROOT.with_name("." + INSTALL_ROOT.name + ".next")
        staged.mkdir(mode=0o700)  # Existing staging is ambiguous and must not be silently retried.
        with tarfile.open(fileobj=handle, mode="r:") as source:
            for item in source.getmembers():
                destination = staged / item.name
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                member = source.extractfile(item)
                if member is None:
                    raise PostgresRuntimeError("Verified runtime member became unreadable")
                with destination.open("xb") as output:
                    shutil.copyfileobj(member, output, length=1024 * 1024)
                destination.chmod(item.mode)
        for path in sorted((p for p in staged.rglob("*") if p.is_dir()), reverse=True):
            path.chmod(0o555)
        staged.chmod(0o555)
        _verify_tree(staged, manifest)
        staged.rename(INSTALL_ROOT)
        return {"state": "installed", "source_sha": expected_source_sha, "archive_sha256": expected_sha256}


def smoke_runtime() -> dict:
    """Exercise the installed runtime with an owned, private, synthetic cluster."""
    if os.geteuid() == 0:
        raise PostgresRuntimeError("Native recovery runtime programs must not run as root")
    manifest = verify_installed_runtime()
    work = Path(tempfile.mkdtemp(prefix="asterproof-pg17-smoke-"))
    data, socket = work / "data", work / "socket"
    socket.mkdir(mode=0o700)
    environment = {
        "PATH": "/usr/bin:/bin", "HOME": str(work), "LANG": "C.UTF-8", "PGHOST": str(socket),
        "PGPORT": "55439", "PGUSER": "postgres", "PGCONNECT_TIMEOUT": "10",
    }
    started = False
    try:
        for name in PROGRAMS:
            version = _command([str(program_path(name)), "--version"], env=environment)
            if not re.search(r"\b17\.9\b", version):
                raise PostgresRuntimeError("A bundled recovery program has an unexpected version")
        _command([
            str(program_path("initdb")), "-D", str(data), "-A", "trust", "-U", "postgres",
            "--locale=en_US.utf8", "--encoding=UTF8",
        ], env=environment)
        options = shlex.join([
            "-k", str(socket), "-p", "55439", "-c", "listen_addresses=", "-c", "shared_buffers=16MB",
            "-c", "max_connections=10", "-c", "jit=off",
        ])
        _command([
            str(program_path("pg_ctl")), "-D", str(data), "-l", str(work / "postgres.log"),
            "-w", "-o", options, "start",
        ], env=environment)
        started = True
        for name in ("runtime_source", "runtime_restore"):
            _command([str(program_path("createdb")), name], env=environment)
        _command([
            str(program_path("psql")), "-X", "--set=ON_ERROR_STOP=1", "--dbname=runtime_source", "--command",
            "CREATE TABLE preservation(id integer PRIMARY KEY,note text,metadata jsonb);"
            "INSERT INTO preservation VALUES (1,'Keep notes','{\"a\":1}'),(2,'Keep identifiers','{\"b\":2}');",
        ], env=environment)
        dump = work / "synthetic.dump"
        _command([
            str(program_path("pg_dump")), "--format=custom", "--file", str(dump), "--dbname=runtime_source",
        ], env=environment)
        _command([
            str(program_path("pg_restore")), "--exit-on-error", "--no-owner", "--no-privileges",
            "--dbname=runtime_restore", str(dump),
        ], env=environment)
        query = (
            "SELECT count(*)::text||':'||md5(string_agg(id::text||note||metadata::text,',' ORDER BY id)) "
            "FROM preservation"
        )
        digests = [
            _command([
                str(program_path("psql")), "-X", "-At", "--set=ON_ERROR_STOP=1", "--dbname", name,
                "--command", query,
            ], env=environment)
            for name in ("runtime_source", "runtime_restore")
        ]
        if digests[0] != digests[1] or not digests[0].startswith("2:"):
            raise PostgresRuntimeError("Isolated PostgreSQL runtime restore changed its synthetic fixture")
        return {"state": "verified", "postgres_version": 170009, "source_sha": manifest["source_sha"], "rows": 2}
    finally:
        if started:
            _command([str(program_path("pg_ctl")), "-D", str(data), "-m", "immediate", "-w", "stop"], env=environment)
        shutil.rmtree(work)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--container", required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--output", type=Path, required=True)
    install = commands.add_parser("install")
    install.add_argument("--archive", type=Path, required=True)
    install.add_argument("--sha256", required=True)
    install.add_argument("--source-sha", required=True)
    commands.add_parser("smoke")
    args = parser.parse_args()
    if args.command == "build":
        result = build_runtime(args.container, output=args.output, source_sha=args.source_sha)
        result = {k: result[k] for k in ("source_sha", "archive_sha256", "archive_size")}
    elif args.command == "install":
        result = validate_and_install_archive(
            args.archive, expected_sha256=args.sha256, expected_source_sha=args.source_sha,
        )
    else:
        result = smoke_runtime()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
