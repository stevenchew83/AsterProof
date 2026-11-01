from django.core.checks import Tags
from django.core.management.base import BaseCommand

from inspinia.pages.statement_similarity import rebuild_similarity_index


class Command(BaseCommand):
    help = "Build the indexed library search used before community problem submission."
    requires_system_checks = [Tags.models]

    def handle(self, *args, **options):
        count = rebuild_similarity_index()
        self.stdout.write(f"Similarity index ready; indexed {count} statements (0 means already current).")
