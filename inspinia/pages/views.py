import re
from collections import Counter
from collections import defaultdict
from datetime import date
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg
from django.db.models import Count
from django.db.models import F
from django.db.models import Max
from django.db.models import Min
from django.db.models import Q
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.asymptote_render import has_asymptote_blocks
from inspinia.pages.contest_rename import ContestRenameValidationError
from inspinia.pages.contest_rename import rename_contests
from inspinia.pages.forms import ContestRenameForm
from inspinia.pages.forms import ProblemStatementImportForm
from inspinia.pages.forms import ProblemXlsxImportForm
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import build_parsed_preview_payload
from inspinia.pages.problem_import import build_problem_export_workbook_bytes
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.pages.statement_import import LATEX_STATEMENT_SAMPLE
from inspinia.pages.statement_import import ProblemStatementImportValidationError
from inspinia.pages.statement_import import ProblemStatementPreviewPayload
from inspinia.pages.statement_import import ProblemStatementSavePreviewPayload
from inspinia.pages.statement_import import build_problem_statement_preview_payload
from inspinia.pages.statement_import import build_problem_statement_save_preview
from inspinia.pages.statement_import import import_problem_statements
from inspinia.pages.statement_import import parse_contest_problem_statements
from inspinia.pages.statement_import import relink_problem_statement_rows
from inspinia.users.models import AuditEvent
from inspinia.users.monitoring import record_event
from inspinia.users.roles import user_has_admin_role

CONTEST_TOPIC_PREVIEW_LIMIT = 3
CONTEST_PROBLEM_PREVIEW_LIMIT = 6
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@login_required
def root_page_view(request):
    can_explore_library = request.user.is_authenticated
    context = {
        "library_access_enabled": can_explore_library,
        "featured_problems": [],
        "landing_highlights": [
            {
                "icon": "ti ti-radar-2",
                "label": "Contest search",
                "tone": "primary",
                "value": "Ready",
                "helper": "The landing experience is wired for contest discovery.",
            },
            {
                "icon": "ti ti-file-description",
                "label": "Problem statements",
                "tone": "warning",
                "value": "Soon",
                "helper": "Statement text can plug into search as soon as it is imported.",
            },
            {
                "icon": "ti ti-tags",
                "label": "Topic tags",
                "tone": "success",
                "value": "Indexed",
                "helper": "Topic tag search is part of the landing page search model.",
            },
            {
                "icon": "ti ti-user-circle",
                "label": "Profile hub",
                "tone": "info",
                "value": "Live",
                "helper": "Profile navigation stays available from the top bar.",
            },
        ],
        "library_overview": {
            "contest_total": 0,
            "problem_total": 0,
            "topic_total": 0,
            "tag_total": 0,
            "year_range_label": "Awaiting dataset import",
        },
        "search_entries": [],
        "trending_contests": [],
        "trending_tags": [],
    }

    if can_explore_library:
        base = ProblemSolveRecord.objects.all()
        overview = base.aggregate(
            contest_total=Count("contest", distinct=True),
            problem_total=Count("id"),
            topic_total=Count("topic", distinct=True),
            year_min=Min("year"),
            year_max=Max("year"),
        )
        tag_total = ProblemTopicTechnique.objects.values("technique").distinct().count()
        year_min = overview["year_min"]
        year_max = overview["year_max"]
        year_range_label = "Awaiting dataset import"
        if year_min is not None and year_max is not None:
            year_range_label = str(year_min) if year_min == year_max else f"{year_min}-{year_max}"

        contest_rows = list(
            base.values("contest")
            .annotate(
                problem_count=Count("id"),
                year_min=Min("year"),
                year_max=Max("year"),
                active_years=Count("year", distinct=True),
                avg_mohs=Avg("mohs"),
            )
            .order_by("-problem_count", "contest"),
        )
        for row in contest_rows:
            row["avg_mohs"] = round(float(row["avg_mohs"] or 0), 1)
            row["year_span_label"] = (
                str(row["year_min"])
                if row["year_min"] == row["year_max"]
                else f"{row['year_min']}-{row['year_max']}"
            )
        contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
            [row["contest"] for row in contest_rows],
        )

        featured_problems = list(
            base.annotate(technique_count=Count("topic_techniques"))
            .values(
                "contest",
                "problem",
                "contest_year_problem",
                "topic",
                "mohs",
                "year",
                "technique_count",
            )
            .order_by("-year", "contest", "problem")[:6],
        )
        all_tag_rows = list(
            ProblemTopicTechnique.objects.values("technique")
            .annotate(problem_count=Count("record", distinct=True))
            .order_by("-problem_count", "technique"),
        )

        context["featured_problems"] = featured_problems
        context["landing_highlights"] = [
            {
                "icon": "ti ti-trophy",
                "label": "Contests tracked",
                "tone": "primary",
                "value": overview["contest_total"],
                "helper": year_range_label,
            },
            {
                "icon": "ti ti-binary-tree-2",
                "label": "Problems indexed",
                "tone": "info",
                "value": overview["problem_total"],
                "helper": "Search covers contest and problem identifiers today.",
            },
            {
                "icon": "ti ti-category-2",
                "label": "Core topics",
                "tone": "success",
                "value": overview["topic_total"],
                "helper": "Distinct root topics already imported into the archive.",
            },
            {
                "icon": "ti ti-tags",
                "label": "Topic tags",
                "tone": "warning",
                "value": tag_total,
                "helper": "Parsed techniques are searchable from the landing bar.",
            },
        ]
        context["library_overview"] = {
            "contest_total": overview["contest_total"],
            "problem_total": overview["problem_total"],
            "topic_total": overview["topic_total"],
            "tag_total": tag_total,
            "year_range_label": year_range_label,
        }
        context["trending_contests"] = contest_rows[:4]
        context["trending_tags"] = all_tag_rows[:8]

        search_entries: list[dict] = []
        search_entries.extend(
            [
                {
                    "description": (
                        f"{row['problem_count']} problems across {row['year_span_label']} "
                        f"with avg MOHS {row['avg_mohs']:.1f}"
                    ),
                    "href": reverse("pages:contest_problem_list", args=[contest_to_slug[row["contest"]]]),
                    "label": row["contest"],
                    "searchable": (
                        f"{row['contest']} {row['problem_count']} "
                        f"{row['year_span_label']} {row['avg_mohs']}"
                    ),
                    "type": "Contest",
                }
                for row in contest_rows
            ],
        )

        for problem_row in base.values(
            "contest",
            "problem",
            "contest_year_problem",
            "topic",
            "mohs",
            "year",
        ).order_by("-year", "contest", "problem"):
            problem_label = (
                problem_row["contest_year_problem"]
                or f"{problem_row['contest']} {problem_row['year']} {problem_row['problem']}"
            )
            search_entries.append(
                {
                    "description": f"{problem_row['topic']} topic - MOHS {problem_row['mohs']}",
                    "href": (
                        reverse("pages:contest_problem_list", args=[contest_to_slug[problem_row["contest"]]])
                        + f"#{_problem_anchor(problem_label, problem_row['problem'])}"
                    ),
                    "label": problem_label,
                    "searchable": (
                        f"{problem_label} {problem_row['contest']} {problem_row['problem']} "
                        f"{problem_row['topic']} {problem_row['year']} {problem_row['mohs']}"
                    ),
                    "type": "Problem",
                },
            )

        search_entries.extend(
            {
                "description": f"Appears in {row['problem_count']} imported problem(s)",
                "href": reverse("pages:problem_list") + f"?{urlencode({'q': row['technique']})}",
                "label": row["technique"],
                "searchable": f"{row['technique']} technique tag",
                "type": "Topic tag",
            }
            for row in all_tag_rows
        )

        context["search_entries"] = search_entries

    return render(request, "pages/index.html", context)


