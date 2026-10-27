# ruff: noqa: EM101, TRY003, TRY301
"""Authenticated streaming encryption for root-held database recovery archives.

The caller owns and checks directory isolation. Files are private, exclusive,
and durable; an unfinished encryption is retained for explicit reconciliation.
Decryption never leaves an unauthenticated newly created plaintext output.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from typing import TYPE_CHECKING
from typing import BinaryIO

if TYPE_CHECKING:
    from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes

MAGIC = b"ASTERPROOF-DB-BACKUP\x01"
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 64 * 1024
MAX_PLAINTEXT_BYTES = 1024 * 1024 * 1024
MAX_AAD_BYTES = 64 * 1024


class RecoveryCryptoError(ValueError):
    """A recovery archive cannot be safely created or authenticated."""


def _error(message: str) -> RecoveryCryptoError:
    return RecoveryCryptoError(message)


def _check_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise _error("Recovery archive paths must be absolute and canonical")
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise _error("Recovery archive parent directories must not be symlinks")


def _missing(path: Path) -> None:
    _check_path(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise _error("Recovery archive operation collides with an existing file; reconcile before retrying")


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_private(path: Path) -> BinaryIO:
    _check_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise _error("Recovery output already exists; reconcile before retrying") from exc
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "wb")


def _open_private(path: Path) -> BinaryIO:
    _check_path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _error("Recovery archive input cannot be opened without following links") from exc
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077
    ):
        os.close(descriptor)
        raise _error("Recovery archive input is not a private, owned, single-link regular file")
    return os.fdopen(descriptor, "rb")


def _aad(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) > MAX_AAD_BYTES:
        raise _error("Recovery archive associated data must be bounded bytes")
    return value


def _durable(handle: BinaryIO, path: Path) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    _sync_directory(path.parent)


def encrypt_stream(source: BinaryIO, destination: Path, key_path: Path, aad: bytes) -> dict:
    """Create one authenticated ciphertext/key pair; never overwrite prior work."""
    associated = _aad(aad)
    _missing(destination)
    _missing(key_path)
    if destination == key_path:
        raise _error("Recovery archive and encryption key paths must differ")
    key = secrets.token_bytes(KEY_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    header = MAGIC + nonce
    with _create_private(key_path) as output:
        output.write(key)
        _durable(output, key_path)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header + associated)
    plaintext_hash, ciphertext_hash = hashlib.sha256(), hashlib.sha256()
    plaintext_bytes, ciphertext_bytes = 0, len(header)
    with _create_private(destination) as output:
        output.write(header)
        ciphertext_hash.update(header)
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not isinstance(chunk, bytes):
                raise _error("Recovery source must supply blocking binary chunks")
            if not chunk:
                break
            plaintext_bytes += len(chunk)
            if plaintext_bytes > MAX_PLAINTEXT_BYTES:
                raise _error("Recovery archive exceeds the plaintext size limit")
            plaintext_hash.update(chunk)
            encoded = encryptor.update(chunk)
            output.write(encoded)
            ciphertext_hash.update(encoded)
            ciphertext_bytes += len(encoded)
        final = encryptor.finalize()
        output.write(final)
        output.write(encryptor.tag)
        ciphertext_hash.update(final)
        ciphertext_hash.update(encryptor.tag)
        ciphertext_bytes += len(final) + len(encryptor.tag)
        _durable(output, destination)
    return {
        "plaintext_sha256": plaintext_hash.hexdigest(), "ciphertext_sha256": ciphertext_hash.hexdigest(),
        "plaintext_bytes": plaintext_bytes, "ciphertext_bytes": ciphertext_bytes,
    }


def _remove_created(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (info.st_dev, info.st_ino) == identity and stat.S_ISREG(info.st_mode):
        path.unlink()
        _sync_directory(path.parent)


def decrypt_archive(
    archive: Path, destination: Path, key_path: Path, aad: bytes, expected_plaintext_sha256: str,
) -> None:
    """Authenticate and hash a new private plaintext file before returning it."""
    associated = _aad(aad)
    if not isinstance(expected_plaintext_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plaintext_sha256):
        raise _error("Expected recovery plaintext digest is invalid")
    _missing(destination)
    identity = None
    try:
        with _open_private(archive) as source, _open_private(key_path) as key_input:
            key = key_input.read(KEY_BYTES + 1)
            if len(key) != KEY_BYTES:
                raise _error("Recovery encryption key length is invalid")
            size = os.fstat(source.fileno()).st_size
            overhead = len(MAGIC) + NONCE_BYTES + TAG_BYTES
            if not overhead <= size <= MAX_PLAINTEXT_BYTES + overhead:
                raise _error("Recovery ciphertext is truncated or exceeds the size limit")
            header = source.read(len(MAGIC) + NONCE_BYTES)
            if header[:len(MAGIC)] != MAGIC:
                raise _error("Recovery archive format header is invalid")
            nonce = header[len(MAGIC):]
            source.seek(-TAG_BYTES, os.SEEK_END)
            tag = source.read(TAG_BYTES)
            source.seek(len(header))
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(header + associated)
            digest = hashlib.sha256()
            remaining = size - overhead
            with _create_private(destination) as output:
                info = os.fstat(output.fileno())
                identity = (info.st_dev, info.st_ino)
                while remaining:
                    chunk = source.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise _error("Recovery ciphertext ended before its authenticated boundary")
                    remaining -= len(chunk)
                    decoded = decryptor.update(chunk)
                    output.write(decoded)
                    digest.update(decoded)
                decoded = decryptor.finalize()
                output.write(decoded)
                digest.update(decoded)
                if digest.hexdigest() != expected_plaintext_sha256:
                    raise _error("Recovered plaintext digest does not match the recorded archive")
                _durable(output, destination)
    except BaseException as exc:
        _remove_created(destination, identity)
        if isinstance(exc, InvalidTag):
            raise _error("Recovery archive authentication failed") from exc
        raise
