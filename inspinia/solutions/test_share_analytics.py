"""Admin oversight must not turn private editor content into public metadata."""

# ruff: noqa: PLR2004

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.db import DatabaseError
from django.db import IntegrityError
from django.db import connection
from django.db import transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import admin_sharing
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.models import SolutionShareDailyViews
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


@pytest.fixture
def shared():
    owner = UserFactory(name="Ada Sharer", email="ada@example.test")
    problem = ProblemSolveRecord.objects.create(contest="ANALYTICS", year=2026, problem="P1", topic="ALG", mohs=5)
    solution = ProblemSolution.objects.create(author=owner, problem=problem, title="PRIVATE-TITLE-NEW-EDIT")
    return SolutionPublicShare.objects.create(
        solution=solution, is_active=True, source_updated_at=solution.updated_at,
        snapshot={
            "version": 1, "title": "A public square", "summary": "A shared argument.", "author": "Ada",
            "date": "", "show_footer": False,
            "problem": {"label": "ANALYTICS 2026 P1", "topic": "Algebra", "mohs": 5, "segments": [],
                        "areas": [], "concepts": []},
            "blocks": [{"heading": "Proof", "label": "Proof", "format": "plain_text", "source": "SHARED-PROOF"}],
        },
    )


@pytest.fixture
def admin(client):
    user = UserFactory(role=User.Role.ADMIN)
    client.force_login(user)
    return user


def dashboard_url():
    return reverse("solutions:admin_public_shares")


def reader_url(share):
    return reverse("solutions:public_solution", args=[share.token])


def test_anonymous_readership_counts_daily_without_storing_request_details(client, shared):
    for _ in range(2):
        response = client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT, REMOTE_ADDR="192.0.2.42")
        assert response.status_code == HTTPStatus.OK
        assert "no-store" in response["Cache-Control"]
    counter = SolutionShareDailyViews.objects.get(share=shared)
    assert counter.day == timezone.localdate()
    assert counter.views == 2
    assert set(SolutionShareDailyViews.objects.values().get(pk=counter.pk)) == {"id", "share_id", "day", "views"}
    assert not response.cookies
    shared.refresh_from_db()
    assert shared.snapshot["title"] == "A public square"


@pytest.mark.parametrize("agent", [
    "WhatsApp/2.24.1", "facebookexternalhit/1.1", "Googlebot", "TelegramBot", "Twitterbot/1.0",
    "Slackbot-LinkExpanding", "Discordbot", "LinkedInBot", "curl/8.0", "python-requests/2.0", "",
])
def test_preview_and_automated_fetches_do_not_count(client, shared, agent):
    assert client.get(reader_url(shared), HTTP_USER_AGENT=agent).status_code == HTTPStatus.OK
    assert not SolutionShareDailyViews.objects.exists()


@pytest.mark.parametrize("header", ["HTTP_PURPOSE", "HTTP_SEC_PURPOSE", "HTTP_X_PURPOSE"])
def test_prefetch_does_not_count(client, shared, header):
    response = client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT, **{header: "prefetch"})
    assert response.status_code == HTTPStatus.OK
    assert not SolutionShareDailyViews.objects.exists()


def test_head_images_and_revoked_links_do_not_count(client, shared):
    assert client.head(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT).status_code == HTTPStatus.OK
    image = reverse("solutions:public_solution_image", args=[shared.token, shared.revision])
    assert client.get(image, HTTP_USER_AGENT=BROWSER_AGENT).status_code == HTTPStatus.OK
    shared.is_active = False
    shared.snapshot = {}
    shared.save()
    assert client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT).status_code == HTTPStatus.NOT_FOUND
    assert not SolutionShareDailyViews.objects.exists()


@pytest.mark.parametrize("identity", ["owner", "admin", "superuser"])
def test_owner_and_admin_reading_does_not_inflate_traffic(client, shared, identity):
    user = shared.solution.author if identity == "owner" else UserFactory(
        role=User.Role.ADMIN if identity == "admin" else User.Role.NORMAL, is_superuser=identity == "superuser",
    )
    client.force_login(user)
    assert client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT).status_code == HTTPStatus.OK
    assert not SolutionShareDailyViews.objects.exists()


def test_other_signed_in_reader_counts(client, shared):
    client.force_login(UserFactory())
    assert client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT).status_code == HTTPStatus.OK
    assert SolutionShareDailyViews.objects.get(share=shared).views == 1


def test_analytics_failure_does_not_break_reading_or_log_request_details(client, shared, monkeypatch, caplog):
    def unavailable(**kwargs):
        message = "sensitive database parameters"
        raise DatabaseError(message)

    monkeypatch.setattr(SolutionShareDailyViews.objects, "get_or_create", unavailable)
    response = client.get(reader_url(shared), HTTP_USER_AGENT=BROWSER_AGENT)
    assert response.status_code == HTTPStatus.OK
    assert "Could not record an aggregate public solution view." in caplog.text
    assert "sensitive database parameters" not in caplog.text
    assert str(shared.token) not in caplog.text


def test_daily_uniqueness_and_solution_deletion_cascades(shared):
    SolutionShareDailyViews.objects.create(share=shared, day=timezone.localdate(), views=3)
    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionShareDailyViews.objects.create(share=shared, day=timezone.localdate(), views=8)
    shared.solution.delete()
    assert not SolutionShareDailyViews.objects.exists()


def test_admin_dashboard_requires_sign_in(client):
    response = client.get(dashboard_url())
    assert response.status_code == HTTPStatus.FOUND
    assert "/accounts/login/" in response.url


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.MODERATOR, User.Role.TRAINER])
def test_admin_dashboard_rejects_other_roles_even_in_debug(client, settings, role):
    settings.DEBUG = True
    client.force_login(UserFactory(role=role, is_staff=True))
    response = client.get(dashboard_url())
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "Public solutions" not in response.content.decode()


