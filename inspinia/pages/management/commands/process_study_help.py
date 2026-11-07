"""Process at most one pending archive assistance request."""

from django.core.management.base import BaseCommand

from inspinia.pages.study_help_worker import process_next


class Command(BaseCommand):
    help = "Reap expired Study Help requests and process at most one pending request."

    def handle(self, *args, **options):
        self.stdout.write(process_next())
