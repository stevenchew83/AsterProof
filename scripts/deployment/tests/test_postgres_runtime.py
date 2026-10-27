# ruff: noqa: SLF001
"""Runtime integrity checks must reject unsafe public-software archives before installation."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from scripts.deployment import postgres_runtime as runtime

SOURCE = "a" * 40


def artifact(tmp_path, *, changed=None, additional=None, identity=None, member_mode=None):
    contents = {str(runtime.BIN / p): runtime.wrapper(p) for p in runtime.PROGRAMS}
    contents.update({str(runtime.BIN / (p + ".real")): b"\x7fELFsynthetic" for p in runtime.PROGRAMS})
    contents.update({
        "lib/" + runtime.LOADER: b"\x7fELFloader",
        str(runtime.PLUGIN / "plpgsql.so"): b"\x7fELFmodule",
        str(runtime.SHARE / "postgresql.conf.sample"): b"sample",
        str(runtime.LOCALE / "LC_CTYPE"): b"synthetic-locale",
    })
    if additional:
        contents.update(additional)
    records = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": runtime._mode(name)}
        for name, data in sorted(contents.items())
    ]
    manifest = {
        "format_version": 1, "postgres_version": 170009, "image": runtime.IMAGE,
        "install_root": str(runtime.INSTALL_ROOT), "source_sha": SOURCE, "files": records,
        **(identity or {}),
    }
    if changed:
        contents.update(changed)
    contents[runtime.MANIFEST] = json.dumps(manifest).encode()
    output = tmp_path / "runtime.tar"
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in contents.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o444 if name == runtime.MANIFEST else runtime._mode(name)
            if member_mode and name == member_mode[0]:
                item.mode = member_mode[1]
            archive.addfile(item, io.BytesIO(data))
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def validate(path, digest):
    return runtime.validate_runtime_archive(path, expected_sha256=digest, expected_source_sha=SOURCE)


def test_valid_archive_preserves_exact_fixed_launcher_and_manifest(tmp_path):
    path, digest = artifact(tmp_path)
    result = validate(path, digest)
    assert result["image"] == runtime.IMAGE
    assert result["install_root"] == "/usr/local/libexec/asterproof-recovery-tools/pg17-170009"
    assert b"--library-path" in runtime.wrapper("postgres")
    assert b"export LOCPATH=" in runtime.wrapper("initdb")
    assert result["source_sha"] == SOURCE


@pytest.mark.parametrize(("field", "value"), [
    ("source_sha", "b" * 40), ("image", "postgres:latest"), ("format_version", True),
    ("install_root", "/var/another-runtime"), ("postgres_version", 160015),
])
def test_changed_identity_is_rejected(tmp_path, field, value):
    path, digest = artifact(tmp_path, identity={field: value})
    with pytest.raises(runtime.PostgresRuntimeError, match="identity mismatch"):
        validate(path, digest)


def test_incorrect_archive_digest_is_rejected(tmp_path):
    path, _ = artifact(tmp_path)
    with pytest.raises(runtime.PostgresRuntimeError, match="digest or size"):
        validate(path, "0" * 64)


def test_modified_regular_member_is_rejected(tmp_path):
    path, digest = artifact(tmp_path, changed={str(runtime.BIN / "pg_dump.real"): b"modified executable"})
    with pytest.raises(runtime.PostgresRuntimeError, match="size or mode|digest mismatch"):
        validate(path, digest)


def test_arbitrary_wrapper_is_rejected_even_if_its_digest_matches(tmp_path):
    name = str(runtime.BIN / "postgres")
    path, digest = artifact(tmp_path, additional={name: b"#!/bin/sh\nexec unexpected\n"})
    with pytest.raises(runtime.PostgresRuntimeError, match="fixed launcher"):
        validate(path, digest)


@pytest.mark.parametrize("name", [
    "../outside", "/etc/secret", "usr/lib/postgresql/17/bin/arbitrary", "lib/libx/../../bad",
])
def test_unsafe_or_unapproved_paths_are_rejected(tmp_path, name):
    path, digest = artifact(tmp_path, additional={name: b"unexpected"})
    with pytest.raises(runtime.PostgresRuntimeError, match="Unsafe|Invalid"):
        validate(path, digest)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.DIRTYPE])
def test_nonregular_members_are_rejected(tmp_path, kind):
    path, _ = artifact(tmp_path)
    with tarfile.open(path, "a") as archive:
        item = tarfile.TarInfo("usr/share/postgresql/17/unsafe")
        item.type, item.linkname = kind, "../../outside"
        archive.addfile(item)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(runtime.PostgresRuntimeError, match="regular files"):
        validate(path, digest)


def test_duplicate_file_is_rejected(tmp_path):
    path, _ = artifact(tmp_path)
    with tarfile.open(path, "a") as archive:
        item = tarfile.TarInfo("lib/" + runtime.LOADER)
        item.size = 0
        archive.addfile(item, io.BytesIO(b""))
    with pytest.raises(runtime.PostgresRuntimeError, match="unique regular"):
        validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_member_permissions_are_bound_to_manifest(tmp_path):
    path, digest = artifact(tmp_path, member_mode=(str(runtime.BIN / "pg_dump"), 0o777))
    with pytest.raises(runtime.PostgresRuntimeError, match="size or mode"):
        validate(path, digest)


def test_input_symlink_is_rejected(tmp_path):
    path, digest = artifact(tmp_path)
    link = tmp_path / "linked.tar"
    link.symlink_to(path)
    with pytest.raises(runtime.PostgresRuntimeError, match="regular file"):
        validate(link, digest)


def test_install_requires_host_administrator_without_executing_native_programs(tmp_path, monkeypatch):
    path, digest = artifact(tmp_path)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 1000)
    with pytest.raises(runtime.PostgresRuntimeError, match="host administrator"):
        runtime.validate_and_install_archive(path, expected_sha256=digest, expected_source_sha=SOURCE)


def test_native_smoke_refuses_root(monkeypatch):
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0)
    with pytest.raises(runtime.PostgresRuntimeError, match="must not run as root"):
        runtime.smoke_runtime()


def test_program_names_cannot_supply_an_arbitrary_executable():
    with pytest.raises(runtime.PostgresRuntimeError, match="Unsupported"):
        runtime.program_path("../sh")


def test_builder_rejects_nonfixed_container_identity_before_docker_calls(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Docker was invoked before checking the producer identity")

    monkeypatch.setattr(runtime, "_command", forbidden)
    with pytest.raises(runtime.PostgresRuntimeError, match="producer identity"):
        runtime.build_runtime("container;unexpected", output=tmp_path / "tool.tar", source_sha=SOURCE)
