import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.website.automation import MAX_MESSAGES
from inspinia.website.automation import MAX_SECONDS
from inspinia.website.automation import process_queue


class Command(BaseCommand):
    help = "Process one bounded newsletter queue batch. This command can send real email."

    def add_arguments(self, parser):
        parser.add_argument("--max-messages", type=int, default=20)
        parser.add_argument("--seconds", type=int, default=50)

    def handle(self, *args, **options):
        if not 1 <= options["max_messages"] <= MAX_MESSAGES or not 1 <= options["seconds"] <= MAX_SECONDS:
            msg = "Use 1-20 messages and a 1-50 second processing window."
            raise CommandError(msg)
        try:
            result = process_queue(maximum=options["max_messages"], seconds=options["seconds"])
        except ValidationError as error:
            msg = "Background newsletter sending is disabled."
            raise CommandError(msg) from error
        self.stdout.write(json.dumps(result))
        if result["state"] == "failed":
            msg = "Newsletter worker failed; inspect the private backend worker status."
            raise CommandError(msg)
