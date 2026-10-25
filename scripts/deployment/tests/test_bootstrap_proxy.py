from types import SimpleNamespace

import pytest

from scripts.deployment.bootstrap import _managed_service_text_matches
from scripts.deployment.bootstrap import _read_service


def test_nginx_bootstrap_audit_reads_included_routes(monkeypatch):
    calls = []

    def run(arguments, **_kwargs):
        calls.append(arguments)
        output = "[Service]\nExecStart=/usr/sbin/nginx\n"
        if arguments == ["/usr/sbin/nginx", "-T"]:
            output = "location /media/ { alias /var/lib/asterproof/media/; }\n"
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert "/var/lib/asterproof/media/" in _read_service("nginx.service")
    assert calls == [
        ["/usr/bin/systemctl", "cat", "--", "nginx.service"],
        ["/usr/sbin/nginx", "-T"],
    ]


def test_bootstrap_proxy_configuration_failure_does_not_pass_routes(monkeypatch):
    def run(arguments, **_kwargs):
        return SimpleNamespace(returncode=int(arguments[0] == "/usr/sbin/nginx"), stdout="[Service]\n")

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert "/var/lib/asterproof/media/" not in _read_service("nginx.service")


def test_other_services_do_not_read_nginx_configuration(monkeypatch):
    def run(arguments, **_kwargs):
        assert arguments == [
            "/usr/bin/systemctl",
            "show",
            "--property=Id,User,WorkingDirectory,EnvironmentFiles,ExecStart",
            "--",
            "asterproof.service",
        ]
        return SimpleNamespace(returncode=0, stdout="Id=asterproof.service\nUser=asterproof\n")

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert "User=asterproof" in _read_service("asterproof.service")


@pytest.mark.parametrize("launcher", ["/srv/legacy/.venv/bin/gunicorn", "/srv/asterproof/current/.venv/bin/gunicorn"])
def test_loaded_exec_start_override_controls_readiness(monkeypatch, launcher):
    contract = SimpleNamespace(
        release_root="/srv/asterproof",
        app_user="asterproof",
        environment_file="/var/lib/asterproof/environment",
    )

    def run(_arguments, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Id=asterproof.service\nUser=asterproof\nWorkingDirectory=/srv/asterproof/current\n"
                "EnvironmentFiles=/var/lib/asterproof/environment (ignore_errors=no)\n"
                f"ExecStart={{ path={launcher} ; argv[]={launcher} config.wsgi:application ; ignore_errors=no ; }}\n"
            ),
        )

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert _managed_service_text_matches(contract, _read_service("asterproof.service"), executable="gunicorn") == (
        launcher == "/srv/asterproof/current/.venv/bin/gunicorn"
    )


@pytest.mark.parametrize(
    "environment",
    [
        "",
        "/var/lib/asterproof/environment (ignore_errors=yes)",
        "/var/lib/asterproof/environment (ignore_errors=no) /tmp/override (ignore_errors=no)",
    ],
)
def test_missing_optional_or_additional_environment_files_fail_closed(monkeypatch, environment):
    contract = SimpleNamespace(
        release_root="/srv/asterproof",
        app_user="asterproof",
        environment_file="/var/lib/asterproof/environment",
    )

    def run(_arguments, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Id=asterproof.service\nUser=asterproof\nWorkingDirectory=/srv/asterproof/current\n"
                f"EnvironmentFiles={environment}\n"
                "ExecStart={ path=/srv/asterproof/current/.venv/bin/gunicorn ; }\n"
            ),
        )

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert not _managed_service_text_matches(contract, _read_service("asterproof.service"), executable="gunicorn")


def test_unreadable_loaded_service_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "scripts.deployment.bootstrap.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert _read_service("asterproof.service") == ""