def test_superuser_can_review_dashboard_without_app_admin_role(client):
    client.force_login(UserFactory(is_superuser=True, role=User.Role.NORMAL))
    assert client.get(dashboard_url()).status_code == HTTPStatus.OK


def test_dashboard_lists_public_metadata_without_private_proof_or_preview_blob(client, admin, shared):
    shared.preview_image = b"PRIVATE-LARGE-IMAGE"
    shared.save()
    with CaptureQueriesContext(connection) as queries:
        response = client.get(dashboard_url())
    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "A public square" in html
    assert "ada@example.test" in html
    assert "Algebra" in html
    assert "MOHS 5" in html
    assert "PRIVATE-TITLE-NEW-EDIT" not in html
    assert "SHARED-PROOF" not in html
    assert "PRIVATE-LARGE-IMAGE" not in html
    assert "preview_image" not in " ".join(query["sql"] for query in queries)
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    assert "noindex" in response["X-Robots-Tag"]
    assert response.context["metrics"] == {"active": 1, "stopped": 0, "authors": 1, "views": 0}
    assert dashboard_url() in html  # Navigation entry.
    assert client.post(dashboard_url()).status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_dashboard_searches_shared_version_and_owner_but_never_private_title(client, admin, shared):
    assert client.get(dashboard_url(), {"q": "public square"}).context["page_obj"].paginator.count == 1
    assert client.get(dashboard_url(), {"q": "ANALYTICS 2026"}).context["page_obj"].paginator.count == 1
    assert client.get(dashboard_url(), {"q": "ada@example.test"}).context["page_obj"].paginator.count == 1
    assert client.get(dashboard_url(), {"q": "PRIVATE-TITLE-NEW-EDIT"}).context["page_obj"].paginator.count == 0
    private_problem = ProblemSolveRecord.objects.create(
        contest="PRIVATE", year=2026, problem="P2", topic="GEO", mohs=10,
    )
    ProblemSolution.objects.create(author=shared.solution.author, problem=private_problem, title="UNSHARED-PRIVATE")
    assert "UNSHARED-PRIVATE" not in client.get(dashboard_url()).content.decode()


def test_metrics_respect_window_filters_and_stopped_content_removal(client, admin, shared):
    today = timezone.localdate()
    SolutionShareDailyViews.objects.bulk_create([
        SolutionShareDailyViews(share=shared, day=today, views=7),
        SolutionShareDailyViews(share=shared, day=today - timedelta(days=29), views=3),
        SolutionShareDailyViews(share=shared, day=today - timedelta(days=30), views=100),
    ])
    response = client.get(dashboard_url(), {"topic": "Algebra"})
    assert response.context["metrics"]["views"] == 10
    assert response.context["page_obj"][0]["views_30d"] == 10
    assert sum(row["shares"] for row in response.context["trend"]) == 1
    assert sum(row["views"] for row in response.context["trend"]) == 10
    assert response.context["topic_counts"] == [{"shared_topic": "Algebra", "total": 1}]
    shared.is_active = False
    shared.snapshot = {}
    shared.save()
    stopped = client.get(dashboard_url(), {"status": "stopped"})
    assert stopped.context["metrics"] == {"active": 0, "stopped": 1, "authors": 0, "views": 10}
    html = stopped.content.decode()
    assert "Shared content removed" in html
    assert "A public square" not in html
    assert reader_url(shared) not in html
    assert "ada@example.test" in html
    assert not client.get(dashboard_url(), {"status": "active"}).context["metrics"]["views"]


def test_empty_invalid_filters_and_pagination_preserve_query(client, admin, shared, monkeypatch):
    second_problem = ProblemSolveRecord.objects.create(
        contest="ANALYTICS", year=2026, problem="P2", topic="GEO", mohs=10,
    )
    second_solution = ProblemSolution.objects.create(author=shared.solution.author, problem=second_problem)
    SolutionPublicShare.objects.create(solution=second_solution, source_updated_at=timezone.now(), snapshot={})
    monkeypatch.setattr(admin_sharing, "PAGE_SIZE", 1)
    response = client.get(dashboard_url(), {"q": "ada@example.test", "sort": "views", "page": 999})
    assert response.context["page_obj"].number == 2
    assert "q=ada%40example.test" in response.content.decode()
    assert "sort=views" in response.content.decode()
    invalid = client.get(dashboard_url(), {"status": "bad", "sort": "bad", "topic": "bad", "page": "bad"})
    assert invalid.context["filters"] == {"status": "", "sort": "updated", "topic": "", "q": ""}
    empty = client.get(dashboard_url(), {"q": "does not exist"})
    assert empty.context["metrics"] == {"active": 0, "stopped": 0, "authors": 0, "views": 0}
    assert "No shared solutions match these filters." in empty.content.decode()


def test_non_admin_navigation_does_not_advertise_dashboard(client):
    client.force_login(UserFactory(role=User.Role.NORMAL))
    response = client.get(reverse("solutions:my_solution_list"))
    assert response.status_code == HTTPStatus.OK
    assert dashboard_url() not in response.content.decode()


@pytest.mark.parametrize("mohs", [None, 0])
def test_missing_mohs_is_unavailable_and_zero_is_preserved(client, admin, shared, mohs):
    shared.snapshot["problem"]["mohs"] = mohs
    shared.save()
    response = client.get(dashboard_url())
    assert f"MOHS {mohs if mohs is not None else '—'}" in response.content.decode()
