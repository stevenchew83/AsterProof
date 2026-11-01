"""Explicit capability appointment through the same audited service as the workspace."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.solutions.evaluation import EvaluationError
from inspinia.solutions.evaluation import grant


class Command(BaseCommand):
    help = "Appoint a scoped evaluation capability. Writes assignments; never enables AI or contacts a provider."

    def add_arguments(self, parser):
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--user", type=int, required=True)
        parser.add_argument("--role", required=True)
        parser.add_argument("--scope", required=True)
        parser.add_argument("--expertise", default="")

    def handle(self, **options):
        users = get_user_model()
        try:
            item = grant(
                users.objects.get(pk=options["actor"]),
                users.objects.get(pk=options["user"]),
                options["role"],
                options["scope"],
                expertise=options["expertise"],
            )
        except (EvaluationError, users.DoesNotExist, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"Recorded appointment {item.pk}. AI execution remains disabled.")
