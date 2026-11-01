"""Isolation command contracts; these tests never require Docker or import Django settings."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import offline_evaluation as isolation
from scripts import offline_evaluation_gate as gate

PREPARED_IMAGE = "sha256:" + "a" * 64


def environment(mode="none"):
    return {
        "ASTERPROOF_OFFLINE_EVALUATION": "1", "ASTERPROOF_OFFLINE_TEST_GATE": "1",
        "ASTERPROOF_OFFLINE_ISOLATION_MODE": mode,
        "DJANGO_SETTINGS_MODULE": "config.settings.test", "DJANGO_READ_DOT_ENV_FILE": "false",
        "DJANGO_MEDIA_ROOT": "/scratch/media", "SOLUTION_AI_REVIEW_ENABLED": "false",
        "SOLUTION_AI_EXECUTION_MODE": "offline", "OPENAI_API_KEY": "",
    }


@pytest.mark.parametrize("value", ["python:latest", "repo@sha256:" + "a" * 64, "sha256:ABC", "--privileged"])
def test_prepared_image_requires_local_immutable_id(value):
    with pytest.raises(isolation.IsolationError, match="immutable image ID"):
        isolation.validate_image_id(value)


@pytest.mark.parametrize("target", ["/etc/passwd", "inspinia/solutions/../../secret.py", "--help", "config/test.py"])
def test_targets_cannot_escape_test_locations(target):
    with pytest.raises(isolation.IsolationError, match="explicit solution"):
        isolation.validate_target(target)


@pytest.mark.parametrize("value", [
    ".env", ".envs/local/django", ".aws/config", ".git/config", "db.sqlite3", "key.pem",
    ".ci-quality/lib/site-packages/helper.py", ".release-quality/bin/python",
])
def test_source_snapshot_excludes_credentials_and_application_data(value):
    assert not isolation.safe_source_path(value)


def test_snapshot_copies_only_regular_git_visible_source(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "example.py").write_text("safe source")
    (root / ".env").write_text("synthetic private configuration")
    (root / "link.py").symlink_to(root / ".env")
    monkeypatch.setattr(isolation.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(isolation.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        stdout=b"example.py\0.env\0link.py\0",
    ))
    destination = tmp_path / "snapshot"
    isolation.snapshot_source(root, destination)
    assert sorted(path.name for path in destination.iterdir()) == ["example.py"]


def test_runner_has_no_host_env_or_credentials_and_drops_privileges(tmp_path):
    arguments = isolation.runner_arguments(
        image_id=PREPARED_IMAGE, source=tmp_path, name="local-test", network="none",
        postgres=False, targets=list(isolation.DEFAULT_TARGETS),
    )
    assert arguments[arguments.index("--network") + 1] == "none"
    assert "--pull=never" in arguments
    assert "--read-only" in arguments
    assert "--cap-drop=ALL" in arguments
    assert "--user=65534:65534" in arguments
    assert "--env-file" not in arguments
    mounts = [arguments[index + 1] for index, value in enumerate(arguments) if value == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path},dst=/workspace,readonly"]
    assert "OPENAI_API_KEY=" in arguments
    assert "SOLUTION_AI_EXECUTION_MODE=offline" in arguments


def test_local_docker_does_not_inherit_remote_endpoint_or_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2375")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    monkeypatch.setattr(isolation.shutil, "which", lambda _name: "/usr/bin/docker")
    docker = isolation.LocalDocker(tmp_path)
    captured = {}

    def run(arguments, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stdout="local")

    monkeypatch.setattr(isolation.subprocess, "run", run)
    assert docker.run(["version"]) == "local"
    assert set(captured["env"]) == {"PATH", "DOCKER_CONFIG"}
    assert captured["env"]["DOCKER_CONFIG"] == str(tmp_path)


def test_absent_docker_is_an_explicit_unverified_result(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation.shutil, "which", lambda _name: None)
    with pytest.raises(isolation.IsolationError, match="has not been verified"):
        isolation.LocalDocker(tmp_path)


def test_prepared_image_cannot_embed_provider_environment():
    row = {"Id": PREPARED_IMAGE, "Config": {
        "Labels": {"io.asterproof.offline-dependencies": "true"},
        "Env": ["PATH=/usr/local/bin", "OPENAI_API_KEY=synthetic"],
    }}
    docker = SimpleNamespace(run=lambda _args: json.dumps([row]))
    with pytest.raises(isolation.IsolationError, match="must not embed"):
        isolation.verify_prepared_image(docker, PREPARED_IMAGE)
    row["Config"]["Env"] = ["PATH=/usr/local/bin"]
    isolation.verify_prepared_image(docker, PREPARED_IMAGE)


def test_prepared_image_cannot_create_undeclared_persistent_storage():
    row = {"Id": PREPARED_IMAGE, "Config": {
        "Labels": {"io.asterproof.offline-dependencies": "true"},
        "Volumes": {"/private-state": {}},
    }}
    docker = SimpleNamespace(run=lambda _args: json.dumps([row]))
    with pytest.raises(isolation.IsolationError, match="volumes"):
        isolation.verify_prepared_image(docker, PREPARED_IMAGE)


@pytest.mark.parametrize(("key", "value"), [
    ("DJANGO_SETTINGS_MODULE", "config.settings.production"),
    ("DJANGO_READ_DOT_ENV_FILE", "true"), ("DJANGO_MEDIA_ROOT", "/workspace/media"),
    ("OPENAI_API_KEY", "synthetic"), ("AWS_PROFILE", "production"),
    ("DATABASE_URL", "postgres://remote.invalid/application"),
    ("SOLUTION_AI_REVIEW_ENABLED", "true"), ("SOLUTION_AI_EXECUTION_MODE", "provider"),
])
def test_gate_rejects_unsafe_environment_before_settings_import(tmp_path, key, value):
    values = environment()
    values[key] = value
    with pytest.raises(isolation.IsolationError):
        gate.verify_environment(values, scratch=tmp_path)


def test_gate_accepts_only_explicit_scratch_directory(tmp_path):
    assert gate.verify_environment(environment(), scratch=tmp_path) == "none"
    with pytest.raises(isolation.IsolationError, match="scratch"):
        gate.verify_environment(environment(), scratch=tmp_path / "missing")


def test_outbound_connection_probe_fails_closed(monkeypatch):
    closed = []
    monkeypatch.setattr(gate.socket, "create_connection", lambda *_args, **_kwargs: SimpleNamespace(
        close=lambda: closed.append(True),
    ))
    with pytest.raises(isolation.IsolationError, match="Outbound TCP"):
        gate.verify_blocked_connections()
    assert closed == [True]


def test_blocked_probes_do_not_send_http_or_provider_requests(monkeypatch):
    calls = []

    def blocked(address, **kwargs):
        calls.append(address)
        message = "isolated"
        raise OSError(message)

    monkeypatch.setattr(gate.socket, "create_connection", blocked)
    gate.verify_blocked_connections()
    assert calls == [("1.1.1.1", 443), ("8.8.8.8", 443)]


def test_gate_rejects_database_or_media_override():
    settings = SimpleNamespace(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/scratch/offline.sqlite3"}},
        MEDIA_ROOT="/scratch/media", SOLUTION_AI_REVIEW_ENABLED=False,
        SOLUTION_AI_EXECUTION_MODE="offline", OPENAI_API_KEY="",
    )
    gate.verify_settings(settings, "none")
    settings.DATABASES["default"]["NAME"] = "/workspace/db.sqlite3"
    with pytest.raises(isolation.IsolationError, match="disposable"):
        gate.verify_settings(settings, "none")


def test_postgres_gate_requires_actual_concurrency_passes():
    plugin = gate.BootstrapPlugin(postgres=True)
    session = SimpleNamespace(exitstatus=0)
    plugin.pytest_sessionfinish(session)
    assert session.exitstatus == 1
    for target in isolation.CONCURRENCY_TARGETS:
        plugin.pytest_runtest_logreport(SimpleNamespace(when="call", passed=True, nodeid=target))
    session.exitstatus = 0
    plugin.pytest_sessionfinish(session)
    assert session.exitstatus == 0


def test_postgres_orchestrator_verifies_internal_network_and_cleans_owned_resources(monkeypatch):
    calls = []

    class Docker:
        def __init__(self, _config):
            pass

        def run(self, arguments, **kwargs):
            calls.append(arguments)
            if arguments[:2] == ["network", "inspect"]:
                return json.dumps([{"Internal": True}])
            return ""

    monkeypatch.setattr(isolation, "LocalDocker", Docker)
    monkeypatch.setattr(isolation, "verify_prepared_image", lambda *_args: None)

    def snapshot(_root, destination):
        (destination / "inspinia/solutions").mkdir(parents=True)
        for target in isolation.DEFAULT_TARGETS:
            (destination / target).touch()

    monkeypatch.setattr(isolation, "snapshot_source", snapshot)
    isolation.execute(PREPARED_IMAGE, list(isolation.DEFAULT_TARGETS), postgres=True)
    assert calls[1][:3] == ["network", "create", "--internal"]
    runner = next(call for call in calls if call[0] == "run" and "--read-only" in call)
    assert "--publish" not in runner
    assert all(target in runner for target in isolation.CONCURRENCY_TARGETS)
    assert calls[-1][:2] == ["network", "rm"]
    assert all("asterproof-offline-" in call[-1] for call in calls[-3:])


def test_failed_container_does_not_skip_cleanup(monkeypatch):
    calls = []

    class Docker:
        def __init__(self, _config):
            pass

        def run(self, arguments, **kwargs):
            calls.append(arguments)
            if arguments[0] == "run":
                message = "synthetic test failure"
                raise isolation.IsolationError(message)
            return ""

    monkeypatch.setattr(isolation, "LocalDocker", Docker)
    monkeypatch.setattr(isolation, "verify_prepared_image", lambda *_args: None)

    def snapshot(_root, destination):
        (destination / "inspinia/solutions").mkdir(parents=True)
        (destination / isolation.DEFAULT_TARGETS[0]).touch()

    monkeypatch.setattr(isolation, "snapshot_source", snapshot)
    with pytest.raises(isolation.IsolationError, match="synthetic test failure"):
        isolation.execute(PREPARED_IMAGE, [isolation.DEFAULT_TARGETS[0]])
    assert calls[-1][:2] == ["rm", "--force"]


def test_postgres_network_must_be_internal_before_any_container_starts(monkeypatch):
    calls = []

    class Docker:
        def __init__(self, _config):
            pass

        def run(self, arguments, **kwargs):
            calls.append(arguments)
            if arguments[:2] == ["network", "inspect"]:
                return json.dumps([{"Internal": False}])
            return ""

    monkeypatch.setattr(isolation, "LocalDocker", Docker)
    monkeypatch.setattr(isolation, "verify_prepared_image", lambda *_args: None)

    def snapshot(_root, destination):
        (destination / "inspinia/solutions").mkdir(parents=True)
        (destination / isolation.DEFAULT_TARGETS[0]).touch()

    monkeypatch.setattr(isolation, "snapshot_source", snapshot)
    with pytest.raises(isolation.IsolationError, match="internal-only"):
        isolation.execute(PREPARED_IMAGE, [isolation.DEFAULT_TARGETS[0]], postgres=True)
    assert not any(arguments[0] == "run" for arguments in calls)
    assert calls[-1][:2] == ["network", "rm"]


def test_direct_plugin_loading_cannot_claim_isolation():
    with pytest.raises(pytest.UsageError, match="directly loading"):
        gate.pytest_configure(SimpleNamespace())
