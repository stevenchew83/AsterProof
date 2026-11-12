# ruff: noqa: PLR2004
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit

import pytest
from django.core import signing
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementIssueReport
from inspinia.pages.statement_reports import FORM_SALT
from inspinia.pages.statement_reports import REPORTS_PER_HOUR
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def statement():
    problem = ProblemSolveRecord.objects.create(
        year=2026, contest="IMO", problem="P1", topic="ALG", mohs=10,
    )
    return ContestProblemStatement.objects.create(
        linked_problem=problem, contest_year=2026, contest_name="IMO", problem_code="P1", problem_number=1,
        statement_latex="Find all $x$ such that $x^2=-1$.",
    )


@pytest.fixture
def public_list(statement):
    problem_list = ProblemList.objects.create(
        author=UserFactory(), title="Practice", visibility=ProblemList.Visibility.PUBLIC,
    )
    ProblemListItem.objects.create(problem_list=problem_list, problem=statement.linked_problem, position=1)
    return problem_list


def report_url(statement, problem_list=None):
    url = reverse("pages:statement_report_create", args=[statement.statement_uuid])
    return url + "?" + urlencode({"list": problem_list.share_token}) if problem_list else url


def submit(client, url, **values):
    response = client.get(url)
    assert response.status_code == 200
    return client.post(url, {
        "description": "The domain for x is missing.",
        "token": response.context["form"]["token"].value(),
        **values,
    })


def test_guest_reports_public_statement_without_changing_it(client, statement, public_list):
    url = report_url(statement, public_list)
    public_page = client.get(public_list.public_url())
    assert url in public_page.content.decode()
    response = submit(client, url)
    assert response.status_code == 302
    report = StatementIssueReport.objects.get()
    assert report.statement == statement
    assert report.statement_uuid == statement.statement_uuid
    assert report.problem_uuid == statement.problem_uuid
    assert report.statement_snapshot == statement.statement_latex
    assert report.description == "The domain for x is missing."
    assert report.reporter is None
    assert report.status == StatementIssueReport.Status.OPEN
    assert report.reviewed_at is None
    statement.refresh_from_db()
    assert statement.statement_latex == report.statement_snapshot
    confirmation = client.get(response.url)
    assert "sent to the administrators" in confirmation.content.decode()
    assert "no-store" in confirmation["Cache-Control"]
    assert confirmation["X-Robots-Tag"] == "noindex, nofollow"


def test_signed_in_reporter_is_server_derived(client, statement):
    user = UserFactory()
    client.force_login(user)
    url = report_url(statement)
    detail = client.get(reverse("pages:problem_statement_detail", args=[statement.statement_uuid]))
    assert url in detail.content.decode()
    response = submit(client, url, reporter=UserFactory().pk, status="resolved", statement_uuid=str(uuid.uuid4()))
    assert response.status_code == 302
    report = StatementIssueReport.objects.get()
    assert report.reporter == user
    assert report.status == "open"
    assert report.statement == statement


def test_guest_cannot_report_a_private_or_unlisted_statement(client, statement, public_list):
    assert client.get(report_url(statement)).status_code == 404
    public_list.visibility = ProblemList.Visibility.PRIVATE
    public_list.save()
    assert client.get(report_url(statement, public_list)).status_code == 404
    assert not StatementIssueReport.objects.exists()


@pytest.mark.parametrize("change", ["private", "removed", "inactive_problem", "inactive_statement"])
def test_public_access_is_rechecked_on_submission(client, statement, public_list, change):
    url = report_url(statement, public_list)
    token = client.get(url).context["form"]["token"].value()
    if change == "private":
        public_list.visibility = ProblemList.Visibility.PRIVATE
        public_list.save()
    elif change == "removed":
        public_list.items.all().delete()
    elif change == "inactive_problem":
        statement.linked_problem.is_active = False
        statement.linked_problem.save()
    else:
        statement.is_active = False
        statement.save()
    assert client.post(url, {"description": "A typo.", "token": token}).status_code == 404
    assert not StatementIssueReport.objects.exists()


def test_guest_cannot_substitute_a_different_statement(client, statement, public_list):
    other = ContestProblemStatement.objects.create(
        contest_year=2026, contest_name="IMO", problem_code="P2", problem_number=2,
        statement_latex="Private statement",
    )
    assert client.get(report_url(other, public_list)).status_code == 404


def test_public_report_respects_hidden_source_and_custom_title(client, statement, public_list):
    public_list.hide_source = True
    public_list.save()
    url = report_url(statement, public_list)
    response = client.get(url)
    assert "Problem 1" in response.content.decode()
    assert "IMO 2026" not in response.content.decode()
    item = public_list.items.get()
    item.custom_title = "Warm-up"
    item.save()
    assert "Warm-up" in client.get(url).content.decode()


def test_unapproved_member_can_report_public_content_only(client, statement, public_list):
    client.force_login(UserFactory(is_approved=False))
    assert submit(client, report_url(statement, public_list)).status_code == 302
    assert client.get(report_url(statement)).status_code == 404


