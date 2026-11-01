from django.core.checks import Tags
from django.core.management.base import BaseCommand

from inspinia.pages.statement_reviews import process_statement_review


class Command(BaseCommand):
    help = "Process one explicitly queued community statement AI review; never retries dispatched requests."
    requires_system_checks = [Tags.models]

    def handle(self, *args, **options):
        self.stdout.write(process_statement_review())
