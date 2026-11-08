# ruff: noqa: ARG002, EM101, PLR2004, SLF001, TRY003
"""Bound the whole stop transaction and fail closed before the database boundary."""
from __future__ import annotations

import copy
import subprocess
from types import SimpleNamespace

import pytest

from scripts.deployment import operation_worker as worker
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json


@pytest.fixture
def drain(tmp_path, monkeypatch):
    contract = SimpleNamespace(service="app.service", scheduler_service="scheduler.service")
    timer = "scheduler.timer"
    backend = worker.WorkerBackend()
    path = tmp_path / "operation.json"
    atomic_write_json(path, {"state": "draining"})
    clock = SimpleNamespace(value=0.0)
    commands, observations, writers = [], [], []
    states = {
        unit: {"ActiveState": "inactive", "MainPID": "0", "ControlGroup": "", "Job": ""}
        for unit in (timer, contract.scheduler_service, contract.service)
    }

    def sleep(seconds):
        clock.value += seconds

    def observe(unit, names, *, timeout):
        observations.append((unit, timeout, clock.value))
        return copy.deepcopy(states[unit])

    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock.value, sleep=sleep))
    monkeypatch.setattr(worker.subprocess, "run", lambda args, **kwargs: commands.append((args, kwargs)))
    monkeypatch.setattr(backend, "_scheduler_plan", lambda _contract: (timer, True))
    monkeypatch.setattr(backend, "_unit_properties", observe)
    monkeypatch.setattr(backend, "assert_database_drained", lambda: writers.append(clock.value))
    return SimpleNamespace(
        backend=backend, contract=contract, path=path, clock=clock, commands=commands,
        states=states, observations=observations, writers=writers, observe=observe,
    )


