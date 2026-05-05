"""URL builders for dashboard contest drill-down links."""

from urllib.parse import urlencode

from django.urls import reverse
from django.utils.text import slugify


def contest_dashboard_listing_url(contest_name: str, **params: object) -> str:
    """Build ``/dashboard/contests/listing/?contest=...`` with optional extra query keys."""
    extra = {key: value for key, value in params.items() if value not in (None, "")}
    query: dict[str, object] = {"contest": contest_name, **extra}
    return reverse("pages:contest_dashboard_listing") + "?" + urlencode(query, doseq=True)


def problem_anchor(problem_label: str, fallback: str) -> str:
    """Build the stable fragment used by contest dashboard problem rows."""
    return slugify(problem_label) or slugify(fallback) or "problem"


def contest_dashboard_problem_url(
    contest_name: str,
    *,
    year: int,
    problem_label: str,
    fallback: str,
) -> str:
    """Build a contest dashboard URL anchored to one visible problem row."""
    return contest_dashboard_listing_url(contest_name, year=year) + f"#{problem_anchor(problem_label, fallback)}"


def problem_statement_contest_year_master_url(contest_name: str, year: int) -> str:
    """Build the uncapped statement-first master list URL for one contest-year."""
    query = {"contest": contest_name, "year": year}
    return reverse("pages:problem_statement_contest_year_master") + "?" + urlencode(query)
