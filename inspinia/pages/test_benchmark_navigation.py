"""Catalog navigation keeps the learner's target and clears stale chart filters."""

from http import HTTPStatus
from urllib.parse import parse_qs

import pytest
from django.http import QueryDict
from django.urls import reverse

from inspinia.pages.technique_benchmarking.dashboard import benchmark_navigation_context
from inspinia.users.tests.factories import UserFactory


def navigation(query):
    return benchmark_navigation_context(QueryDict(query), options=[], target_profile="imo_tst")


def test_subject_change_keeps_target_search_and_sort_without_chart_selection():
    context = navigation(
        "area=Number+Theory&scope=shared&view=profiles&family=Old+family"
        "&row_key=method:old&page=3&q=invariant&sort=name&target_profile=imo_tst",
    )

    geometry = next(option for option in context["benchmark_area_options"] if option["label"] == "Geometry")
    assert parse_qs(geometry["query"]) == {
        "area": ["Geometry"], "view": ["profiles"], "q": ["invariant"],
        "sort": ["name"], "target_profile": ["imo_tst"],
    }
    all_subjects = context["benchmark_area_options"][0]
    assert "area" not in parse_qs(all_subjects["query"])


def test_view_change_keeps_subject_scope_and_target_without_chart_selection():
    context = navigation(
        "area=Number+Theory&scope=shared&view=profiles&page=2"
        "&row_key=method:old&family=Old+family&target_profile=imo_tst",
    )

    concepts, profiles = context["benchmark_view_options"]
    assert profiles["selected"] is True
    assert concepts["selected"] is False
    assert parse_qs(concepts["query"]) == {
        "area": ["Number Theory"], "scope": ["shared"], "target_profile": ["imo_tst"],
    }


@pytest.mark.parametrize("query", ["", "area=Geometry", "area=Number+Theory&view=profiles"])
def test_shared_tools_navigation_is_only_available_in_number_theory_concepts(query):
    assert navigation(query)["benchmark_scope_options"] == []


def test_shared_tools_switch_keeps_search_and_target_but_clears_chart_selection():
    context = navigation(
        "area=Number+Theory&scope=shared&family=Old+family&page=3"
        "&row_key=concept:old&q=parity&target_profile=imo_tst",
    )

    core, shared = context["benchmark_scope_options"]
    assert shared["selected"] is True
    assert parse_qs(core["query"]) == {
        "area": ["Number Theory"], "scope": ["core"], "q": ["parity"], "target_profile": ["imo_tst"],
    }


@pytest.mark.django_db
def test_filtered_empty_catalog_offers_filter_recovery(client):
    client.force_login(UserFactory())
    response = client.get(reverse("pages:technique_benchmark_list"), {"q": "no matching concept"})

    assert response.status_code == HTTPStatus.OK
    assert "No matching benchmarks" in response.content.decode()
    assert "No technique benchmarks yet." not in response.content.decode()
    assert response.context["technique_benchmark_total"] == 0
