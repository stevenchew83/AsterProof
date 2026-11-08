"""Chart totals, filter links and claim evidence stay consistent."""

# ruff: noqa: PLR2004 - Explicit counts are chart acceptance criteria.
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from inspinia.rankings.services.student_charts import achievement_charts
from inspinia.rankings.services.student_charts import matches_evidence


def chart_row(year=2025, discipline="unknown", status="unreviewed", *, achievement=True):
    return {"year": year, "discipline": discipline, "evidence_status": status, "claims": [],
            "has_outcome": achievement}


def query(url):
    return parse_qs(urlsplit(url).query)


def test_chart_counts_include_unclassified_and_exclude_nonachievement_records():
    charts = achievement_charts([
        chart_row(2024), chart_row(2025, "mathematics", "verified"),
        chart_row(2025, "computing", "reported"), chart_row(achievement=False),
    ], {}, "/students/1/")
    assert charts["total"] == 3
    assert [(year["year"], year["count"], year["cells"]) for year in charts["years"]] == [
        (2024, 1, [1, 0, 0]), (2025, 2, [0, 1, 1]),
    ]
    assert [item["label"] for item in charts["disciplines"]] == ["Not classified", "Mathematics", "Computing"]
    assert {item["value"]: item["count"] for item in charts["evidence"]} == {
        "verified": 1, "reported": 1, "pending": 0, "conflicting": 0, "unreviewed": 1,
    }


def test_chart_links_preserve_other_filters_and_toggle_their_own_selection():
    filters = {"year": "2025", "discipline": "computing", "evidence": "achievement_verified",
               "q": "A [B] & C", "page": "4"}
    charts = achievement_charts([chart_row(2025, "computing", "verified")], filters, "/students/1/")
    year = charts["years"][0]
    assert query(year["url"]) == {"discipline": ["computing"], "evidence": ["achievement_verified"],
                                 "q": ["A [B] & C"]}
    assert query(year["segments"][0]["url"]) == {"evidence": ["achievement_verified"], "q": ["A [B] & C"]}
    assert query(charts["disciplines"][0]["url"])["year"] == ["2025"]
    verified = next(item for item in charts["evidence"] if item["value"] == "verified")
    assert "evidence" not in query(verified["url"])
    assert verified["active"]


def test_award_filter_never_uses_verified_score_or_secondary_ranking_evidence():
    row = chart_row()
    row["claims"] = [{"kind": "score", "status": "verified"}, {"kind": "ranking", "status": "verified"}]
    assert matches_evidence(row, "verified")  # Existing any-claim filter remains available.
    assert not matches_evidence(row, "achievement_verified")
    assert matches_evidence(row, "achievement_unreviewed")
    row["has_outcome"] = False
    assert not matches_evidence(row, "achievement_unreviewed")


def test_empty_chart_data_has_no_division_by_zero_or_filter_targets():
    charts = achievement_charts([], {}, "/students/1/")
    assert charts["total"] == 0
    assert charts["years"] == charts["disciplines"] == []
    assert all(item["count"] == 0 and item["width"] == "0" for item in charts["evidence"])