@pytest.mark.parametrize("description", ["", "   ", "x" * 2001])
def test_report_requires_bounded_nonblank_description(client, statement, public_list, description):
    response = submit(client, report_url(statement, public_list), description=description)
    assert response.status_code == 200
    assert response.context["form"].errors["description"]
    assert not StatementIssueReport.objects.exists()


@pytest.mark.parametrize("case", ["", "tampered", "wrong_statement", "expired"])
def test_invalid_form_tokens_are_rejected(client, statement, public_list, case):
    token = case
    if case == "wrong_statement":
        token = signing.dumps({"statement": str(uuid.uuid4()), "submission": str(uuid.uuid4())}, salt=FORM_SALT)
    if case == "expired":
        with patch("django.core.signing.time.time", return_value=0):
            token = signing.dumps(
                {"statement": str(statement.statement_uuid), "submission": str(uuid.uuid4())}, salt=FORM_SALT,
            )
    response = submit(client, report_url(statement, public_list), token=token)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not StatementIssueReport.objects.exists()


def test_post_replay_creates_only_one_report(client, statement, public_list):
    url = report_url(statement, public_list)
    token = client.get(url).context["form"]["token"].value()
    for _ in range(2):
        assert client.post(url, {"description": "A typo.", "token": token}).status_code == 302
    assert StatementIssueReport.objects.count() == 1


def test_rate_limit_and_honeypot(client, statement, public_list):
    url = report_url(statement, public_list)
    assert submit(client, url, website="spam").context["form"].errors
    assert not StatementIssueReport.objects.exists()
    for _ in range(REPORTS_PER_HOUR):
        assert submit(client, url).status_code == 302
    response = submit(client, url)
    assert response.status_code == 429
    assert "Too many reports" in response.content.decode()
    assert StatementIssueReport.objects.count() == REPORTS_PER_HOUR


@pytest.mark.parametrize("failure", ["exception", "ignored"])
def test_rate_limit_fails_closed_when_cache_is_unavailable(client, statement, public_list, failure):
    behavior = {"side_effect": OSError} if failure == "exception" else {"return_value": None}
    with patch("inspinia.pages.statement_reports.cache.incr", **behavior):
        assert submit(client, report_url(statement, public_list)).status_code == 429
    assert not StatementIssueReport.objects.exists()


def test_submission_requires_csrf(statement, public_list):
    client = Client(enforce_csrf_checks=True)
    url = report_url(statement, public_list)
    response = client.get(url)
    data = {"description": "A typo.", "token": response.context["form"]["token"].value()}
    assert client.post(url, data).status_code == 403
    assert not StatementIssueReport.objects.exists()
    data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    assert client.post(url, data).status_code == 302


@pytest.mark.parametrize("debug", [True, False])
def test_admin_queue_and_update_are_private_even_in_debug(client, statement, public_list, settings, debug):
    settings.DEBUG = debug
    submit(client, report_url(statement, public_list))
    report = StatementIssueReport.objects.get()
    queue_url = reverse("pages:statement_report_list")
    update_url = reverse("pages:statement_report_update", args=[report.pk])
    assert client.get(queue_url).status_code == 302
    assert client.post(update_url, {"status": "resolved"}).status_code == 302
    for role in [User.Role.NORMAL, User.Role.MODERATOR, User.Role.TRAINER]:
        client.force_login(UserFactory(role=role))
        assert client.get(queue_url).status_code == 403
        assert client.post(update_url, {"status": "resolved"}).status_code == 403
    report.refresh_from_db()
    assert report.status == "open"


def test_admin_review_filters_badge_and_snapshot_survive_deletion(client, statement, public_list):
    submit(client, report_url(statement, public_list), description='<script>alert("bad")</script>')
    report = StatementIssueReport.objects.get()
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    queue_url = reverse("pages:statement_report_list")
    update_url = reverse("pages:statement_report_update", args=[report.pk])
    response = client.get(queue_url)
    assert response.context["open_count"] == 1
    assert report in response.context["reports"]
    assert "&lt;script&gt;" in response.content.decode()
    assert '<script>alert("bad")</script>' not in response.content.decode()
    assert 'aria-label="1 open reports"' in response.content.decode()
    assert client.get(update_url).status_code == 405
    assert client.post(update_url, {"status": "invalid"}).status_code == 400
    assert client.post(update_url, {"status": "resolved"}).status_code == 302
    report.refresh_from_db()
    assert report.reviewed_by == admin
    assert report.reviewed_at is not None
    assert report.status == "resolved"
    assert client.get(queue_url).context["open_count"] == 0
    assert not client.get(queue_url).context["reports"]
    assert report in client.get(queue_url, {"status": "resolved"}).context["reports"]
    assert client.post(update_url, {"status": "dismissed"}).status_code == 302
    assert report in client.get(queue_url, {"status": "dismissed"}).context["reports"]
    assert client.post(update_url, {"status": "open"}).status_code == 302
    report.refresh_from_db()
    assert report.reviewed_by is None
    assert report.reviewed_at is None
    statement.delete()
    report.refresh_from_db()
    assert report.statement is None
    assert report.statement_snapshot == "Find all $x$ such that $x^2=-1$."
    assert "Statement deleted" in client.get(queue_url).content.decode()


