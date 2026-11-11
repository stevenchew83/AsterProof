"""The library previews missing metadata and allows administrators to save it."""

import json
from datetime import timedelta
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inspinia.pages import library_classification as classification
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.study_help_access import statement_revision
from inspinia.solutions.admin_review_models import AdminSolutionReviewSettings
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.users.models import User
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
        api_key="synthetic-key",
    )
    row.refresh_from_db()
    assert row.linked_problem_id is None
    assert row.topic is None
    assert row.mohs is None
    assert row.imo_slot_guess is None
    assert row.ai_concept_suggestions is None
    assert not StatementTopicTechnique.objects.exists()


def test_admin_saves_fields_and_supported_concept_evidence_for_the_shared_row(client, provider, settings):
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    row = make_statement(statement_latex=(
        r"Determine all functions $f: \mathbb{R} \to \mathbb{R}$ such that "
        r"$$f(x+yf(x+y))=f(x)f(y)+y^2$$for all $x,y \in \mathbb{R}$"
    ))
    provider.return_value = {
        "topic": ["Algebra"], "mohs": 0, "confidence": "High", "imo_slots": [4, 1],
        "concepts": [{
            "subject": "Algebra", "kind": "lemma", "label": "AM-GM",
            "quote": "Quote absent from the statement", "why": "An unsupported reason.",
        }],
    }

    response = client.post(url(row))

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["saved"] is True
    assert payload["suggestions"] == {}
    assert payload["row"]["linked_problem_topic"] == "Algebra"
    assert payload["row"]["linked_problem_mohs"] == 0
    assert payload["row"]["linked_problem_imo_slot_display"] == "P1, P4"
    row.refresh_from_db()
    assert (row.topic, row.mohs, row.confidence, row.imo_slot_guess_value) == ("Algebra", 0, "High", "1,4")
    assert row.ai_concept_suggestions["saved_by"] == admin.pk
    assert row.ai_concept_suggestions["statement_revision"] == statement_revision(row)
    saved, = row.ai_concept_suggestions["concepts"]
    assert saved["id"] == "function-composition"
    assert saved["area"] == "Functions and functional equations"
    assert saved["quote"] == "f(x+yf(x+y))"
    assert saved["why"]
    assert payload["row"]["saved_ai_concepts"][0]["id"] == saved["id"]
    assert payload["row"]["concept_coverage"] == []
    assert client.post(url(row)).json()["saved"] is False
    provider.assert_called_once()

    settings.PROBLEM_LIBRARY_AI_SUGGESTIONS_ENABLED = False
    client.force_login(UserFactory())
    library_url = reverse("pages:problem_statement_list")
    reloaded, = client.get(library_url).context["statement_table_rows"]
    assert reloaded["linked_problem_mohs"] == 0
    assert reloaded["saved_ai_concepts"] == payload["row"]["saved_ai_concepts"]
    assert "classification_url" not in reloaded
    assert not StatementTopicTechnique.objects.exists()

    original_text = row.statement_latex
    ContestProblemStatement.objects.filter(pk=row.pk).update(statement_latex="A revised problem.")
    assert "saved_ai_concepts" not in client.get(library_url).context["statement_table_rows"][0]
    ContestProblemStatement.objects.filter(pk=row.pk).update(statement_latex=original_text)

    now = timezone.now()
    AssistancePolicy.objects.create(
        problem_uuid=row.problem_uuid, mode="restricted_assessment", starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1), reason="Fixture restricted problem",
    )
    assert "saved_ai_concepts" not in client.get(library_url).context["statement_table_rows"][0]


def test_admin_save_keeps_existing_and_concurrently_filled_metadata(client, provider):
    client.force_login(UserFactory(is_superuser=True))
    legacy = ProblemSolveRecord.objects.create(
        year=2026, contest="Classification fixtures", problem="P1", topic="A", mohs=0,
    )
    row = make_statement(problem_uuid=legacy.problem_uuid, imo_slot_guess="Prior workbook annotation")

    def fill_confidence(*args, **kwargs):
        ContestProblemStatement.objects.filter(pk=row.pk).update(confidence="High")
        return {"topic": ["Geometry"], "mohs": 30, "confidence": "Low", "imo_slots": [3]}

    provider.side_effect = fill_confidence
    response = client.post(url(row))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["saved"] is False
    assert response.json()["row"]["linked_problem_confidence"] == "High"
    row.refresh_from_db()
    assert (row.topic, row.mohs, row.linked_problem_id) == (None, None, None)
    assert row.confidence == "High"
    assert row.imo_slot_guess == "Prior workbook annotation"


