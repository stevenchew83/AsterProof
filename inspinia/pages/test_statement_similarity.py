"""Similarity recall, stale-index behavior, and bounded administrator AI dispatch."""
# ruff: noqa: PLR2004, SLF001

import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.models import F
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.community_models import StatementAIReview
from inspinia.pages.community_models import StatementReviewPolicy
from inspinia.pages.community_models import StatementSimilarityDocument
from inspinia.pages.community_models import StatementSimilarityIndex
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.statement_review_provider import generate_statement_review
from inspinia.pages.statement_reviews import StatementReviewError
from inspinia.pages.statement_reviews import claim_statement_review
from inspinia.pages.statement_reviews import enqueue_statement_review
from inspinia.pages.statement_reviews import process_statement_review
from inspinia.pages.statement_similarity import check_statement_similarity
from inspinia.pages.statement_similarity import index_ready
from inspinia.pages.statement_similarity import rebuild_similarity_index
from inspinia.pages.test_community_problems import post
from inspinia.solutions.review_provider import ProviderError
from inspinia.solutions.review_provider import ProviderResult
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def statement(text, number=1, **kwargs):
    return ContestProblemStatement.objects.create(
        contest_name="SIMILARITY",
        contest_year=2026,
        problem_number=number,
        problem_code=f"P{number}",
        statement_latex=text,
        **kwargs,
    )


def test_short_latex_equivalents_and_variable_renaming_are_candidates():
    original = statement(r"Prove $\dfrac{x}{y} \ge x-y$.")
    statement("An unrelated triangle construction.", 2)
    rebuild_similarity_index()
    formatted = check_statement_similarity(r"Prove \(\frac{x}{y}\geq x-y\).")
    assert formatted["matches"][0]["statement_uuid"] == str(original.statement_uuid)
    assert formatted["matches"][0]["reason"] == "Matching wording"
    renamed = check_statement_similarity(r"Prove $\frac{a}{b}\geq a-b$.")
    assert renamed["matches"][0]["reason"] == "Similar structure / renamed variables"


def test_number_changes_remain_candidates_not_exact_equivalence_and_diagrams_are_disclosed():
    statement(r"Prove $a^2+b^2\geq 2ab$.[asy]draw(A--B);[/asy]")
    rebuild_similarity_index()
    result = check_statement_similarity(r"Prove $a^2+b^2\geq 3ab$.[asy]draw(C--D);[/asy]")
    assert result["matches"]
    assert result["matches"][0]["reason"] == "Related wording"
    assert "diagrams" in result["message"]
    assert "originality" in result["message"]


def test_stale_index_detects_direct_update_and_get_never_builds():
    row = statement("Original text.")
    rebuild_similarity_index()
    assert index_ready()
    ContestProblemStatement.objects.filter(pk=row.pk).update(statement_latex="Changed without updated_at.")
    assert not index_ready()
    with patch(
        "inspinia.pages.statement_similarity.rebuild_similarity_index", side_effect=AssertionError("request build"),
    ):
        assert not check_statement_similarity("Changed without updated_at.")["available"]
    call_command("refresh_statement_similarity_index")
    assert index_ready()


def test_unrelated_catalogue_activity_does_not_invalidate_statement_index():
    row = statement("A problem statement.")
    rebuild_similarity_index()
    CatalogueState.objects.filter(pk=1).update(source_revision=F("source_revision") + 1)
    row.topic = "ALG"
    row.save()
    assert index_ready()


def test_index_excludes_inactive_rows_and_rolls_back_failed_build():
    statement("An active test statement.")
    statement("A hidden statement.", 2, is_active=False)
    rebuild_similarity_index()
    assert StatementSimilarityDocument.objects.count() == 1
    before = StatementSimilarityIndex.objects.get().signature
    statement("Another active statement.", 3)
    with pytest.raises(TimeoutError):
        rebuild_similarity_index(max_seconds=-1)
    assert StatementSimilarityDocument.objects.count() == 1
    assert StatementSimilarityIndex.objects.get().signature == before
    assert not index_ready()


def test_search_uses_bounded_postings_without_full_statement_body_scan():
    for number in range(1, 36):
        statement(f"Find the largest integer n with property UNIQUEWORD{number}.", number)
    rebuild_similarity_index()
    with CaptureQueriesContext(connection) as queries:
        result = check_statement_similarity("Find the largest integer n with property UNIQUEWORD35.")
    assert result["matches"][0]["label"] == "SIMILARITY 2026 P35"
    body_queries = [q["sql"] for q in queries if '"statement_latex"' in q["sql"]]
    assert len(body_queries) == 1
    assert "LIMIT 200" in body_queries[0]


@pytest.fixture
def review_setup(settings):
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = True
    settings.OPENAI_API_KEY = "synthetic-test-key"
    admin = UserFactory(role=User.Role.ADMIN)
    problem = post(UserFactory())
    rebuild_similarity_index()
    policy = StatementReviewPolicy.objects.create(
        model="test-model",
        enabled=True,
        request_budget_micros=10_000_000,
        daily_budget_micros=100_000_000,
        monthly_budget_micros=1_000_000_000,
        input_price_micros_per_million=10_000_000,
        output_price_micros_per_million=50_000_000,
        pricing_verified_at=timezone.now(),
    )
    return admin, problem, policy


def enqueue(setup):
    admin, problem, _ = setup
    return enqueue_statement_review(admin, problem.pk, problem.version, acknowledged=True)


