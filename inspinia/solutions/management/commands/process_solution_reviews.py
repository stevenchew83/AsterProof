"""One bounded, explicitly activated coaching dispatch per worker invocation."""

import json
import signal

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from inspinia.solutions.evaluation import EvaluationError
from inspinia.solutions.review_provider import ProviderError
from inspinia.solutions.reviews import ReviewError
from inspinia.solutions.reviews import process_next_review


def _timeout(_signum, _frame):
    msg = "worker_timeout"
    raise ProviderError(msg)


class Command(BaseCommand):
    help = "Provider execution is refused by the offline release. No paid request can be dispatched."

    def handle(self, *args, **options):
        previous = signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(330)
        try:
            try:
                result = process_next_review()
            except (ReviewError, EvaluationError) as error:
                raise CommandError(str(error)) from error
            self.stdout.write(json.dumps(result))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
