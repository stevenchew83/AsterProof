import json

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.concept_assignment_service import AssignmentConflictError
from inspinia.pages.concept_assignment_service import activate_projection
from inspinia.pages.concept_assignment_service import verify_seed
from inspinia.pages.models import ConceptAssignmentState


class Command(BaseCommand):
    help = "Verify the complete seed read-only; activation/deactivation requires an exact verification hash."

    def add_arguments(self, parser):
        parser.add_argument("--disable", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-verification-sha256")
        parser.add_argument("--operation-id")

    def handle(self, *args, **options):
        if options["disable"]:
            state = ConceptAssignmentState.objects.filter(singleton_key=1).first()
            verification = {"revision": state.revision if state else 0, "enabled": bool(state and state.enabled)}
        else:
            verification = verify_seed()
        if not options["apply"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "verification": verification,
                        "sha256": digest(verification),
                        "source_writes": 0,
                    },
                ),
            )
            return
        if not options["expected_verification_sha256"] or not options["operation_id"]:
            message = "Apply needs an exact verification hash and unique operation ID."
            raise CommandError(message)
        try:
            receipt = activate_projection(
                options["expected_verification_sha256"],
                enable=not options["disable"],
                operation_id=options["operation_id"],
            )
        except AssignmentConflictError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(receipt))
