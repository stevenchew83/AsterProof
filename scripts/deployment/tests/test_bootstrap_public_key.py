from pathlib import Path

from scripts.deployment.bootstrap import install_authority
from scripts.deployment.tests.test_bootstrap import _audit_config
from scripts.deployment.tests.test_bootstrap import _fixture
from scripts.deployment.tests.test_bootstrap import _materialize_test_snapshot
from scripts.deployment.tests.test_bootstrap import _service_reader


def test_installed_public_key_is_readable_without_granting_deploy_write_access(tmp_path):
    contract, path = _fixture(tmp_path)
    install_authority(
        contract,
        source_root=Path(__file__).resolve().parents[3],
        contract_path=path,
        deploy_public_key="ssh-ed25519 AAAATEST deploy",
        migration_audit_config=_audit_config(tmp_path),
        expected_authority_sha="a" * 40,
        confirmation=contract.marker,
        root=tmp_path,
        service_reader=_service_reader,
        user_exists=lambda _user: True,
        runtime_matches=lambda *_args: True,
        oidc_reachable=lambda: True,
        source_matches=lambda *_args: True,
        ownership_matches=lambda *_args: True,
        source_sha_reader=lambda _path: "a" * 40,
        snapshot_materializer=_materialize_test_snapshot,
        reload_systemd=False,
    )
    key = tmp_path / "var/lib/asterproof-deploy/.ssh/authorized_keys"
    assert key.stat().st_mode & 0o777 == 0o644  # noqa: PLR2004
    assert key.stat().st_mode & 0o022 == 0
    assert key.read_text().startswith('restrict,command="/usr/local/libexec/asterproof-deploy-gateway ')
