"""Read-only baseline inventory for Training 2.0 mapping review."""

import json

from django.core.management.base import BaseCommand

from inspinia.training.curriculum_audit import audit_learning_scope


class Command(BaseCommand):
    help = "Inspect canonical and legacy curriculum identities without changing any rows."

    def add_arguments(self, parser):
        parser.add_argument("--area", dest="area_id")
        parser.add_argument("--subject", dest="subject_id")
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        result = audit_learning_scope(
            area_id=options["area_id"], subject_id=options["subject_id"], limit=options["limit"],
        )
        self.stdout.write(json.dumps(result, sort_keys=True, indent=2, default=str))
