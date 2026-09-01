# ruff: noqa: C901, EM101, PLR0911, PLR0912, PLR0913, PLR0915, S603, T201, TRY003, TRY300
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import MigrationAuditError
from scripts.deployment.migration_audit import collect_audit
from scripts.deployment.oidc import GITHUB_CONFIGURATION_URL
from scripts.deployment.oidc import GITHUB_ISSUER
from scripts.deployment.oidc import fetch_json
from scripts.deployment.protocol import DIGEST_RE
from scripts.deployment.protocol import SHA_RE
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import utc_now
from scripts.deployment.target import TargetContract
from scripts.deployment.target import TargetContractError

if TYPE_CHECKING:
    from collections.abc import Callable

AUTHORITY_ROOT = Path("/usr/local/libexec/asterproof-authority")
AUTHORITY_VERSIONS_ROOT = Path("/usr/local/libexec/asterproof-authority-versions")
CONTRACT_PATH = Path("/etc/asterproof/deployment-target.json")
MARKER_PATH = Path("/etc/asterproof/target-marker")
SYSTEMD_PATH = Path("/etc/systemd/system/asterproof-deploy-operation@.service")
SUDOERS_PATH = Path("/etc/sudoers.d/asterproof-deploy-submit")
AUTHORIZED_KEYS_PATH = Path("/var/lib/asterproof-deploy/.ssh/authorized_keys")
AUTHORITY_MANIFEST_PATH = Path("/etc/asterproof/authority-manifest.json")
MIGRATION_AUDIT_CONFIG_PATH = Path("/etc/asterproof/migration-audit.json")
SECRET_FILE_MODE = 0o600
ROOT_DIRECTORY_MODE = 0o755
GIT_SHA1_LENGTH = 40


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditResult:
    contract_digest: str
    checks: dict[str, bool]
    marker: str
    repository: str
    service: str

    @property
    def ok(self) -> bool:
        return all(self.checks.values())

    def public_dict(self) -> dict[str, object]:
        return asdict(self) | {"ok": self.ok}


def _under_root(root: Path, absolute: Path) -> Path:
    if not absolute.is_absolute():
        raise BootstrapError("bootstrap path must be absolute")
    return root / absolute.relative_to("/")


