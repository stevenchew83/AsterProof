"""One consistent source/assignment snapshot; never copies the complete database."""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.concept_assignment_bulk import SUBJECTS
from inspinia.pages.concept_assignment_bulk import BulkReviewError
from inspinia.pages.concept_assignment_bulk import capture_snapshot
from inspinia.pages.concept_assignment_bulk import write_document


class Command(BaseCommand):
    help = "Read-only scoped snapshot with published evidence and exact assignment before-images."
    requires_system_checks = []

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--subject", choices=SUBJECTS)
        group.add_argument("--problem-uuid", action="append")
        parser.add_argument("--year", default="")
        parser.add_argument("--contest", default="")
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args, **options):
        scope = {"subject": options["subject"], "year": options["year"], "contest": options["contest"]}
        if options["problem_uuid"]:
            scope = {"problem_uuids": options["problem_uuid"], "year": options["year"], "contest": options["contest"]}
        try:
            snapshot = capture_snapshot(scope)
            write_document(options["output"], snapshot)
        except (BulkReviewError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Exported {snapshot['counts']['problems']} problems; SHA-256 {snapshot['sha256']}; source writes 0.",
        )
