"""Audit and apply exactly the owner-reviewed Algebra concept normalization."""

from inspinia.pages.algebra_concept_cleanup import PLAN_PATH
from inspinia.pages.algebra_concept_cleanup import build_concept_cleanup_report
from inspinia.pages.algebra_concept_cleanup import load_reviewed_operation
from inspinia.pages.management.commands.cleanup_algebra_tags import Command as ReviewedCleanupCommand


class Command(ReviewedCleanupCommand):
    help = "Dry-run or audit/apply the frozen 180-concept normalization; excluded mappings are unchanged."
    report_builder = staticmethod(build_concept_cleanup_report)

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.set_defaults(plan=PLAN_PATH)

    def load_operation(self, options):
        if options["plan"].resolve() != PLAN_PATH.resolve():
            from inspinia.pages.algebra_tag_aliases import AlgebraAliasError

            message = "Only the packaged owner-reviewed concept normalization is allowed."
            raise AlgebraAliasError(message)
        return load_reviewed_operation()