def report():
    return {
        "assessment": "changes_recommended",
        "summary": "Clarify the domain.",
        "issues": ["State that the variables are real."],
        "metadata_suggestions": ["Use the squares tag."],
        "similarity_assessment": "Related wording is not proof of duplication.",
        "limitations": ["No originality guarantee."],
    }


def test_ai_policy_permissions_acknowledgement_version_and_separate_budget(review_setup, settings):
    admin, problem, policy = review_setup
    with pytest.raises(StatementReviewError):
        enqueue_statement_review(problem.author, problem.pk, 1, acknowledged=True)
    with pytest.raises(StatementReviewError):
        enqueue_statement_review(admin, problem.pk, 1)
    with pytest.raises(StatementReviewError):
        enqueue_statement_review(admin, problem.pk, 2, acknowledged=True)
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    with pytest.raises(StatementReviewError):
        enqueue(review_setup)
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = True
    policy.pricing_verified_at = timezone.now() - timedelta(days=31)
    policy.save()
    with pytest.raises(StatementReviewError):
        enqueue(review_setup)
    policy.pricing_verified_at = timezone.now()
    policy.request_budget_micros = 1
    policy.save()
    with pytest.raises(StatementReviewError):
        enqueue(review_setup)
    assert not StatementAIReview.objects.exists()


def test_ai_snapshot_dedup_dispatch_and_feedback_never_approve(review_setup):
    job = enqueue(review_setup)
    assert enqueue(review_setup).pk == job.pk
    assert job.input_snapshot["solution_outline"].startswith("PRIVATE-OUTLINE")
    provider = Mock(
        return_value=ProviderResult(
            feedback=report(),
            response_id="resp_test",
            usage={"input_tokens": 100, "output_tokens": 50},
        ),
    )
    assert process_statement_review(provider) == "completed"
    assert process_statement_review(provider) == "idle"
    provider.assert_called_once()
    job.refresh_from_db()
    assert job.feedback["summary"] == "Clarify the domain."
    assert job.accounted_micros < job.reserved_micros
    job.problem.refresh_from_db()
    assert job.problem.status == "pending"


def test_unknown_provider_outcome_keeps_reservation_and_is_never_retried(review_setup):
    job = enqueue(review_setup)
    provider = Mock(side_effect=ProviderError("provider_connection_uncertain"))
    assert process_statement_review(provider) == "unknown"
    job.refresh_from_db()
    assert job.accounted_micros == job.reserved_micros
    assert enqueue(review_setup).pk == job.pk
    assert process_statement_review(provider) == "idle"
    provider.assert_called_once()


def test_stale_version_is_expired_before_provider_dispatch(review_setup):
    job = enqueue(review_setup)
    CommunityProblem.objects.filter(pk=job.problem_id).update(version=2)
    provider = Mock()
    assert process_statement_review(provider) == "expired"
    provider.assert_not_called()
    job.refresh_from_db()
    assert job.accounted_micros == 0


def test_interrupted_worker_marks_unknown_without_replaying(review_setup):
    job = enqueue(review_setup)
    assert claim_statement_review().pk == job.pk
    policy = StatementReviewPolicy.objects.get()
    policy.lease_until = timezone.now() - timedelta(seconds=1)
    policy.save()
    provider = Mock()
    assert process_statement_review(provider) == "idle"
    provider.assert_not_called()
    job.refresh_from_db()
    assert job.status == "unknown"


def test_invalid_report_is_not_published_and_overbudget_usage_disables_policy(review_setup):
    enqueue(review_setup)
    provider = Mock(
        return_value=ProviderResult(
            feedback={"summary": "bad"},
            usage={
                "input_tokens": 10_000_000,
                "output_tokens": 1,
            },
        ),
    )
    assert process_statement_review(provider) == "failed"
    assert StatementAIReview.objects.get().feedback == {}
    assert not StatementReviewPolicy.objects.get().enabled


def test_ai_feedback_is_admin_only(review_setup, client):
    admin, problem, _ = review_setup
    job = enqueue(review_setup)
    job.feedback, job.status = report(), "completed"
    job.save()
    url = reverse("pages:community_problem_detail", args=[problem.pk])
    client.force_login(problem.author)
    assert "Clarify the domain." not in client.get(url).content.decode()
    client.force_login(admin)
    assert "Clarify the domain." in client.get(url).content.decode()


def test_provider_requests_strict_json_without_storage_or_automatic_retries(review_setup, settings):
    job = enqueue(review_setup)
    settings.OPENAI_API_KEY = "synthetic-key"
    response = SimpleNamespace(
        status="completed", output=[], output_text=__import__("json").dumps(report()), usage=None, id="resp_fake",
    )
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.responses.create.return_value = response
    sdk = SimpleNamespace(
        OpenAI=Mock(return_value=client),
        APITimeoutError=type("Timeout", (Exception,), {}),
        APIConnectionError=type("Connection", (Exception,), {}),
        APIStatusError=type("Status", (Exception,), {}),
    )
    with patch.dict(sys.modules, {"openai": sdk}):
        result = generate_statement_review(job)
    assert result.feedback == report()
    assert sdk.OpenAI.call_args.kwargs["max_retries"] == 0
    assert client.responses.create.call_args.kwargs["store"] is False
    assert client.responses.create.call_args.kwargs["text"]["format"]["strict"] is True
