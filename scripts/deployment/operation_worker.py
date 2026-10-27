# ruff: noqa: C901, EM101, PLR0911, PLR0912, PLR0913, PLR0915, S603, TRY003, TRY301
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.deployment import catalogue_schema
from scripts.deployment.concept_schema import MIGRATION_APPLY
from scripts.deployment.concept_schema import PLAN_CHECK
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import audit_matches
from scripts.deployment.concept_schema import validate_build_evidence
from scripts.deployment.concept_schema import validate_candidate
from scripts.deployment.concept_schema import validate_disclosure
from scripts.deployment.protocol import DIGEST_RE
from scripts.deployment.protocol import NUMERIC_RE
from scripts.deployment.protocol import SHA_RE
from scripts.deployment.release_state import TRANSITIONS
from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import protected_release_shas
from scripts.deployment.release_state import read_json
from scripts.deployment.release_state import release_sha_from_link
from scripts.deployment.release_state import safe_release_path
from scripts.deployment.release_state import transition
from scripts.deployment.release_state import utc_now
from scripts.deployment.server_activate import activate_release
from scripts.deployment.server_activate import restart_service
from scripts.deployment.server_activate import restore_previous
from scripts.deployment.server_activate import verify_release
from scripts.deployment.server_activate import write_runtime_state
from scripts.deployment.server_gate import DEFAULT_CONTRACT
from scripts.deployment.target import TargetContract

PREPARE_HELPER = Path("/usr/local/libexec/asterproof-prepare-release")
MIGRATION_AUDIT_HELPER = Path("/usr/local/libexec/asterproof-migration-audit")
RUNUSER = Path("/usr/sbin/runuser")
SYSTEMD_RUN = Path("/usr/bin/systemd-run")
MAX_RETAINED_RELEASES = 5
MIN_RETAINED_RELEASES = 2


class OperationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _release_record_path(contract: TargetContract, release_sha: str) -> Path:
    safe_release_path(contract.releases_dir, release_sha)
    return contract.registry_dir / "releases" / f"{release_sha}.json"


def _load_release_record(contract: TargetContract, release_sha: str) -> dict[str, Any]:
    record = read_json(_release_record_path(contract, release_sha))
    if (
        record.get("release_sha") != release_sha
        or not DIGEST_RE.fullmatch(str(record.get("artifact_digest", "")))
        or not DIGEST_RE.fullmatch(str(record.get("state_fingerprint", "")))
    ):
        raise OperationError("release_record_invalid")
    return record


def _write_release_record(
    contract: TargetContract,
    request: dict[str, Any],
    *,
    state: str,
    rollback_eligible: bool,
    state_fingerprint: str,
) -> None:
    atomic_write_json(
        _release_record_path(contract, request["release_sha"]),
        {
            "artifact_digest": request["artifact_digest"],
            "migration_class": request["migration_class"],
            "state_fingerprint": state_fingerprint,
            "release_sha": request["release_sha"],
            "rollback_eligible": rollback_eligible,
            "state": state,
            "updated_at": utc_now(),
        },
    )


def _set_release_record_state(
    contract: TargetContract,
    release_sha: str,
    state: str,
    *,
    state_fingerprint: str | None = None,
) -> None:
    path = _release_record_path(contract, release_sha)
    record = read_json(path)
    record.update({"state": state, "updated_at": utc_now()})
    if state_fingerprint is not None:
        record["state_fingerprint"] = state_fingerprint
    atomic_write_json(path, record)


