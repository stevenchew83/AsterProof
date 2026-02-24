from django.core.management import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Apply Part B migrations safely with --fake-initial support for pre-existing tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print commands without executing migrations.",
        )

    def handle(self, *args, **options):  # noqa: ANN002, ANN003
        apps = [
            "users",
            "catalog",
            "progress",
            "notes",
            "community",
            "organization",
            "feedback",
            "contests",
            "backoffice",
        ]
        for app_label in apps:
            self.stdout.write(self.style.NOTICE(f"migrate {app_label} --fake-initial"))
            if not options["dry_run"]:
                call_command("migrate", app_label, fake_initial=True)

        self.stdout.write(self.style.SUCCESS("Part B migration routine complete."))
