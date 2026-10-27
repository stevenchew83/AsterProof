"""Recovery plaintext is usable only after authentication and its recorded hash pass."""

from __future__ import annotations

import hashlib
import io
import os
import stat

import pytest

from scripts.deployment import recovery_crypto as crypto

AAD = b"fixed-recovery-operation-and-database-identity"
PRIVATE_MODE = 0o600


def paths(tmp_path):
    root = tmp_path.resolve()
    return root / "archive.enc", root / "key.bin", root / "restore.dump"


@pytest.mark.parametrize("payload", [b"", b"small database dump", bytes(range(256)) * 1000])
def test_roundtrip_is_streamed_private_and_returns_only_integrity_metadata(tmp_path, payload):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(payload), archive, key, AAD)
    assert set(result) == {"plaintext_sha256", "ciphertext_sha256", "plaintext_bytes", "ciphertext_bytes"}
    assert result["plaintext_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["ciphertext_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert result["plaintext_bytes"] == len(payload)
    assert result["ciphertext_bytes"] == archive.stat().st_size
    assert len(key.read_bytes()) == crypto.KEY_BYTES
    assert all(stat.S_IMODE(p.stat().st_mode) == PRIVATE_MODE for p in (archive, key))
    crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert restored.read_bytes() == payload
    assert stat.S_IMODE(restored.stat().st_mode) == PRIVATE_MODE


@pytest.mark.parametrize("mutation", ["header", "nonce", "ciphertext", "tag", "aad", "key", "hash", "truncate"])
def test_modified_or_misbound_archive_leaves_no_new_plaintext_and_retains_originals(tmp_path, mutation):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(b"database records and private notes"), archive, key, AAD)
    data = bytearray(archive.read_bytes())
    aad, expected = AAD, result["plaintext_sha256"]
    if mutation == "header":
        data[0] ^= 1
    elif mutation == "nonce":
        data[len(crypto.MAGIC)] ^= 1
    elif mutation == "ciphertext":
        data[len(crypto.MAGIC) + crypto.NONCE_BYTES] ^= 1
    elif mutation == "tag":
        data[-1] ^= 1
    elif mutation == "aad":
        aad = b"another database"
    elif mutation == "key":
        key.write_bytes(b"x" * crypto.KEY_BYTES)
    elif mutation == "hash":
        expected = "0" * 64
    else:
        data = data[:len(crypto.MAGIC)]
    archive.write_bytes(data)
    with pytest.raises(crypto.RecoveryCryptoError):
        crypto.decrypt_archive(archive, restored, key, aad, expected)
    assert not restored.exists()
    assert archive.exists()
    assert key.exists()


@pytest.mark.parametrize("collision", ["archive", "key", "restore"])
def test_existing_files_are_never_overwritten(tmp_path, collision):
    archive, key, restored = paths(tmp_path)
    if collision in {"archive", "key"}:
        target = archive if collision == "archive" else key
        target.write_bytes(b"keep existing operation")
        with pytest.raises(crypto.RecoveryCryptoError, match="existing file"):
            crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
    else:
        result = crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
        target = restored
        target.write_bytes(b"keep existing operation")
        with pytest.raises(crypto.RecoveryCryptoError, match="existing file"):
            crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert target.read_bytes() == b"keep existing operation"


@pytest.mark.parametrize("link", ["archive", "key", "restore"])
def test_symlink_paths_are_rejected(tmp_path, link):
    archive, key, restored = paths(tmp_path)
    target = tmp_path.resolve() / "keep"
    target.write_bytes(b"untouched")
    if link in {"archive", "key"}:
        (archive if link == "archive" else key).symlink_to(target)
        with pytest.raises(crypto.RecoveryCryptoError):
            crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
    else:
        result = crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
        restored.symlink_to(target)
        with pytest.raises(crypto.RecoveryCryptoError):
            crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert target.read_bytes() == b"untouched"


def test_decrypt_rejects_linked_or_public_key_without_creating_plaintext(tmp_path):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
    key.chmod(0o644)
    with pytest.raises(crypto.RecoveryCryptoError, match="private"):
        crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert not restored.exists()


@pytest.mark.parametrize("input_name", ["archive", "key"])
def test_decrypt_never_follows_an_input_symlink(tmp_path, input_name):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
    link = tmp_path.resolve() / "input-link"
    link.symlink_to(archive if input_name == "archive" else key)
    with pytest.raises(crypto.RecoveryCryptoError, match="without following links"):
        crypto.decrypt_archive(
            link if input_name == "archive" else archive, restored,
            link if input_name == "key" else key, AAD, result["plaintext_sha256"],
        )
    assert not restored.exists()


def test_decrypt_rejects_a_hardlinked_input(tmp_path):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(b"new"), archive, key, AAD)
    os.link(key, tmp_path.resolve() / "aliased-key")
    with pytest.raises(crypto.RecoveryCryptoError, match="single-link"):
        crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert not restored.exists()


def test_size_guard_retains_private_partial_work_for_explicit_reconciliation(tmp_path, monkeypatch):
    archive, key, _ = paths(tmp_path)
    monkeypatch.setattr(crypto, "MAX_PLAINTEXT_BYTES", 8)
    with pytest.raises(crypto.RecoveryCryptoError, match="size limit"):
        crypto.encrypt_stream(io.BytesIO(b"too many bytes"), archive, key, AAD)
    assert key.exists()
    assert archive.exists()
    assert archive.stat().st_size <= len(crypto.MAGIC) + crypto.NONCE_BYTES + 8
    with pytest.raises(crypto.RecoveryCryptoError, match="existing file"):
        crypto.encrypt_stream(io.BytesIO(b"retry"), archive, key, AAD)


def test_decrypt_rejects_short_key_and_oversized_ciphertext(tmp_path, monkeypatch):
    archive, key, restored = paths(tmp_path)
    result = crypto.encrypt_stream(io.BytesIO(b"sample"), archive, key, AAD)
    original = key.read_bytes()
    key.write_bytes(b"short")
    with pytest.raises(crypto.RecoveryCryptoError, match="key length"):
        crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    key.write_bytes(original)
    monkeypatch.setattr(crypto, "MAX_PLAINTEXT_BYTES", 1)
    with pytest.raises(crypto.RecoveryCryptoError, match="size limit"):
        crypto.decrypt_archive(archive, restored, key, AAD, result["plaintext_sha256"])
    assert not restored.exists()