def _contract_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_target(
    contract: TargetContract,
    *,
    contract_path: Path,
    root: Path = Path("/"),
    service_reader: Callable[[str], str] | None = None,
    user_exists: Callable[[str], bool] | None = None,
    runtime_matches: Callable[[Path, str, str], bool] | None = None,
    oidc_reachable: Callable[[], bool] | None = None,
    source_matches: Callable[[Path, TargetContract], bool] | None = None,
    ownership_matches: Callable[[Path, str], bool] | None = None,
    source_root: Path,
) -> AuditResult:
    """Return a read-only, secret-free target report. No inferred values are written."""
    contract.validate()
    service_reader = service_reader or _read_service
    user_exists = user_exists or _user_exists
    runtime_matches = runtime_matches or _runtime_matches
    oidc_reachable = oidc_reachable or _oidc_reachable
    source_matches = source_matches or _source_matches
    ownership_matches = ownership_matches or _ownership_matches
    release_root = _under_root(root, contract.release_root)
    shared_root = _under_root(root, contract.shared_root)
    environment_file = _under_root(root, contract.environment_file)
    media_root = _under_root(root, contract.media_root)
    python_executable = _under_root(root, contract.python_executable)
    tex_executable = _under_root(root, contract.tex_executable)
    marker_path = _under_root(root, MARKER_PATH)
    deploy_home = _under_root(root, AUTHORIZED_KEYS_PATH.parent.parent)
    deploy_ssh = _under_root(root, AUTHORIZED_KEYS_PATH.parent)
    service_text = service_reader(contract.service)
    scheduler_text = service_reader(contract.scheduler_service)
    proxy_text = service_reader(contract.proxy_service)
    audit_config_ok = False
    try:
        audit_config = AuditConfig.load(_under_root(root, MIGRATION_AUDIT_CONFIG_PATH))
        audit_service_file = _under_root(root, audit_config.pg_service_file)
        audit_config_ok = (
            user_exists(audit_config.os_user)
            and audit_service_file.is_file()
            and not audit_service_file.is_symlink()
            and stat.S_IMODE(audit_service_file.stat().st_mode) == SECRET_FILE_MODE
        )
    except (OSError, MigrationAuditError):
        pass
    current_fragment = f"{contract.release_root}/current"
    directory_contracts = (
        (contract.incoming_dir, contract.deploy_user, 0o711),
        (contract.build_dir, contract.build_user, 0o700),
        (contract.releases_dir, "root", 0o755),
        (contract.registry_dir, "root", 0o711),
        (contract.registry_dir / "operations", "root", 0o755),
        (contract.registry_dir / "releases", "root", 0o755),
        (contract.processing_dir, "root", 0o711),
    )
    deployment_directories_ready = all(
        (path := _under_root(root, absolute)).is_dir()
        and stat.S_IMODE(path.stat().st_mode) == mode
        and ownership_matches(path, owner)
        for absolute, owner, mode in directory_contracts
    )
    checks = {
        "accounts_exist": all(
            user_exists(user) for user in (contract.app_user, contract.build_user, contract.deploy_user)
        ),
        "environment_exists": environment_file.is_file(),
        "deployment_directories_ready": deployment_directories_ready,
        "environment_outside_releases": release_root.resolve(strict=False)
        not in environment_file.resolve(strict=False).parents,
        "marker_matches": marker_path.is_file() and marker_path.read_text().strip() == contract.marker,
        "media_exists": media_root.is_dir(),
        "media_outside_releases": release_root.resolve(strict=False) not in media_root.resolve(strict=False).parents,
        "minimum_free_space": release_root.is_dir()
        and shutil.disk_usage(release_root).free >= contract.minimum_free_bytes,
        "oidc_provider_reachable": oidc_reachable(),
        "migration_audit_configured": audit_config_ok,
        "proxy_routes_media_external": str(contract.media_root) in proxy_text,
        "proxy_static_stable": contract.static_mode == "whitenoise"
        or f"{current_fragment}/staticfiles" in proxy_text,
        "release_root_exists": release_root.is_dir(),
        "repository_source_matches": source_matches(source_root, contract),
        "runtime_matches": python_executable.is_file()
        and runtime_matches(python_executable, contract.python_abi, contract.target_platform),
        "scheduler_uses_current": current_fragment in scheduler_text,
        "ssh_authority_directory": deploy_home.is_dir()
        and deploy_ssh.is_dir()
        and not deploy_home.is_symlink()
        and not deploy_ssh.is_symlink()
        and stat.S_IMODE(deploy_home.stat().st_mode) == ROOT_DIRECTORY_MODE
        and stat.S_IMODE(deploy_ssh.stat().st_mode) == ROOT_DIRECTORY_MODE
        and ownership_matches(deploy_home, "root")
        and ownership_matches(deploy_ssh, "root"),
        "service_environment_external": str(contract.environment_file) in service_text,
        "service_identity": contract.service in service_text or bool(service_text),
        "service_runs_as_app_user": f"User={contract.app_user}" in service_text,
        "service_uses_current": current_fragment in service_text,
        "shared_root_exists": shared_root.is_dir(),
        "tex_available": tex_executable.is_file(),
        "trusted_authority_matches": _authority_matches(root),
    }
    return AuditResult(
        contract_digest=_contract_digest(contract_path),
        checks=checks,
        marker=contract.marker,
        repository=contract.repository,
        service=contract.service,
    )


