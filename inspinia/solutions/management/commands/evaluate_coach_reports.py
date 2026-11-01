"""Score external reports locally; no provider calls or approval promotion."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.solutions.coach_evaluation import CoachEvaluationError
from inspinia.solutions.coach_evaluation import evaluate_reports
from inspinia.solutions.coach_evaluation import load_json_file


class Command(BaseCommand):
    help = "Evaluate externally supplied AI reports against explicitly coach-approved labels. No API calls."

    def add_arguments(self, parser):
        parser.add_argument("--cases", type=Path, required=True)
        parser.add_argument("--reports", type=Path, required=True)
        parser.add_argument("--split", choices=["development", "held_out"], default="held_out")

    def handle(self, *args, **options):
        try:
            result = evaluate_reports(
                load_json_file(options["cases"]),
                load_json_file(options["reports"]),
                split=options["split"],
            )
        except (CoachEvaluationError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, sort_keys=True))
        if not result["release_gate_passed"] and options["split"] == "held_out":
            message = "The held-out coaching quality gate did not pass."
            raise CommandError(message)
