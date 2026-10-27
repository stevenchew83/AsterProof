"""Production freshness check: default and only mode is read-only dry run."""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.concept_assignment_bulk import BulkReviewError
from inspinia.pages.concept_assignment_bulk import check_live_packet
from inspinia.pages.concept_assignment_bulk import read_document
from inspinia.pages.concept_assignment_bulk import write_document


class Command(BaseCommand):
    help = "Read-only live validation of a reviewed packet. This command has no --apply option."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--packet", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args, **options):
        try:
            report = check_live_packet(read_document(options["packet"]))
            write_document(options["output"], report)
        except (BulkReviewError, ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Live dry run: {report['row_changes']} proposed changes; {len(report['conflicts'])} conflicts; writes 0.",
        )
        if report["conflicts"]:
            message = (
                "Production differs or decisions conflict; review the report before generating any apply preview."
            )
            raise CommandError(message)
