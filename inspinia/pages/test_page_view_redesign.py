"""Filter scope and native-form round trips for the compact view dashboard."""

from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from django.urls import reverse

from inspinia.pages.models import PageViewEvent
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class DashboardForms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = {}
        self.ids = []
        self.labels = []
        self.form = None
        self.select = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "label" and values.get("for", "").startswith("page-view-"):
            self.labels.append(values["for"])
        if tag == "form":
            self.form = []
            self.forms[values.get("id")] = self.form
        if self.form is None:
            return
        if tag == "input" and values.get("name"):
            if values.get("type") == "checkbox" and "checked" not in values:
                return
            self.form.append((values["name"], values.get("value", "")))
        if tag == "select":
            self.select = {"name": values["name"], "options": []}
        if tag == "option" and self.select is not None:
            self.select["options"].append((values.get("value", ""), "selected" in values))

    def handle_endtag(self, tag):
        if tag == "select" and self.select is not None:
            options = self.select["options"]
            selected = [value for value, checked in options if checked]
            self.form.append((self.select["name"], selected[0] if selected else options[0][0]))
            self.select = None
        if tag == "form":
            self.form = None


@pytest.mark.parametrize("include_admins", ["", "1"])
@pytest.mark.parametrize("include_anonymous", ["0", "1"])
def test_page_view_redesign_forms_preserve_audience_and_recent_filter_scope(client, include_admins, include_anonymous):
    admin = UserFactory(role=User.Role.ADMIN)
    alpha = UserFactory(name="Alpha Viewer")
    beta = UserFactory(name="Beta Viewer")
    for user, surface, label in [
        (alpha, PageViewEvent.ViewType.SOLUTION, "Alpha geometry"),
        (beta, PageViewEvent.ViewType.LIST, "Beta archive"),
        (admin, PageViewEvent.ViewType.SOLUTION, "Admin geometry"),
        (None, PageViewEvent.ViewType.SOLUTION, "Anonymous geometry"),
    ]:
        PageViewEvent.objects.create(user=user, view_type=surface, label=label, path="/solutions/")
    client.force_login(admin)
    url = reverse("pages:page_view_analytics")
    params = {
        "range": "7d", "include_admins": include_admins, "include_anonymous": include_anonymous,
        "surface": PageViewEvent.ViewType.SOLUTION, "user": str(alpha.pk), "q": "geometry",
    }
    response = client.get(url, params)
    expected_total = 2 + int(include_admins == "1") + int(include_anonymous == "1")
    assert response.context["page_view_stats"]["total"] == expected_total
    assert [row["label"] for row in response.context["page_view_recent_rows"]] == ["Alpha geometry"]
    parser = DashboardForms()
    parser.feed(response.content.decode())
    assert not [value for value, count in Counter(parser.ids).items() if count > 1]
    assert set(parser.labels) <= set(parser.ids)
    for form_id in ["page-view-global-filters", "page-view-recent-filters"]:
        submitted = client.get(url + "?" + urlencode(parser.forms[form_id]))
        assert submitted.context["page_view_stats"] == response.context["page_view_stats"]
        assert submitted.context["page_view_filters"] == response.context["page_view_filters"]
        assert submitted.context["page_view_recent_rows"] == response.context["page_view_recent_rows"]


def test_page_view_redesign_empty_state_keeps_native_date_controls(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    response = client.get(reverse("pages:page_view_analytics"), {"range": "all"})
    html = response.content.decode()
    assert response.context["page_view_stats"]["total"] == 0
    assert "No page views in this range" in html
    assert 'id="page-view-custom-dates"' in html
    assert 'id="page-view-start"' in html
    assert 'id="page-view-end"' in html
    assert 'id="page-view-recent-filters"' not in html
