from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Placeholder for catalog backfill pipeline."

    def handle(self, *args, **options):  # noqa: ANN002, ANN003
        self.stdout.write(self.style.WARNING("Backfill command scaffolded. Implement source import adapters next."))
