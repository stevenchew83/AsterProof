from types import SimpleNamespace

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
        assert arguments == ["/usr/bin/systemctl", "cat", "--", "asterproof.service"]
        return SimpleNamespace(returncode=0, stdout="[Service]\nUser=asterproof\n")

    monkeypatch.setattr("scripts.deployment.bootstrap.subprocess.run", run)
    assert "User=asterproof" in _read_service("asterproof.service")
