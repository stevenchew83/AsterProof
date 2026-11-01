"""Bounded explicit maintenance; retained content is never a cleanup target."""

import json

from django.core.management.base import BaseCommand

from inspinia.learning.assets import cleanup_assets


class Command(BaseCommand):
    help = "Inspect unreferenced learning assets older than seven days. Defaults to a read-only dry run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Tombstone and remove only eligible unreferenced files.",
        )
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(cleanup_assets(dry_run=not options["apply"], limit=options["limit"])))