def test_queue_is_paginated(client, statement, public_list):
    submit(client, report_url(statement, public_list))
    report = StatementIssueReport.objects.get()
    for _ in range(25):
        report.pk = None
        report.submission_uuid = uuid.uuid4()
        report.save()
    client.force_login(UserFactory(role=User.Role.ADMIN))
    response = client.get(reverse("pages:statement_report_list"))
    assert len(response.context["reports"]) == 25
    assert response.context["reports"].paginator.count == 26


def test_queue_search_matches_problem_and_report_with_status_counts(client, statement, public_list):
    submit(client, report_url(statement, public_list))
    original = StatementIssueReport.objects.get()
    resolved = StatementIssueReport.objects.create(
        statement=statement, statement_uuid=statement.statement_uuid, problem_uuid=statement.problem_uuid,
        statement_label="Geometry Invitational P3", statement_snapshot=statement.statement_latex,
        description="A diagram label is missing.", status="resolved",
    )
    client.force_login(UserFactory(role=User.Role.ADMIN))
    url = reverse("pages:statement_report_list")
    response = client.get(url, {"status": "all", "q": " diagram "})
    assert list(response.context["reports"]) == [resolved]
    assert response.context["query"] == "diagram"
    assert response.context["open_count"] == 1
    counts = {tab["value"]: tab["count"] for tab in response.context["status_tabs"]}
    assert counts == {"open": 0, "resolved": 1, "dismissed": 0, "all": 1}
    for tab in response.context["status_tabs"]:
        assert parse_qs(urlsplit(tab["url"]).query)["q"] == ["diagram"]
    assert list(client.get(url, {"q": "IMO"}).context["reports"]) == [original]
    assert not client.get(url, {"q": "diagram"}).context["reports"]
    assert "No matching reports" in client.get(url, {"q": "unmatched"}).content.decode()


def test_review_keeps_search_status_and_page(client, statement, public_list):
    submit(client, report_url(statement, public_list))
    report = StatementIssueReport.objects.get()
    client.force_login(UserFactory(role=User.Role.ADMIN))
    response = client.post(reverse("pages:statement_report_update", args=[report.pk]), {
        "status": "resolved", "return_status": "all", "return_query": "IMO & algebra", "return_page": "2",
    })
    assert response.status_code == 302
    assert urlsplit(response.url).path == reverse("pages:statement_report_list")
    assert parse_qs(urlsplit(response.url).query) == {
        "status": ["all"], "q": ["IMO & algebra"], "page": ["2"],
    }
    report.refresh_from_db()
    assert report.status == "resolved"


def test_review_redirect_rejects_untrusted_status_and_bounds_query(client, statement, public_list):
    submit(client, report_url(statement, public_list))
    report = StatementIssueReport.objects.get()
    client.force_login(UserFactory(role=User.Role.ADMIN))
    url = reverse("pages:statement_report_update", args=[report.pk])
    response = client.post(url, {"status": "dismissed", "return_status": "https://example.test"})
    assert response.url == reverse("pages:statement_report_list")
    response = client.post(url, {
        "status": "open", "return_status": "all", "return_query": "x" * 300, "return_page": "bad",
    })
    query = parse_qs(urlsplit(response.url).query)
    assert query["q"] == ["x" * 200]
    assert query["page"] == ["1"]


def test_inline_review_updates_filtered_queue_and_clamps_emptied_page(client, statement, public_list):
    submit(client, report_url(statement, public_list))
    oldest = StatementIssueReport.objects.get()
    StatementIssueReport.objects.bulk_create([
        StatementIssueReport(
            statement=statement,
            statement_uuid=statement.statement_uuid,
            problem_uuid=statement.problem_uuid,
            statement_label="IMO P1",
            statement_snapshot=statement.statement_latex,
            description="The domain for x is missing.",
        )
        for _ in range(25)
    ])
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    endpoint = reverse("pages:statement_report_update", args=[oldest.pk])
    response = client.post(endpoint, {
        "status": "resolved", "return_status": "open", "return_query": "domain", "return_page": "2",
    }, HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    payload = response.json()
    assert parse_qs(urlsplit(payload["url"]).query) == {"status": ["open"], "q": ["domain"], "page": ["1"]}
    assert 'value="domain"' in payload["html"]
    assert "of 25 reports" in payload["html"]
    assert f'id="statement-report-{oldest.pk}"' not in payload["html"]
    oldest.refresh_from_db()
    assert oldest.status == "resolved"
    assert oldest.reviewed_by == admin
