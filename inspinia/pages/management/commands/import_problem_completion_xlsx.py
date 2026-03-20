"""Import user problem completion dates from an Excel workbook."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.problem_completion_import import completion_dataframe_from_excel
from inspinia.pages.problem_completion_import import import_problem_completion_dataframe
from inspinia.pages.problem_import import ProblemImportValidationError


class Command(BaseCommand):
    help = (
        "Import user problem completion dates from XLSX. Required columns: USER EMAIL and "
        "COMPLETION DATE. Match problems by PROBLEM UUID when present, otherwise by "
        "YEAR+CONTEST+PROBLEM or CONTEST PROBLEM."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("xlsx_path", type=str, help="Path to .xlsx file")

    def handle(self, *args, **options) -> None:
        path = Path(options["xlsx_path"]).expanduser().resolve()
        if not path.is_file():
            msg = f"File not found: {path}"
            raise CommandError(msg)

        try:
            dataframe = completion_dataframe_from_excel(path)
        except ProblemImportValidationError as exc:
            raise CommandError(str(exc)) from exc

        result = import_problem_completion_dataframe(dataframe)

        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(warning))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Upserted {result.n_completions} user problem completion row(s).",
            ),
        )
