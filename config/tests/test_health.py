from __future__ import annotations

import importlib
import json
import os
from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import RequestFactory

from config import health


@pytest.fixture
def valid_state() -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "status": "ok",
        "process_commit_sha": "a" * 40,
        "artifact_sha256": "b" * 64,
        "state_fingerprint": "c" * 64,
        "recorded_at": "2026-09-01T00:00:00Z",
    }


def _write_state(release_root, state) -> None:
    (release_root / health.RUNTIME_RELEASE_STATE_FILENAME).write_text(
        json.dumps(state),
        encoding="utf-8",
    )


def test_healthz_returns_process_release_state_without_cache(rf, monkeypatch, valid_state):
    monkeypatch.setattr(
        health,
        "PROCESS_RUNTIME_RELEASE_STATE",
        health.RuntimeReleaseState(**valid_state),
    )

    response = health.healthz(rf.get("/healthz/"))

    assert response.status_code == HTTPStatus.OK
    assert response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.content) == valid_state


def test_healthz_missing_state_fails_without_detail(rf, monkeypatch):
    monkeypatch.setattr(health, "PROCESS_RUNTIME_RELEASE_STATE", None)

    response = health.healthz(rf.get("/healthz/"))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.content) == {"status": "unavailable"}


def test_healthz_rejects_non_get_without_state_detail(rf):
    response = health.healthz(rf.post("/healthz/"))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers["Allow"] == "GET"
    assert response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.content) == {"status": "method_not_allowed"}


def test_healthz_url_is_public(client, monkeypatch, valid_state):
    monkeypatch.setattr(
        health,
        "PROCESS_RUNTIME_RELEASE_STATE",
        health.RuntimeReleaseState(**valid_state),
    )

    response = client.get("/healthz/")

    assert response.status_code == HTTPStatus.OK


def test_runtime_state_is_bound_once_at_process_startup(
    monkeypatch,
    tmp_path,
    valid_state,
):
    original_base_dir = settings.BASE_DIR
    _write_state(tmp_path, valid_state)
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    reloaded_health = importlib.reload(health)

    changed_state = {**valid_state, "process_commit_sha": "d" * 40}
    _write_state(tmp_path, changed_state)

    response = reloaded_health.healthz(RequestFactory().get("/healthz/"))
    assert json.loads(response.content)["process_commit_sha"] == "a" * 40

    monkeypatch.setattr(settings, "BASE_DIR", original_base_dir)
    importlib.reload(health)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: {**state, "schema_version": 2},
        lambda state: {**state, "schema_version": True},
        lambda state: {**state, "extra": "not-allowed"},
        lambda state: {**state, "process_commit_sha": "A" * 40},
        lambda state: {**state, "artifact_sha256": "short"},
        lambda state: {**state, "state_fingerprint": "not-a-digest"},
        lambda state: {**state, "recorded_at": "2026-02-30T00:00:00Z"},
        lambda state: {**state, "status": "degraded"},
    ],
)
def test_runtime_state_rejects_wrong_version_shape_or_values(tmp_path, valid_state, mutate):
    _write_state(tmp_path, mutate(valid_state))

    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)


def test_runtime_state_rejects_malformed_json(tmp_path):
    (tmp_path / health.RUNTIME_RELEASE_STATE_FILENAME).write_text("{", encoding="utf-8")

    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)


def test_runtime_state_rejects_missing_file(tmp_path):
    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)


def test_runtime_state_rejects_duplicate_fields(tmp_path, valid_state):
    raw = json.dumps(valid_state)
    raw = raw.replace('"status": "ok"', '"status": "ok", "status": "ok"')
    (tmp_path / health.RUNTIME_RELEASE_STATE_FILENAME).write_text(raw, encoding="utf-8")

    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)


def test_runtime_state_rejects_oversized_file(tmp_path):
    (tmp_path / health.RUNTIME_RELEASE_STATE_FILENAME).write_bytes(
        b"x" * (health.MAX_RUNTIME_RELEASE_STATE_BYTES + 1),
    )

    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)


def test_runtime_state_rejects_symlink_escape(tmp_path, valid_state):
    outside = tmp_path.parent / "outside-runtime-release-state.json"
    outside.write_text(json.dumps(valid_state), encoding="utf-8")
    state_path = tmp_path / health.RUNTIME_RELEASE_STATE_FILENAME
    state_path.symlink_to(outside)

    try:
        with pytest.raises(health.InvalidRuntimeReleaseStateError):
            health.load_runtime_release_state(tmp_path)
    finally:
        outside.unlink()


def test_runtime_state_rejects_unreadable_file(monkeypatch, tmp_path, valid_state):
    _write_state(tmp_path, valid_state)
    original_open = os.open

    def denied_open(path, flags):
        if os.fspath(path).endswith(health.RUNTIME_RELEASE_STATE_FILENAME):
            raise PermissionError
        return original_open(path, flags)

    monkeypatch.setattr(os, "open", denied_open)

    with pytest.raises(health.InvalidRuntimeReleaseStateError):
        health.load_runtime_release_state(tmp_path)