@login_required
def latex_preview_view(request):
    parsed_statement_payload: ProblemStatementPreviewPayload | None = None
    statement_save_preview: ProblemStatementSavePreviewPayload | None = None
    statement_import_result: dict[str, int] | None = None

    if request.method == "POST":
        form = ProblemStatementImportForm(request.POST)
        if form.is_valid():
            action = request.POST.get("action") or "preview"
            source_text = form.cleaned_data["source_text"]
            try:
                parsed_import = parse_contest_problem_statements(source_text)
            except ProblemStatementImportValidationError as exc:
                messages.error(request, str(exc))
            else:
                parsed_statement_payload = build_problem_statement_preview_payload(parsed_import)
                for problem in parsed_statement_payload["problems"]:
                    problem.update(_statement_render_payload(problem["statement_latex"]))
                statement_save_preview = build_problem_statement_save_preview(parsed_import)
                if action == "save":
                    _require_admin_tools_access(request)
                    save_result = import_problem_statements(parsed_import)
                    statement_import_result = {
                        "created_count": save_result.created_count,
                        "linked_problem_count": save_result.linked_problem_count,
                        "updated_count": save_result.updated_count,
                    }
                    messages.success(
                        request,
                        (
                            f"Saved {parsed_statement_payload['problem_count']} problem statement(s): "
                            f"{save_result.created_count} created, {save_result.updated_count} updated, "
                            f"{save_result.linked_problem_count} linked to existing problem rows."
                        ),
                    )
                else:
                    day_total = len(parsed_statement_payload["day_rows"])
                    messages.info(
                        request,
                        (
                            f"Parsed {parsed_statement_payload['problem_count']} problem(s) from "
                            f"{parsed_statement_payload['contest_name']} {parsed_statement_payload['contest_year']} "
                            f"across {day_total} day section(s)."
                        ),
                    )
                    if statement_save_preview["existing_count"] > 0:
                        messages.warning(
                            request,
                            (
                                "Duplicate check: "
                                f"{statement_save_preview['existing_count']} existing row(s) found. "
                                f"Saving will create {statement_save_preview['create_count']} row(s), "
                                f"update {statement_save_preview['update_count']} row(s), and "
                                f"refresh {statement_save_preview['unchanged_count']} identical row(s) "
                                "without inserting duplicate contest/problem keys."
                            ),
                        )
    else:
        form = ProblemStatementImportForm(initial={"source_text": LATEX_STATEMENT_SAMPLE})

    return render(
        request,
        "pages/latex-preview.html",
        {
            "form": form,
            "latex_preview_sample": LATEX_STATEMENT_SAMPLE,
            "parsed_statement_payload": parsed_statement_payload,
            "statement_save_preview": statement_save_preview,
            "statement_import_result": statement_import_result,
        },
    )


@login_required
def statement_render_preview_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required.", "ok": False}, status=405)

    statement_latex = request.POST.get("source_text", "")
    render_payload = _statement_render_payload(statement_latex)
    html = render_to_string(
        "partials/statement-render-content.html",
        {"segments": render_payload["statement_render_segments"]},
        request=request,
    )
    return JsonResponse(
        {
            "has_asymptote": render_payload["statement_has_asymptote"],
            "html": html,
            "ok": True,
        },
    )


def _rows_to_bar_payload(
    rows: list[dict],
    label_key: str,
    *,
    value_key: str = "c",
    decimals: int | None = None,
) -> dict:
    values: list[int | float] = []
    for row in rows:
        raw_value = row.get(value_key)
        if raw_value is None:
            values.append(0 if decimals is None else 0.0)
            continue
        if decimals is None:
            values.append(int(raw_value))
        else:
            values.append(round(float(raw_value), decimals))
    return {
        "labels": [str(r[label_key]) for r in rows],
        "values": values,
    }


def _statement_preview_text(statement_latex: str, *, max_length: int = 220) -> str:
    collapsed = re.sub(r"\s+", " ", statement_latex.strip())
    if len(collapsed) <= max_length:
        return collapsed
    return f"{collapsed[: max_length - 1].rstrip()}…"


def _statement_render_payload(statement_latex: str) -> dict:
    return {
        "statement_has_asymptote": has_asymptote_blocks(statement_latex),
        "statement_render_segments": build_statement_render_segments(statement_latex),
    }


def _statement_table_rows(base) -> list[dict]:
    linked_statement_rows = list(
        base.filter(linked_problem__isnull=False).values_list("linked_problem_id", "linked_problem__contest"),
    )
    linked_problem_ids = sorted({row[0] for row in linked_statement_rows if row[0] is not None})
    linked_contest_names = [row[1] for row in linked_statement_rows if row[1]]
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(linked_contest_names)
    topic_tag_rows = list(
        ProblemTopicTechnique.objects.filter(record_id__in=linked_problem_ids)
        .values("record_id", "technique")
        .order_by("technique", "record_id"),
    )
    topic_tags_by_problem_id: dict[int, list[str]] = defaultdict(list)
    seen_topic_tags_by_problem_id: dict[int, set[str]] = defaultdict(set)
    for tag_row in topic_tag_rows:
        record_id = tag_row["record_id"]
        technique = tag_row["technique"]
        if technique in seen_topic_tags_by_problem_id[record_id]:
            continue
        seen_topic_tags_by_problem_id[record_id].add(technique)
        topic_tags_by_problem_id[record_id].append(technique)

    def _build_filter_url(base_url: str, **params: object) -> str:
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        if not clean_params:
            return base_url
        return f"{base_url}?{urlencode(clean_params)}"

    table_rows: list[dict] = []
    for statement in base.select_related("linked_problem").order_by(
        "-updated_at",
        "-id",
    ):
        linked_problem = statement.linked_problem
        linked_problem_label = ""
        linked_problem_url = ""
        linked_problem_topic_tags: list[str] = []
        linked_problem_topic_tag_links: list[dict[str, str]] = []
        linked_problem_mohs = None
        linked_problem_mohs_url = ""
        linked_problem_confidence = ""
        linked_problem_confidence_url = ""
        linked_problem_imo_slot_guess_value = ""
        linked_problem_imo_slot_url = ""
        if linked_problem is not None:
            linked_problem_label = linked_problem.contest_year_problem or (
                f"{linked_problem.contest} {linked_problem.year} {linked_problem.problem}"
            )
            linked_problem_topic_tags = topic_tags_by_problem_id.get(linked_problem.id, [])
            linked_problem_mohs = linked_problem.mohs
            linked_problem_confidence = linked_problem.confidence or ""
            linked_problem_imo_slot_guess_value = linked_problem.imo_slot_guess_value or ""
            contest_slug = contest_to_slug.get(linked_problem.contest)
            if contest_slug:
                contest_filter_base_url = reverse("pages:contest_problem_list", args=[contest_slug])
                linked_problem_url = contest_filter_base_url + "#" + (
                    _problem_anchor(
                        linked_problem_label,
                        f"{linked_problem.year}-{linked_problem.problem}",
                    )
                )
                linked_problem_topic_tag_links = [
                    {
                        "label": technique,
                        "url": _build_filter_url(contest_filter_base_url, tag=technique),
                    }
                    for technique in linked_problem_topic_tags
                ]
                linked_problem_mohs_url = _build_filter_url(contest_filter_base_url, mohs=linked_problem.mohs)
                linked_problem_confidence_url = (
                    _build_filter_url(contest_filter_base_url, q=linked_problem_confidence)
                    if linked_problem_confidence
                    else ""
                )
                linked_problem_imo_slot_url = (
                    _build_filter_url(contest_filter_base_url, q=linked_problem_imo_slot_guess_value)
                    if linked_problem_imo_slot_guess_value
                    else ""
                )

        table_rows.append(
            {
                "contest_name": statement.contest_name,
                "contest_year": statement.contest_year,
                "contest_year_problem": statement.contest_year_problem,
                "day_label": statement.day_label or "Unlabeled",
                "is_linked": linked_problem is not None,
                "linked_problem_label": linked_problem_label,
                "linked_problem_url": linked_problem_url,
                "problem_code": statement.problem_code,
                "problem_uuid": str(statement.problem_uuid),
                "linked_problem_mohs": linked_problem_mohs,
                "linked_problem_mohs_url": linked_problem_mohs_url,
                "linked_problem_confidence": linked_problem_confidence,
                "linked_problem_confidence_url": linked_problem_confidence_url,
                "linked_problem_imo_slot_guess_value": linked_problem_imo_slot_guess_value,
                "linked_problem_imo_slot_url": linked_problem_imo_slot_url,
                "linked_problem_topic_tags": linked_problem_topic_tags,
                "linked_problem_topic_tag_links": linked_problem_topic_tag_links,
                "statement_length": len(statement.statement_latex),
                "statement_preview": _statement_preview_text(statement.statement_latex),
                "updated_at": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d %H:%M"),
                "updated_at_sort": statement.updated_at.isoformat(),
            },
        )

    return table_rows


