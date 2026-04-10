from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db.models import Prefetch

from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.ranking_compute import compute_rank_rows
from inspinia.rankings.services.ranking_snapshot_store import clear_ranking_snapshots
from inspinia.rankings.services.ranking_snapshot_store import lock_formula_for_snapshot_refresh
from inspinia.rankings.services.ranking_snapshot_store import store_ranking_snapshots


class Command(BaseCommand):
    help = "Recompute ranking snapshots for one formula, a season/division scope, or all active formulas."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--formula", type=int, help="RankingFormula ID to recompute.")
        parser.add_argument("--season", type=int, help="Season year to recompute.")
        parser.add_argument("--division", type=str, help="Division to recompute within a season.")

    def handle(self, *args, **options) -> None:
        formula_id = options.get("formula")
        season_year = options.get("season")
        division = options.get("division")

        if formula_id is not None and formula_id < 1:
            msg = "--formula must be a positive integer."
            raise CommandError(msg)
        if formula_id is not None and (season_year is not None or division):
            msg = "--formula cannot be combined with --season or --division."
            raise CommandError(msg)
        if division and season_year is None:
            msg = "--division requires --season."
            raise CommandError(msg)

        formulas = list(self._get_formulas(formula_id=formula_id, season_year=season_year, division=division))
        if formula_id is not None and not formulas:
            msg = f"RankingFormula {formula_id} does not exist."
            raise CommandError(msg)

        snapshot_count = 0
        recomputed_formula_count = 0
        for formula in formulas:
            with lock_formula_for_snapshot_refresh(formula_id=formula.id) as locked_formula:
                if not locked_formula.items.exists():
                    deleted_count = clear_ranking_snapshots(
                        formula=locked_formula,
                        formula_locked=True,
                    )
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped RankingFormula {locked_formula.id} ({locked_formula.name}): "
                            f"no formula items configured; cleared {deleted_count} existing snapshot(s).",
                        ),
                    )
                    continue

                students = self._get_students_for_formula(locked_formula)
                rows = compute_rank_rows(formula=locked_formula, students=students)
                snapshot_count += store_ranking_snapshots(
                    formula=locked_formula,
                    rows=rows,
                    formula_locked=True,
                )
            recomputed_formula_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Recomputed {recomputed_formula_count} formula(s), stored {snapshot_count} snapshot(s).",
            ),
        )

    def _get_formulas(
        self,
        *,
        formula_id: int | None,
        season_year: int | None,
        division: str | None,
    ):
        if formula_id is not None:
            return RankingFormula.objects.filter(pk=formula_id).order_by("season_year", "division", "id")

        queryset = RankingFormula.objects.filter(is_active=True)
        if season_year is not None:
            queryset = queryset.filter(season_year=season_year)
        if division:
            queryset = queryset.filter(division=division.strip())
        return queryset.order_by("season_year", "division", "id")

    def _get_students_for_formula(self, formula: RankingFormula):
        assessment_ids = list(
            formula.items.order_by("sort_order", "id").values_list("assessment_id", flat=True),
        )
        results_queryset = StudentResult.objects.filter(
            assessment_id__in=assessment_ids,
        ).order_by("assessment_id", "id")
        return Student.objects.filter(active=True).prefetch_related(
            Prefetch("results", queryset=results_queryset),
        )
