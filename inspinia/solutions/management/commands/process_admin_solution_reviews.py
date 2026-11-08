"""Run as a bounded background task; never invoked by a dashboard GET."""

import json
import signal
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import django
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.db import connections

from inspinia.solutions import admin_review_worker as worker

JOB_DEADLINE_SECONDS = 300


class WorkerDeadline(BaseException):
    """Bypass provider and mail handlers so the durable claim can be reconciled."""


def _deadline(_signum, _frame):
    raise WorkerDeadline


def _process_claim(review_id, *, notification=False):
    # Each process can enforce its own deadline without interrupting other jobs.
    close_old_connections()
    previous = signal.signal(signal.SIGALRM, _deadline)
    signal.alarm(JOB_DEADLINE_SECONDS)
    try:
        return worker.process_claim(review_id, notification=notification)
    except WorkerDeadline:
        connections.close_all()
        return worker.mark_timed_out(review_id, notification=notification)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        close_old_connections()


class Command(BaseCommand):
    help = "Process queued AI solution reviews and published-review emails."

    def add_arguments(self, parser):
        parser.add_argument("--drain", action="store_true", help="Process up to five reviews at once until idle.")

    def _report(self, result):
        self.stdout.write(json.dumps(result))

    def handle(self, *args, **options):
        if options["drain"]:
            stopping = False

            def request_stop(_signum, _frame):
                nonlocal stopping
                stopping = True

            previous = signal.signal(signal.SIGTERM, request_stop)
            try:
                with ProcessPoolExecutor(
                    max_workers=worker.REVIEW_SLOTS + 1, mp_context=get_context("spawn"), initializer=django.setup,
                ) as executor:
                    worker.drain_queue(executor, _process_claim, self._report, stop_requested=lambda: stopping)
            finally:
                signal.signal(signal.SIGTERM, previous)
            return

        previous = signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(JOB_DEADLINE_SECONDS)
        try:
            self._report(worker.process_next())
        except WorkerDeadline:
            message = "The worker timed out. The claimed operation will not be retried automatically."
            raise CommandError(message) from None
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