def _statement_dashboard_rows(base) -> list[dict]:
    rows = list(
        base.values("contest_name", "contest_year")
        .annotate(
            statement_count=Count("id"),
            linked_count=Count("id", filter=Q(linked_problem__isnull=False)),
            last_updated=Max("updated_at"),
        )
        .order_by("-contest_year", "contest_name"),
    )

    for row in rows:
        statement_count = int(row["statement_count"] or 0)
        linked_count = int(row["linked_count"] or 0)
        row["contest_year_label"] = f"{row['contest_name']} {row['contest_year']}"
        row["statement_count"] = statement_count
        row["linked_count"] = linked_count
        row["unlinked_count"] = statement_count - linked_count
        row["link_rate"] = round((linked_count / statement_count) * 100, 2) if statement_count else 0.0
        row["last_updated_label"] = (
            timezone.localtime(row["last_updated"]).strftime("%Y-%m-%d %H:%M")
            if row["last_updated"] is not None
            else ""
        )

    rows.sort(
        key=lambda row: (
            -row["statement_count"],
            -int(row["contest_year"]),
            row["contest_name"],
        ),
    )
    return rows


def _statement_heatmap_payload(rows: list[dict]) -> dict[str, object]:
    if not rows:
        return {"max_value": 0, "series": [], "years": []}

    years = sorted({int(row["contest_year"]) for row in rows})
    statement_count_by_contest_year: dict[str, dict[int, int]] = defaultdict(dict)
    contest_totals: dict[str, int] = defaultdict(int)

    for row in rows:
        contest_name = row["contest_name"]
        contest_year = int(row["contest_year"])
        statement_count = int(row["statement_count"] or 0)
        statement_count_by_contest_year[contest_name][contest_year] = statement_count
        contest_totals[contest_name] += statement_count

    ordered_contests = sorted(
        contest_totals,
        key=lambda contest_name: (-contest_totals[contest_name], contest_name),
    )
    max_value = max(int(row["statement_count"] or 0) for row in rows)

    return {
        "max_value": max_value,
        "series": [
            {
                "data": [
                    {
                        "x": str(year),
                        "y": statement_count_by_contest_year[contest_name].get(year, 0),
                    }
                    for year in years
                ],
                "name": contest_name,
            }
            for contest_name in ordered_contests
        ],
        "years": [str(year) for year in years],
    }


def _statement_year_bar_payload(rows: list[dict]) -> dict[str, object]:
    if not rows:
        return {"labels": [], "values": []}

    year_totals: dict[int, int] = defaultdict(int)
    for row in rows:
        year_totals[int(row["contest_year"])] += int(row["statement_count"] or 0)

    years = sorted(year_totals)
    return {"labels": [str(year) for year in years], "values": [year_totals[year] for year in years]}


