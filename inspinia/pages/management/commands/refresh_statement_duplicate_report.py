"""Independent, bounded duplicate analysis; catalogue maintenance never calls it."""

from django.core.cache import cache
from django.core.checks import Tags
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.statement_duplicate_snapshot import DEFAULT_BUILD_SECONDS
from inspinia.pages.statement_duplicate_snapshot import MANIFEST_KEY
from inspinia.pages.statement_duplicate_snapshot import refresh_statement_duplicate_snapshot
from inspinia.pages.statement_duplicate_snapshot import retain_statement_duplicate_snapshot


class Command(BaseCommand):
    help = "Publish a duplicate-statement report independently of catalogue/progress refresh."
    requires_system_checks = [Tags.models]

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--force", action="store_true", help="Refresh even when the previous report is current.")
        mode.add_argument(
            "--retain-current", action="store_true",
            help="Only renew the complete existing cache; never run analysis.",
        )

    def handle(self, *args, **options):
        if options["retain_current"]:
            retained = retain_statement_duplicate_snapshot()
            self.stdout.write(
                "Retained complete existing duplicate report." if retained else "No complete report to retain.",
            )
            return
        try:
            refreshed = refresh_statement_duplicate_snapshot(
                force=options["force"],
                max_seconds=DEFAULT_BUILD_SECONDS,
            )
        except Exception as exc:  # Fail the job without exposing database/statement details.
            message = f"Duplicate report refresh failed ({type(exc).__name__}); previous publication retained."
            raise CommandError(message) from exc
        if not refreshed:
            self.stdout.write("Duplicate report is current, busy, or its sources changed; no new report published.")
            return
        report = cache.get(MANIFEST_KEY)
        if report is None:
            message = "Published duplicate report could not be read back."
            raise CommandError(message)
        self.stdout.write(
            "Refreshed statement duplicate report: "
            f"{report['statement_total']} statements, {report['exact_duplicate_group_total']} exact groups, "
            f"{report['similar_pair_total']} similar pairs, {report['build_seconds']} seconds.",
        )
