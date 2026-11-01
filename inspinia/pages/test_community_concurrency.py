"""Real row-lock behavior for request deduplication and shared budget reservations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.db import connection

from inspinia.pages.community_models import StatementAIReview
from inspinia.pages.statement_reviews import StatementReviewError
from inspinia.pages.statement_reviews import enqueue_statement_review
from inspinia.pages.test_community_problems import post
from inspinia.pages.test_statement_similarity import review_setup  # noqa: F401 - shared fixture

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires PostgreSQL row locking"),
]


def run_concurrently(operations):
    barrier = Barrier(len(operations))

    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return operation()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return list(executor.map(run, operations))


def test_concurrent_same_version_dispatch_request_is_deduplicated(review_setup):  # noqa: F811
    admin, problem, _ = review_setup

    def request():
        return enqueue_statement_review(admin, problem.pk, problem.version, acknowledged=True).pk

    identifiers = run_concurrently([request, request])
    assert identifiers[0] == identifiers[1]
    assert StatementAIReview.objects.count() == 1


def test_concurrent_distinct_requests_cannot_exceed_daily_request_allowance(review_setup):  # noqa: F811
    admin, problem, policy = review_setup
    other = post(problem.author, title="Another problem")
    policy.daily_request_limit = 1
    policy.save()

    def request(problem_id):
        try:
            enqueue_statement_review(admin, problem_id, 1, acknowledged=True)
        except StatementReviewError:
            return "blocked"
        return "queued"

    outcomes = run_concurrently([lambda: request(problem.pk), lambda: request(other.pk)])
    assert sorted(outcomes) == ["blocked", "queued"]
    assert StatementAIReview.objects.count() == 1
