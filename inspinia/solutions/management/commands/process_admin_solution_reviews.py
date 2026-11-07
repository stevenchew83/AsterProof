"""Run as a bounded background task; never invoked by a dashboard GET."""

import json
import signal

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.solutions.admin_review_worker import process_next


class WorkerDeadline(BaseException):
    """Bypass provider and mail handlers so the durable claim can be reconciled."""


def _deadline(_signum, _frame):
    raise WorkerDeadline


class Command(BaseCommand):
    help = "Process one admin AI solution review or send one published-review email."

    def handle(self, *args, **options):
        previous = signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(300)
        try:
            self.stdout.write(json.dumps(process_next()))
        except WorkerDeadline:
            message = "The worker timed out. The claimed operation will not be retried automatically."
            raise CommandError(message) from None
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