@dataclass
class WorkerBackend:
    """Trusted host adapter. Candidate code is invoked only below through runuser."""

    contract_path: Path = DEFAULT_CONTRACT

    def prepare(self, contract: TargetContract, request: dict[str, Any], destination: Path) -> None:
        incoming = contract.incoming_dir / f"{request['run_id']}-{request['release_sha']}.tar"
        processing = contract.processing_dir / incoming.name
        if processing.exists() or processing.is_symlink():
            raise OperationError("artifact_processing_collision")
        read_flags = os.O_RDONLY
        write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            read_flags |= os.O_NOFOLLOW
            write_flags |= os.O_NOFOLLOW
        try:
            incoming_fd = os.open(incoming, read_flags)
        except OSError as exc:
            raise OperationError("artifact_missing") from exc
        try:
            incoming_stat = os.fstat(incoming_fd)
            if not stat.S_ISREG(incoming_stat.st_mode) or incoming_stat.st_nlink != 1:
                raise OperationError("artifact_not_regular")
            build_account = pwd.getpwnam(contract.build_user)
            processing_fd = os.open(processing, write_flags, 0o440)
            try:
                with (
                    os.fdopen(incoming_fd, "rb", closefd=False) as source,
                    os.fdopen(processing_fd, "wb", closefd=False) as output,
                ):
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.fchmod(processing_fd, 0o440)
                os.fchown(processing_fd, 0, build_account.pw_gid)
            finally:
                os.close(processing_fd)
            incoming.unlink()
            stable = processing.lstat()
            if not stat.S_ISREG(stable.st_mode) or stable.st_nlink != 1:
                raise OperationError("artifact_not_regular")
            try:
                subprocess.run(
                    [
                        str(RUNUSER),
                        "--user",
                        contract.build_user,
                        "--",
                        str(PREPARE_HELPER),
                        "--archive",
                        str(processing),
                        "--destination",
                        str(destination),
                        "--final-destination",
                        str(contract.releases_dir / destination.name),
                        "--digest",
                        request["artifact_digest"],
                        "--python",
                        str(contract.python_executable),
                        "--repository",
                        contract.repository,
                        "--repository-id",
                        contract.repository_id,
                        "--python-abi",
                        contract.python_abi,
                        "--target-platform",
                        contract.target_platform,
                    ],
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError):
                if destination.parent == contract.build_dir and destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                raise
        finally:
            os.close(incoming_fd)
            processing.unlink(missing_ok=True)

    def publish_permissions(self, contract: TargetContract, staging: Path, release: Path) -> None:
        expected_staging = safe_release_path(contract.build_dir, staging.name).resolve(strict=True)
        if expected_staging != staging.resolve(strict=True) or release.exists() or release.is_symlink():
            raise OperationError("release_path_invalid")
        build_uid = pwd.getpwnam(contract.build_user).pw_uid
        paths = {staging}
        for root, directories, files in os.walk(staging, topdown=False, followlinks=False):
            paths.update(Path(root) / name for name in directories + files)
        for path in paths:
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise OperationError("release_member_invalid")
            if path.lstat().st_uid != build_uid or mode & 0o222:
                raise OperationError("release_permissions_invalid")
        for path in sorted(paths, key=lambda member: len(member.parts), reverse=True):
            os.chown(path, 0, 0, follow_symlinks=False)
        staging.replace(release)

    def _run_candidate(
        self,
        contract: TargetContract,
        release: Path,
        arguments: list[str],
        *,
        migration: bool = False,
        runtime_seconds: int | None = None,
    ) -> None:
        subprocess.run(
            [
                str(SYSTEMD_RUN),
                "--quiet",
                "--wait",
                "--collect",
                "--service-type=exec",
                f"--uid={contract.app_user}",
                "--setenv=DJANGO_READ_DOT_ENV_FILE=False",
                *(["--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s"] if migration else []),
                f"--property=WorkingDirectory={release}",
                f"--property=EnvironmentFile={contract.environment_file}",
                "--property=NoNewPrivileges=yes",
                "--property=PrivateTmp=yes",
                "--property=ProtectHome=yes",
                "--property=ProtectSystem=strict",
                "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
                *([f"--property=RuntimeMaxSec={runtime_seconds}s"] if runtime_seconds else []),
                str(release / ".venv/bin/python"),
                str(release / "manage.py"),
                *arguments,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **({"timeout": runtime_seconds + 30} if runtime_seconds else {}),
        )

    def candidate_check(self, contract: TargetContract, release: Path) -> None:
        self._run_candidate(contract, release, ["check", "--deploy"])
        self._run_candidate(contract, release, ["makemigrations", "--check", "--dry-run"])

    def candidate_migrations_applied(self, contract: TargetContract, release: Path) -> None:
        self._run_candidate(contract, release, ["migrate", "--check"])

    def migrate(self, contract: TargetContract, release: Path) -> None:
        self._run_candidate(contract, release, ["migrate", "--noinput"])

    def check_concept_schema(self, contract: TargetContract, release: Path) -> None:
        validate_candidate(release)
        self._run_candidate(contract, release, ["shell", "--command", PLAN_CHECK])

    def migrate_concept_schema(self, contract: TargetContract, release: Path) -> None:
        # MigrationExecutor avoids unrelated post_migrate content-type/permission writes.
        self._run_candidate(contract, release, ["shell", "--command", MIGRATION_APPLY], migration=True)

    def check_catalogue_schema(self, contract: TargetContract, release: Path) -> None:
        catalogue_schema.validate_candidate(release)
        self._run_candidate(contract, release, ["shell", "--command", catalogue_schema.PLAN_CHECK])

    def migrate_catalogue_schema(self, contract: TargetContract, release: Path) -> None:
        self._run_candidate(
            contract, release, ["shell", "--command", catalogue_schema.MIGRATION_APPLY], migration=True,
        )

    def refresh_catalogue(self, contract: TargetContract, release: Path) -> None:
        self._run_candidate(contract, release, ["refresh_concept_summaries"], runtime_seconds=900)

    def catalogue_audit(self, contract: TargetContract) -> dict[str, Any]:
        audit = self.schema_audit(contract)
        response = subprocess.run(
            [str(MIGRATION_AUDIT_HELPER), "catalogue-behaviour", "--contract", str(self.contract_path)],
            check=True, capture_output=True, text=True, timeout=45,
        )
        try:
            behaviour = json.loads(response.stdout)
            if behaviour["database_identity_hash"] != audit["state"]["database_identity_hash"]:
                raise OperationError("catalogue_audit_identity_mismatch")
            fingerprint = behaviour["behaviour_fingerprint"]
            if not isinstance(fingerprint, str) or not DIGEST_RE.fullmatch(fingerprint):
                raise OperationError("catalogue_audit_invalid")
        except (ValueError, TypeError, KeyError) as exc:
            raise OperationError("catalogue_audit_invalid") from exc
        return {**audit, "behaviour_fingerprint": fingerprint}

    def preflight_recovery(self, contract: TargetContract) -> None:
        from scripts.deployment.database_recovery import preflight_recovery

        try:
            preflight_recovery(contract)
            self._scheduler_plan(contract)
        except Exception as exc:
            raise OperationError("recovery_preflight_failed") from exc

    def create_recovery(self, contract: TargetContract, run_id: str, active_sha: str, fingerprint: str) -> dict:
        from scripts.deployment.database_recovery import create_verified_backup

        try:
            return create_verified_backup(contract, run_id, active_sha, fingerprint)
        except Exception as exc:
            raise OperationError("recovery_backup_or_restore_failed") from exc

    def verify_recovery(self, contract: TargetContract, run_id: str, active_sha: str, fingerprint: str) -> dict:
        from scripts.deployment.database_recovery import validate_saved_recovery

        try:
            return validate_saved_recovery(contract, run_id, active_sha, fingerprint)
        except Exception as exc:
            raise OperationError("recovery_receipt_invalid") from exc

    def verify_catalogue_records(self, contract: TargetContract, run_id: str, active_sha: str) -> None:
        from scripts.deployment.database_recovery import verify_preserved_records

        try:
            verify_preserved_records(contract, run_id, active_sha)
        except Exception as exc:
            raise OperationError("catalogue_original_records_changed") from exc

    def _unit_properties(self, unit: str, names: str) -> dict[str, str]:
        response = subprocess.run(
            ["/usr/bin/systemctl", "show", unit, "--property=" + names],
            check=True, capture_output=True, text=True, timeout=15,
        )
        return dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)

    def _scheduler_plan(self, contract: TargetContract) -> tuple[str, bool]:
        timer = contract.scheduler_service.removesuffix(".service") + ".timer"
        scheduler = self._unit_properties(contract.scheduler_service, "LoadState,TriggeredBy")
        timer_state = self._unit_properties(timer, "LoadState,ActiveState")
        if scheduler.get("LoadState") != "loaded" or set(scheduler.get("TriggeredBy", "").split()) != {timer}:
            raise OperationError("maintenance_scheduler_trigger_unknown")
        if timer_state.get("LoadState") != "loaded" or timer_state.get("ActiveState") not in {"active", "inactive"}:
            raise OperationError("maintenance_scheduler_state_unknown")
        return timer, timer_state["ActiveState"] == "active"

    def drain(self, contract: TargetContract, state_path: Path) -> None:
        timer, was_active = self._scheduler_plan(contract)
        state = read_json(state_path)
        state["maintenance_scheduler_was_active"] = was_active
        atomic_write_json(state_path, state)
        subprocess.run(
            ["/usr/bin/systemctl", "stop", timer, contract.scheduler_service, contract.service],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
        )
        for unit in (timer, contract.scheduler_service, contract.service):
            properties = self._unit_properties(unit, "ActiveState,MainPID,ControlGroup")
            if properties.get("ActiveState") != "inactive" or properties.get("MainPID", "0") != "0":
                raise OperationError("maintenance_drain_incomplete")
            group = properties.get("ControlGroup", "")
            if group:
                path = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
                if path.exists() and path.read_text().strip():
                    raise OperationError("maintenance_cgroup_not_empty")

        self.assert_database_drained()

    def assert_database_drained(self) -> None:
        from scripts.deployment.migration_audit import DEFAULT_CONFIG
        from scripts.deployment.migration_audit import AuditConfig
        from scripts.deployment.migration_audit import _run_query
        from scripts.deployment.migration_audit import collect_identity

        config = AuditConfig.load(DEFAULT_CONFIG)
        if collect_identity(config)["database_identity_hash"] != config.expected_database_identity_hash:
            raise OperationError("maintenance_database_identity_drift")
        count = _run_query(config, """
            SELECT count(*) FROM pg_catalog.pg_stat_activity
            WHERE datname=current_database() AND backend_type='client backend'
              AND pid<>pg_backend_pid() AND usename<>current_user
        """).strip()
        if count != "0":
            raise OperationError("maintenance_database_writers_present")

    def resume_scheduler(self, contract: TargetContract, state_path: Path) -> None:
        if read_json(state_path).get("maintenance_scheduler_was_active"):
            timer = contract.scheduler_service.removesuffix(".service") + ".timer"
            subprocess.run(
                ["/usr/bin/systemctl", "start", timer], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
            if self._unit_properties(timer, "ActiveState").get("ActiveState") != "active":
                raise OperationError("maintenance_scheduler_resume_failed")

    def schema_audit(self, contract: TargetContract) -> dict[str, Any]:
        result = subprocess.run(
            [str(MIGRATION_AUDIT_HELPER), "fingerprint", "--contract", str(self.contract_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise OperationError("migration_audit_invalid") from exc
        fingerprint = value.get("state_fingerprint") if isinstance(value, dict) else None
        if not isinstance(fingerprint, str) or not DIGEST_RE.fullmatch(fingerprint):
            raise OperationError("migration_audit_invalid")
        return value

    def state_fingerprint(self, contract: TargetContract) -> str:
        return self.schema_audit(contract)["state_fingerprint"]

    def legacy_service_matches(self, contract: TargetContract, source_root: Path) -> bool:
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

    def legacy_source_matches(self, contract: TargetContract, source_root: Path, legacy_sha: str) -> bool:
        try:
            owner = pwd.getpwuid(source_root.stat().st_uid).pw_name
            environment = os.environ.copy()
            environment.update(
                {
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_NO_REPLACE_OBJECTS": "1",
                    "GIT_OPTIONAL_LOCKS": "0",
                    "GIT_TERMINAL_PROMPT": "0",
                    "XDG_CONFIG_HOME": "/nonexistent",
                },
            )

            def git(*arguments: str) -> str:
                # Probe an existing owner's checkout without executing its Git config as root.
                return subprocess.run(
                    [str(RUNUSER), "--user", owner, "--", "/usr/bin/git", "-c", "core.fsmonitor=false", *arguments],
                    cwd=source_root,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout

            head = git("rev-parse", "HEAD").strip()
            origin = git("remote", "get-url", "origin").strip()
            status = git("status", "--porcelain=v1", "--untracked-files=all")
        except (KeyError, OSError, subprocess.SubprocessError):
            return False
        normalized = origin.removesuffix(".git").replace("git@github.com:", "https://github.com/")
        return head == legacy_sha and not status and normalized == f"https://github.com/{contract.repository}"

    def discard_candidate(self, contract: TargetContract, release: Path) -> None:
        if release.parent != contract.releases_dir or release.is_symlink() or not release.is_dir():
            raise OperationError("candidate_cleanup_path_invalid")
        if (contract.registry_dir / "releases" / f"{release.name}.json").exists():
            raise OperationError("candidate_cleanup_recorded")
        for link_name in ("current", "previous"):
            linked = release_sha_from_link(contract.release_root / link_name, releases_dir=contract.releases_dir)
            if linked == release.name:
                raise OperationError("candidate_cleanup_active")
        shutil.rmtree(release)

    def activate(self, contract: TargetContract, release_sha: str) -> str | None:
        return activate_release(contract, release_sha)

    def restore(self, contract: TargetContract) -> str:
        return restore_previous(contract)

    def restart_and_verify(
        self,
        contract: TargetContract,
        release_sha: str,
        artifact_digest: str,
    ) -> dict[str, Any]:
        restart_service(contract)
        return self.verify(contract, release_sha, artifact_digest)

    def verify(self, contract: TargetContract, release_sha: str, artifact_digest: str) -> dict[str, Any]:
        return verify_release(contract, release_sha, artifact_digest)

    def prune(self, contract: TargetContract) -> list[str]:
        return prune_releases(contract)


def prune_releases(
    contract: TargetContract,
    *,
    max_retained: int = MAX_RETAINED_RELEASES,
    expected_uid: int | None = None,
) -> list[str]:
    if max_retained < MIN_RETAINED_RELEASES:
        raise OperationError("retention_limit_invalid")
    expected_uid = os.geteuid() if expected_uid is None else expected_uid
    protected = protected_release_shas(contract.release_root, contract.registry_dir / "operations")
    releases: list[Path] = []
    for path in contract.releases_dir.iterdir():
        mode = path.lstat().st_mode
        if path.name in protected:
            continue
        if SHA_RE.fullmatch(path.name) is None or not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise OperationError("retention_release_invalid")
        if path.lstat().st_uid != expected_uid:
            raise OperationError("retention_release_owner_invalid")
        releases.append(path)
    keep_unprotected = max(0, max_retained - len(protected))
    releases.sort(key=lambda path: path.lstat().st_mtime_ns, reverse=True)
    removed: list[str] = []
    for path in releases[keep_unprotected:]:
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def _validate_request(request: dict[str, Any], run_id: str) -> None:
    required = {
        "artifact_digest",
        "deployment_id",
        "migration_class",
        "operation",
        "release_sha",
        "run_id",
        "target_marker",
        "workflow_sha",
        "workflow_ref",
    }
    if set(request) not in (required, required | {"schema_disclosure"}) or request.get("run_id") != run_id:
        raise OperationError("request_invalid")
    if "schema_disclosure" in request:
        if request["operation"] != "deploy" or request["migration_class"] not in {
            "backward-compatible-schema", "data-or-non-compatible",
        }:
            raise OperationError("request_invalid")
        try:
            validator = (
                catalogue_schema.validate_disclosure
                if request["migration_class"] == "data-or-non-compatible"
                else validate_disclosure
            )
            validator(request["schema_disclosure"], target_sha=request["release_sha"])
        except ValueError as exc:
            raise OperationError("schema_disclosure_invalid") from exc
    elif request["migration_class"] == "data-or-non-compatible":
        raise OperationError("schema_disclosure_invalid")
    if not NUMERIC_RE.fullmatch(run_id) or not SHA_RE.fullmatch(str(request.get("release_sha", ""))):
        raise OperationError("request_invalid")
    if not DIGEST_RE.fullmatch(str(request.get("artifact_digest", ""))):
        raise OperationError("request_invalid")
    if not SHA_RE.fullmatch(str(request.get("workflow_sha", ""))):
        raise OperationError("request_invalid")
    if request.get("operation") == "deploy" and request["workflow_sha"] != request["release_sha"]:
        raise OperationError("deploy_sha_mismatch")


def _baseline(contract: TargetContract, backend: WorkerBackend) -> tuple[str | None, dict[str, Any], str]:
    current_sha = release_sha_from_link(contract.release_root / "current", releases_dir=contract.releases_dir)
    if current_sha is None:
        adoption_path = contract.registry_dir / "adoption.json"
        adoption = read_json(adoption_path)
        required = {
            "authorized_at",
            "legacy_sha",
            "legacy_source_root",
            "state_fingerprint",
            "repository",
            "state",
            "target_marker",
        }
        if (
            set(adoption) != required
            or adoption.get("state") != "authorized"
            or adoption.get("repository") != contract.repository
            or adoption.get("target_marker") != contract.marker
            or not SHA_RE.fullmatch(str(adoption.get("legacy_sha", "")))
            or not DIGEST_RE.fullmatch(str(adoption.get("state_fingerprint", "")))
        ):
            raise OperationError("baseline_missing")
        legacy_source_root = Path(str(adoption["legacy_source_root"]))
        if (
            not legacy_source_root.is_absolute()
            or ".." in legacy_source_root.parts
            or not backend.legacy_service_matches(contract, legacy_source_root)
            or not backend.legacy_source_matches(contract, legacy_source_root, str(adoption["legacy_sha"]))
        ):
            raise OperationError("baseline_legacy_process_drift")
        fingerprint = backend.state_fingerprint(contract)
        if fingerprint != adoption["state_fingerprint"]:
            raise OperationError("baseline_state_drift")
        return None, {"rollback_eligible": False}, fingerprint
    record = _load_release_record(contract, current_sha)
    if record.get("state") != "active":
        raise OperationError("baseline_unverified")
    health = backend.verify(contract, current_sha, record["artifact_digest"])
    fingerprint = backend.state_fingerprint(contract)
    if health.get("state_fingerprint") != fingerprint or record["state_fingerprint"] != fingerprint:
        raise OperationError("baseline_state_drift")
    return current_sha, record, fingerprint


def _mark_failure(path: Path, *, recovery: bool, code: str) -> dict[str, Any]:
    state = read_json(path).get("state")
    target = "recovery_required" if recovery else "failed"
    if target in TRANSITIONS.get(state, set()):
        return transition(path, target, error_code=code)
    current = read_json(path)
    current.update({"error_code": code, "state": "recovery_required", "updated_at": utc_now()})
    atomic_write_json(path, current)
    return current


def _assert_no_unresolved_operations(contract: TargetContract, current_run_id: str) -> None:
    operations = contract.registry_dir / "operations"
    if not operations.is_dir():
        return
    for path in operations.glob("*.json"):
        if path.stem == current_run_id:
            continue
        try:
            state = read_json(path).get("state")
        except ReleaseStateError as exc:
            raise OperationError("unresolved_operation_exists") from exc
        if state not in {"active", "failed", "rolled_back"}:
            raise OperationError("unresolved_operation_exists")


def _deploy(
    contract: TargetContract,
    request: dict[str, Any],
    state_path: Path,
    backend: WorkerBackend,
) -> dict[str, Any]:
    baseline_sha, baseline_record, baseline_fingerprint = _baseline(contract, backend)
    staging = safe_release_path(contract.build_dir, request["release_sha"])
    release = safe_release_path(contract.releases_dir, request["release_sha"])
    backend.prepare(contract, request, staging)
    backend.publish_permissions(contract, staging, release)
    try:
        backend.candidate_check(contract, release)
        transition(state_path, "prepared")
        if request["migration_class"] == "data-or-non-compatible":
            disclosure = request["schema_disclosure"]
            if baseline_sha is None or disclosure["active_sha"] != baseline_sha or not catalogue_schema.audit_matches(
                disclosure, backend.catalogue_audit(contract), stage="starting",
            ):
                raise OperationError("catalogue_starting_state_mismatch")
            try:
                catalogue_schema.validate_build_evidence(release, disclosure)
                backend.check_catalogue_schema(contract, release)
            except (OSError, ValueError) as exc:
                raise OperationError("catalogue_candidate_invalid") from exc
            backend.preflight_recovery(contract)
            if not catalogue_schema.audit_matches(disclosure, backend.catalogue_audit(contract), stage="starting"):
                raise OperationError("catalogue_starting_state_drift")
            transition(state_path, "draining")
            backend.drain(contract, state_path)
            transition(state_path, "backing_up")
            backend.create_recovery(contract, request["run_id"], baseline_sha, baseline_fingerprint)
            receipt = backend.verify_recovery(contract, request["run_id"], baseline_sha, baseline_fingerprint)
            if (
                not isinstance(receipt, dict) or not isinstance(receipt.get("backup_id"), str)
                or not receipt["backup_id"] or not DIGEST_RE.fullmatch(str(receipt.get("archive_sha256", "")))
            ):
                raise OperationError("recovery_receipt_invalid")
            state = read_json(state_path)
            state.update({
                "recovery_backup_id": receipt["backup_id"],
                "recovery_archive_sha256": receipt["archive_sha256"],
            })
            atomic_write_json(state_path, state)
            if not catalogue_schema.audit_matches(disclosure, backend.catalogue_audit(contract), stage="starting"):
                raise OperationError("catalogue_starting_state_drift")
            backend.assert_database_drained()
            transition(state_path, "migrating")
            backend.migrate_catalogue_schema(contract, release)
            if not catalogue_schema.audit_matches(disclosure, backend.catalogue_audit(contract), stage="expected"):
                raise OperationError("catalogue_ending_state_mismatch")
            backend.refresh_catalogue(contract, release)
            backend.verify_catalogue_records(contract, request["run_id"], baseline_sha)
            if not catalogue_schema.audit_matches(disclosure, backend.catalogue_audit(contract), stage="expected"):
                raise OperationError("catalogue_ending_behaviour_drift")
        if request["migration_class"] == "backward-compatible-schema":
            disclosure = request.get("schema_disclosure")
            if disclosure is None:
                raise OperationError("migration_disclosure_contract_missing")
            if disclosure["active_sha"] != baseline_sha or not audit_matches(
                disclosure,
                backend.schema_audit(contract),
                stage="starting",
            ):
                raise OperationError("schema_starting_state_mismatch")
            try:
                validate_build_evidence(release, disclosure)
                backend.check_concept_schema(contract, release)
            except ConceptSchemaError as exc:
                raise OperationError("schema_candidate_invalid") from exc
            if not audit_matches(disclosure, backend.schema_audit(contract), stage="starting"):
                raise OperationError("schema_starting_state_drift")
            transition(state_path, "migrating")
            backend.migrate_concept_schema(contract, release)
            if not audit_matches(disclosure, backend.schema_audit(contract), stage="expected"):
                raise OperationError("schema_ending_state_mismatch")
        backend.candidate_migrations_applied(contract, release)
        ending_fingerprint = backend.state_fingerprint(contract)
        if request["migration_class"] in {"backward-compatible-schema", "data-or-non-compatible"} and (
            ending_fingerprint != request["schema_disclosure"]["expected"]["state_fingerprint"]
        ):
            raise OperationError("schema_ending_state_drift")
        if request["migration_class"] == "none" and ending_fingerprint != baseline_fingerprint:
            raise OperationError("unexpected_state_drift")
        write_runtime_state(
            release,
            release_sha=request["release_sha"],
            artifact_digest=request["artifact_digest"],
            state_fingerprint=ending_fingerprint,
        )
    except Exception:
        if read_json(state_path).get("state") not in {"draining", "backing_up", "migrating"}:
            backend.discard_candidate(contract, release)
        raise
    transition(state_path, "activating")
    backend.activate(contract, request["release_sha"])
    try:
        health = backend.restart_and_verify(contract, request["release_sha"], request["artifact_digest"])
        if (
            health.get("state_fingerprint") != ending_fingerprint
            or backend.state_fingerprint(contract) != ending_fingerprint
        ):
            raise OperationError("activation_state_drift")
        if request["migration_class"] == "data-or-non-compatible" and not catalogue_schema.audit_matches(
            request["schema_disclosure"], backend.catalogue_audit(contract), stage="expected",
        ):
            raise OperationError("catalogue_activation_behaviour_drift")
    except Exception as activation_error:
        can_rollback = request["migration_class"] in {"none", "backward-compatible-schema"} and bool(
            baseline_record.get("rollback_eligible"),
        )
        if not can_rollback:
            raise OperationError("activation_failed_ineligible_rollback") from activation_error
        try:
            if backend.state_fingerprint(contract) != ending_fingerprint:
                raise OperationError("rollback_database_state_drift")
            write_runtime_state(
                safe_release_path(contract.releases_dir, baseline_sha),
                release_sha=baseline_sha,
                artifact_digest=baseline_record["artifact_digest"],
                state_fingerprint=ending_fingerprint,
            )
            restored = backend.restore(contract)
            if restored != baseline_sha:
                raise OperationError("rollback_target_mismatch")
            health = backend.restart_and_verify(contract, baseline_sha, baseline_record["artifact_digest"])
            if (
                health.get("state_fingerprint") != ending_fingerprint
                or backend.state_fingerprint(contract) != ending_fingerprint
            ):
                raise OperationError("rollback_health_state_drift")
        except Exception as rollback_error:
            raise OperationError("automatic_rollback_failed") from rollback_error
        _write_release_record(
            contract,
            request,
            state="failed",
            rollback_eligible=False,
            state_fingerprint=ending_fingerprint,
        )
        if baseline_sha is not None:
            _set_release_record_state(contract, baseline_sha, "active", state_fingerprint=ending_fingerprint)
        return transition(state_path, "rolled_back", error_code="activation_failed")
    if request["migration_class"] == "data-or-non-compatible":
        backend.resume_scheduler(contract, state_path)
    _write_release_record(
        contract,
        request,
        state="active",
        rollback_eligible=request["migration_class"] in {"none", "backward-compatible-schema"},
        state_fingerprint=ending_fingerprint,
    )
    if baseline_sha is not None:
        _set_release_record_state(contract, baseline_sha, "previous", state_fingerprint=ending_fingerprint)
    else:
        adoption_path = contract.registry_dir / "adoption.json"
        adoption = read_json(adoption_path)
        adoption.update(
            {"consumed_by_release_sha": request["release_sha"], "state": "consumed", "updated_at": utc_now()},
        )
        atomic_write_json(adoption_path, adoption)
    cleanup_error = None
    try:
        backend.prune(contract)
    except (OSError, OperationError):
        cleanup_error = "retention_cleanup_failed"
    return transition(state_path, "active", error_code=cleanup_error)


def _rollback(
    contract: TargetContract,
    request: dict[str, Any],
    state_path: Path,
    backend: WorkerBackend,
) -> dict[str, Any]:
    current_sha = release_sha_from_link(contract.release_root / "current", releases_dir=contract.releases_dir)
    if current_sha is None:
        raise OperationError("baseline_missing")
    current_record = _load_release_record(contract, current_sha)
    if current_record.get("migration_class") == "data-or-non-compatible":
        raise OperationError("rollback_requires_independent_recovery")
    target_record = _load_release_record(contract, request["release_sha"])
    if current_record.get("state") != "active" or target_record.get("state") != "previous":
        raise OperationError("rollback_release_state_invalid")
    if target_record["artifact_digest"] != request["artifact_digest"] or not target_record.get("rollback_eligible"):
        raise OperationError("rollback_target_ineligible")
    previous_sha = release_sha_from_link(contract.release_root / "previous", releases_dir=contract.releases_dir)
    if previous_sha != request["release_sha"]:
        raise OperationError("rollback_target_not_previous")
    before_fingerprint = backend.state_fingerprint(contract)
    if (
        current_record["state_fingerprint"] != before_fingerprint
        or target_record["state_fingerprint"] != before_fingerprint
    ):
        raise OperationError("rollback_database_state_drift")
    write_runtime_state(
        safe_release_path(contract.releases_dir, request["release_sha"]),
        release_sha=request["release_sha"],
        artifact_digest=request["artifact_digest"],
        state_fingerprint=before_fingerprint,
    )
    transition(state_path, "activating")
    restored = backend.restore(contract)
    try:
        health = backend.restart_and_verify(contract, restored, request["artifact_digest"])
        if health.get("state_fingerprint") != before_fingerprint:
            raise OperationError("rollback_health_state_drift")
        if backend.state_fingerprint(contract) != before_fingerprint:
            raise OperationError("rollback_database_state_drift")
    except Exception as exc:
        raise OperationError("rollback_verification_failed") from exc
    _set_release_record_state(
        contract,
        request["release_sha"],
        "active",
        state_fingerprint=before_fingerprint,
    )
    _set_release_record_state(contract, current_sha, "previous")
    cleanup_error = None
    try:
        backend.prune(contract)
    except (OSError, OperationError):
        cleanup_error = "retention_cleanup_failed"
    return transition(state_path, "rolled_back", error_code=cleanup_error)


def run_operation(
    contract: TargetContract,
    run_id: str,
    *,
    backend: WorkerBackend | None = None,
) -> dict[str, Any]:
    if not NUMERIC_RE.fullmatch(run_id):
        raise OperationError("run_id_invalid")
    backend = backend or WorkerBackend()
    request_path = contract.registry_dir / "requests" / f"{run_id}.json"
    state_path = contract.registry_dir / "operations" / f"{run_id}.json"
    request = read_json(request_path)
    _validate_request(request, run_id)
    current = read_json(state_path)
    if current.get("state") in {"active", "rolled_back", "failed", "recovery_required"}:
        return current
    if current.get("state") != "verified":
        return _mark_failure(state_path, recovery=True, code="interrupted_operation")

    contract.registry_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = contract.registry_dir / "operation.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _mark_failure(state_path, recovery=False, code="operation_busy")
        try:
            _assert_no_unresolved_operations(contract, run_id)
            if request["operation"] == "deploy":
                return _deploy(contract, request, state_path, backend)
            if request["operation"] == "rollback":
                return _rollback(contract, request, state_path, backend)
            raise OperationError("operation_not_supported")
        except OperationError as exc:
            state = read_json(state_path).get("state")
            recovery = state in {"draining", "backing_up", "migrating", "activating"}
            return _mark_failure(state_path, recovery=recovery, code=exc.code)
        except (OSError, subprocess.SubprocessError, ReleaseStateError):
            state = read_json(state_path).get("state")
            recovery = state in {"draining", "backing_up", "migrating", "activating"}
            return _mark_failure(state_path, recovery=recovery, code="operation_failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run_operation(TargetContract.load(args.contract), args.run_id, backend=WorkerBackend(contract_path=args.contract))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
