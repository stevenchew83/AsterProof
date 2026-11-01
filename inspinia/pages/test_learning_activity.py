# ruff: noqa: PLR2004 -- Explicit counts and timings describe the test cases.
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.http import QueryDict
from django.test import Client
from django.test import RequestFactory
from django.urls import resolve
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.learning_activity import TOKEN_SALT
from inspinia.pages.learning_activity import learning_activity_context
from inspinia.pages.learning_activity_analytics import build_learning_activity_analytics
from inspinia.pages.models import LearningPageAction
from inspinia.pages.models import LearningPageVisit
from inspinia.pages.page_view_analytics import _resolve_date_range
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_activity_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def learner():
    return UserFactory(is_approved=True)


def configuration(user, path="/dashboard/my-activity/"):
    request = RequestFactory().get(path)
    request.user = user
    request.resolver_match = resolve(path)
    return learning_activity_context(request).get("learning_activity_config")


def snapshot(client, config, *, sequence=1, visible_ms=0, clicks=None, **extra):
    payload = {"token": config["token"], "sequence": sequence, "visible_ms": visible_ms, "clicks": clicks or {}}
    payload.update(extra)
    return client.post(
        reverse("pages:learning_activity_collect"), json.dumps(payload), content_type="application/json",
    )


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard/page-views/",
        "/accounts/login/",
        "/users/~redirect/",
        "/",
        "/privacy/",
        "/trainer/",
        f"/solutions/shared/{uuid.uuid4()}/",
    ],
)
def test_account_admin_and_public_routes_never_emit_tracking(learner, path):
    assert configuration(learner, path) is None


def test_learning_page_has_signed_configuration_without_query_or_form_content(client, learner):
    client.force_login(learner)
    response = client.get(reverse("pages:user_activity_dashboard"), {"q": "private search value"})
    config = response.context["learning_activity_config"]
    token = signing.loads(config["token"], salt=TOKEN_SALT)
    assert token["user"] == learner.pk
    assert token["path"] == "/dashboard/my-activity/"
    assert "private search value" not in json.dumps(config)
    assert b"learning-activity.js" in response.content
    assert not LearningPageVisit.objects.exists()  # Rendering does not create telemetry records.


def test_generic_save_labels_are_only_classified_as_solution_actions_on_solution_pages(learner):
    activity_rules = configuration(learner)["rules"]
    assert "save_solution" not in {rule["key"] for rule in activity_rules}
    assert "import_completions" in {rule["key"] for rule in activity_rules}
    solution_rules = configuration(learner, f"/solutions/problems/{uuid.uuid4()}/draft/")["rules"]
    assert "save_solution" in {rule["key"] for rule in solution_rules}


def test_snapshots_are_cumulative_and_stale_or_duplicate_reports_do_not_double_count(client, learner):
    client.force_login(learner)
    config = configuration(learner)
    with patch("inspinia.pages.learning_activity.timezone.now", return_value=timezone.now() + timedelta(seconds=60)):
        assert snapshot(client, config, sequence=2, visible_ms=15000, clicks={"save_solution": 2}).status_code == 204
        assert snapshot(client, config, sequence=2, visible_ms=30000, clicks={"save_solution": 4}).status_code == 204
        assert snapshot(client, config, sequence=1, visible_ms=5000, clicks={"save_solution": 1}).status_code == 204
        assert (
            snapshot(
                client, config, sequence=3, visible_ms=20000, clicks={"save_solution": 2, "download_pdf": 1},
            ).status_code
            == 204
        )
    visit = LearningPageVisit.objects.get()
    assert visit.visible_ms == 20000
    assert visit.click_total == 3
    assert dict(visit.actions.values_list("action", "count")) == {"save_solution": 2, "download_pdf": 1}


def test_visible_time_cannot_exceed_time_since_server_issued_page(client, learner):
    client.force_login(learner)
    config = configuration(learner)
    assert snapshot(client, config, visible_ms=3600000).status_code == 204
    assert LearningPageVisit.objects.get().visible_ms < 5000


