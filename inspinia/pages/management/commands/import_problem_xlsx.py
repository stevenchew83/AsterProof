"""Import problem analytics rows (+ parsed topic techniques) from an Excel workbook."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe


class Command(BaseCommand):
    help = (
        "Import rows from the analytics XLSX (headers: YEAR, TOPIC, MOHS, CONTEST, PROBLEM, "
        "CONTEST PROBLEM, ... Topic tags, ...). Upserts ProblemSolveRecord and topic techniques."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("xlsx_path", type=str, help="Path to .xlsx file")
        parser.add_argument(
            "--replace-tags",
            action="store_true",
            help="Delete existing ProblemTopicTechnique rows for each updated record before insert.",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["xlsx_path"]).expanduser().resolve()
        if not path.is_file():
            msg = f"File not found: {path}"
            raise CommandError(msg)

        try:
            dataframe = dataframe_from_excel(path)
        except ProblemImportValidationError as exc:
            raise CommandError(str(exc)) from exc

        replace_tags: bool = options["replace_tags"]
        result = import_problem_dataframe(dataframe, replace_tags=replace_tags)

        for w in result.warnings:
            self.stdout.write(self.style.WARNING(w))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Upserted {result.n_records} problem record(s); "
                f"touched {result.n_techniques} technique row(s).",
            ),
        )