def test_admin_discards_suggestions_if_statement_changes_during_request(client, provider):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    row = make_statement()

    def edit_statement(*args, **kwargs):
        ContestProblemStatement.objects.filter(pk=row.pk).update(statement_latex="A different problem.")
        return {"mohs": 20}

    provider.side_effect = edit_statement

    assert client.post(url(row)).status_code == HTTPStatus.CONFLICT
    row.refresh_from_db()
    assert row.mohs is None
    assert row.ai_concept_suggestions is None


def test_memo_p1_returns_canonical_composition_from_the_statement(client, provider):
    client.force_login(UserFactory())
    row = make_statement(statement_latex=(
        r"Determine all functions $f: \mathbb{R} \to \mathbb{R}$ such that "
        r"$$f(x+yf(x+y))=f(x)f(y)+y^2$$for all $x,y \in \mathbb{R}$"
    ))
    provider.return_value = {
        "topic": ["Algebra"],
        "concepts": [{
            "subject": "Algebra", "kind": "method", "label": "Functional equation",
            "quote": "Determine all functions", "why": "This is a functional equation.",
        }],
    }

    response = client.post(url(row))

    assert response.status_code == HTTPStatus.OK
    suggestions = response.json()["suggestions"]
    assert suggestions["area"] == ["Functions and functional equations"]
    assert suggestions["coverage"] == [{
        "id": "function-composition", "label": "Function composition", "subject": "Algebra",
        "area": "Functions and functional equations", "quote": "f(x+yf(x+y))",
        "why": "The argument of the outer function call contains another call to the same function.",
    }]


def test_canonical_label_can_be_given_under_another_role():
    source = "Evaluate the composition of the given functions."
    report = {"concepts": [{
        "subject": "Algebra", "kind": "method", "label": "Function composition",
        "quote": "composition of the given functions", "why": "The problem asks to compose functions.",
    }]}

    suggestions = classification.validated_suggestions(report, ("coverage",), {
        "statement": source, "existing_topic": "Algebra",
    })

    assert [concept["id"] for concept in suggestions["coverage"]] == ["function-composition"]


def test_separate_calls_and_generic_equation_label_do_not_infer_a_concept():
    source = r"Find $f: \mathbb{R} \to \mathbb{R}$ satisfying $f(x)+f(y)=x+y$."
    report = {"concepts": [{
        "subject": "Algebra", "kind": "method", "label": "Functional equation",
        "quote": "f(x)+f(y)=x+y", "why": "This is a functional equation.",
    }]}

    assert classification.validated_suggestions(report, ("area", "coverage"), {
        "statement": source, "existing_topic": "Algebra",
    }) == {}


def test_library_uses_saved_ai_key_and_respects_the_override(client, provider, settings):
    settings.OPENAI_API_KEY = ""
    fernet_key = Fernet.generate_key()
    settings.ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY = fernet_key.decode()
    saved_key = b"synthetic-saved-review-key"
    AdminSolutionReviewSettings.objects.create(encrypted_key=Fernet(fernet_key).encrypt(saved_key))

    user = UserFactory()
    client.force_login(user)
    row = make_statement()
    library_url = reverse("pages:problem_statement_list")
    library = client.get(library_url)
    assert library.context["statement_table_rows"][0]["classification_url"] == url(row)
    assert saved_key not in library.content
    provider.assert_not_called()

    provider.return_value = {"mohs": 20}
    result = client.post(url(row))
    assert result.status_code == HTTPStatus.OK
    assert result.json() == {"suggestions": {"mohs": 20}}
    assert provider.call_args.kwargs["api_key"] == saved_key.decode()
    assert saved_key not in result.content

    settings.PROBLEM_LIBRARY_AI_SUGGESTIONS_ENABLED = False
    assert "classification_url" not in client.get(library_url).context["statement_table_rows"][0]
    assert client.post(url(row)).status_code == HTTPStatus.FORBIDDEN
    assert provider.call_count == 1

    client.force_login(UserFactory(is_superuser=True))
    admin_page = client.get(reverse("solutions:admin_ai_review_settings"))
    assert b"Disabled by configuration" in admin_page.content
    assert saved_key not in admin_page.content


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


def test_openai_request_uses_short_instructions_and_only_missing_fields(monkeypatch):
    transport = MagicMock()
    generate = transport.return_value.__enter__.return_value.responses.create
    generate.return_value = SimpleNamespace(status="completed", output=[], output_text='{"mohs": 0}')
    monkeypatch.setattr("openai.OpenAI", transport)

    snapshot = {"statement": STATEMENT, "existing_topic": "Algebra", "existing_mohs": None}
    assert classification.generate_suggestions(snapshot, ("mohs",), api_key="synthetic-key") == {"mohs": 0}

    request = generate.call_args.kwargs
    assert request["store"] is False
    assert request["text"]["format"]["schema"]["required"] == ["mohs"]
    assert json.loads(request["input"]) == snapshot
    assert len(request["instructions"]) < 360  # noqa: PLR2004
