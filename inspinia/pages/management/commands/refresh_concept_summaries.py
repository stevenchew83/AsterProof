"""Refresh derived memberships without changing any source/user record."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.pages.catalogue_models import ConceptLibrarySnapshot
from inspinia.pages.catalogue_models import UserConceptProgressSummary
from inspinia.pages.catalogue_snapshots import SnapshotChangedError
from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.catalogue_snapshots import user_progress_summary
from inspinia.users.models import User


class Command(BaseCommand):
    help = "Publish catalogue problem memberships and optionally warm per-user progress summaries."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Rebuild even if the published revision is current.")
        parser.add_argument("--user-id", type=int, action="append", default=[])
        parser.add_argument("--all-users", action="store_true", help="Warm users with existing completion records.")

    def handle(self, *args, **options):
        if options["all_users"] and options["user_id"]:
            message = "Choose --all-users or --user-id."
            raise CommandError(message)
        if any(pk < 1 for pk in options["user_id"]):
            message = "User IDs must be positive integers."
            raise CommandError(message)
        try:
            snapshot = rebuild_library_snapshot(force=options["force"])
            users = User.objects.none()
            if options["all_users"]:
                users = User.objects.filter(is_active=True, problem_completions__isnull=False).distinct()
            elif options["user_id"]:
                users = User.objects.filter(pk__in=options["user_id"])
            for user in users.iterator():
                user_progress_summary(user, snapshot)
            retained = list(ConceptLibrarySnapshot.objects.order_by("-created_at").values_list("pk", flat=True)[:2])
            # Only disposable projections are pruned. Original completions,
            # problem identities and reviewed assignments are never deleted here.
            ConceptLibrarySnapshot.objects.exclude(pk__in=[snapshot.pk, *retained]).delete()
            for uid in (
                UserConceptProgressSummary.objects.filter(snapshot=snapshot)
                .values_list("user_id", flat=True)
                .distinct()
            ):
                summaries = UserConceptProgressSummary.objects.filter(snapshot=snapshot, user_id=uid)
                keep = list(summaries.order_by("-created_at", "-pk").values_list("pk", flat=True)[:2])
                summaries.exclude(pk__in=keep).delete()
        except SnapshotChangedError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Published catalogue summary {snapshot.pk} (revision {snapshot.source_revision})."),
        )
