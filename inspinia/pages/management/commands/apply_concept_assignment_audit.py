import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.concept_assignment_service import AssignmentConflictError
from inspinia.pages.concept_assignment_service import apply_refresh


class Command(BaseCommand):
    help = "Apply one frozen assignment-only audit batch; requires an exact file hash and operation ID."

    def add_arguments(self, parser):
        parser.add_argument("--report", type=Path, required=True)
        parser.add_argument("--expected-report-sha256", required=True)
        parser.add_argument("--operation-id", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        content = options["report"].read_bytes()
        if hashlib.sha256(content).hexdigest() != options["expected_report_sha256"]:
            message = "Report file hash does not match."
            raise CommandError(message)
        report = json.loads(content)
        if not options["apply"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "changes": len(report["changes"]),
                        "conflicts": report["conflicts"],
                        "source_writes": 0,
                    },
                ),
            )
            return
        try:
            receipt = apply_refresh(report, operation_id=options["operation_id"])
        except AssignmentConflictError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(receipt))
