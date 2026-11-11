"""The library may preview missing metadata without changing shared records."""

import json
from datetime import timedelta
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inspinia.pages import library_classification as classification
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
QUOTE = "For positive real numbers"
STATEMENT = r"For positive real numbers $x,y$, prove that $x+y \ge 2\sqrt{xy}$."


def make_statement(number=1, **kwargs):
    return ContestProblemStatement.objects.create(
        contest_year=2026, contest_name="Classification fixtures", problem_number=number, **{
            "statement_latex": STATEMENT, **kwargs,
        },
    )


def url(statement):
    return reverse("pages:library_classification", args=[statement.statement_uuid])


@pytest.fixture
def provider(settings, monkeypatch):
    settings.PROBLEM_LIBRARY_AI_SUGGESTIONS_ENABLED = True
    settings.OPENAI_API_KEY = "synthetic-key"
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "classification-tests"},
    }
    cache.clear()
    fake = Mock(return_value={})
    monkeypatch.setattr(classification, "generate_suggestions", fake)
    return fake


def test_page_offers_ai_only_on_active_incomplete_rows_with_a_statement(client, provider):
    client.force_login(UserFactory())
    incomplete = make_statement()
    inactive = make_statement(2, is_active=False)
    missing_statement = make_statement(3, statement_latex="")
    complete = make_statement(4, topic="A", mohs=0, confidence="High", imo_slot_guess="P1")
    StatementTopicTechnique.objects.create(statement=complete, technique="AM-GM", main_topic="ALG")

    response = client.get(reverse("pages:problem_statement_list"))
    rows = {row["statement_uuid"]: row for row in response.context["statement_table_rows"]}

    assert rows[str(incomplete.statement_uuid)]["classification_url"] == url(incomplete)
    for row in (inactive, missing_statement, complete):
        assert "classification_url" not in rows[str(row.statement_uuid)]
    provider.assert_not_called()
    assert client.post(url(complete)).json() == {"suggestions": {}}
    provider.assert_not_called()


def test_preview_uses_effective_values_and_requires_canonical_evidence(client, provider):
    client.force_login(UserFactory())
    linked = ProblemSolveRecord.objects.create(
        year=2026, contest="Classification fixtures", problem="P1", topic="A", mohs=0, confidence="High",
    )
    row = make_statement(problem_uuid=linked.problem_uuid)
    base = {"subject": "Algebra", "kind": "lemma", "label": "AM-GM", "quote": QUOTE, "why": "Bounds a sum."}
    provider.return_value = {
        "topic": ["Geometry"], "mohs": 30, "confidence": "Low", "imo_slots": [True, 5, 2, 7],
        "concepts": [
            {**base, "label": "Invented concept"},
            {**base, "label": "Cauchy-Schwarz", "quote": "Quote absent from statement"},
            {**base, "subject": "Geometry", "label": "Power of a point"},
            base,
        ],
    }

    response = client.post(url(row), {"statement": "Client-supplied text is ignored."})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["suggestions"] == {
        "area": ["Inequalities and optimization"], "imo_slots": [2, 5],
        "coverage": [{
            "id": "am-gm", "label": classification.REGISTRY.definitions["am-gm"]["label"], "subject": "Algebra",
            "area": "Inequalities and optimization", "quote": QUOTE, "why": "Bounds a sum.",
        }],
    }
    provider.assert_called_once_with(
        {"statement": STATEMENT, "existing_topic": "Algebra", "existing_mohs": 0},
        ("area", "coverage", "imo_slots"),
    )
    row.refresh_from_db()
    assert row.linked_problem_id is None
    assert row.topic is None
    assert row.mohs is None
    assert not StatementTopicTechnique.objects.exists()


def test_paid_post_requires_login_csrf_and_feature_flag(provider, settings):
    client = Client(enforce_csrf_checks=True)
    row = make_statement()
    assert client.post(url(row)).status_code == HTTPStatus.FORBIDDEN
    assert client.get(url(row)).status_code == HTTPStatus.FOUND
    client.force_login(UserFactory())
    assert client.get(url(row)).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert client.post(url(row)).status_code == HTTPStatus.FORBIDDEN

    client.get(reverse("pages:problem_statement_list"))
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
    settings.PROBLEM_LIBRARY_AI_SUGGESTIONS_ENABLED = False
    assert client.post(url(row), HTTP_X_CSRFTOKEN=csrf).status_code == HTTPStatus.FORBIDDEN
    provider.assert_not_called()


def test_restricted_inactive_and_unusable_sources_do_not_dispatch(client, provider):
    client.force_login(UserFactory())
    row = make_statement()
    now = timezone.now()
    AssistancePolicy.objects.create(
        problem_uuid=row.problem_uuid, mode="restricted_assessment", starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1), reason="Fixture restricted problem",
    )
    assert client.post(url(row)).status_code == HTTPStatus.FORBIDDEN
    assert client.post(url(make_statement(2, is_active=False))).status_code == HTTPStatus.NOT_FOUND
    assert client.post(url(make_statement(3, statement_latex="   "))).status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    provider.assert_not_called()


def test_site_and_account_limits_prevent_dispatch(client, provider, monkeypatch):
    monkeypatch.setattr(classification, "USER_DAILY_LIMIT", 1)
    monkeypatch.setattr(classification, "SITE_DAILY_LIMIT", 2)
    row = make_statement()

    client.force_login(UserFactory())
    assert client.post(url(row)).status_code == HTTPStatus.OK
    assert client.post(url(row)).status_code == HTTPStatus.TOO_MANY_REQUESTS
    client.force_login(UserFactory())
    assert client.post(url(row)).status_code == HTTPStatus.OK
    client.force_login(UserFactory())
    assert client.post(url(row)).status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert provider.call_count == 2  # noqa: PLR2004


def test_openai_request_uses_short_instructions_and_only_missing_fields(settings, monkeypatch):
    settings.OPENAI_API_KEY = "synthetic-key"
    transport = MagicMock()
    generate = transport.return_value.__enter__.return_value.responses.create
    generate.return_value = SimpleNamespace(status="completed", output=[], output_text='{"mohs": 0}')
    monkeypatch.setattr("openai.OpenAI", transport)

    snapshot = {"statement": STATEMENT, "existing_topic": "Algebra", "existing_mohs": None}
    assert classification.generate_suggestions(snapshot, ("mohs",)) == {"mohs": 0}

    request = generate.call_args.kwargs
    assert request["store"] is False
    assert request["text"]["format"]["schema"]["required"] == ["mohs"]
    assert json.loads(request["input"]) == snapshot
    assert len(request["instructions"]) < 360  # noqa: PLR2004
