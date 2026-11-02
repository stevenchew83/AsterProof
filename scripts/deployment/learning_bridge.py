"""One frozen, read-only bridge activation before the shared-learning schema.

Trusted code inspects candidate bytes and metadata only. Candidate Python runs as
its application identity with PostgreSQL transactions forced read-only.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path  # noqa: TC003

from scripts.deployment import learning_compat
from scripts.deployment import learning_schema
from scripts.deployment.release_manifest import ReleaseManifest

PRODUCTION_SETTINGS = "config/settings/production.py"
PRODUCTION_SHA256 = "2595557222e5c71f56c0c3527d6a8f3a99bf2cda7e04bdaff615fff34505e495"
BRIDGE_MARKER = re.compile(rb"(?m)^\s*LEARNING_READER_BRIDGE\s*=\s*True\b")
MAX_SETTINGS_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class LearningBridgeError(ValueError):
    pass


def _read_static(release: Path, relative: str, *, maximum=None):
    path = release / relative
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent == release or release in parent.parents):
        message = "Learning bridge source files cannot be symlinks"
        raise LearningBridgeError(message)
    if not path.is_file():
        message = "Learning bridge source files must be regular files"
        raise LearningBridgeError(message)
    try:
        with path.open("rb") as stream:
            value = stream.read(maximum + 1) if maximum is not None else stream.read()
    except OSError as exc:
        message = "Learning bridge source file is unavailable"
        raise LearningBridgeError(message) from exc
    if maximum is not None and len(value) > maximum:
        message = "Learning bridge source file exceeds its bound"
        raise LearningBridgeError(message)
    return value


def has_bridge_marker(release: Path) -> bool:
    path = release / PRODUCTION_SETTINGS
    if not path.exists() and not path.is_symlink():
        return False
    return bool(BRIDGE_MARKER.search(_read_static(release, PRODUCTION_SETTINGS, maximum=MAX_SETTINGS_BYTES)))


def is_bridge_source(release: Path) -> bool:
    try:
        body = _read_static(release, PRODUCTION_SETTINGS, maximum=MAX_SETTINGS_BYTES)
    except LearningBridgeError:
        return False
    return hashlib.sha256(body).hexdigest() == PRODUCTION_SHA256


def validate_bridge_source(release: Path) -> None:
    if not is_bridge_source(release):
        message = "Production settings do not match the frozen learning reader bridge"
        raise LearningBridgeError(message)
    for relative, expected in learning_compat.READER_SOURCES.items():
        if hashlib.sha256(_read_static(release, relative, maximum=MAX_MANIFEST_BYTES)).hexdigest() != expected:
            message = "Learning bridge reader bytes differ from the reviewed capability"
            raise LearningBridgeError(message)
    learning_schema.validate_candidate(release)


def validate_bridge_candidate(release: Path) -> None:
    validate_bridge_source(release)
    manifest = ReleaseManifest.from_bytes(
        _read_static(release, "release-metadata.json", maximum=MAX_MANIFEST_BYTES),
    )
    entries = {item["path"]: item["sha256"] for item in manifest.files}
    if entries.get(PRODUCTION_SETTINGS) != PRODUCTION_SHA256 or not learning_compat.verified_reader_release(
        release, manifest=manifest,
    ):
        message = "Learning bridge manifest or actual guarded reader bytes are invalid"
        raise LearningBridgeError(message)


PLAN_CHECK = f"""from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
if settings.SETTINGS_MODULE != 'config.settings.production':
    raise RuntimeError('Learning bridge requires the production settings module')
if getattr(settings, 'LEARNING_READER_BRIDGE', None) is not True or any(
    getattr(settings, name, None) is not False
    for name in ('LEARNING_MODULE_ENABLED','LEARNING_CONTRIBUTIONS_ENABLED','LEARNING_PUBLICATION_ENABLED')
):
    raise RuntimeError('Learning bridge must keep all learning features disabled')
if connection.vendor != 'postgresql' or connection.pg_version != {learning_schema.POSTGRES_VERSION!r}:
    raise RuntimeError('Learning bridge requires PostgreSQL 17.9')
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SET LOCAL lock_timeout='2s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        cursor.execute({learning_compat.FLOOR_SQL!r})
        if cursor.fetchone() != (False,):
            raise RuntimeError('Learning bridge exception requires the learning schema to be absent')
    executor=MigrationExecutor(connection)
    plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
    actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
    if actual != {learning_schema.EXPECTED_PLAN!r}:
        raise RuntimeError('Learning bridge permits only the exact four deferred migrations')
"""