def test_other_users_cannot_reuse_a_page_token(client, learner):
    config = configuration(learner)
    client.force_login(UserFactory(is_approved=True))
    assert snapshot(client, config, clicks={"save_solution": 1}).status_code == 400
    assert not LearningPageVisit.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"token": "forged"},
        {"clicks": {"private arbitrary label": 1}},
        {"visible_ms": -1},
        {"sequence": True},
        {"clicks": {"search": True}},
        {"clicks": {"search": 2001}},
        {"typed_text": "must never be accepted"},
        {"visible_ms": 43200001},
    ],
)
def test_invalid_snapshots_are_rejected_without_storing_content(client, learner, changes):
    client.force_login(learner)
    assert snapshot(client, configuration(learner), **changes).status_code == 400
    assert not LearningPageVisit.objects.exists()


def test_expired_tokens_and_disabled_collection_are_rejected(client, learner, settings):
    client.force_login(learner)
    config = configuration(learner)
    with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 90000):
        assert snapshot(client, config).status_code == 400
    settings.LEARNING_ACTIVITY_ENABLED = False
    assert configuration(learner) is None
    assert snapshot(client, config).status_code == 403


def test_collect_requires_csrf_and_authentication(learner):
    client = Client(enforce_csrf_checks=True)
    assert client.get(reverse("pages:learning_activity_collect")).status_code == 302
    client.force_login(learner)
    config = configuration(learner)
    assert snapshot(client, config).status_code == 403
    response = client.get(reverse("pages:user_activity_dashboard"))
    config = response.context["learning_activity_config"]
    payload = {"token": config["token"], "sequence": 1, "visible_ms": 0, "clicks": {}}
    assert (
        client.post(
            config["endpoint"], json.dumps(payload), content_type="application/json", HTTP_X_CSRFTOKEN=config["csrf"],
        ).status_code
        == 204
    )


def test_request_rate_is_bounded(client, learner):
    client.force_login(learner)
    with patch("inspinia.pages.learning_activity._rate_allowed", return_value=False):
        assert snapshot(client, configuration(learner)).status_code == 429
    assert not LearningPageVisit.objects.exists()


def test_rotating_action_keys_cannot_exceed_per_visit_cap(client, learner):
    client.force_login(learner)
    config = configuration(learner)
    assert snapshot(client, config, clicks={"search": 2000}).status_code == 204
    assert snapshot(client, config, sequence=2, clicks={"download_pdf": 1}).status_code == 400
    assert LearningPageVisit.objects.get().click_total == 2000
    assert not LearningPageAction.objects.filter(action="download_pdf").exists()


def test_admin_summaries_filter_measured_data_independently_and_preserve_audience(learner):
    admin = UserFactory(role=User.Role.ADMIN)
    other = UserFactory(is_approved=True)
    for user, visible in [(learner, 60000), (other, 120000), (admin, 300000)]:
        visit = LearningPageVisit.objects.create(
            user=user,
            page_name="solutions:problem_solution_edit",
            path="/solutions/proof/draft/",
            visible_ms=visible,
            click_total=2,
        )
        LearningPageAction.objects.create(visit=visit, action="save_solution", count=2)
    params = QueryDict(f"range=7d&activity_user={learner.pk}&include_anonymous=0")
    result = build_learning_activity_analytics(_resolve_date_range(params), include_admins=False, params=params)
    assert result["visits"] == 1
    assert result["duration"] == "1m 0s"
    assert result["average"] == "1m 0s"
    assert result["actions"][0]["label"] == "Save solution"
    assert result["actions"][0]["clicks"] == 2
    result = build_learning_activity_analytics(
        _resolve_date_range(params), include_admins=False, params=QueryDict("range=7d"),
    )
    assert result["visits"] == 2
    assert result["duration"] == "3m 0s"
    result = build_learning_activity_analytics(
        _resolve_date_range(params), include_admins=True, params=QueryDict("range=7d"),
    )
    assert result["visits"] == 3


def test_measurements_are_removed_with_account(learner):
    visit = LearningPageVisit.objects.create(
        user=learner, page_name="pages:user_activity_dashboard", path="/dashboard/my-activity/",
    )
    LearningPageAction.objects.create(visit=visit, action="search", count=1)
    learner.delete()
    assert not LearningPageVisit.objects.exists()
    assert not LearningPageAction.objects.exists()


def test_missing_activity_schema_preserves_the_outer_request_transaction():
    def unavailable(*args):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM missing_synthetic_activity_table")

    with patch("inspinia.pages.learning_activity_analytics._build", side_effect=unavailable):
        result = build_learning_activity_analytics(
            _resolve_date_range(QueryDict()), include_admins=False, params=QueryDict(),
        )
    assert result["available"] is False
    assert LearningPageVisit.objects.count() == 0
