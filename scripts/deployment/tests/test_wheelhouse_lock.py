from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.deployment.release_manifest import sha256_file
from scripts.deployment.wheelhouse_lock import render_wheelhouse_lock


def _fixture(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    source_lock = tmp_path / "production.lock"
    # Source archive hashes intentionally differ from the built wheel hashes.
    source_lock.write_text("django-allauth==65.8.0 --hash=sha256:" + "a" * 64 + "\n")
    return wheelhouse, source_lock


def _wheel(wheelhouse, *, name="django-allauth", version="65.8.0", tag="py3-none-any"):
    distribution = name.replace("-", "_")
    path = wheelhouse / f"{distribution}-{version}-{tag}.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{distribution}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
    return path


def test_source_only_package_gets_built_wheel_hash_without_changing_version(tmp_path):
    wheelhouse, source_lock = _fixture(tmp_path)
    wheel = _wheel(wheelhouse)
    content = render_wheelhouse_lock(wheelhouse, source_lock)
    assert f"django-allauth==65.8.0 --hash=sha256:{sha256_file(wheel)}\n" in content
    assert "a" * 64 not in content
    (wheelhouse / "install.lock").write_text(content)
    assert render_wheelhouse_lock(wheelhouse, source_lock) == content


@pytest.mark.parametrize("change", ["missing", "extra", "version", "duplicate", "source_archive", "symlink"])
def test_incomplete_or_changed_wheelhouse_is_rejected(tmp_path, change):
    wheelhouse, source_lock = _fixture(tmp_path)
    if change != "missing":
        _wheel(wheelhouse, version="65.9.0" if change == "version" else "65.8.0")
    if change == "extra":
        _wheel(wheelhouse, name="unexpected")
    elif change == "duplicate":
        _wheel(wheelhouse, tag="py2.py3-none-any")
    elif change == "source_archive":
        (wheelhouse / "source.tar.gz").write_bytes(b"source")
    elif change == "symlink":
        (wheelhouse / "install.lock").symlink_to(source_lock)
    with pytest.raises(ValueError, match="wheelhouse"):
        render_wheelhouse_lock(wheelhouse, source_lock)


def test_offline_installs_use_the_generated_hash_lock_with_no_source_builds():
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/production-deploy.yml").read_text()
    prepare = (root / "scripts/deployment/prepare_release.py").read_text()
    assert "pip wheel --require-hashes --only-binary=:all: --no-binary=django-allauth" in workflow
    assert "scripts.deployment.wheelhouse_lock" in workflow
    assert "--only-binary=:all: --find-links .release-wheelhouse -r .release-wheelhouse/install.lock" in workflow
    assert '"--only-binary=:all:"' in prepare
    assert 'destination / "wheelhouse/install.lock"' in prepare