def test_queued_ordered_stops_wait_for_every_unit_and_only_request_once(drain, monkeypatch):
    drain.states["scheduler.service"].update(ActiveState="active", MainPID="12")
    drain.states["app.service"].update(ActiveState="deactivating", MainPID="34")
    app_stop_completed = 345  # The app stops after the review worker's 330-second grace period.

    def observe(unit, names, *, timeout):
        if drain.clock.value >= 0.5:
            drain.states["scheduler.service"].update(ActiveState="inactive", MainPID="0")
        if drain.clock.value >= app_stop_completed:
            drain.states["app.service"].update(ActiveState="inactive", MainPID="0")
        return drain.observe(unit, names, timeout=timeout)

    monkeypatch.setattr(drain.backend, "_unit_properties", observe)
    drain.backend.drain(drain.contract, drain.path)
    assert drain.writers == [app_stop_completed]
    assert len(drain.commands) == 1
    assert drain.commands[0] == (
        ["/usr/bin/systemctl", "stop", "--no-block", "scheduler.timer", "scheduler.service", "app.service"],
        {"check": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": 30},
    )
    assert read_json(drain.path)["maintenance_scheduler_was_active"] is True
    assert read_json(drain.path)["maintenance_scheduler_stop_result"]["ActiveState"] == "inactive"


@pytest.mark.parametrize("active_state", ["active", "activating", "deactivating", "reloading"])
def test_pending_unit_hits_one_bounded_stop_deadline(drain, active_state):
    drain.states["app.service"].update(ActiveState=active_state, MainPID="34")
    with pytest.raises(worker.OperationError, match="^maintenance_drain_timeout$"):
        drain.backend.drain(drain.contract, drain.path)
    assert drain.clock.value == 450
    assert len(drain.commands) == 1
    assert drain.writers == []


def test_inactive_unit_with_queued_job_does_not_advance_early(drain, monkeypatch):
    drain.states["app.service"]["Job"] = "123"

    def observe(unit, names, *, timeout):
        if drain.clock.value >= 0.5:
            drain.states["app.service"]["Job"] = ""
        return drain.observe(unit, names, timeout=timeout)

    monkeypatch.setattr(drain.backend, "_unit_properties", observe)
    drain.backend.drain(drain.contract, drain.path)
    assert drain.writers == [0.5]
    assert len(drain.commands) == 1


@pytest.mark.parametrize("unit", ["scheduler.timer", "scheduler.service", "app.service"])
def test_persistent_job_blocks_even_inactive_unit(drain, unit):
    drain.states[unit]["Job"] = "123"
    with pytest.raises(worker.OperationError, match="^maintenance_drain_timeout$"):
        drain.backend.drain(drain.contract, drain.path)
    assert drain.clock.value == 450
    assert drain.writers == []
    assert len(drain.commands) == 1


def test_missing_job_observation_fails_closed(drain):
    del drain.states["app.service"]["Job"]
    with pytest.raises(worker.OperationError, match="^maintenance_drain_incomplete$"):
        drain.backend.drain(drain.contract, drain.path)
    assert drain.writers == []


@pytest.mark.parametrize("consumed", [449, 450, 451])
def test_slow_request_and_observations_cannot_reset_or_overrun_deadline(drain, monkeypatch, consumed):
    def request(args, **kwargs):
        drain.commands.append((args, kwargs))
        drain.clock.value += 29

    def observe(unit, names, *, timeout):
        result = drain.observe(unit, names, timeout=timeout)
        drain.clock.value = consumed
        return result

    monkeypatch.setattr(worker.subprocess, "run", request)
    monkeypatch.setattr(drain.backend, "_unit_properties", observe)
    if consumed < 450:
        drain.backend.drain(drain.contract, drain.path)
        assert drain.writers == [449]
        assert [timeout for _unit, timeout, _time in drain.observations] == [15, 1, 1]
    else:
        with pytest.raises(worker.OperationError, match="^maintenance_drain_timeout$"):
            drain.backend.drain(drain.contract, drain.path)
        assert drain.writers == []
        assert len(drain.observations) == 1


@pytest.mark.parametrize(
    ("phase", "failure", "code"),
    [
        ("request", subprocess.TimeoutExpired("systemctl", 30), "maintenance_stop_request_timeout"),
        ("request", subprocess.CalledProcessError(1, "systemctl", stderr="private"),
         "maintenance_stop_request_failed"),
        ("request", OSError("private"), "maintenance_stop_request_failed"),
        ("observation", subprocess.TimeoutExpired("systemctl", 15), "maintenance_drain_observation_timeout"),
        ("observation", subprocess.CalledProcessError(1, "systemctl"), "maintenance_drain_observation_failed"),
        ("observation", OSError("private"), "maintenance_drain_observation_failed"),
        ("plan", subprocess.TimeoutExpired("systemctl", 15), "maintenance_drain_observation_timeout"),
        ("plan", OSError("private"), "maintenance_drain_observation_failed"),
    ],
)
def test_systemctl_errors_are_normalized_without_retry_or_private_output(drain, monkeypatch, phase, failure, code):
    def fail(*args, **kwargs):
        raise failure

    if phase == "request":
        monkeypatch.setattr(worker.subprocess, "run", fail)
    else:
        monkeypatch.setattr(drain.backend, "_scheduler_plan" if phase == "plan" else "_unit_properties", fail)
    with pytest.raises(worker.OperationError, match="^" + code + "$") as caught:
        drain.backend.drain(drain.contract, drain.path)
    assert str(caught.value) == code
    assert "private" not in str(caught.value)
    assert len(drain.commands) <= 1
    assert drain.writers == []


def test_real_property_query_bounds_systemctl_observation_timeout(monkeypatch):
    commands = []

    def run(args, **kwargs):
        commands.append((args, kwargs))
        return SimpleNamespace(stdout="ActiveState=inactive\nMainPID=0\n")

    monkeypatch.setattr(worker.subprocess, "run", run)
    assert worker.WorkerBackend()._unit_properties("app.service", "ActiveState,MainPID", timeout=0.5) == {
        "ActiveState": "inactive", "MainPID": "0",
    }
    assert commands[0][1]["timeout"] == 0.5


def test_clock_crossing_deadline_before_sleep_normalizes_timeout(drain, monkeypatch):
    drain.states["app.service"]["ActiveState"] = "deactivating"
    calls = 0
    sleeps = []

    def monotonic():
        nonlocal calls
        calls += 1
        # Initial deadline, three observations' before/after checks, final check,
        # then a scheduling delay before calculating the sleep duration.
        return 451.0 if calls >= 9 else 0.0

    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=monotonic, sleep=sleeps.append))
    with pytest.raises(worker.OperationError, match="^maintenance_drain_timeout$"):
        drain.backend.drain(drain.contract, drain.path)
    assert sleeps == [0]
    assert drain.writers == []
    assert len(drain.commands) == 1


@pytest.mark.parametrize("error", [PermissionError("private"), FileNotFoundError("private")])
def test_unreadable_cgroup_is_not_treated_as_empty(drain, monkeypatch, error):
    drain.states["app.service"]["ControlGroup"] = "/app"

    class Cgroup:
        def __truediv__(self, _part):
            return self

        def exists(self):
            return True

        def read_text(self):
            raise error

    monkeypatch.setattr(worker, "Path", lambda _value: Cgroup())
    with pytest.raises(worker.OperationError, match="^maintenance_drain_observation_failed$"):
        drain.backend.drain(drain.contract, drain.path)
    assert drain.writers == []
