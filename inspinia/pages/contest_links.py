"""URL builders for dashboard contest drill-down (replaces public /problems/contests/ links)."""

from urllib.parse import urlencode

from django.urls import reverse


def contest_dashboard_listing_url(contest_name: str, **params: object) -> str:
    """Build ``/dashboard/contests/listing/?contest=...`` with optional extra query keys."""
    extra = {key: value for key, value in params.items() if value not in (None, "")}
    query: dict[str, object] = {"contest": contest_name, **extra}
    return reverse("pages:contest_dashboard_listing") + "?" + urlencode(query, doseq=True)


def problem_statement_contest_year_master_url(contest_name: str, year: int) -> str:
    """Build the uncapped statement-first master list URL for one contest-year."""
    query = {"contest": contest_name, "year": year}
    return reverse("pages:problem_statement_contest_year_master") + "?" + urlencode(query)