def _shift_month(value: date, offset: int) -> date:
    month_index = (value.year * 12 + value.month - 1) + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _completion_heatmap_level(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    return min(4, max(1, -(-count * 4 // max_count)))


def _user_completion_heatmap_payload(
    completion_dates: list[date],
    *,
    end_date: date,
    day_window: int = 365,
) -> dict[str, object]:
    start_date = end_date - timedelta(days=day_window - 1)
    grid_start = start_date - timedelta(days=start_date.weekday())
    grid_end = end_date + timedelta(days=(6 - end_date.weekday()))
    counts_by_day = Counter(
        completion_date
        for completion_date in completion_dates
        if start_date <= completion_date <= end_date
    )
    max_count = max(counts_by_day.values(), default=0)
    month_labels: list[str] = []
    weeks: list[dict[str, object]] = []
    current_day = grid_start

    while current_day <= grid_end:
        week_days: list[dict[str, object]] = []
        week_dates = [current_day + timedelta(days=offset) for offset in range(7)]
        month_label = next(
            (
                week_day.strftime("%b")
                for week_day in week_dates
                if start_date <= week_day <= end_date and week_day.day == 1
            ),
            "",
        )
        month_labels.append(month_label)
        for week_day in week_dates:
            in_range = start_date <= week_day <= end_date
            count = counts_by_day.get(week_day, 0) if in_range else 0
            tooltip = ""
            if in_range:
                tooltip = (
                    f"{count} completion{'s' if count != 1 else ''} on "
                    f"{week_day.isoformat()}"
                )
            week_days.append(
                {
                    "count": count,
                    "date_label": week_day.isoformat(),
                    "in_range": in_range,
                    "level": _completion_heatmap_level(count, max_count),
                    "tooltip": tooltip,
                },
            )
        weeks.append({"days": week_days})
        current_day += timedelta(days=7)

    return {
        "day_labels": ["Mon", "", "Wed", "", "Fri", "", ""],
        "end_label": end_date.isoformat(),
        "max_count": max_count,
        "month_labels": month_labels,
        "start_label": start_date.isoformat(),
        "total_in_window": sum(counts_by_day.values()),
        "weeks": weeks,
    }


def _user_completion_monthly_bar_payload(
    completion_dates: list[date],
    *,
    end_date: date,
    month_window: int = 12,
) -> dict[str, object]:
    end_month = date(end_date.year, end_date.month, 1)
    month_starts = [
        _shift_month(end_month, offset)
        for offset in range(-(month_window - 1), 1)
    ]
    counts_by_month = Counter(
        date(completion_date.year, completion_date.month, 1)
        for completion_date in completion_dates
    )
    return {
        "labels": [month_start.strftime("%b %Y") for month_start in month_starts],
        "values": [counts_by_month.get(month_start, 0) for month_start in month_starts],
    }


def _user_completion_table_rows(completions: list[UserProblemCompletion]) -> tuple[list[dict], dict[str, list]]:
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [completion.problem.contest for completion in completions],
    )
    table_rows: list[dict] = []
    completion_years: set[str] = set()
    contests: set[str] = set()
    topics: set[str] = set()
    mohs_values: set[int] = set()
    has_known_dates = False
    has_unknown_dates = False

    for completion in completions:
        problem = completion.problem
        problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
        contest_slug = contest_to_slug.get(problem.contest)
        problem_url = ""
        if contest_slug:
            problem_url = reverse("pages:contest_problem_list", args=[contest_slug]) + "#" + (
                _problem_anchor(problem_label, f"{problem.year}-{problem.problem}")
            )

        completion_known = completion.completion_date is not None
        completion_date_label = completion.completion_date.isoformat() if completion_known else "Unknown"
        completion_date_sort = completion.completion_date.isoformat() if completion_known else "0000-00-00"
        completion_year = str(completion.completion_date.year) if completion_known else ""
        date_status = "Known date" if completion_known else "Unknown date"
        if completion_known:
            has_known_dates = True
            completion_years.add(completion_year)
        else:
            has_unknown_dates = True

        contests.add(problem.contest)
        topics.add(problem.topic)
        mohs_values.add(problem.mohs)
        table_rows.append(
            {
                "completion_date": completion_date_label,
                "completion_date_sort": completion_date_sort,
                "completion_known": completion_known,
                "completion_year": completion_year,
                "contest": problem.contest,
                "date_status": date_status,
                "mohs": problem.mohs,
                "problem_code": problem.problem,
                "problem_label": problem_label,
                "problem_url": problem_url,
                "problem_uuid": str(problem.problem_uuid),
                "problem_year": problem.year,
                "topic": problem.topic,
            },
        )

    filter_options = {
        "completion_years": sorted(completion_years, reverse=True),
        "contests": sorted(contests),
        "date_statuses": [
            label
            for label, present in (
                ("Known date", has_known_dates),
                ("Unknown date", has_unknown_dates),
            )
            if present
        ],
        "mohs_values": sorted(mohs_values),
        "topics": sorted(topics),
    }
    return table_rows, filter_options


def _require_admin_tools_access(request) -> None:
    if not settings.DEBUG and not user_has_admin_role(request.user):
        raise PermissionDenied


def _problem_table_rows(base, *, include_listing_fields: bool = False) -> list[dict]:
    fields = [
        "year",
        "topic",
        "mohs",
        "contest",
        "problem",
        "contest_year_problem",
        "technique_count",
    ]
    if include_listing_fields:
        fields.extend(["confidence", "imo_slot_guess_value"])

    return list(
        base.annotate(technique_count=Count("topic_techniques"))
        .values(*fields)
        .order_by("-year", "contest", "problem"),
    )


def _build_contest_slug_maps(contest_names: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    contest_to_slug: dict[str, str] = {}
    slug_to_contest: dict[str, str] = {}

    for contest_name in sorted({name for name in contest_names if name}):
        base_slug = slugify(contest_name) or "contest"
        contest_slug = base_slug
        suffix = 2
        while contest_slug in slug_to_contest:
            contest_slug = f"{base_slug}-{suffix}"
            suffix += 1
        contest_to_slug[contest_name] = contest_slug
        slug_to_contest[contest_slug] = contest_name

    return contest_to_slug, slug_to_contest


def _format_year_span_label(year_min: int | None, year_max: int | None) -> str | None:
    if year_min is None or year_max is None:
        return None
    return str(year_min) if year_min == year_max else f"{year_min}-{year_max}"


def _contest_inventory_rows() -> list[dict]:
    inventory: dict[str, dict] = {}

    for row in (
        ProblemSolveRecord.objects.values("contest")
        .annotate(
            problem_count=Count("id"),
            problem_year_min=Min("year"),
            problem_year_max=Max("year"),
        )
        .order_by("contest")
    ):
        contest_name = row["contest"]
        inventory[contest_name] = {
            "contest": contest_name,
            "problem_count": row["problem_count"],
            "problem_year_min": row["problem_year_min"],
            "problem_year_max": row["problem_year_max"],
            "statement_count": 0,
            "statement_year_min": None,
            "statement_year_max": None,
        }

    for row in (
        ContestProblemStatement.objects.values("contest_name")
        .annotate(
            statement_count=Count("id"),
            statement_year_min=Min("contest_year"),
            statement_year_max=Max("contest_year"),
        )
        .order_by("contest_name")
    ):
        contest_name = row["contest_name"]
        inventory_row = inventory.setdefault(
            contest_name,
            {
                "contest": contest_name,
                "problem_count": 0,
                "problem_year_min": None,
                "problem_year_max": None,
                "statement_count": 0,
                "statement_year_min": None,
                "statement_year_max": None,
            },
        )
        inventory_row["statement_count"] = row["statement_count"]
        inventory_row["statement_year_min"] = row["statement_year_min"]
        inventory_row["statement_year_max"] = row["statement_year_max"]

    rows: list[dict] = []
    for inventory_row in inventory.values():
        year_candidates = [
            year
            for year in (
                inventory_row["problem_year_min"],
                inventory_row["problem_year_max"],
                inventory_row["statement_year_min"],
                inventory_row["statement_year_max"],
            )
            if year is not None
        ]
        overall_year_min = min(year_candidates) if year_candidates else None
        overall_year_max = max(year_candidates) if year_candidates else None
        inventory_row["problem_year_span_label"] = _format_year_span_label(
            inventory_row["problem_year_min"],
            inventory_row["problem_year_max"],
        )
        inventory_row["statement_year_span_label"] = _format_year_span_label(
            inventory_row["statement_year_min"],
            inventory_row["statement_year_max"],
        )
        inventory_row["year_span_label"] = _format_year_span_label(overall_year_min, overall_year_max)
        rows.append(inventory_row)

    return sorted(
        rows,
        key=lambda row: (-row["problem_count"], -row["statement_count"], row["contest"].lower()),
    )


def _problem_sort_key(problem_label: str | None) -> list[tuple[int, int | str]]:
    parts = re.split(r"(\d+)", str(problem_label or ""))
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in parts
        if part
    ]


def _problem_anchor(problem_label: str, fallback: str) -> str:
    return slugify(problem_label) or slugify(fallback) or "problem"


def _build_contest_directory_rows(base) -> list[dict]:
    contest_rows = list(
        base.values("contest")
        .annotate(
            active_years=Count("year", distinct=True),
            avg_mohs=Avg("mohs"),
            distinct_topics=Count("topic", distinct=True),
            problem_count=Count("id"),
            year_max=Max("year"),
            year_min=Min("year"),
        )
        .order_by("-problem_count", "contest"),
    )
    if not contest_rows:
        return []

    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [row["contest"] for row in contest_rows],
    )
    statement_rows = list(
        ContestProblemStatement.objects.filter(
            linked_problem__contest__in=[row["contest"] for row in contest_rows],
        )
        .values("linked_problem__contest")
        .annotate(
            statement_problem_count=Count("linked_problem_id", distinct=True),
            statement_year_total=Count("contest_year", distinct=True),
        )
        .order_by("linked_problem__contest"),
    )
    statements_by_contest = {
        row["linked_problem__contest"]: row
        for row in statement_rows
    }

    topic_rows = list(
        base.values("contest", "topic")
        .annotate(problem_count=Count("id"))
        .order_by("contest", "-problem_count", "topic"),
    )
    topics_by_contest: dict[str, list[str]] = defaultdict(list)
    for row in topic_rows:
        topic_list = topics_by_contest[row["contest"]]
        if len(topic_list) < CONTEST_TOPIC_PREVIEW_LIMIT:
            topic_list.append(row["topic"])

    preview_rows = list(
        base.values(
            "contest",
            "contest_year_problem",
            "problem",
            "topic",
            "year",
        ).order_by("contest", "-year", "problem"),
    )
    previews_by_contest: dict[str, list[dict]] = defaultdict(list)
    for row in preview_rows:
        preview_list = previews_by_contest[row["contest"]]
        if len(preview_list) >= CONTEST_PROBLEM_PREVIEW_LIMIT:
            continue
        label = row["contest_year_problem"] or f"{row['contest']} {row['year']} {row['problem']}"
        preview_list.append(
            {
                "label": label,
                "problem": row["problem"],
                "topic": row["topic"],
                "year": row["year"],
            },
        )

    for row in contest_rows:
        statement_row = statements_by_contest.get(row["contest"], {})
        row["slug"] = contest_to_slug[row["contest"]]
        row["avg_mohs"] = round(float(row["avg_mohs"] or 0), 1)
        row["year_span_label"] = (
            str(row["year_min"])
            if row["year_min"] == row["year_max"]
            else f"{row['year_min']}-{row['year_max']}"
        )
        row["statement_problem_count"] = int(statement_row.get("statement_problem_count") or 0)
        row["statement_year_total"] = int(statement_row.get("statement_year_total") or 0)
        row["has_statements"] = row["statement_problem_count"] > 0
        row["top_topics"] = topics_by_contest.get(row["contest"], [])
        row["preview_problems"] = previews_by_contest.get(row["contest"], [])

    contest_rows.sort(
        key=lambda row: (
            -int(row["has_statements"]),
            -row["statement_problem_count"],
            -row["problem_count"],
            row["contest"],
        ),
    )
    return contest_rows


def _build_topic_tag_directory_rows(
    tag_rows: list[ProblemTopicTechnique],
) -> list[dict]:
    buckets: dict[str, dict] = {}

    for tag_row in tag_rows:
        record = tag_row.record
        bucket = buckets.setdefault(
            tag_row.technique,
            {
                "technique": tag_row.technique,
                "problem_count": 0,
                "contest_names": set(),
                "contest_counts": defaultdict(int),
                "domain_names": set(),
                "mohs_values": [],
                "year_values": set(),
            },
        )
        bucket["problem_count"] += 1
        bucket["contest_names"].add(record.contest)
        bucket["contest_counts"][record.contest] += 1
        bucket["domain_names"].update(tag_row.domains or [])
        bucket["mohs_values"].append(record.mohs)
        bucket["year_values"].add(record.year)

    directory_rows: list[dict] = []
    for technique, bucket in buckets.items():
        contest_names = sorted(bucket["contest_names"])
        domain_names = sorted(bucket["domain_names"])
        year_values = sorted(bucket["year_values"])
        year_min = year_values[0]
        year_max = year_values[-1]
        sample_contests = [
            contest_name
            for contest_name, _count in sorted(
                bucket["contest_counts"].items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        ]
        directory_rows.append(
            {
                "technique": technique,
                "problem_count": bucket["problem_count"],
                "contest_count": len(contest_names),
                "domain_count": len(domain_names),
                "domains_label": ", ".join(domain_names),
                "active_years": len(year_values),
                "year_min": year_min,
                "year_max": year_max,
                "year_span_label": str(year_min) if year_min == year_max else f"{year_min}-{year_max}",
                "avg_mohs": round(sum(bucket["mohs_values"]) / len(bucket["mohs_values"]), 2),
                "max_mohs": max(bucket["mohs_values"]),
                "sample_contests_label": ", ".join(sample_contests),
            },
        )

    directory_rows.sort(key=lambda row: (-row["problem_count"], row["technique"]))
    return directory_rows


@login_required
def user_activity_dashboard_view(request):
    """Logged-in user's personal completion dashboard."""
    completion_qs = UserProblemCompletion.objects.filter(user=request.user).select_related("problem").order_by(
        F("completion_date").desc(nulls_last=True),
        "-updated_at",
        "problem__contest",
        "-problem__year",
        "problem__problem",
    )
    completions = list(completion_qs)
    today = timezone.localdate()
    dated_completion_dates = [
        completion.completion_date
        for completion in completions
        if completion.completion_date is not None
    ]
    table_rows, filter_options = _user_completion_table_rows(completions)
    current_year_total = sum(
        1
        for completion_date in dated_completion_dates
        if completion_date.year == today.year
    )

    context = {
        "activity_total": len(completions),
        "activity_stats": {
            "contest_total": len({completion.problem.contest for completion in completions}),
            "current_year_total": current_year_total,
            "dated_total": len(dated_completion_dates),
            "latest_completion_date": max(dated_completion_dates, default=None),
            "unknown_date_total": len(completions) - len(dated_completion_dates),
        },
        "activity_filter_options": filter_options,
        "activity_heatmap": _user_completion_heatmap_payload(
            dated_completion_dates,
            end_date=today,
        ),
        "activity_month_window_label": (
            f"{_shift_month(date(today.year, today.month, 1), -11).strftime('%b %Y')} - "
            f"{date(today.year, today.month, 1).strftime('%b %Y')}"
        ),
        "activity_charts_payload": {
            "completionsByMonth": _user_completion_monthly_bar_payload(
                dated_completion_dates,
                end_date=today,
            ),
        },
        "activity_table_rows": table_rows,
    }
    return render(request, "pages/user-activity-dashboard.html", context)


@login_required
def dashboard_analytics_view(request):
    """Problem analytics: charts plus searchable table."""
    _require_admin_tools_access(request)

    base = ProblemSolveRecord.objects.all()
    total = base.count()

    stats = base.aggregate(
        year_min=Min("year"),
        year_max=Max("year"),
        contest_n=Count("contest", distinct=True),
        topic_n=Count("topic", distinct=True),
    )
    technique_total = ProblemTopicTechnique.objects.count()

    by_year = list(base.values("year").annotate(c=Count("id")).order_by("year"))
    by_topic = list(base.values("topic").annotate(c=Count("id")).order_by("-c")[:18])
    by_contest = list(base.values("contest").annotate(c=Count("id")).order_by("-c")[:12])
    by_mohs = list(base.values("mohs").annotate(c=Count("id")).order_by("mohs"))
    top_techniques = list(
        ProblemTopicTechnique.objects.values("technique")
        .annotate(c=Count("id"))
        .order_by("-c")[:18],
    )

    charts_payload = {
        "byYear": _rows_to_bar_payload(by_year, "year"),
        "byTopic": _rows_to_bar_payload(by_topic, "topic"),
        "byContest": _rows_to_bar_payload(by_contest, "contest"),
        "byMohs": _rows_to_bar_payload(by_mohs, "mohs"),
        "topTechniques": _rows_to_bar_payload(top_techniques, "technique"),
    }

    table_rows = _problem_table_rows(base)

    context = {
        "analytics_total": total,
        "analytics_stats": stats,
        "analytics_technique_total": technique_total,
        "charts_payload": charts_payload,
        "table_rows": table_rows,
    }
    return render(request, "pages/dashboard-analytics.html", context)


@login_required
def problem_statement_list_view(request):
    """Statement library listing with shared problem UUIDs and link status."""
    if request.method == "POST" and request.POST.get("action") == "recheck_links":
        _require_admin_tools_access(request)
        relink_result = relink_problem_statement_rows()
        messages.success(
            request,
            (
                f"Rechecked {relink_result.checked_count} statement row(s): "
                f"{relink_result.linked_count} linked, "
                f"{relink_result.newly_linked_count} newly linked, "
                f"{relink_result.skipped_count} skipped, "
                f"{relink_result.unlinked_count} still unlinked, "
                f"{relink_result.updated_count} updated."
            ),
        )
        return redirect("pages:problem_statement_list")

    base = ContestProblemStatement.objects.all()
    statement_total = base.count()
    linked_total = base.filter(linked_problem__isnull=False).count()
    contest_total = base.values("contest_name").distinct().count()
    year_bounds = base.aggregate(year_min=Min("contest_year"), year_max=Max("contest_year"))

    year_min = year_bounds["year_min"]
    year_max = year_bounds["year_max"]
    year_range_label = "Awaiting statement import"
    if year_min is not None and year_max is not None:
        year_range_label = str(year_min) if year_min == year_max else f"{year_min}-{year_max}"

    context = {
        "statement_total": statement_total,
        "statement_stats": {
            "contest_total": contest_total,
            "linked_total": linked_total,
            "unlinked_total": statement_total - linked_total,
            "year_range_label": year_range_label,
        },
        "statement_table_rows": _statement_table_rows(base) if statement_total else [],
    }
    return render(request, "pages/problem-statement-list.html", context)


@login_required
def problem_statement_analytics_view(request):
    """Contest-year statement analytics focused on archive coverage per import set."""
    _require_admin_tools_access(request)

    base = ContestProblemStatement.objects.all()
    statement_total = base.count()
    dashboard_rows = _statement_dashboard_rows(base)
    statement_set_total = len(dashboard_rows)
    contest_total = base.values("contest_name").distinct().count()
    linked_total = base.filter(linked_problem__isnull=False).count()
    year_bounds = base.aggregate(year_min=Min("contest_year"), year_max=Max("contest_year"))

    year_min = year_bounds["year_min"]
    year_max = year_bounds["year_max"]
    year_range_label = "Awaiting statement import"
    if year_min is not None and year_max is not None:
        year_range_label = str(year_min) if year_min == year_max else f"{year_min}-{year_max}"

    average_statements_per_set = round(statement_total / statement_set_total, 2) if statement_set_total else 0.0
    overall_link_rate = round((linked_total / statement_total) * 100, 2) if statement_total else 0.0

    biggest_set = dashboard_rows[0] if dashboard_rows else None
    best_linked_set = (
        max(
            dashboard_rows,
            key=lambda row: (row["link_rate"], row["linked_count"], row["statement_count"], row["contest_year_label"]),
        )
        if dashboard_rows
        else None
    )
    biggest_backlog_set = (
        max(
            dashboard_rows,
            key=lambda row: (row["unlinked_count"], row["statement_count"], row["contest_year_label"]),
        )
        if dashboard_rows
        else None
    )
    newest_set = (
        max(
            dashboard_rows,
            key=lambda row: (row["contest_year"], row["statement_count"], row["contest_year_label"]),
        )
        if dashboard_rows
        else None
    )

    charts_payload = {
        "statementCountHeatmap": _statement_heatmap_payload(dashboard_rows),
        "statementYearBarChart": _statement_year_bar_payload(dashboard_rows),
    }

    context = {
        "statement_dashboard_total": statement_set_total,
        "statement_dashboard_statement_total": statement_total,
        "statement_dashboard_stats": {
            "average_statements_per_set": average_statements_per_set,
            "contest_total": contest_total,
            "linked_total": linked_total,
            "overall_link_rate": overall_link_rate,
            "year_range_label": year_range_label,
        },
        "statement_dashboard_leaders": {
            "biggest": biggest_set,
            "best_linked": best_linked_set,
            "biggest_backlog": biggest_backlog_set,
            "newest": newest_set,
        },
        "statement_dashboard_rows": dashboard_rows,
        "charts_payload": charts_payload,
    }
    return render(request, "pages/problem-statement-analytics.html", context)


@login_required
def problem_list_view(request):
    """Contest-first problem explorer for browsing the imported archive."""
    base = ProblemSolveRecord.objects.all()
    contest_directory = _build_contest_directory_rows(base)
    statement_ready_total = sum(1 for row in contest_directory if row["has_statements"])

    stats = base.aggregate(
        contest_n=Count("contest", distinct=True),
        problem_n=Count("id"),
        topic_n=Count("topic", distinct=True),
        year_min=Min("year"),
        year_max=Max("year"),
    )
    year_min = stats["year_min"]
    year_max = stats["year_max"]
    year_range_label = "Awaiting dataset import"
    if year_min is not None and year_max is not None:
        year_range_label = str(year_min) if year_min == year_max else f"{year_min}-{year_max}"

    initial_search_query = (request.GET.get("q") or "").strip()
    if initial_search_query:
        query = initial_search_query.lower()
        contest_directory = [
            row
            for row in contest_directory
            if query
            in " ".join(
                [
                    row["contest"],
                    row["year_span_label"],
                    *row["top_topics"],
                    *(preview["label"] for preview in row["preview_problems"]),
                ],
            ).lower()
        ]

    context = {
        "contest_directory": contest_directory,
        "problem_listing_total": stats["problem_n"],
        "problem_listing_stats": {
            "contest_total": stats["contest_n"],
            "statement_ready_total": statement_ready_total,
            "year_range_label": year_range_label,
        },
        "initial_search_query": initial_search_query,
        "visible_contest_total": len(contest_directory),
    }
    return render(request, "pages/problem-list.html", context)


@login_required
def contest_problem_list_view(request, contest_slug: str):
    """Checklist-style drill-down for one contest, grouped by year."""
    base = ProblemSolveRecord.objects.all()
    _contest_to_slug, slug_to_contest = _build_contest_slug_maps(
        list(base.values_list("contest", flat=True).distinct()),
    )
    contest_name = slug_to_contest.get(contest_slug)
    if contest_name is None:
        msg = "Contest not found."
        raise Http404(msg)

    contest_base = base.filter(contest=contest_name)
    stats = contest_base.aggregate(
        avg_mohs=Avg("mohs"),
        problem_n=Count("id"),
        topic_n=Count("topic", distinct=True),
        year_max=Max("year"),
        year_min=Min("year"),
    )
    if not stats["problem_n"]:
        msg = "Contest has no problems."
        raise Http404(msg)

    initial_search_query = (request.GET.get("q") or "").strip()
    selected_mohs = (request.GET.get("mohs") or "").strip()
    selected_year = (request.GET.get("year") or "").strip()
    selected_topic = (request.GET.get("topic") or "").strip()
    selected_tag = (request.GET.get("tag") or "").strip()
    statement_by_problem_id: dict[int, dict] = {}
    for statement in (
        ContestProblemStatement.objects.filter(linked_problem__contest=contest_name)
        .select_related("linked_problem")
        .order_by("-updated_at", "-contest_year", "day_label", "problem_number")
    ):
        if statement.linked_problem_id in statement_by_problem_id:
            continue
        render_payload = _statement_render_payload(statement.statement_latex)
        statement_by_problem_id[statement.linked_problem_id] = {
            "day_label": statement.day_label or "",
            "statement_has_asymptote": render_payload["statement_has_asymptote"],
            "statement_latex": statement.statement_latex,
            "statement_render_segments": render_payload["statement_render_segments"],
            "updated_at_label": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d"),
        }

    topic_tag_rows = list(
        ProblemTopicTechnique.objects.filter(record__contest=contest_name)
        .values("record_id", "technique", "domains")
        .order_by("technique", "record_id"),
    )
    topic_tags_by_problem_id: dict[int, list[dict]] = defaultdict(list)
    topic_tag_options: list[str] = []
    seen_topic_tags: set[str] = set()
    for tag_row in topic_tag_rows:
        technique = tag_row["technique"]
        domains = tag_row.get("domains") or []
        topic_tags_by_problem_id[tag_row["record_id"]].append(
            {
                "domains": domains,
                "domains_label": ", ".join(domains),
                "technique": technique,
            },
        )
        if technique not in seen_topic_tags:
            seen_topic_tags.add(technique)
            topic_tag_options.append(technique)

    problem_rows = list(
        contest_base.annotate(technique_count=Count("topic_techniques"))
        .values(
            "id",
            "contest_year_problem",
            "confidence",
            "imo_slot_guess_value",
            "mohs",
            "problem",
            "problem_uuid",
            "technique_count",
            "topic",
            "year",
        ),
    )
    problem_rows.sort(
        key=lambda row: (
            -int(row["year"]),
            0 if row["id"] in statement_by_problem_id else 1,
            _problem_sort_key(row["problem"]),
            row["contest_year_problem"] or "",
        ),
    )

    if selected_year:
        problem_rows = [row for row in problem_rows if str(row["year"]) == selected_year]

    if selected_mohs:
        problem_rows = [row for row in problem_rows if str(row["mohs"]) == selected_mohs]

    if selected_topic:
        problem_rows = [row for row in problem_rows if row["topic"] == selected_topic]

    if selected_tag:
        problem_rows = [
            row
            for row in problem_rows
            if any(
                tag["technique"] == selected_tag
                for tag in topic_tags_by_problem_id.get(row["id"], [])
            )
        ]

    if initial_search_query:
        query = initial_search_query.lower()
        problem_rows = [
            row
            for row in problem_rows
            if query
            in " ".join(
                [
                    str(row["year"]),
                    row["problem"],
                    row["topic"],
                    row["contest_year_problem"] or "",
                    row.get("confidence") or "",
                    row.get("imo_slot_guess_value") or "",
                    *(
                        tag["technique"]
                        for tag in topic_tags_by_problem_id.get(row["id"], [])
                    ),
                    *(
                        tag["domains_label"]
                        for tag in topic_tags_by_problem_id.get(row["id"], [])
                        if tag["domains_label"]
                    ),
                ],
            ).lower()
        ]

    completion_by_problem_id = {
        row["problem_id"]: row["completion_date"]
        for row in UserProblemCompletion.objects.filter(
            user=request.user,
            problem__contest=contest_name,
        ).values("problem_id", "completion_date")
    }

    grouped_years: list[dict] = []
    for row in problem_rows:
        statement_data = statement_by_problem_id.get(row["id"])
        label = row["contest_year_problem"] or f"{contest_name} {row['year']} {row['problem']}"
        is_completed = row["id"] in completion_by_problem_id
        topic_tags = topic_tags_by_problem_id.get(row["id"], [])
        problem_item = {
            "anchor": _problem_anchor(label, f"{row['year']}-{row['problem']}"),
            "confidence": row.get("confidence"),
            "completion_date": completion_by_problem_id.get(row["id"]),
            "completion_known": (
                is_completed and completion_by_problem_id.get(row["id"]) is not None
            ),
            "is_completed": is_completed,
            "imo_slot_guess_value": row.get("imo_slot_guess_value"),
            "label": label,
            "mohs": row["mohs"],
            "problem": row["problem"],
            "problem_uuid": str(row["problem_uuid"]),
            "statement_day_label": statement_data["day_label"] if statement_data else "",
            "statement_has_asymptote": (
                statement_data["statement_has_asymptote"] if statement_data else False
            ),
            "statement_latex": statement_data["statement_latex"] if statement_data else "",
            "statement_render_segments": (
                statement_data["statement_render_segments"] if statement_data else []
            ),
            "statement_updated_at_label": (
                statement_data["updated_at_label"] if statement_data else ""
            ),
            "has_statement": statement_data is not None,
            "technique_count": row["technique_count"],
            "topic_tags": topic_tags,
            "topic": row["topic"],
        }
        if not grouped_years or grouped_years[-1]["year"] != row["year"]:
            grouped_years.append({"year": row["year"], "problems": [problem_item]})
            continue
        grouped_years[-1]["problems"].append(problem_item)

    top_topics = list(
        contest_base.values("topic")
        .annotate(problem_count=Count("id"))
        .order_by("-problem_count", "topic")[:6],
    )

    context = {
        "contest_problem_total": stats["problem_n"],
        "contest_problem_stats": {
            "avg_mohs": round(float(stats["avg_mohs"] or 0), 1),
            "statement_total": len(statement_by_problem_id),
            "year_range_label": (
                str(stats["year_min"])
                if stats["year_min"] == stats["year_max"]
                else f"{stats['year_min']}-{stats['year_max']}"
            ),
        },
        "contest_slug": contest_slug,
        "contest_title": contest_name,
        "filter_options": {
            "mohs_values": list(
                contest_base.values_list("mohs", flat=True).distinct().order_by("mohs"),
            ),
            "tags": topic_tag_options,
            "topics": list(
                contest_base.values_list("topic", flat=True).distinct().order_by("topic"),
            ),
            "years": list(
                contest_base.values_list("year", flat=True).distinct().order_by("-year"),
            ),
        },
        "grouped_years": grouped_years,
        "has_active_filters": bool(
            initial_search_query or selected_mohs or selected_year or selected_topic or selected_tag,
        ),
        "initial_search_query": initial_search_query,
        "matching_problem_total": len(problem_rows),
        "selected_mohs": selected_mohs,
        "selected_tag": selected_tag,
        "selected_topic": selected_topic,
        "selected_year": selected_year,
        "statement_rendering_enabled": bool(statement_by_problem_id),
        "top_topics": [row["topic"] for row in top_topics],
    }
    return render(request, "pages/contest-problem-list.html", context)


@login_required
def contest_analytics_view(request):
    """Contest analytics: contest-level summaries, charts, and ranked table."""
    _require_admin_tools_access(request)

    base = ProblemSolveRecord.objects.all()
    problem_total = base.count()

    contest_rows = list(
        base.values("contest")
        .annotate(
            problem_count=Count("id"),
            year_min=Min("year"),
            year_max=Max("year"),
            active_years=Count("year", distinct=True),
            distinct_topics=Count("topic", distinct=True),
            avg_mohs=Avg("mohs"),
            max_mohs=Max("mohs"),
        )
        .order_by("-problem_count", "contest"),
    )
    technique_rows_by_contest = {
        row["record__contest"]: int(row["c"])
        for row in ProblemTopicTechnique.objects.values("record__contest").annotate(c=Count("id"))
    }
    for row in contest_rows:
        row["technique_rows"] = technique_rows_by_contest.get(row["contest"], 0)
        row["avg_mohs"] = round(float(row["avg_mohs"] or 0), 2)
        row["techniques_per_problem"] = round(row["technique_rows"] / row["problem_count"], 2)
        row["year_span_label"] = (
            str(row["year_min"])
            if row["year_min"] == row["year_max"]
            else f"{row['year_min']}-{row['year_max']}"
        )

    contest_total = len(contest_rows)
    multi_year_contests = sum(1 for row in contest_rows if row["active_years"] > 1)
    average_problems_per_contest = round(problem_total / contest_total, 2) if contest_total else 0.0

    biggest_contest = contest_rows[0] if contest_rows else None
    longest_running_contest = (
        max(contest_rows, key=lambda row: (row["active_years"], row["problem_count"], row["contest"]))
        if contest_rows
        else None
    )
    hardest_contest = (
        max(contest_rows, key=lambda row: (row["avg_mohs"], row["problem_count"], row["contest"]))
        if contest_rows
        else None
    )
    broadest_contest = (
        max(contest_rows, key=lambda row: (row["distinct_topics"], row["problem_count"], row["contest"]))
        if contest_rows
        else None
    )

    charts_payload = {
        "byProblemVolume": _rows_to_bar_payload(
            contest_rows[:12],
            "contest",
            value_key="problem_count",
        ),
        "byActiveYears": _rows_to_bar_payload(
            sorted(
                contest_rows,
                key=lambda row: (row["active_years"], row["problem_count"], row["contest"]),
                reverse=True,
            )[:12],
            "contest",
            value_key="active_years",
        ),
        "byAvgMohs": _rows_to_bar_payload(
            sorted(
                contest_rows,
                key=lambda row: (row["avg_mohs"], row["problem_count"], row["contest"]),
                reverse=True,
            )[:12],
            "contest",
            value_key="avg_mohs",
            decimals=2,
        ),
        "byTopicBreadth": _rows_to_bar_payload(
            sorted(
                contest_rows,
                key=lambda row: (row["distinct_topics"], row["problem_count"], row["contest"]),
                reverse=True,
            )[:12],
            "contest",
            value_key="distinct_topics",
        ),
        "byTechniqueDensity": _rows_to_bar_payload(
            sorted(
                contest_rows,
                key=lambda row: (row["techniques_per_problem"], row["problem_count"], row["contest"]),
                reverse=True,
            )[:12],
            "contest",
            value_key="techniques_per_problem",
            decimals=2,
        ),
    }

    context = {
        "contest_total": contest_total,
        "contest_problem_total": problem_total,
        "contest_stats": {
            "average_problems_per_contest": average_problems_per_contest,
            "multi_year_contests": multi_year_contests,
        },
        "contest_leaders": {
            "biggest": biggest_contest,
            "longest_running": longest_running_contest,
            "hardest": hardest_contest,
            "broadest": broadest_contest,
        },
        "contest_rows": contest_rows,
        "charts_payload": charts_payload,
    }
    return render(request, "pages/contest-analytics.html", context)


@login_required
def topic_tag_analytics_view(request):
    """Topic tag analytics: coverage, breadth, and difficulty signals per tag."""
    _require_admin_tools_access(request)

    tag_rows = list(
        ProblemTopicTechnique.objects.select_related("record")
        .all()
        .order_by("technique", "record__contest", "record__problem"),
    )
    tag_directory = _build_topic_tag_directory_rows(tag_rows)

    tag_total = len(tag_directory)
    tagged_problem_total = len({tag_row.record_id for tag_row in tag_rows})
    contest_total = len({tag_row.record.contest for tag_row in tag_rows})
    average_tags_per_problem = round(len(tag_rows) / tagged_problem_total, 2) if tagged_problem_total else 0.0

    most_used_tag = tag_directory[0] if tag_directory else None
    broadest_contest_tag = (
        sorted(
            tag_directory,
            key=lambda row: (-row["contest_count"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    broadest_domain_tag = (
        sorted(
            tag_directory,
            key=lambda row: (-row["domain_count"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    longest_running_tag = (
        sorted(
            tag_directory,
            key=lambda row: (-row["active_years"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )

    charts_payload = {
        "byProblemVolume": _rows_to_bar_payload(
            tag_directory[:12],
            "technique",
            value_key="problem_count",
        ),
        "byContestCoverage": _rows_to_bar_payload(
            sorted(
                tag_directory,
                key=lambda row: (-row["contest_count"], -row["problem_count"], row["technique"]),
            )[:12],
            "technique",
            value_key="contest_count",
        ),
        "byDomainBreadth": _rows_to_bar_payload(
            sorted(
                tag_directory,
                key=lambda row: (-row["domain_count"], -row["problem_count"], row["technique"]),
            )[:12],
            "technique",
            value_key="domain_count",
        ),
        "byAvgMohs": _rows_to_bar_payload(
            sorted(
                tag_directory,
                key=lambda row: (-row["avg_mohs"], -row["problem_count"], row["technique"]),
            )[:12],
            "technique",
            value_key="avg_mohs",
            decimals=2,
        ),
    }

    context = {
        "topic_tag_total": tag_total,
        "tagged_problem_total": tagged_problem_total,
        "topic_tag_stats": {
            "contest_total": contest_total,
            "average_tags_per_problem": average_tags_per_problem,
        },
        "topic_tag_leaders": {
            "most_used": most_used_tag,
            "broadest_contest": broadest_contest_tag,
            "broadest_domain": broadest_domain_tag,
            "longest_running": longest_running_tag,
        },
        "topic_tag_rows": tag_directory,
        "charts_payload": charts_payload,
    }
    return render(request, "pages/topic-tag-analytics.html", context)


def _preview_problem_import(request, workbook_df) -> dict:
    preview_data = build_parsed_preview_payload(workbook_df)
    skip_warnings = preview_data.pop("warnings", [])
    msg = (
        f"Parsed preview: {preview_data['total_prepared_problems']} problem row(s) and "
        f"{preview_data['total_parsed_techniques']} technique row(s) from "
        f"{preview_data['total_sheet_rows']} sheet row(s). Tables below match what Import will write "
        "(not raw Excel). Re-upload the same file and click Import to save."
    )
    if preview_data["problems_truncated"] or preview_data["techniques_truncated"]:
        msg += (
            f" Showing first {preview_data['preview_problems_count']} problems and "
            f"{preview_data['preview_techniques_count']} techniques in the browser."
    )
    messages.info(request, msg)
    _emit_warning_messages(request, skip_warnings, overflow_label="skip warnings")
    record_event(
        event_type=AuditEvent.EventType.IMPORT_PREVIEWED,
        message=(
            f"Previewed workbook import with {preview_data['total_prepared_problems']} problem row(s) "
            f"and {preview_data['total_parsed_techniques']} technique row(s)."
        ),
        request=request,
        metadata={
            "problem_rows": preview_data["total_prepared_problems"],
            "sheet_rows": preview_data["total_sheet_rows"],
            "technique_rows": preview_data["total_parsed_techniques"],
        },
    )
    return preview_data


def _emit_warning_messages(request, warnings: list[str], *, overflow_label: str) -> None:
    max_warn = 25
    for warning in warnings[:max_warn]:
        messages.warning(request, warning)
    if len(warnings) > max_warn:
        messages.warning(request, f"...and {len(warnings) - max_warn} more {overflow_label}.")


def _import_problem_workbook(request, workbook_df, *, replace_tags: bool) -> None:
    result = import_problem_dataframe(workbook_df, replace_tags=replace_tags)
    messages.success(
        request,
        f"Import finished. Upserted {result.n_records} problem record(s); "
        f"touched {result.n_techniques} technique row(s).",
    )
    _emit_warning_messages(
        request,
        result.warnings,
        overflow_label="warnings (see server logs if needed)",
    )
    record_event(
        event_type=AuditEvent.EventType.IMPORT_COMPLETED,
        message=(
            f"Imported workbook with {result.n_records} problem row(s) and "
            f"{result.n_techniques} technique row(s)."
        ),
        request=request,
        metadata={
            "problem_rows": result.n_records,
            "replace_tags": replace_tags,
            "technique_rows": result.n_techniques,
            "warning_count": len(result.warnings),
        },
    )


def _export_problem_workbook_response() -> HttpResponse:
    records = list(
        ProblemSolveRecord.objects.prefetch_related("topic_techniques").order_by("-year", "contest", "problem"),
    )
    workbook_bytes = build_problem_export_workbook_bytes(records)
    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(workbook_bytes, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="asterproof-problems-{timestamp}.xlsx"'
    return response


def _preview_contest_names(contests: tuple[str, ...]) -> str:
    preview_limit = 3
    preview = ", ".join(f'"{contest}"' for contest in contests[:preview_limit])
    if len(contests) > preview_limit:
        return f"{preview}, and {len(contests) - preview_limit} more"
    return preview


@login_required
def contest_rename_view(request):
    _require_admin_tools_access(request)

    inventory_rows = _contest_inventory_rows()
    contest_choices = [
        (
            row["contest"],
            (
                f'{row["contest"]} '
                f'({row["problem_count"]} problems, {row["statement_count"]} statements)'
            ),
        )
        for row in inventory_rows
    ]

    if request.method == "POST":
        form = ContestRenameForm(request.POST, contest_choices=contest_choices)
        if form.is_valid():
            try:
                result = rename_contests(
                    old_names=form.cleaned_data["source_contests"],
                    new_name=form.cleaned_data["new_contest_name"],
                )
            except ContestRenameValidationError as exc:
                form.add_error(None, str(exc))
            else:
                if len(result.source_contests) == 1:
                    action_verb = "Merged" if result.merged_into_existing else "Renamed"
                    success_message = (
                        f'{action_verb} "{result.source_contest}" into "{result.target_contest}" '
                        f"across {result.problem_count} problem row(s) and "
                        f"{result.statement_count} statement row(s)."
                    )
                else:
                    action_verb = "Merged" if result.merged_into_existing else "Updated"
                    success_message = (
                        f'{action_verb} {len(result.source_contests)} contest names into '
                        f'"{result.target_contest}" across {result.problem_count} problem row(s) '
                        f"and {result.statement_count} statement row(s). Source contests: "
                        f"{_preview_contest_names(result.source_contests)}."
                    )
                messages.success(
                    request,
                    success_message,
                )
                return redirect("pages:contest_rename")
    else:
        form = ContestRenameForm(contest_choices=contest_choices)

    return render(
        request,
        "pages/contest-rename.html",
        {
            "form": form,
            "inventory_rows": inventory_rows,
            "selected_source_contests": list(form["source_contests"].value() or []),
        },
    )


@login_required
def problem_import_view(request):
    """Import/export analytics workbooks and preview parsed problem rows."""
    _require_admin_tools_access(request)

    if request.method == "GET" and request.GET.get("action") == "export":
        return _export_problem_workbook_response()

    replace_tags_initial = request.method == "POST" and bool(request.POST.get("replace_tags"))
    preview_payload: dict | None = None
    form = ProblemXlsxImportForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action") or "import"
        replace_tags = form.cleaned_data["replace_tags"]
        replace_tags_initial = replace_tags

        try:
            workbook_df = dataframe_from_excel(form.cleaned_data["file"].read())
        except ProblemImportValidationError as exc:
            messages.error(request, str(exc))
            record_event(
                event_type=AuditEvent.EventType.IMPORT_FAILED,
                message=f"Workbook import failed validation: {exc}",
                request=request,
                metadata={"error": str(exc)},
            )
        else:
            if action == "preview":
                preview_payload = _preview_problem_import(request, workbook_df)
            else:
                _import_problem_workbook(request, workbook_df, replace_tags=replace_tags)
        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})

    if request.method == "GET":
        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})

    return render(
        request,
        "pages/problem-import.html",
        {"form": form, "preview_payload": preview_payload},
    )
