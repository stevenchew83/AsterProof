"""Offline review, exact row CSV, and frozen bounded manifests without database reads."""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.concept_assignment_bulk import BulkReviewError
from inspinia.pages.concept_assignment_bulk import make_packet
from inspinia.pages.concept_assignment_bulk import read_document
from inspinia.pages.concept_assignment_bulk import review_packet
from inspinia.pages.concept_assignment_bulk import write_document
from inspinia.pages.concept_assignment_views import _safe_csv


class Command(BaseCommand):
    help = "Pure local dry run from a snapshot plus explicit decisions; no local database import needed."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--decisions", type=Path, required=True)
        parser.add_argument("--protected-keys", type=Path)
        parser.add_argument("--output-directory", type=Path, required=True)

    def handle(self, *args, **options):
        try:
            snapshot = read_document(options["snapshot"])
            protected = read_document(options["protected_keys"]) if options["protected_keys"] else []
            packet = make_packet(snapshot, read_document(options["decisions"]), protected)
            report = review_packet(snapshot, packet)
            directory = options["output_directory"]
            directory.mkdir(mode=0o700, parents=False, exist_ok=False)
            write_document(directory / "review-packet.json", packet)
            write_document(directory / "dry-run.json", report)
            # No executable batch files are emitted when any conflict exists.
            for index, batch in enumerate(report["batches"], 1):
                write_document(directory / f"decisions-{index:03}.json", batch["decisions"])
            with (directory / "row-changes.csv").open("x", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Problem UUID", "Concept ID", "Before", "After", "Roles", "Rationale"])
                for batch in report["batches"]:
                    for row in batch["changes"]:
                        writer.writerow(
                            [
                                _safe_csv(value)
                                for value in (
                                    row["problem_uuid"],
                                    row["concept_id"],
                                    row["before"].get("disposition", "No decision"),
                                    row["after"]["disposition"],
                                    ", ".join(row["after"]["roles"]),
                                    row["after"]["rationale"],
                                )
                            ],
                        )
        except (BulkReviewError, ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Dry run: {report['decision_count']} decisions, {report['row_changes']} row changes, "
            f"{len(report['conflicts'])} conflicts; writes 0.",
        )
        if report["conflicts"]:
            message = "Review conflicts in dry-run.json; no executable decision batches were emitted."
            raise CommandError(message)
