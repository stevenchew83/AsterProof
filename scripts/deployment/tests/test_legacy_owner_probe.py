import subprocess
from types import SimpleNamespace

import pytest

from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract


@pytest.mark.parametrize("change", [None, "head", "origin", "dirty", "git_error"])
def test_legacy_git_checks_run_as_checkout_owner_without_global_trust(tmp_path, monkeypatch, change):
    contract = _contract(tmp_path)
    source = tmp_path / "legacy"
    source.mkdir()
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.pwd.getpwuid",
        lambda uid: SimpleNamespace(pw_name="legacy-owner"),
    )
    commands = []

    def run(command, **kwargs):
        assert command[:7] == [
            "/usr/sbin/runuser", "--user", "legacy-owner", "--", "/usr/bin/git", "-c", "core.fsmonitor=false",
        ]
        assert kwargs["cwd"] == source
        environment = kwargs["env"]
        assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
        assert environment["GIT_OPTIONAL_LOCKS"] == "0"
        assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert environment["GIT_TERMINAL_PROMPT"] == "0"
        assert environment["XDG_CONFIG_HOME"] == "/nonexistent"
        commands.append(command[7:])
        if change == "git_error":
            raise subprocess.CalledProcessError(128, command)
        if command[7] == "rev-parse":
            stdout = ("f" * 40 if change == "head" else OLD_SHA) + "\n"
        elif command[7] == "remote":
            repository = "other/repository" if change == "origin" else contract.repository
            stdout = f"https://github.com/{repository}.git\n"
        else:
            stdout = " M manage.py\n" if change == "dirty" else ""
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", run)
    assert WorkerBackend().legacy_source_matches(contract, source, OLD_SHA) is (change is None)
    assert commands[0] == ["rev-parse", "HEAD"]
