from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog


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
