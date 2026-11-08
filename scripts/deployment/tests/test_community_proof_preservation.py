# ruff: noqa: EM101, PLR2004, SLF001, TRY003
"""Every prior record/sequence survives; only frozen migration projections differ."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import community_proof_preservation as preservation
from scripts.deployment import database_recovery as recovery
from scripts.deployment.migration_audit import AuditConfig


def digest(data):
    return {"rows": data.count(b"\n"), "sha256": hashlib.sha256(data).hexdigest()}


def wire_rows(rows):
    encoded = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    return b"".join(value.encode() + b"\n" for value in sorted(encoded))


class FakeCursor:
    def __init__(self, database):
        self.database, self.result = database, []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return None

    def execute(self, query, *unused):
        self.database.executed.append(query)
        if query == recovery.TABLES_SQL:
            self.result = [(schema, table, []) for schema, table in sorted(self.database.tables)]
        elif query == recovery.SEQUENCES_SQL:
            self.result = sorted(self.database.sequences)
        elif query == preservation.COLUMN_SQL:
            self.result = [(name,) for name in self.database.columns]
        elif query == preservation.DEFAULTS_SQL:
            rows = self.database.tables[("public", "pages_communityproblem")]
            self.result = [
                (
                    sum(
                        row.get("legacy_member_visible") is not True
                        or row.get("solution_known") is not False
                        or row.get("public_hint") != ""
                        or row.get("embargo_until") is not None
                        for row in rows
                    ),
                ),
            ]
        elif query == preservation.MIGRATION_DELTA_SQL:
            rows = [
                row
                for row in self.database.tables[("public", "django_migrations")]
                if row["app"] == "pages" and row["name"] == preservation.MIGRATION
            ]
            value, called = self.database.sequences[preservation.MIGRATION_SEQUENCE]
            self.result = [(len(rows), bool(rows) and all(row["id"] == value for row in rows), called and value > 1)]
        elif query == preservation.SOURCE_IDENTITY_SQL:
            self.result = [self.database.identity]
        elif query == recovery.META_SQL:
            self.result = [(self.database.metadata,)]
        elif str(query).startswith("SET "):
            self.result = []
        else:
            raise AssertionError("Unexpected SQL")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0]

    def copy(self, query):
        query = query.as_string(None) if hasattr(query, "as_string") else query
        self.database.copied.append(query)
        if "pg_largeobject_metadata" in query:
            data = b""
        elif "row_to_json" in query:
            key = next(key for key in self.database.tables if '"{}"."{}"'.format(*key) in query)
            rows = self.database.tables[key]
            if key == ("public", "pages_communityproblem"):
                projection = ",".join('"' + name + '"' for name in preservation.COMMUNITY_COLUMNS)
                assert "FROM (SELECT " + projection + ' FROM "public"."pages_communityproblem") t' in query  # noqa: S608 - assertion only, frozen identifiers
                rows = [{name: row[name] for name in preservation.COMMUNITY_COLUMNS} for row in rows]
            elif key == ("public", "django_migrations"):
                assert "WHERE NOT (app='pages' AND name='0045_community_proof_library')" in query
                rows = [row for row in rows if not (row["app"] == "pages" and row["name"] == preservation.MIGRATION)]
            assert 'ORDER BY row_to_json(t)::text COLLATE "C"' in query
            data = wire_rows(rows)
        else:
            key = next(key for key in self.database.sequences if '"{}"."{}"'.format(*key) in query)
            value, called = self.database.sequences[key]
            if key == preservation.MIGRATION_SEQUENCE:
                assert "last_value - 1 AS last_value,true AS is_called" in query
                value, called = value - 1, True
            data = f"{value}\t{'t' if called else 'f'}\n".encode()
        # Non-row-aligned blocks exercise the real streaming digest/count routine.
        return nullcontext([data[offset : offset + 7] for offset in range(0, len(data), 7)])


class Database:
    def __init__(self):
        row = dict.fromkeys(preservation.COMMUNITY_COLUMNS, "")
        row.update({"id": "synthetic-problem", "title": "PRIVATE SYNTHETIC RECORD", "mohs": 0, "version": 1})
        self.tables = {
            ("public", "pages_communityproblem"): [row],
            ("public", "django_migrations"): [
                {"id": 100, "app": "pages", "name": "0044_learning_page_activity", "applied": "synthetic"},
            ],
            ("public", "users_user"): [{"id": 1, "email": "synthetic@example.invalid"}],
            ("public", "pages_statementreviewpolicy"): [{"enabled": False, "request_budget_micros": 0}],
            ("public", "pages_statementaireview"): [],
            ("other_namespace", "preserved_records"): [{"id": 1, "value": "PRIVATE OTHER NAMESPACE"}],
        }
        self.sequences = {preservation.MIGRATION_SEQUENCE: (100, True), ("public", "users_user_id_seq"): (1, True)}
        self.columns = preservation.COMMUNITY_COLUMNS
        self.executed, self.copied = [], []
        self.identity = ("synthetic", "application_role", "synthetic-cluster", "127.0.0.1", "5432")
        self.metadata = {
            "server_version": 170009,
            "encoding": "UTF8",
            "locale": "en_US.utf8",
            "provider": "c",
            "extensions": {"plpgsql": "1.0"},
            "database_bytes": 123456,
        }

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        return nullcontext()

    def baseline(self):
        return {
            "tables": [
                {"schema": schema, "table": table, **digest(wire_rows(rows))}
                for (schema, table), rows in sorted(self.tables.items())
            ],
            "sequences": [
                {"schema": schema, "sequence": sequence, **digest(f"{value}\t{'t' if called else 'f'}\n".encode())}
                for (schema, sequence), (value, called) in sorted(self.sequences.items())
            ],
            "large_objects": digest(b""),
            "schema_snapshot": {
                "columns": [
                    {"schema": "public", "table": "pages_communityproblem", "position": position, "column": name}
                    for position, name in enumerate(self.columns, 1)
                ],
            },
        }

    def migrate(self):
        self.columns += preservation.NEW_COLUMNS
        for row in self.tables[("public", "pages_communityproblem")]:
            row.update(
                {"embargo_until": None, "legacy_member_visible": True, "public_hint": "", "solution_known": False},
            )
        self.tables[("public", "django_migrations")].append(
            {
                "id": 101,
                "app": "pages",
                "name": preservation.MIGRATION,
                "applied": "new-synthetic",
            },
        )
        for table in preservation.TABLES:
            self.tables[("public", table)] = []
        self.sequences[preservation.MIGRATION_SEQUENCE] = (101, True)
        self.sequences[preservation.NEW_SEQUENCE] = (1, False)


@pytest.fixture
def state():
    database = Database()
    before = database.baseline()
    database.migrate()
    return database, before


def capture(database):
    return {**preservation.capture_preservation(database), "ai_review_disabled": True}


def test_full_records_sequences_and_large_objects_are_preserved(state):
    database, before = state
    after = capture(database)
    result = preservation.compare_preserved(before, after)
    assert result["verified"] is True
    assert result["tables"] == len(before["tables"])
    assert result["sequences"] == len(before["sequences"])
    output = json.dumps(after)
    assert "PRIVATE" not in output
    assert "@example.invalid" not in output
    assert len(after["tables"]) == len(before["tables"]) + 9


@pytest.mark.parametrize("table", ["pages_communityproblem", "users_user", "pages_statementreviewpolicy"])
def test_changes_to_any_prior_record_including_private_and_ai_fields_fail(state, table):
    database, before = state
    row = database.tables[("public", table)][0]
    field, value = {
        "pages_communityproblem": ("title", "changed"),
        "users_user": ("email", "changed@example.invalid"),
        "pages_statementreviewpolicy": ("enabled", True),
    }[table]
    row[field] = value
    with pytest.raises(recovery.RecoveryError, match="existing_records_changed"):
        preservation.compare_preserved(before, capture(database))


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("legacy_member_visible", False),
        ("solution_known", True),
        ("public_hint", "new hint"),
        ("embargo_until", "2099-01-01"),
    ],
)
def test_new_legacy_columns_have_only_the_frozen_values(state, column, value):
    database, _ = state
    database.tables[("public", "pages_communityproblem")][0][column] = value
    with pytest.raises(recovery.RecoveryError, match="legacy_defaults_changed"):
        capture(database)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("new_row", "new_tables_not_empty"),
        ("old_row_added", "existing_records_changed"),
        ("old_row_deleted", "existing_records_changed"),
        ("old_sequence", "existing_sequences_changed"),
        ("new_sequence", "new_sequence_used"),
        ("extra_table", "table_set_changed"),
        ("missing_table", "table_set_changed"),
        ("extra_sequence", "sequence_set_changed"),
        ("other_namespace", "existing_records_changed"),
        ("large_object", "large_objects_changed"),
    ],
)
def test_unrelated_changes_or_initialization_are_rejected(state, mutation, code):  # noqa: C901 - independent forbidden changes
    database, before = state
    if mutation == "new_row":
        database.tables[("public", "pages_communityattempt")] = [{"id": "new-private-draft"}]
    elif mutation == "old_row_added":
        database.tables[("public", "users_user")].append({"id": 2})
    elif mutation == "old_row_deleted":
        database.tables[("public", "users_user")].clear()
    elif mutation == "old_sequence":
        database.sequences[("public", "users_user_id_seq")] = (2, True)
    elif mutation == "new_sequence":
        database.sequences[preservation.NEW_SEQUENCE] = (1, True)
    elif mutation == "extra_table":
        database.tables[("public", "unexpected")] = []
    elif mutation == "missing_table":
        del database.tables[("public", "pages_statementaireview")]
    elif mutation == "extra_sequence":
        database.sequences[("public", "unexpected")] = (1, False)
    elif mutation == "other_namespace":
        database.tables[("other_namespace", "preserved_records")][0]["value"] = "changed"
    after = capture(database)
    if mutation == "large_object":
        after["large_objects"] = digest(b"1\t01\n")
    with pytest.raises(recovery.RecoveryError, match=code):
        preservation.compare_preserved(before, after)


@pytest.mark.parametrize(
    "which", ["duplicate", "missing", "counter_not_advanced", "counter_advanced_twice", "row_id", "uncalled"],
)
def test_only_one_new_migration_row_and_one_counter_increment_are_accepted(state, which):
    database, before = state
    rows = database.tables[("public", "django_migrations")]
    if which == "duplicate":
        rows.append(dict(rows[-1]))
    elif which == "missing":
        rows.pop()
    elif which == "counter_not_advanced":
        rows[-1]["id"] = 100
        database.sequences[preservation.MIGRATION_SEQUENCE] = (100, True)
    elif which == "counter_advanced_twice":
        rows[-1]["id"] = 102
        database.sequences[preservation.MIGRATION_SEQUENCE] = (102, True)
    elif which == "row_id":
        rows[-1]["id"] = 103
    else:
        database.sequences[preservation.MIGRATION_SEQUENCE] = (101, False)
    with pytest.raises(recovery.RecoveryError, match="migration_delta_invalid|existing_sequences_changed"):
        preservation.compare_preserved(before, capture(database))


@pytest.mark.parametrize("which", ["reordered", "extra", "missing"])
def test_community_projection_is_exact_and_physically_ordered(state, which):
    database, _ = state
    if which == "reordered":
        database.columns = ("title", "id", *database.columns[2:])
    elif which == "extra":
        database.columns += ("unexpected",)
    else:
        database.columns = database.columns[1:]
    with pytest.raises(recovery.RecoveryError, match="columns_invalid"):
        capture(database)


class RootPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, value):
        return RootPath(self.path / value)

    def lstat(self):
        value = self.path.lstat()
        return SimpleNamespace(st_uid=0, st_mode=value.st_mode, st_nlink=value.st_nlink)

    def __getattr__(self, name):
        return getattr(self.path, name)


@pytest.fixture
def parent(tmp_path, monkeypatch, state):
    database, before = state
    registry = tmp_path / "registry"
    directory = registry / "recovery/42"
    directory.mkdir(mode=0o700, parents=True)
    identity = "b" * 64
    config = SimpleNamespace(
        os_user="asterproof_audit", expected_role="asterproof_catalog", expected_database_identity_hash=identity,
    )
    receipt = {
        "format_version": 1,
        "run_id": "42",
        "backup_id": "42",
        "source_active_sha": "a" * 40,
        "database_identity_hash": identity,
        "table_manifest_sha256": recovery._sha(before),
        "restore_manifest_sha256": recovery._sha(before),
        "isolated": True,
        "encrypted": True,
        "rpo_seconds": 0,
    }
    for name, value in (("manifest.json", before), ("receipt.json", receipt)):
        path = directory / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(AuditConfig, "load", lambda path: config)
    commands = []
    output = {**capture(database)}

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(output).encode(), stderr=b"not exposed")

    monkeypatch.setattr(preservation.subprocess, "run", run)
    contract = SimpleNamespace(
        registry_dir=RootPath(registry),
        releases_dir=Path("/safe/releases"),
        app_user="asterproof",
        environment_file=Path("/safe/environment"),
    )
    return SimpleNamespace(
        contract=contract,
        directory=directory,
        output=output,
        commands=commands,
        before=before,
        receipt=receipt,
        config=config,
    )


def test_parent_uses_exact_existing_unprivileged_sandbox_command_and_verified_manifest(parent):
    result = preservation.verify_preserved_records(parent.contract, "42", "a" * 40)
    assert result["verified"] is True
    command, options = parent.commands[0]
    expected = recovery._unit_command(parent.contract, "42", "verify", "a" * 40, parent.config)
    index = expected.index("scripts.deployment.database_recovery")
    expected[index] = preservation.MODULE
    assert command == expected
    assert "--uid=asterproof" in command
    assert "--property=NoNewPrivileges=yes" in command
    assert "--property=ProtectSystem=strict" in command
    assert "--property=PrivateTmp=yes" in command
    assert "--property=EnvironmentFile=/safe/environment" in command
    assert "--setenv=DJANGO_READ_DOT_ENV_FILE=false" in command
    assert options == {"capture_output": True, "timeout": 600, "check": False}


@pytest.mark.parametrize(
    "which", ["public_manifest", "symlink", "hardlink", "unverified", "wrong_source", "oversized", "bad_json"],
)
def test_private_verified_baseline_is_required(parent, which):
    manifest, receipt = parent.directory / "manifest.json", parent.directory / "receipt.json"
    if which == "public_manifest":
        manifest.chmod(0o644)
    elif which == "symlink":
        manifest.unlink()
        manifest.symlink_to(receipt)
    elif which == "hardlink":
        (parent.directory / "second-link").hardlink_to(manifest)
    elif which == "oversized":
        manifest.write_bytes(b" " * (recovery.MAX_METADATA_BYTES + 1))
    elif which == "bad_json":
        manifest.write_bytes(b"{ invalid")
    else:
        parent.receipt["restore_manifest_sha256" if which == "unverified" else "source_active_sha"] = "c" * 64
        receipt.write_text(json.dumps(parent.receipt))
    with pytest.raises(recovery.RecoveryError, match="recovery_|community_proof_preservation_"):
        preservation.verify_preserved_records(parent.contract, "42", "a" * 40)
    assert not parent.commands


@pytest.mark.parametrize(
    ("key", "value"), [("ai_review_disabled", False), ("migration_rows", True), ("legacy_default_violations", False)],
)
def test_parent_does_not_trust_malformed_or_unsafe_child_metadata(parent, key, value):
    parent.output[key] = value
    with pytest.raises(recovery.RecoveryError):
        preservation.verify_preserved_records(parent.contract, "42", "a" * 40)


@pytest.mark.parametrize("sha", ["../../etc", "a" * 39, "A" * 40, "a" * 40 + "/other"])
def test_runtime_target_sha_cannot_escape_the_verified_active_release(parent, sha):
    with pytest.raises(recovery.RecoveryError, match="active_sha_invalid"):
        preservation.verify_preserved_records(parent.contract, "42", sha)
    assert not parent.commands


def test_unsafe_child_arguments_and_root_execution_fail_before_django_setup(monkeypatch):
    import django

    monkeypatch.setattr(django, "setup", lambda: pytest.fail("Django must not be initialized"))
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 0)
    args = SimpleNamespace(action="verify", identity="b" * 64, audit_role="catalogue")
    with pytest.raises(recovery.RecoveryError, match="unprivileged"):
        preservation._source_cli(args)
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 1000)
    for changes in ({"identity": "invalid"}, {"audit_role": "role;SELECT secret"}, {"action": "source"}):
        with pytest.raises(recovery.RecoveryError, match="identity_arguments_invalid"):
            preservation._source_cli(SimpleNamespace(**{**vars(args), **changes}))


def test_cli_rejects_sql_files_restore_and_abbreviated_options():
    for arguments in (
        ["restore", "--scratch", "/unreviewed/restore"],
        ["verify", "--identity", "b" * 64, "--audit-role", "catalogue", "--sql", "SELECT 1"],
        ["verify", "--ident", "b" * 64, "--audit-role", "catalogue"],
    ):
        with pytest.raises(SystemExit):
            preservation.main(arguments)


@pytest.mark.parametrize("enabled_flag", [None, "PROBLEM_STATEMENT_AI_REVIEW_ENABLED", "SOLUTION_AI_REVIEW_ENABLED"])
def test_source_uses_verified_identity_readonly_bounds_and_no_other_clients(
    state, settings, monkeypatch, capsys, enabled_flag,
):
    import django
    import django.db

    database, _ = state
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(django, "setup", lambda: None)
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    if enabled_flag:
        setattr(settings, enabled_flag, True)
    wrapper = SimpleNamespace(vendor="postgresql", connection=database, ensure_connection=lambda: None)
    monkeypatch.setattr(django.db, "connection", wrapper)
    isolation = []
    monkeypatch.setattr(recovery, "_assert_no_other_clients", lambda raw, role: isolation.append((raw, role)))
    identity = list(database.identity)
    identity[1] = "catalogue"
    args = SimpleNamespace(action="verify", identity=recovery._sha(identity), audit_role="catalogue")
    if enabled_flag:
        with pytest.raises(recovery.RecoveryError, match="ai_review_not_disabled"):
            preservation._source_cli(args)
        assert not database.executed
        return
    preservation._source_cli(args)
    result = json.loads(capsys.readouterr().out)
    assert result["ai_review_disabled"] is True
    assert isolation == [(database, "catalogue"), (database, "catalogue")]
    assert database.executed[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "SET LOCAL statement_timeout='120s'" in database.executed
    assert "SET LOCAL lock_timeout='2s'" in database.executed
    assert "PRIVATE" not in json.dumps(result)


def test_source_refuses_identity_drift_before_copying_rows(state, settings, monkeypatch):
    import django
    import django.db

    database, _ = state
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(
        django.db,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            connection=database,
            ensure_connection=lambda: None,
        ),
    )
    with pytest.raises(recovery.RecoveryError, match="source_identity_mismatch"):
        preservation._source_cli(SimpleNamespace(action="verify", identity="0" * 64, audit_role="catalogue"))
    assert not database.copied


def test_schema_constants_match_the_frozen_allowance():
    from scripts.deployment import community_proof_schema

    assert preservation.NEW_COLUMNS == community_proof_schema.NEW_COLUMNS
    assert preservation.TABLES == community_proof_schema.TABLES


@pytest.mark.parametrize(("key", "value"), [
    ("server_version", 170008), ("locale", "unreviewed-locale"), ("provider", "i"),
    ("database_bytes", recovery.MAX_SOURCE_BYTES + 1), ("extensions", {"unreviewed_extension": "1"}),
])
def test_source_metadata_scope_is_checked_before_any_record_copy(state, settings, monkeypatch, key, value):
    import django
    import django.db

    database, _ = state
    database.metadata[key] = value
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    monkeypatch.setattr(preservation.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(django.db, "connection", SimpleNamespace(
        vendor="postgresql", connection=database, ensure_connection=lambda: None,
    ))
    identity = list(database.identity)
    identity[1] = "catalogue"
    with pytest.raises(recovery.RecoveryError, match="metadata_outside_reviewed_scope"):
        preservation._source_cli(SimpleNamespace(
            action="verify", identity=recovery._sha(identity), audit_role="catalogue",
        ))
    assert not database.copied


@pytest.mark.parametrize("which", [
    "duplicate", "unhashed_rows", "invalid_digest", "oversized", "invalid_json", "failed",
])
def test_parent_rejects_unbounded_or_unexpected_child_protocol(parent, monkeypatch, which):
    if which == "duplicate":
        parent.output["tables"].append(dict(parent.output["tables"][0]))
    elif which == "unhashed_rows":
        parent.output["tables"][0]["private_rows"] = []
    elif which == "invalid_digest":
        parent.output["tables"][0]["sha256"] = "not a digest"
    else:
        data = b" " * (recovery.MAX_METADATA_BYTES + 1) if which == "oversized" else b"not JSON"
        monkeypatch.setattr(preservation.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
            returncode=1 if which == "failed" else 0, stdout=data, stderr=b"private error details",
        ))
    with pytest.raises(recovery.RecoveryError, match="metadata_|source_failed") as error:
        preservation.verify_preserved_records(parent.contract, "42", "a" * 40)
    assert "private error details" not in str(error.value)


def test_cli_never_prints_server_exception_details(monkeypatch, capsys):
    def fail(_args):
        raise RuntimeError("PRIVATE DATABASE URL OR RECORD")

    monkeypatch.setattr(preservation, "_source_cli", fail)
    assert preservation.main(["verify", "--identity", "b" * 64, "--audit-role", "catalogue"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "community_proof_preservation_subprocess_failed_RuntimeError\n"
