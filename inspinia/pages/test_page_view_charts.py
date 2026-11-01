# ruff: noqa: PLR2004 -- Literal counts document the synthetic traffic expectations.
from datetime import UTC
from datetime import datetime
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from django.http import QueryDict

from inspinia.pages.models import PageViewEvent
from inspinia.pages.page_view_analytics import build_page_view_analytics_context
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def traffic():
    viewer = UserFactory(name="Reader", email="reader@example.com")
    admin = UserFactory(role=User.Role.ADMIN)
    # The UTC date boundary differs from the dashboard's local midnight.
    for user, hour, minute in [(viewer, 15, 59), (viewer, 16, 0), (None, 16, 0), (admin, 16, 0)]:
        PageViewEvent.objects.create(
            user=user,
            view_type=PageViewEvent.ViewType.SOLUTION,
            path="/solutions/example/",
            created_at=datetime(2026, 10, 4, hour, minute, tzinfo=UTC),
        )
    return viewer


def chart_total(context):
    return sum(sum(series["data"]) for series in context["page_view_charts"]["timeline"]["series"])


def test_charts_zero_fill_days_and_use_local_midnight_consistently(traffic):
    context = build_page_view_analytics_context(QueryDict("range=custom&start=2026-10-04&end=2026-10-06"))
    charts = context["page_view_charts"]
    assert charts["timezone"] == "Asia/Kuala_Lumpur"
    assert charts["timeline"]["labels"] == ["2026-10-04", "2026-10-05", "2026-10-06"]
    solutions = next(series for series in charts["timeline"]["series"] if series["name"] == "Solution")
    assert solutions["data"] == [1, 2, 0]
    heatmap = {row["name"]: row["data"] for row in charts["heatmap"]}
    assert heatmap["Sun"][23]["y"] == 1
    assert heatmap["Mon"][0]["y"] == 2
    assert sum(point["y"] for row in heatmap.values() for point in row) == chart_total(context) == 3
    assert context["page_view_summary"]["active_days"] == 2
    assert context["page_view_summary"]["views_per_day"] == 1.0
    assert context["page_view_summary"]["known_views"] == 2
    assert context["page_view_stats"]["known_user_total"] == 1
    assert charts["mix"]["series"] == [0, 3, 0, 0]


def test_charts_follow_audience_but_keep_recent_filters_local(traffic):
    base = "range=custom&start=2026-10-04&end=2026-10-06"
    context = build_page_view_analytics_context(QueryDict(base + f"&user={traffic.pk}&surface=list&q=missing"))
    assert context["page_view_recent_rows"] == []
    assert chart_total(context) == 3
    audience = build_page_view_analytics_context(QueryDict(base + "&include_admins=1&include_anonymous=0"))
    assert chart_total(audience) == 3
    assert audience["page_view_stats"]["known_user_total"] == 2
    assert audience["page_view_summary"]["known_share"] == 100
    assert audience["page_view_stats"]["anonymous_view_total"] == 0


def test_empty_charts_have_zero_totals_and_complete_hour_grid():
    context = build_page_view_analytics_context(QueryDict("range=7d"))
    assert chart_total(context) == 0
    assert len(context["page_view_charts"]["timeline"]["labels"]) == 7
    assert [len(row["data"]) for row in context["page_view_charts"]["heatmap"]] == [24] * 7
    assert context["page_view_summary"]["active_days"] == 0
    assert context["page_view_summary"]["known_share"] == 0
    assert context["page_view_readers"] == []


@pytest.mark.parametrize(
    ("start", "end", "granularity", "buckets"),
    [("2025-12-15", "2026-11-01", "month", 12), ("2000-01-01", "2026-11-01", "year", 27)],
)
def test_long_ranges_aggregate_without_losing_views(traffic, start, end, granularity, buckets):
    context = build_page_view_analytics_context(QueryDict(f"range=custom&start={start}&end={end}"))
    timeline = context["page_view_charts"]["timeline"]
    assert timeline["granularity"] == granularity
    assert len(timeline["labels"]) == buckets
    assert chart_total(context) == context["page_view_stats"]["total"] == 3


def test_reader_links_preserve_audience_and_dates_and_clear_recent_filters(traffic):
    context = build_page_view_analytics_context(QueryDict(
        "range=custom&start=2026-10-04&end=2026-10-06&include_anonymous=0&surface=list&q=missing",
    ))
    reader = context["page_view_readers"][0]
    assert reader["label"] == "Reader"
    assert reader["total"] == 2
    url = urlparse(reader["url"])
    assert url.fragment == "page-view-recent"
    assert parse_qs(url.query) == {
        "range": ["custom"], "start": ["2026-10-04"], "end": ["2026-10-06"],
        "include_anonymous": ["0"], "user": [str(traffic.pk)],
    }
    active = [group["key"] for group in context["page_view_rankings"] if group["active"]]
    assert active == ["solutions"]
