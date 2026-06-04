"""Backfill user completions across exact duplicate statement rows."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from inspinia.pages.completion_duplicates import backfill_exact_duplicate_statement_completions


class Command(BaseCommand):
    help = (
        "Create missing statement-backed user completions for exact duplicate problem statements. "
        "Existing completion rows are left unchanged."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be created without inserting them.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = bool(options["dry_run"])
        result = backfill_exact_duplicate_statement_completions(dry_run=dry_run)
        prefix = "Dry run. " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Created {result.created_count} duplicate completion row(s). "
                f"Scanned {result.scanned_completion_count} solved completion row(s); "
                f"{result.eligible_source_count} had exact duplicate statement target(s); "
                f"{result.existing_count} target row(s) already existed.",
            ),
        )
