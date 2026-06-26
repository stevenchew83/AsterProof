from __future__ import annotations

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.pages.technique_progress_catalog import technique_progress_catalog_needs_rebuild

CATALOG_REBUILD_LOCK_KEY = "technique-progress-catalog-rebuild-lock:v1"
CATALOG_REBUILD_LOCK_TIMEOUT_SECONDS = 30 * 60


class Command(BaseCommand):
    help = "Recompute technique progress catalog facts for all statements or a targeted statement/problem scope."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--statement-id",
            action="append",
            dest="statement_ids",
            type=int,
            help="ContestProblemStatement ID to recompute. May be passed multiple times.",
        )
        parser.add_argument(
            "--problem-id",
            action="append",
            dest="problem_ids",
            type=int,
            help="ProblemSolveRecord ID whose linked statements should be recomputed. May be passed multiple times.",
        )
        parser.add_argument(
            "--if-stale",
            action="store_true",
            dest="if_stale",
            help="Only run a full rebuild when the catalog is stale or missing.",
        )

    def handle(self, *args, **options) -> None:
        statement_ids = options.get("statement_ids") or []
        problem_ids = options.get("problem_ids") or []
        invalid_ids = [
            value
            for value in [*statement_ids, *problem_ids]
            if value < 1
        ]
        if invalid_ids:
            msg = "--statement-id and --problem-id values must be positive integers."
            raise CommandError(msg)
        if options.get("if_stale") and not statement_ids and not problem_ids:
            if not technique_progress_catalog_needs_rebuild():
                self.stdout.write("Technique progress catalog is already current; skipping rebuild.")
                return

        if not cache.add(CATALOG_REBUILD_LOCK_KEY, "1", timeout=CATALOG_REBUILD_LOCK_TIMEOUT_SECONDS):
            self.stdout.write("Technique progress catalog rebuild is already running; skipping rebuild.")
            return

        try:
            refreshed_count = rebuild_technique_progress_catalog(
                statement_ids=statement_ids,
                problem_ids=problem_ids,
            )
            total_count = TechniqueProgressFact.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    "Recomputed technique progress catalog: "
                    f"refreshed {refreshed_count} fact(s), stored {total_count} fact(s).",
                ),
            )
        finally:
            cache.delete(CATALOG_REBUILD_LOCK_KEY)
