import pytest

from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.server_activate import READINESS_POLL_SECONDS
from scripts.deployment.server_activate import verify_release
from scripts.deployment.tests.test_server_activate import _contract


def test_release_waits_for_health_after_service_start(tmp_path, monkeypatch):
    attempts = []
    sleeps = []

    def health(*_args):
        if not attempts:
            attempts.append("starting")
            msg = "connection refused during startup"
            raise ConnectionRefusedError(msg)
        attempts.append("ready")
        return {"status": "ok"}

    monkeypatch.setattr("scripts.deployment.server_activate.health_check", health)
    monkeypatch.setattr("scripts.deployment.server_activate.verify_static_assets", lambda *_args: None)
    monkeypatch.setattr("scripts.deployment.server_activate.verify_service_processes", lambda *_args: {1: 100})
    monkeypatch.setattr("scripts.deployment.server_activate.time.sleep", sleeps.append)
    monkeypatch.setattr("scripts.deployment.server_activate.time.monotonic", lambda: 0)

    assert verify_release(_contract(tmp_path), "a" * 40, "b" * 64, stabilization_seconds=0) == {"status": "ok"}
    assert attempts == ["starting", "ready", "ready"]
    assert sleeps == [READINESS_POLL_SECONDS, 0]


@pytest.mark.parametrize("error_type", [ConnectionRefusedError, ReleaseStateError])
def test_release_readiness_deadline_keeps_validation_fail_closed(tmp_path, monkeypatch, error_type):
    def health(*_args):
        msg = "not ready or wrong release identity"
        raise error_type(msg)

    monkeypatch.setattr("scripts.deployment.server_activate.health_check", health)
    monkeypatch.setattr("scripts.deployment.server_activate.time.monotonic", lambda: 0)
    with pytest.raises(ReleaseStateError, match="deadline") as error:
        verify_release(_contract(tmp_path), "a" * 40, "b" * 64, readiness_timeout_seconds=0)
    assert isinstance(error.value.__cause__, error_type)


def test_release_snapshots_workers_after_the_first_successful_request(tmp_path, monkeypatch):
    processes = {1: 100}

    def health(*_args):
        # Gunicorn's worker becomes available while the first health request is served.
        processes[2] = 200
        return {"status": "ok"}

    monkeypatch.setattr("scripts.deployment.server_activate.health_check", health)
    monkeypatch.setattr("scripts.deployment.server_activate.verify_static_assets", lambda *_args: None)
    monkeypatch.setattr("scripts.deployment.server_activate.verify_service_processes", lambda *_args: dict(processes))
    monkeypatch.setattr("scripts.deployment.server_activate.time.sleep", lambda _seconds: None)
    assert verify_release(_contract(tmp_path), "a" * 40, "b" * 64, stabilization_seconds=0) == {"status": "ok"}