def _read_service(service: str) -> str:
    result = subprocess.run(
        ["/usr/bin/systemctl", "cat", "--", service],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def _user_exists(user: str) -> bool:
    try:
        pwd.getpwnam(user)
    except KeyError:
        return False
    return True


def _ownership_matches(path: Path, user: str) -> bool:
    try:
        return path.stat().st_uid == pwd.getpwnam(user).pw_uid
    except (KeyError, OSError):
        return False


def _runtime_matches(path: Path, python_abi: str, target_platform: str) -> bool:
    result = subprocess.run(
        [
            str(path),
            "-c",
            (
                "import cryptography,json,platform,sys; "
                "print(json.dumps({'abi':f'cp{sys.version_info.major}{sys.version_info.minor}',"
                "'machine':platform.machine(),'libc':platform.libc_ver()[1]}))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        value = json.loads(result.stdout)
        _, _, minimum_glibc = target_platform.rpartition("_")
        libc_parts = tuple(int(part) for part in str(value["libc"]).split(".")[:2])
        required_parts = (2, int(minimum_glibc))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        result.returncode == 0
        and value.get("abi") == python_abi
        and value.get("machine") == "x86_64"
        and libc_parts >= required_parts
    )


def _oidc_reachable() -> bool:
    try:
        configuration = fetch_json(GITHUB_CONFIGURATION_URL)
        jwks_uri = configuration.get("jwks_uri")
        return (
            configuration.get("issuer") == GITHUB_ISSUER
            and isinstance(jwks_uri, str)
            and jwks_uri.startswith(f"{GITHUB_ISSUER}/")
            and isinstance(fetch_json(jwks_uri).get("keys"), list)
        )
    except (OSError, ValueError):
        return False


def _source_matches(source_root: Path, contract: TargetContract) -> bool:
    try:
        origin = subprocess.run(
            ["/usr/bin/git", "remote", "get-url", "origin"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        clean = not subprocess.run(
            ["/usr/bin/git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    normalized = origin.removesuffix(".git").replace("git@github.com:", "https://github.com/")
    return clean and normalized == f"https://github.com/{contract.repository}"


def _authority_matches(root: Path) -> bool:
    manifest_path = _under_root(root, AUTHORITY_MANIFEST_PATH)
    try:
        value = json.loads(manifest_path.read_text())
        if (
            not isinstance(value, dict)
            or set(value) != {"format_version", "files", "source_sha"}
            or value["format_version"] != 1
            or SHA_RE.fullmatch(str(value["source_sha"])) is None
        ):
            return False
        files = value["files"]
        if not isinstance(files, dict) or not files:
            return False
        for name, expected in files.items():
            if not isinstance(name, str) or not isinstance(expected, dict):
                return False
            path = _under_root(root, Path(name))
            if not path.is_file() or path.is_symlink():
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected.get("sha256"):
                return False
            if stat.S_IMODE(path.stat().st_mode) != expected.get("mode") or path.stat().st_mode & 0o022:
                return False
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def render_authorized_key(public_key: str) -> str:
    parts = public_key.strip().split()
    if not parts or parts[0] not in {"ssh-ed25519", "sk-ssh-ed25519@openssh.com"} or len(parts) == 1:
        raise BootstrapError("deployment key must be an Ed25519 public key")
    if any(character in public_key for character in "\r\n\x00"):
        raise BootstrapError("deployment public key contains forbidden characters")
    restrictions = (
        'restrict,command="/usr/local/libexec/asterproof-deploy-gateway '
        '--contract /etc/asterproof/deployment-target.json"'
    )
    return f"{restrictions} {public_key.strip()}\n"


def _git_object_digest(object_type: str, content: bytes, object_id: str) -> str:
    algorithm = "sha1" if len(object_id) == GIT_SHA1_LENGTH else "sha256"
    payload = f"{object_type} {len(content)}\0".encode() + content
    return hashlib.new(algorithm, payload).hexdigest()


def _materialize_git_snapshot(source_root: Path, source_sha: str, destination: Path) -> None:
    environment = {
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }

    def git(*arguments: str) -> bytes:
        try:
            return subprocess.run(
                ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *arguments],
                cwd=source_root,
                env=environment,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise BootstrapError("approved Git snapshot cannot be materialized") from exc

    commit = git("cat-file", "commit", source_sha)
    if _git_object_digest("commit", commit, source_sha) != source_sha:
        raise BootstrapError("approved Git commit object failed identity verification")
    listing = git(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        source_sha,
        "--",
        "scripts/__init__.py",
        "scripts/deployment",
        "deployment/systemd/asterproof-deploy-operation@.service.in",
        "deployment/sudoers/asterproof-deploy-submit.in",
    )
    required = {
        "scripts/__init__.py",
        "deployment/systemd/asterproof-deploy-operation@.service.in",
        "deployment/sudoers/asterproof-deploy-submit.in",
    }
    written: set[str] = set()
    destination.mkdir(mode=0o700, parents=False)
    for record in listing.rstrip(b"\0").split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_name = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split()
            name = raw_name.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise BootstrapError("approved Git tree contains an invalid entry") from exc
        path = PurePosixPath(name)
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise BootstrapError("approved Git tree contains a prohibited authority entry")
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise BootstrapError("approved Git tree contains an unsafe authority path")
        content = git("cat-file", "blob", object_id)
        if _git_object_digest("blob", content, object_id) != object_id:
            raise BootstrapError("approved Git blob failed identity verification")
        _write_atomic_bytes(destination / Path(*path.parts), content, int(mode[-3:], 8))
        written.add(name)
    if not required <= written or not any(name.startswith("scripts/deployment/") for name in written):
        raise BootstrapError("approved Git snapshot is missing authority files")


def install_authority(
    contract: TargetContract,
    *,
    source_root: Path,
    contract_path: Path,
    deploy_public_key: str,
    migration_audit_config: Path,
    expected_authority_sha: str,
    confirmation: str,
    root: Path = Path("/"),
    service_reader: Callable[[str], str] | None = None,
    user_exists: Callable[[str], bool] | None = None,
    runtime_matches: Callable[[Path, str, str], bool] | None = None,
    oidc_reachable: Callable[[], bool] | None = None,
    source_matches: Callable[[Path, TargetContract], bool] | None = None,
    ownership_matches: Callable[[Path, str], bool] | None = None,
    source_sha_reader: Callable[[Path], str] | None = None,
    snapshot_materializer: Callable[[Path, str, Path], None] | None = None,
    reload_systemd: bool = True,
) -> AuditResult:
    if os.geteuid() != 0 and root == Path("/"):
        raise PermissionError("bootstrap installation must run as root")
    if confirmation != contract.marker:
        raise BootstrapError("installation confirmation does not match target marker")
    try:
        contract_bytes = contract_path.read_bytes()
        migration_audit_bytes = migration_audit_config.read_bytes()
        if TargetContract.from_bytes(contract_bytes) != contract:
            raise BootstrapError("target contract bytes do not match the audited contract")
        AuditConfig.from_bytes(migration_audit_bytes)
    except (OSError, MigrationAuditError, TargetContractError) as exc:
        raise BootstrapError("bootstrap configuration snapshot is invalid") from exc
    source_sha_reader = source_sha_reader or _legacy_sha
    snapshot_materializer = snapshot_materializer or _materialize_git_snapshot
    if SHA_RE.fullmatch(expected_authority_sha) is None or source_sha_reader(source_root) != expected_authority_sha:
        raise BootstrapError("authority source does not match the explicitly approved SHA")
    audit = audit_target(
        contract,
        contract_path=contract_path,
        root=root,
        service_reader=service_reader,
        user_exists=user_exists,
        runtime_matches=runtime_matches,
        oidc_reachable=oidc_reachable,
        source_matches=source_matches,
        ownership_matches=ownership_matches,
        source_root=source_root,
    )
    if not all(
        value
        for key, value in audit.checks.items()
        if key
        not in {
            "deployment_directories_ready",
            "marker_matches",
            "migration_audit_configured",
            "ssh_authority_directory",
            "trusted_authority_matches",
        }
    ):
        raise BootstrapError("target audit failed; installation is blocked")
    _prepare_deployment_directories(contract, root)

    authority = _under_root(root, AUTHORITY_ROOT)
    versions = _under_root(root, AUTHORITY_VERSIONS_ROOT)
    versions.mkdir(mode=0o755, parents=True, exist_ok=True)
    version = versions / expected_authority_sha
    staged = versions / f".{expected_authority_sha}.next"
    snapshot = versions / f".{expected_authority_sha}.source"
    if staged.exists():
        shutil.rmtree(staged)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot_materializer(source_root, expected_authority_sha, snapshot)
    (staged / "scripts").mkdir(mode=0o755, parents=True)
    shutil.copy2(snapshot / "scripts/__init__.py", staged / "scripts/__init__.py")
    shutil.copytree(snapshot / "scripts/deployment", staged / "scripts/deployment")
    for cache in staged.rglob("__pycache__"):
        shutil.rmtree(cache)
    for path in staged.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    staged.chmod(0o755)
    if version.exists():
        shutil.rmtree(version)
    staged.replace(version)
    if authority.exists() and not authority.is_symlink():
        raise BootstrapError("legacy authority directory requires reviewed migration")

    entrypoints = {
        "asterproof-authority-check": "scripts.deployment.authority_check",
        "asterproof-deploy-gateway": "scripts.deployment.server_gate",
        "asterproof-deploy-submit": "scripts.deployment.server_submit",
        "asterproof-migration-audit": "scripts.deployment.migration_audit",
        "asterproof-operation-worker": "scripts.deployment.operation_worker",
        "asterproof-prepare-release": "scripts.deployment.prepare_release",
    }
    for name, module in entrypoints.items():
        entrypoint = _under_root(root, Path("/usr/local/libexec") / name)
        _write_rendered(
            entrypoint,
            f"#!{contract.python_executable}\n"
            "import sys\n"
            f"sys.path.insert(0, {str(AUTHORITY_ROOT)!r})\n"
            f"from {module} import main\n"
            "raise SystemExit(main())\n",
            0o755,
        )

    contract_destination = _under_root(root, CONTRACT_PATH)
    # The contract contains no secrets and must be readable by the forced-command deploy user.
    _write_atomic_bytes(contract_destination, contract_bytes, 0o644)
    migration_audit_destination = _under_root(root, MIGRATION_AUDIT_CONFIG_PATH)
    _write_atomic_bytes(migration_audit_destination, migration_audit_bytes, 0o600)
    marker_destination = _under_root(root, MARKER_PATH)
    _write_rendered(marker_destination, f"{contract.marker}\n", 0o644)

    unit_source = snapshot / "deployment/systemd/asterproof-deploy-operation@.service.in"
    unit_destination = _under_root(root, SYSTEMD_PATH)
    rendered_unit = unit_source.read_text().replace("@RELEASE_ROOT@", str(contract.release_root))
    _write_rendered(unit_destination, rendered_unit, 0o644)
    sudoers_source = snapshot / "deployment/sudoers/asterproof-deploy-submit.in"
    sudoers_destination = _under_root(root, SUDOERS_PATH)
    rendered_sudoers = sudoers_source.read_text().replace("@DEPLOY_USER@", contract.deploy_user)
    _write_rendered(sudoers_destination, rendered_sudoers, 0o440)
    authorized_keys = _under_root(root, AUTHORIZED_KEYS_PATH)
    deploy_home = authorized_keys.parent.parent
    if deploy_home.is_symlink() or not deploy_home.is_dir():
        raise BootstrapError("deployment account home is unsafe")
    if root == Path("/"):
        os.chown(deploy_home, 0, 0)
    deploy_home.chmod(0o755)
    if authorized_keys.parent.is_symlink():
        raise BootstrapError("deployment SSH directory is unsafe")
    authorized_keys.parent.mkdir(mode=0o755, exist_ok=True)
    if not authorized_keys.parent.is_dir() or authorized_keys.parent.is_symlink():
        raise BootstrapError("deployment SSH directory is unsafe")
    if root == Path("/"):
        os.chown(authorized_keys.parent, 0, 0)
    authorized_keys.parent.chmod(0o755)
    _write_rendered(authorized_keys, render_authorized_key(deploy_public_key), 0o600)
    # Commit the authority generation only after every dependent live file is installed.
    authority_link = authority.with_name(f".{authority.name}.next")
    authority_link.unlink(missing_ok=True)
    authority_link.symlink_to(Path(AUTHORITY_VERSIONS_ROOT.name) / expected_authority_sha)
    authority_link.replace(authority)
    _write_authority_manifest(
        root,
        [
            AUTHORITY_ROOT / "scripts/__init__.py",
            *[
                AUTHORITY_ROOT / path.relative_to(version)
                for path in version.rglob("*")
                if path.is_file()
            ],
            *[Path("/usr/local/libexec") / name for name in entrypoints],
            CONTRACT_PATH,
            MIGRATION_AUDIT_CONFIG_PATH,
            MARKER_PATH,
            SYSTEMD_PATH,
            SUDOERS_PATH,
            AUTHORIZED_KEYS_PATH,
        ],
        source_sha=expected_authority_sha,
    )
    shutil.rmtree(snapshot)
    if reload_systemd:
        subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True)
    return audit_target(
        contract,
        contract_path=_under_root(root, CONTRACT_PATH),
        root=root,
        service_reader=service_reader,
        user_exists=user_exists,
        runtime_matches=runtime_matches,
        oidc_reachable=oidc_reachable,
        source_matches=source_matches,
        ownership_matches=ownership_matches,
        source_root=source_root,
    )


def _prepare_deployment_directories(contract: TargetContract, root: Path) -> None:
    layouts = (
        (contract.release_root, "root", 0o755),
        (contract.incoming_dir, contract.deploy_user, 0o711),
        (contract.build_dir, contract.build_user, 0o700),
        (contract.releases_dir, "root", 0o755),
        (contract.registry_dir, "root", 0o711),
        (contract.registry_dir / "operations", "root", 0o755),
        (contract.registry_dir / "releases", "root", 0o755),
        (contract.processing_dir, "root", 0o711),
    )
    for absolute, owner, mode in layouts:
        path = _under_root(root, absolute)
        path.mkdir(mode=mode, parents=True, exist_ok=True)
        path.chmod(mode)
        if root == Path("/"):
            os.chown(path, pwd.getpwnam(owner).pw_uid, pwd.getpwnam(owner).pw_gid)


def _write_authority_manifest(root: Path, paths: list[Path], *, source_sha: str) -> None:
    files: dict[str, dict[str, object]] = {}
    for absolute in sorted(set(paths)):
        path = _under_root(root, absolute)
        files[str(absolute)] = {
            "mode": stat.S_IMODE(path.stat().st_mode),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    _write_rendered(
        _under_root(root, AUTHORITY_MANIFEST_PATH),
        json.dumps(
            {"files": files, "format_version": 1, "source_sha": source_sha},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        0o644,
    )


def authorize_legacy_adoption(
    contract: TargetContract,
    *,
    contract_path: Path,
    source_root: Path,
    confirmation: str,
    root: Path = Path("/"),
    service_reader: Callable[[str], str] | None = None,
    user_exists: Callable[[str], bool] | None = None,
    runtime_matches: Callable[[Path, str, str], bool] | None = None,
    oidc_reachable: Callable[[], bool] | None = None,
    source_matches: Callable[[Path, TargetContract], bool] | None = None,
    ownership_matches: Callable[[Path, str], bool] | None = None,
    service_uses_source: Callable[[TargetContract, Path], bool] | None = None,
    legacy_sha_reader: Callable[[Path], str] | None = None,
    state_fingerprint_reader: Callable[[Path], str] | None = None,
) -> dict[str, object]:
    if os.geteuid() != 0 and root == Path("/"):
        raise PermissionError("legacy adoption authorization must run as root")
    if confirmation != "LEGACY_NON_ROLLBACK":
        raise BootstrapError("legacy adoption requires explicit non-rollback confirmation")
    audit = audit_target(
        contract,
        contract_path=contract_path,
        root=root,
        service_reader=service_reader,
        user_exists=user_exists,
        runtime_matches=runtime_matches,
        oidc_reachable=oidc_reachable,
        source_matches=source_matches,
        ownership_matches=ownership_matches,
        source_root=source_root,
    )
    if not audit.ok:
        raise BootstrapError("target audit failed; legacy adoption is blocked")
    for link_name in ("current", "previous"):
        link = _under_root(root, contract.release_root / link_name)
        if link.exists() or link.is_symlink():
            raise BootstrapError("managed release links must be absent before legacy adoption")
    for state_directory in (
        contract.releases_dir,
        contract.registry_dir / "operations",
        contract.registry_dir / "releases",
    ):
        path = _under_root(root, state_directory)
        if path.exists() and any(path.iterdir()):
            raise BootstrapError("managed deployment state must be empty before legacy adoption")
    if _under_root(root, contract.registry_dir / "adoption.json").exists():
        raise BootstrapError("legacy adoption is already recorded")
    service_uses_source = service_uses_source or _service_processes_use_source
    if not service_uses_source(contract, source_root):
        raise BootstrapError("running service process does not match the legacy source")
    legacy_sha_reader = legacy_sha_reader or _legacy_sha
    legacy_sha = legacy_sha_reader(source_root)
    if SHA_RE.fullmatch(legacy_sha) is None:
        raise BootstrapError("legacy source SHA is invalid")
    state_fingerprint_reader = state_fingerprint_reader or _state_fingerprint
    fingerprint = state_fingerprint_reader(_under_root(root, MIGRATION_AUDIT_CONFIG_PATH))
    if DIGEST_RE.fullmatch(fingerprint) is None:
        raise BootstrapError("legacy migration fingerprint is invalid")
    record: dict[str, object] = {
        "authorized_at": utc_now(),
        "legacy_sha": legacy_sha,
        "legacy_source_root": str(source_root.resolve(strict=True)),
        "state_fingerprint": fingerprint,
        "repository": contract.repository,
        "state": "authorized",
        "target_marker": contract.marker,
    }
    atomic_write_json(_under_root(root, contract.registry_dir / "adoption.json"), record)
    return record


def _legacy_sha(source_root: Path) -> str:
    return subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _state_fingerprint(config_path: Path) -> str:
    value = collect_audit(AuditConfig.load(config_path))
    return str(value["state_fingerprint"])


def _service_processes_use_source(contract: TargetContract, source_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", contract.service, "--property=ControlGroup", "--value"],
            check=True,
            capture_output=True,
            text=True,
        )
        control_group = result.stdout.strip()
        if not control_group.startswith("/") or ".." in Path(control_group).parts:
            return False
        process_file = Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.procs"
        process_ids = [int(value) for value in process_file.read_text().splitlines() if value]
        expected = source_root.resolve(strict=True)
        return bool(process_ids) and all(
            (working := Path(f"/proc/{process_id}/cwd").readlink().resolve(strict=True)) == expected
            or expected in working.parents
            for process_id in process_ids
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _write_rendered(path: Path, content: str, mode: int) -> None:
    _write_atomic_bytes(path, content.encode(), mode)


def _write_atomic_bytes(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise BootstrapError("authority destination parent is unsafe")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "install", "adopt-legacy"))
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--deploy-public-key")
    parser.add_argument("--migration-audit-config", type=Path)
    parser.add_argument("--expected-authority-sha")
    parser.add_argument("--confirm-marker")
    parser.add_argument("--confirm-no-rollback")
    args = parser.parse_args()
    contract = TargetContract.load(args.contract)
    if args.action == "audit":
        result = audit_target(contract, contract_path=args.contract, source_root=args.source_root)
    elif args.action == "install":
        if (
            not args.deploy_public_key
            or not args.confirm_marker
            or not args.migration_audit_config
            or not args.expected_authority_sha
        ):
            parser.error(
                "install requires --deploy-public-key, --migration-audit-config, "
                "--expected-authority-sha, and --confirm-marker",
            )
        result = install_authority(
            contract,
            source_root=args.source_root,
            contract_path=args.contract,
            deploy_public_key=args.deploy_public_key,
            migration_audit_config=args.migration_audit_config,
            expected_authority_sha=args.expected_authority_sha,
            confirmation=args.confirm_marker,
        )
    else:
        if not args.confirm_marker or args.confirm_marker != contract.marker:
            parser.error("adopt-legacy requires the exact --confirm-marker")
        result = authorize_legacy_adoption(
            contract,
            contract_path=args.contract,
            source_root=args.source_root,
            confirmation=args.confirm_no_rollback or "",
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    print(json.dumps(result.public_dict(), sort_keys=True, separators=(",", ":")))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
