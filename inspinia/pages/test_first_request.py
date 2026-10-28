# ruff: noqa: PLR2004
"""Cold workers render the real pages without lazy URL/template initialization."""

from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.template import engines
from django.urls import clear_url_caches
from django.urls import reverse

from config.startup import prepare_first_request
from inspinia.pages.catalogue_progress import build_progress_context
from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.catalogue_snapshots import user_progress_summary
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.test_concept_progress import statement
from inspinia.pages.test_concept_progress import tag
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_first_pages_use_prepared_templates_and_urls_without_changing_progress(client, settings):
    admin = UserFactory(role=User.Role.ADMIN)
    learner = UserFactory()
    first, second = statement(1), statement(2)
    tag(first)
    tag(second)
    UserProblemCompletion.objects.create(user=learner, statement=first, status="solved")
    snapshot = rebuild_library_snapshot()
    user_progress_summary(learner, snapshot)
    original = list(UserProblemCompletion.objects.values())
    client.force_login(admin)
    settings.PREPARE_FIRST_REQUEST = True
    settings.LANGUAGE_CODE = "en-us"
    clear_url_caches()
    for backend in engines.all():
        for loader in backend.engine.template_loaders:
            loader.reset()
    prepare_first_request()
    with (
        patch("django.template.base.Template.compile_nodelist", side_effect=AssertionError("Cold template")),
        patch("django.urls.resolvers.URLResolver._populate", side_effect=AssertionError("Cold URL reverser")),
    ):
        catalogue = client.get("/dashboard/topic-tags/", HTTP_ACCEPT_LANGUAGE="en-US")
        area_problems = client.get(
            "/dashboard/topic-tags/", {"area": "Algebra:inequalities"}, HTTP_ACCEPT_LANGUAGE="en-US",
        )
        progress = client.get("/dashboard/techniques/", {"user": learner.pk}, HTTP_ACCEPT_LANGUAGE="en-US")
        concepts = client.get(
            "/dashboard/techniques/topics/algebra/",
            {"user": learner.pk, "mode": "concepts"},
            HTTP_ACCEPT_LANGUAGE="en-US",
        )
    assert catalogue.status_code == area_problems.status_code == progress.status_code == concepts.status_code == 200
    assert area_problems.context["examples"].paginator.count == 2
    assert progress.context["stats"]["solved"] == 1
    assert progress.context["stats"]["total"] == 2
    assert concepts.context["stats"]["solved"] == 1
    assert list(UserProblemCompletion.objects.values()) == original


def test_progress_route_reversals_stay_bounded_as_the_catalogue_grows():
    admin = UserFactory(role=User.Role.ADMIN)
    learner = UserFactory()
    tag(statement())
    rebuild_library_snapshot()
    with patch("inspinia.pages.catalogue_progress.reverse", wraps=reverse) as reverser:
        context = build_progress_context(request_user=admin, params={"user": str(learner.pk), "mode": "concepts"})
    # The complete seeded catalogue has hundreds of concepts. Reversing its
    # common route per concept must not bring back hundreds of cold lookups.
    assert reverser.call_count <= 12
    assert context["stats"]["total"] == 1
    for row in [*context["progress_page"], *context["practice_rows"]]:
        query = parse_qs(urlsplit(row["url"]).query)
        assert query["user"] == [str(learner.pk)]
        assert query["concept"] == [row["id"]]
        assert query["mode"] == ["problems"]
