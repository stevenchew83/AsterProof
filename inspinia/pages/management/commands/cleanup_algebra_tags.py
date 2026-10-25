"""Default-read-only, immutable-review algebra cleanup command."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import connection
from django.db import transaction

from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_aliases import load_policy
from inspinia.pages.algebra_tag_cleanup import build_cleanup_report
from inspinia.pages.algebra_tag_cleanup_db import apply_reviewed_report
from inspinia.pages.algebra_tag_cleanup_db import capture_snapshot

DEFAULT_PLAN = Path(__file__).resolve().parents[2] / "data" / "algebra_cleanup_review_v1.json"


class Command(BaseCommand):
    help = (
        "Dry-run the reviewed algebra cleanup. Apply requires an immutable reviewed report and a new audit directory."
    )
    requires_system_checks = []
    report_builder = staticmethod(build_cleanup_report)

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
        parser.add_argument("--report", type=Path, help="New output JSON file; never overwritten.")
        parser.add_argument(
            "--snapshot-input",
            type=Path,
            help="Read captured evidence instead of the database; dry-run only.",
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--review-report", type=Path)
        parser.add_argument("--expected-report-sha256")
        parser.add_argument("--audit-directory", type=Path)

    def handle(self, *args, **options) -> None:
        try:
            self._run(options)
        except (AlgebraAliasError, OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc

    def load_operation(self, options: dict) -> tuple:
        plan_bytes = options["plan"].read_bytes()
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        policy = load_policy()
        if plan_sha != policy["reviewed_plan_sha256"]:
            message = "The plan hash does not match the packaged reviewed policy."
            raise AlgebraAliasError(message)
        plan = json.loads(plan_bytes)
        return plan, policy, plan_sha

    def report_summary(self, report: dict) -> dict:
        return {
            "mode": "dry-run", "counts": report["counts"], "alias_actions":len(report["alias_actions"]),
            "conflicts": report["conflicts"],
        }

    def _run(self, options: dict) -> None:
        plan, policy, plan_sha = self.load_operation(options)
        if options["apply"]:
            if options["snapshot_input"]:
                message = "Captured snapshots can never authorize or execute application."
                raise AlgebraAliasError(message)
            if not all(options.get(k) for k in ("review_report", "expected_report_sha256", "audit_directory")):
                message = "Apply requires --review-report, --expected-report-sha256, and --audit-directory."
                raise AlgebraAliasError(message)
            reviewed_bytes = options["review_report"].read_bytes()
            if hashlib.sha256(reviewed_bytes).hexdigest() != options["expected_report_sha256"]:
                message = "The reviewed report SHA-256 does not match."
                raise AlgebraAliasError(message)
            receipt = apply_reviewed_report(
                json.loads(reviewed_bytes),
                plan,
                policy=policy,
                plan_sha256=plan_sha,
                audit_directory=options["audit_directory"],
                report_builder=self.report_builder,
            )
            self.stdout.write(json.dumps(receipt))
            return
        if options["snapshot_input"]:
            snapshot = json.loads(options["snapshot_input"].read_bytes())
            report = self.report_builder(snapshot, plan, policy=policy, plan_sha256=plan_sha)
        else:
            with transaction.atomic():
                if connection.vendor == "postgresql":
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        cursor.execute("SET LOCAL statement_timeout = '15s'")
                report = self.report_builder(capture_snapshot(plan), plan, policy=policy, plan_sha256=plan_sha)
        if options["report"]:
            # Refuse reuse so the reviewed artifact cannot silently change.
            with options["report"].open("x") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False, default=str)
                handle.write("\n")
        self.stdout.write(json.dumps(self.report_summary(report)))
