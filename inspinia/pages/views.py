import csv
import json
import math
import re
import uuid
from collections import Counter
from collections import defaultdict
from datetime import date
from datetime import timedelta
from io import StringIO
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError
from django.db import transaction
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
from inspinia.pages.contest_links import contest_dashboard_listing_url
from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.contest_rename import ContestRenameValidationError
from inspinia.pages.contest_rename import rename_contests
from inspinia.pages.forms import ContestMetadataForm
from inspinia.pages.forms import ContestRenameForm
from inspinia.pages.forms import HandleSummaryParserForm
from inspinia.pages.forms import ProblemCompletionPasteForm
from inspinia.pages.forms import ProblemStatementCsvImportForm
from inspinia.pages.forms import ProblemStatementDeleteByUuidForm
from inspinia.pages.forms import ProblemStatementEditorUpdateForm
from inspinia.pages.forms import ProblemStatementImportForm
from inspinia.pages.forms import ProblemXlsxImportForm
from inspinia.pages.forms import StatementMetadataWorkbookForm
from inspinia.pages.handle_summary_parser import HandleSummaryParseValidationError
from inspinia.pages.handle_summary_parser import HandleSummaryPreviewPayload
from inspinia.pages.handle_summary_parser import build_handle_summary_preview_payload
from inspinia.pages.handle_summary_parser import parse_handle_summary_text
from inspinia.pages.models import ContestMetadata
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_completion_import import import_problem_completion_text_for_user
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import build_parsed_preview_payload
from inspinia.pages.problem_import import build_problem_export_workbook_bytes
from inspinia.pages.problem_import import build_problem_statement_export_workbook_bytes
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.pages.statement_analytics import annotate_effective_statement_analytics
from inspinia.pages.statement_analytics import contest_key_for_public_slug
from inspinia.pages.statement_analytics import effective_confidence
from inspinia.pages.statement_analytics import effective_imo_slot_guess_value
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem
from inspinia.pages.statement_duplicates import build_statement_duplicate_report
from inspinia.pages.statement_import import LATEX_STATEMENT_SAMPLE
from inspinia.pages.statement_import import ProblemStatementImportValidationError
from inspinia.pages.statement_import import ProblemStatementPreviewPayload
from inspinia.pages.statement_import import ProblemStatementSavePreviewPayload
from inspinia.pages.statement_import import build_problem_statement_preview_payload
from inspinia.pages.statement_import import build_problem_statement_save_preview
from inspinia.pages.statement_import import import_problem_statements
from inspinia.pages.statement_import import parse_contest_problem_statements
from inspinia.pages.statement_import import relink_problem_statement_rows
from inspinia.pages.statement_metadata_backfill import StatementMetadataBackfillValidationError
from inspinia.pages.statement_metadata_backfill import build_statement_metadata_export_dataframe
from inspinia.pages.statement_metadata_backfill import build_statement_metadata_export_workbook_bytes
from inspinia.pages.statement_metadata_backfill import import_statement_metadata_dataframe
from inspinia.pages.statement_metadata_backfill import statement_metadata_dataframe_from_excel
from inspinia.pages.statement_metadata_backfill import statement_metadata_dataframe_from_rows
from inspinia.pages.statement_metadata_backfill import statement_metadata_dataframe_from_text
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import AuditEvent
from inspinia.users.monitoring import record_event
from inspinia.users.roles import user_has_admin_role

CONTEST_TOPIC_PREVIEW_LIMIT = 3
CONTEST_PROBLEM_PREVIEW_LIMIT = 6
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
STATEMENT_CSV_COLUMNS = [
    "PROBLEM UUID",
    "LINKED PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
]
STATEMENT_CSV_REQUIRED_COLUMNS = {
    "CONTEST YEAR",
    "CONTEST NAME",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
}
MAIN_TOPIC_CODE_MAP = {
    "A": "A",
    "ALG": "A",
    "C": "C",
    "COMB": "C",
    "G": "G",
    "GEO": "G",
    "N": "N",
    "NT": "N",
}
MAIN_TOPIC_CODE_ORDER = ("A", "C", "G", "N")
STATEMENT_LINKER_ERROR_PREVIEW_LIMIT = 5
STATEMENT_METADATA_ERROR_PREVIEW_LIMIT = 5
COMPLETION_BOARD_INITIAL_ROW_LIMIT = 30
COMPLETION_BOARD_ROW_LOAD_STEP = 30


class ProblemStatementCsvImportValidationError(ValueError):
    """Raised when a statement CSV upload cannot be parsed or validated."""


def _active_problem_records():
    return ProblemSolveRecord.objects.filter(is_active=True)


def _active_dashboard_statements():
    return ContestProblemStatement.objects.filter(is_active=True)


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
        base = _active_problem_records()
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
                    "href": contest_dashboard_listing_url(row["contest"]),
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
                        contest_dashboard_listing_url(problem_row["contest"])
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
def handle_summary_parser_view(request):
    _require_admin_tools_access(request)
    preview_payload: HandleSummaryPreviewPayload | None = None

    if request.method == "POST":
        form = HandleSummaryParserForm(request.POST)
        if form.is_valid():
            try:
                parsed_rows = parse_handle_summary_text(form.cleaned_data["source_text"])
            except HandleSummaryParseValidationError as exc:
                messages.error(request, str(exc))
            else:
                preview_payload = build_handle_summary_preview_payload(parsed_rows)
                messages.info(
                    request,
                    f'Extracted {preview_payload["row_count"]} handle block(s) into the export table.',
                )
    else:
        form = HandleSummaryParserForm()

    return render(
        request,
        "pages/handle-summary-parser.html",
        {
            "form": form,
            "preview_payload": preview_payload,
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


def _json_script_safe(value):
    """Make values safe for {% json_script %} / browser JSON.parse (no NaN/Infinity)."""
    if isinstance(value, dict):
        return {k: _json_script_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_script_safe(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _statement_completion_sort_value(*, is_solved: bool, completion_date: date | None) -> str:
    if not is_solved:
        return "0-"
    if completion_date is None:
        return "1-9999-12-31"
    return f"2-{completion_date.isoformat()}"


def _statement_completion_dates_by_statement_id(
    statements: list[ContestProblemStatement],
    *,
    user,
) -> dict[int, date | None]:
    if user is None or not statements:
        return {}

    statement_ids = [statement.id for statement in statements]
    completion_by_statement_id = {
        row["statement_id"]: row["completion_date"]
        for row in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).values("statement_id", "completion_date")
    }
    unresolved_linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.id not in completion_by_statement_id and statement.linked_problem_id is not None
        },
    )
    if not unresolved_linked_problem_ids:
        return completion_by_statement_id

    legacy_completion_by_problem_id = {
        row["problem_id"]: row["completion_date"]
        for row in UserProblemCompletion.objects.filter(
            user=user,
            statement__isnull=True,
            problem_id__in=unresolved_linked_problem_ids,
        ).values("problem_id", "completion_date")
    }
    for statement in statements:
        if statement.id in completion_by_statement_id:
            continue
        if statement.linked_problem_id is None:
            continue
        legacy_completion_date = legacy_completion_by_problem_id.get(statement.linked_problem_id)
        if statement.linked_problem_id in legacy_completion_by_problem_id:
            completion_by_statement_id[statement.id] = legacy_completion_date

    return completion_by_statement_id


def _completion_problem_for_statement(statement: ContestProblemStatement | None) -> ProblemSolveRecord | None:
    if statement is None:
        return None
    return statement.linked_problem


def _statement_table_rows(base, *, user=None) -> list[dict]:
    statements_list = list(base.select_related("linked_problem").order_by("-updated_at", "-id"))
    statement_ids = [statement.id for statement in statements_list]
    linked_problem_ids = sorted(
        {statement.linked_problem_id for statement in statements_list if statement.linked_problem_id is not None},
    )
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
    stmt_topic_rows = list(
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values("statement_id", "technique")
        .order_by("technique", "statement_id"),
    )
    topic_tags_by_statement_id: dict[int, list[str]] = defaultdict(list)
    seen_topic_tags_by_statement_id: dict[int, set[str]] = defaultdict(set)
    for tag_row in stmt_topic_rows:
        statement_id = tag_row["statement_id"]
        technique = tag_row["technique"]
        if technique in seen_topic_tags_by_statement_id[statement_id]:
            continue
        seen_topic_tags_by_statement_id[statement_id].add(technique)
        topic_tags_by_statement_id[statement_id].append(technique)
    completion_dates_by_statement_id: dict[int, date | None] = {}
    visible_solution_problem_ids: set[int] = set()
    if user is not None and linked_problem_ids:
        completion_dates_by_statement_id = _statement_completion_dates_by_statement_id(
            statements_list,
            user=user,
        )
        visible_solution_problem_ids = set(
            ProblemSolution.objects.filter(problem_id__in=linked_problem_ids)
            .filter(Q(author=user) | Q(status=ProblemSolution.Status.PUBLISHED))
            .values_list("problem_id", flat=True)
        )

    table_rows: list[dict] = []
    for statement in statements_list:
        linked_problem = statement.linked_problem
        linked_problem_topic = ""
        linked_problem_topic_tags: list[str] = []
        linked_problem_topic_tag_links: list[dict[str, str]] = []
        linked_problem_mohs = None
        linked_problem_mohs_url = ""
        linked_problem_confidence = ""
        linked_problem_confidence_url = ""
        linked_problem_imo_slot_guess_value = ""
        linked_problem_imo_slot_url = ""
        linked_problem_uuid = ""
        user_completion_is_solved = False
        user_completion_date = None
        user_completion_display = "Unsolved"
        user_completion_state_kind = "unsolved"
        user_completion_state_label = "Unsolved"
        if statement.id in completion_dates_by_statement_id:
            user_completion_is_solved = True
            user_completion_date = completion_dates_by_statement_id.get(statement.id)
            user_completion_state_kind = _completion_board_state_kind(
                is_solved=True,
                completion_date=user_completion_date,
            )
            user_completion_state_label = _completion_board_state_label(
                is_solved=True,
                completion_date=user_completion_date,
            )
            user_completion_display = (
                user_completion_date.isoformat() if user_completion_date is not None else "Unknown date"
            )
        eff_topic = effective_topic(statement)
        if eff_topic:
            linked_problem_topic = display_topic_label(eff_topic)
        linked_problem_topic_tags = topic_tags_by_statement_id.get(statement.id, [])
        if not linked_problem_topic_tags and linked_problem is not None:
            linked_problem_topic_tags = topic_tags_by_problem_id.get(linked_problem.id, [])
        eff_mohs = effective_mohs(statement)
        linked_problem_mohs = eff_mohs
        linked_problem_confidence = effective_confidence(statement)
        linked_problem_imo_slot_guess_value = effective_imo_slot_guess_value(statement)
        if linked_problem is not None:
            linked_problem_uuid = str(linked_problem.problem_uuid)
        contest_key = contest_key_for_public_slug(statement)
        if contest_key:
            linked_problem_topic_tag_links = [
                {
                    "label": technique,
                    "url": contest_dashboard_listing_url(contest_key, tag=technique),
                }
                for technique in linked_problem_topic_tags
            ]
            if eff_mohs is not None:
                linked_problem_mohs_url = contest_dashboard_listing_url(contest_key, mohs=eff_mohs)
            linked_problem_confidence_url = (
                contest_dashboard_listing_url(contest_key, q=linked_problem_confidence)
                if linked_problem_confidence
                else ""
            )
            linked_problem_imo_slot_url = (
                contest_dashboard_listing_url(contest_key, q=linked_problem_imo_slot_guess_value)
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
                "linked_problem_topic": linked_problem_topic,
                "linked_problem_uuid": linked_problem_uuid,
                "problem_code": statement.problem_code,
                "statement_uuid": str(statement.statement_uuid),
                "problem_uuid": str(statement.problem_uuid),
                "linked_problem_mohs": linked_problem_mohs,
                "linked_problem_mohs_url": linked_problem_mohs_url,
                "linked_problem_confidence": linked_problem_confidence,
                "linked_problem_confidence_url": linked_problem_confidence_url,
                "linked_problem_imo_slot_guess_value": linked_problem_imo_slot_guess_value,
                "linked_problem_imo_slot_display": _format_imo_slot_label(linked_problem_imo_slot_guess_value),
                "linked_problem_imo_slot_url": linked_problem_imo_slot_url,
                "linked_problem_topic_tags": linked_problem_topic_tags,
                "linked_problem_topic_tag_links": linked_problem_topic_tag_links,
                "problem_destination_label": (
                    "View"
                    if linked_problem is not None and linked_problem.id in visible_solution_problem_ids
                    else ("Start" if linked_problem is not None else "")
                ),
                "problem_destination_url": (
                    reverse("solutions:problem_solution_list", args=[linked_problem.problem_uuid])
                    if linked_problem is not None and linked_problem.id in visible_solution_problem_ids
                    else (
                        reverse("solutions:problem_solution_edit", args=[linked_problem.problem_uuid])
                        if linked_problem is not None
                        else ""
                    )
                ),
                "user_completion_date": user_completion_date.isoformat() if user_completion_date else "",
                "user_completion_display": user_completion_display,
                "user_completion_is_solved": user_completion_is_solved,
                "user_completion_sort": _statement_completion_sort_value(
                    is_solved=user_completion_is_solved,
                    completion_date=user_completion_date,
                ),
                "user_completion_state_kind": user_completion_state_kind,
                "user_completion_state_label": user_completion_state_label,
                "updated_at": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d %H:%M"),
                "updated_at_sort": statement.updated_at.isoformat(),
            },
        )

    return table_rows


def _format_imo_slot_label(value: object) -> str:
    if not value:
        return ""
    parts = [p.strip() for p in str(value).split(",")]
    return ", ".join(f"P{p}" for p in parts if p)


def _statement_row_search_blob(row: dict) -> str:
    parts = [
        str(row.get("contest_year") or ""),
        str(row.get("contest_name") or ""),
        str(row.get("linked_problem_topic") or ""),
        str(row.get("problem_code") or ""),
        str(row.get("day_label") or ""),
        str(row.get("problem_uuid") or ""),
        str(row.get("linked_problem_uuid") or ""),
        str(row.get("user_completion_display") or ""),
        str(row.get("user_completion_state_label") or ""),
        str(row.get("linked_problem_confidence") or ""),
        str(row.get("linked_problem_imo_slot_guess_value") or ""),
        ", ".join(row.get("linked_problem_topic_tags") or []),
        str(row.get("updated_at") or ""),
        str(row.get("contest_year_problem") or ""),
    ]
    return " ".join(parts).lower()


def _filter_statement_table_rows(  # noqa: C901, PLR0913
    rows: list[dict],
    *,
    q: str,
    year: str,
    topic: str,
    confidence: str,
    mohs_min: str,
    mohs_max: str,
) -> list[dict]:
    qn = (q or "").strip().lower()
    year_s = (year or "").strip()
    topic_s = (topic or "").strip()
    confidence_s = (confidence or "").strip()
    try:
        mn = int(mohs_min) if str(mohs_min).strip() != "" else None
    except ValueError:
        mn = None
    try:
        mx = int(mohs_max) if str(mohs_max).strip() != "" else None
    except ValueError:
        mx = None

    def match(row: dict) -> bool:  # noqa: PLR0911
        if year_s and str(row.get("contest_year") or "") != year_s:
            return False
        if topic_s and str(row.get("linked_problem_topic") or "") != topic_s:
            return False
        if confidence_s and str(row.get("linked_problem_confidence") or "") != confidence_s:
            return False
        if mn is not None or mx is not None:
            mval = row.get("linked_problem_mohs")
            if mval is None:
                return False
            try:
                mv = int(mval)
            except (TypeError, ValueError):
                return False
            if mn is not None and mv < mn:
                return False
            if mx is not None and mv > mx:
                return False
        return not (qn and qn not in _statement_row_search_blob(row))

    return [r for r in rows if match(r)]


def _statement_table_rows_copy_tsv(rows: list[dict]) -> str:
    header = (
        "Year\tContest\tTopic\tProblem code\tDay\tSolved\tTopic tags\tMOHS\t"
        "Confidence\tIMO slot\tUpdated\n"
    )
    lines = [header]
    for row in rows:
        tags = ", ".join(row.get("linked_problem_topic_tags") or [])
        mohs = row.get("linked_problem_mohs")
        imo = _format_imo_slot_label(row.get("linked_problem_imo_slot_guess_value") or "")
        lines.append(
            "\t".join(
                [
                    str(row.get("contest_year") or ""),
                    str(row.get("contest_name") or ""),
                    str(row.get("linked_problem_topic") or ""),
                    str(row.get("problem_code") or ""),
                    str(row.get("day_label") or ""),
                    str(row.get("user_completion_display") or ""),
                    tags,
                    "" if mohs is None else str(mohs),
                    str(row.get("linked_problem_confidence") or ""),
                    imo,
                    str(row.get("updated_at") or ""),
                ],
            )
            + "\n",
        )
    return "".join(lines)


def _problem_statement_list_filter_options(rows: list[dict]) -> dict[str, list[str]]:
    years = sorted(
        {str(r.get("contest_year") or "").strip() for r in rows if str(r.get("contest_year") or "").strip()},
        key=lambda s: int(s) if s.isdigit() else 0,
        reverse=True,
    )
    topics = sorted(
        {str(r.get("linked_problem_topic") or "").strip() for r in rows if r.get("linked_problem_topic")},
    )
    confidences = sorted(
        {str(r.get("linked_problem_confidence") or "").strip() for r in rows if r.get("linked_problem_confidence")},
    )
    return {"years": years, "topics": topics, "confidences": confidences}


def _statement_editor_table_payload() -> dict[str, object]:
    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").order_by(
            "-updated_at",
            "-id",
        ),
    )
    if not statements:
        return {
            "contest_names": [],
            "rows": [],
            "stats": {
                "active_total": 0,
                "inactive_total": 0,
                "total": 0,
                "unlinked_total": 0,
            },
            "year_values": [],
        }

    rows: list[dict[str, object]] = []
    active_total = 0
    unlinked_total = 0
    contest_names = sorted({statement.contest_name for statement in statements})
    year_values = sorted({int(statement.contest_year) for statement in statements}, reverse=True)

    for statement in statements:
        if statement.is_active:
            active_total += 1
        if statement.linked_problem is None:
            unlinked_total += 1

        rows.append(_statement_editor_row(statement))

    total = len(rows)
    return {
        "contest_names": contest_names,
        "rows": rows,
        "stats": {
            "active_total": active_total,
            "inactive_total": total - active_total,
            "total": total,
            "unlinked_total": unlinked_total,
        },
        "year_values": [str(year) for year in year_values],
    }


def _statement_editor_row(statement: ContestProblemStatement) -> dict[str, object]:
    linked_problem = statement.linked_problem
    return {
        "statement_id": statement.id,
        "statement_uuid": str(statement.statement_uuid),
        "problem_uuid": str(statement.problem_uuid),
        "contest_year": int(statement.contest_year),
        "contest_name": statement.contest_name,
        "contest_year_label": f"{statement.contest_name} {statement.contest_year}",
        "day_label": statement.day_label,
        "day_label_display": statement.day_label or "Unlabeled",
        "problem_number": statement.problem_number,
        "problem_code": statement.problem_code,
        "statement_latex": statement.statement_latex,
        "topic": (
            display_topic_label(effective_topic(statement))
            if effective_topic(statement)
            else "Unlinked"
        ),
        "is_active": statement.is_active,
        "is_linked": linked_problem is not None,
        "link_status": "Linked" if linked_problem is not None else "Unlinked",
        "linked_problem_label": (
            _statement_linker_problem_label(linked_problem) if linked_problem is not None else ""
        ),
        "updated_at": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d %H:%M"),
        "updated_at_sort": statement.updated_at.isoformat(),
    }


def _statement_linker_statement_label(statement: ContestProblemStatement) -> str:
    day_label = statement.day_label or "Unlabeled"
    return f"{statement.contest_year_problem} · {day_label}"


def _statement_linker_problem_label(problem: ProblemSolveRecord) -> str:
    return problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"


def _statement_linker_problem_option_label(problem: ProblemSolveRecord) -> str:
    return " · ".join(
        [
            problem.problem,
            _statement_linker_problem_label(problem),
            f"Topic {display_topic_label(problem.topic)}",
            f"MOHS {problem.mohs}",
        ],
    )


def _statement_linker_group_key(contest_name: str, contest_year: int) -> str:
    return f"{contest_name}::{contest_year}"


def _statement_linker_problem_is_available(
    problem: ProblemSolveRecord,
    *,
    claimant_by_problem_uuid: dict,
    statement_id: int,
) -> bool:
    claimant = claimant_by_problem_uuid.get(problem.problem_uuid)
    return claimant is None or claimant.id == statement_id


def _statement_linker_suggested_problem(
    *,
    statement: ContestProblemStatement,
    problem_by_uuid: dict,
    problem_by_statement_key: dict,
    statement_problem_code_counts: Counter,
    claimant_by_problem_uuid: dict,
) -> tuple[ProblemSolveRecord | None, str]:
    if statement.linked_problem is not None:
        return statement.linked_problem, "Already linked"

    uuid_match = problem_by_uuid.get(statement.problem_uuid)
    if uuid_match is not None and _statement_linker_problem_is_available(
        uuid_match,
        claimant_by_problem_uuid=claimant_by_problem_uuid,
        statement_id=statement.id,
    ):
        return uuid_match, "UUID match"

    problem_code = (statement.problem_code or "").strip().upper()
    statement_problem_key = (
        statement.contest_name,
        int(statement.contest_year),
        problem_code,
    )
    if problem_code and statement_problem_code_counts[statement_problem_key] == 1:
        direct_match = problem_by_statement_key.get(statement_problem_key)
        if direct_match is not None and _statement_linker_problem_is_available(
            direct_match,
            claimant_by_problem_uuid=claimant_by_problem_uuid,
            statement_id=statement.id,
        ):
            return direct_match, "Problem code match"

        if problem_code == f"P{statement.problem_number}":
            fallback_match = problem_by_statement_key.get(
                (
                    statement.contest_name,
                    int(statement.contest_year),
                    str(statement.problem_number),
                ),
            )
            if fallback_match is not None and _statement_linker_problem_is_available(
                fallback_match,
                claimant_by_problem_uuid=claimant_by_problem_uuid,
                statement_id=statement.id,
            ):
                return fallback_match, "Problem number fallback"

    return None, ""


def _statement_linker_payload() -> dict[str, object]:
    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").order_by(
            "-contest_year",
            "contest_name",
            "day_label",
            "problem_number",
            "problem_code",
        ),
    )
    if not statements:
        return {
            "candidate_groups": {},
            "contest_names": [],
            "rows": [],
            "stats": {
                "contest_total": 0,
                "linked_total": 0,
                "suggested_total": 0,
                "unlinked_total": 0,
            },
            "year_values": [],
        }

    statement_contests = sorted({statement.contest_name for statement in statements})
    statement_years = sorted({int(statement.contest_year) for statement in statements}, reverse=True)
    problems = list(
        ProblemSolveRecord.objects.filter(
            contest__in=statement_contests,
            year__in=statement_years,
        ).order_by("contest", "-year", "problem"),
    )
    problems_by_contest_year: dict[tuple[str, int], list[ProblemSolveRecord]] = defaultdict(list)
    problem_by_uuid = {}
    problem_by_statement_key = {}
    for problem in problems:
        problem_by_uuid[problem.problem_uuid] = problem
        problem_by_statement_key[
            (problem.contest, int(problem.year), (problem.problem or "").strip().upper())
        ] = problem
        problems_by_contest_year[(problem.contest, int(problem.year))].append(problem)

    claimant_by_problem_uuid = {statement.problem_uuid: statement for statement in statements}
    statement_problem_code_counts = Counter(
        (
            statement.contest_name,
            int(statement.contest_year),
            (statement.problem_code or "").strip().upper(),
        )
        for statement in statements
    )

    candidate_groups: dict[str, list[dict[str, object]]] = {}
    for contest_name, contest_year in sorted(
        problems_by_contest_year,
        key=lambda contest_year_key: (-contest_year_key[1], contest_year_key[0].lower()),
    ):
        group_key = _statement_linker_group_key(contest_name, contest_year)
        candidate_groups[group_key] = []
        for problem in sorted(
            problems_by_contest_year[(contest_name, contest_year)],
            key=lambda problem: _problem_sort_key(problem.problem),
        ):
            claimant = claimant_by_problem_uuid.get(problem.problem_uuid)
            candidate_groups[group_key].append(
                {
                    "claimed_statement_label": (
                        _statement_linker_statement_label(claimant)
                        if claimant is not None
                        else ""
                    ),
                    "is_claimed": claimant is not None,
                    "problem_id": problem.id,
                    "problem_label": _statement_linker_problem_label(problem),
                    "option_label": _statement_linker_problem_option_label(problem),
                },
            )

    rows: list[dict[str, object]] = []
    linked_total = 0
    suggested_total = 0
    for statement in statements:
        linked_problem = statement.linked_problem
        group_key = _statement_linker_group_key(statement.contest_name, int(statement.contest_year))
        suggested_problem, suggestion_reason = _statement_linker_suggested_problem(
            statement=statement,
            problem_by_uuid=problem_by_uuid,
            problem_by_statement_key=problem_by_statement_key,
            statement_problem_code_counts=statement_problem_code_counts,
            claimant_by_problem_uuid=claimant_by_problem_uuid,
        )
        if linked_problem is not None:
            linked_total += 1
        elif suggested_problem is not None:
            suggested_total += 1

        rows.append(
            {
                "candidate_count": len(candidate_groups.get(group_key, [])),
                "candidate_group_key": group_key,
                "contest_name": statement.contest_name,
                "contest_year": int(statement.contest_year),
                "contest_year_label": f"{statement.contest_name} {statement.contest_year}",
                "contest_year_problem": statement.contest_year_problem,
                "day_label": statement.day_label or "Unlabeled",
                "has_suggestion": "yes" if linked_problem is None and suggested_problem is not None else "no",
                "is_linked": linked_problem is not None,
                "link_status": "linked" if linked_problem is not None else "unlinked",
                "linked_problem_id": linked_problem.id if linked_problem is not None else None,
                "linked_problem_label": (
                    _statement_linker_problem_label(linked_problem)
                    if linked_problem is not None
                    else ""
                ),
                "problem_code": statement.problem_code,
                "problem_uuid": str(statement.problem_uuid),
                "statement_id": statement.id,
                "statement_preview": _statement_preview_text(statement.statement_latex, max_length=180),
                "suggested_problem_id": (
                    suggested_problem.id
                    if linked_problem is None and suggested_problem is not None
                    else None
                ),
                "suggested_problem_label": (
                    _statement_linker_problem_label(suggested_problem)
                    if linked_problem is None and suggested_problem is not None
                    else ""
                ),
                "suggestion_reason": suggestion_reason if linked_problem is None else "",
            },
        )

    return {
        "candidate_groups": candidate_groups,
        "contest_names": statement_contests,
        "rows": rows,
        "stats": {
            "contest_total": len(statement_contests),
            "linked_total": linked_total,
            "suggested_total": suggested_total,
            "unlinked_total": len(statements) - linked_total,
        },
        "year_values": [str(year) for year in statement_years],
    }


def _statement_linker_apply_link(
    *,
    statement: ContestProblemStatement,
    problem: ProblemSolveRecord,
) -> str | None:
    if int(problem.year) != int(statement.contest_year) or problem.contest != statement.contest_name:
        return "Selected problem must come from the same contest and year as the statement row."

    conflicting_statement = (
        ContestProblemStatement.objects.exclude(id=statement.id)
        .filter(problem_uuid=problem.problem_uuid)
        .first()
    )
    if conflicting_statement is not None:
        return (
            f'"{_statement_linker_problem_label(problem)}" is already claimed by '
            f'"{_statement_linker_statement_label(conflicting_statement)}".'
        )

    statement.linked_problem = problem
    statement.save(update_fields={"linked_problem", "updated_at"})
    statement.refresh_from_db()
    sync_statement_analytics_from_linked_problem(statement)
    return None


def _statement_linker_clear_link(statement: ContestProblemStatement) -> None:
    statement.linked_problem = None
    statement.problem_uuid = uuid.uuid4()
    statement.save(update_fields={"linked_problem", "problem_uuid", "updated_at"})


def _statement_linker_parse_bulk_selection_pairs(post_data) -> tuple[list[tuple[int, int]], str | None]:
    raw_statement_ids = post_data.getlist("statement_ids")
    raw_problem_ids = post_data.getlist("selected_problem_ids")
    if not raw_statement_ids:
        return [], "Stage at least one manual link before saving."
    if len(raw_statement_ids) != len(raw_problem_ids):
        return [], "Submitted bulk link data is incomplete. Please reload the page and try again."

    selection_by_statement_id: dict[int, int] = {}
    for row_number, (raw_statement_id, raw_problem_id) in enumerate(
        zip(raw_statement_ids, raw_problem_ids, strict=True),
        start=1,
    ):
        try:
            statement_id = int(raw_statement_id or "")
        except (TypeError, ValueError):
            return [], f"Bulk row {row_number} is missing a valid statement selection."
        try:
            problem_id = int(raw_problem_id or "")
        except (TypeError, ValueError):
            return [], f'Bulk row {row_number} for statement "{statement_id}" is missing a valid problem.'
        selection_by_statement_id[statement_id] = problem_id

    return list(selection_by_statement_id.items()), None


def _statement_linker_apply_bulk_links(selection_pairs: list[tuple[int, int]]) -> tuple[int, list[str]]:
    statements_by_id = {
        statement.id: statement
        for statement in ContestProblemStatement.objects.select_related("linked_problem").filter(
            id__in=[statement_id for statement_id, _problem_id in selection_pairs],
        )
    }
    problems_by_id = {
        problem.id: problem
        for problem in ProblemSolveRecord.objects.filter(
            id__in=[problem_id for _statement_id, problem_id in selection_pairs],
        )
    }

    success_count = 0
    errors: list[str] = []
    for statement_id, problem_id in selection_pairs:
        statement = statements_by_id.get(statement_id)
        if statement is None:
            errors.append(f"Statement row {statement_id} was not found.")
            continue

        problem = problems_by_id.get(problem_id)
        if problem is None:
            errors.append(
                f'Selected problem "{problem_id}" for "{_statement_linker_statement_label(statement)}" was not found.',
            )
            continue

        error_message = _statement_linker_apply_link(statement=statement, problem=problem)
        if error_message is not None:
            errors.append(error_message)
            continue

        success_count += 1

    return success_count, errors


def _handle_problem_statement_linker_post(request):
    redirect_name = "pages:problem_statement_linker"
    action = (request.POST.get("action") or "").strip()

    if action == "link_selected_bulk":
        selection_pairs, validation_error = _statement_linker_parse_bulk_selection_pairs(request.POST)
        if validation_error is not None:
            messages.error(request, validation_error)
        else:
            success_count, errors = _statement_linker_apply_bulk_links(selection_pairs)
            if success_count:
                messages.success(request, f"Saved {success_count} manual link(s).")
            for error_message in errors[:STATEMENT_LINKER_ERROR_PREVIEW_LIMIT]:
                messages.error(request, error_message)
            if len(errors) > STATEMENT_LINKER_ERROR_PREVIEW_LIMIT:
                suppressed_error_count = len(errors) - STATEMENT_LINKER_ERROR_PREVIEW_LIMIT
                messages.error(
                    request,
                    f"{suppressed_error_count} additional bulk link error(s) were suppressed.",
                )
    else:
        try:
            statement_id = int(request.POST.get("statement_id") or "")
        except (TypeError, ValueError):
            messages.error(request, "Select a statement row before saving a link.")
        else:
            statement = (
                ContestProblemStatement.objects.select_related("linked_problem")
                .filter(id=statement_id)
                .first()
            )
            if statement is None:
                raise Http404

            if action == "clear_link":
                if statement.linked_problem_id is None:
                    messages.info(
                        request,
                        f'No linked problem was attached to "{_statement_linker_statement_label(statement)}".',
                    )
                else:
                    _statement_linker_clear_link(statement)
                    messages.success(
                        request,
                        f'Cleared the linked problem for "{_statement_linker_statement_label(statement)}".',
                    )
            elif action not in {"link_selected", "link_suggested"}:
                messages.error(request, "Unsupported statement link action.")
            else:
                try:
                    selected_problem_id = int(request.POST.get("selected_problem_id") or "")
                except (TypeError, ValueError):
                    messages.error(request, "Select a problem row before saving the link.")
                else:
                    selected_problem = ProblemSolveRecord.objects.filter(id=selected_problem_id).first()
                    if selected_problem is None:
                        raise Http404

                    error_message = _statement_linker_apply_link(statement=statement, problem=selected_problem)
                    if error_message is not None:
                        messages.error(request, error_message)
                    else:
                        messages.success(
                            request,
                            (
                                f'Linked "{_statement_linker_statement_label(statement)}" to '
                                f'"{_statement_linker_problem_label(selected_problem)}".'
                            ),
                        )

    return redirect(redirect_name)


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
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [str(row["contest_name"]) for row in rows],
    )

    for row in rows:
        statement_count = int(row["statement_count"] or 0)
        linked_count = int(row["linked_count"] or 0)
        contest_slug = contest_to_slug.get(str(row["contest_name"]))
        row["contest_year_label"] = f"{row['contest_name']} {row['contest_year']}"
        row["contest_year_url"] = (
            contest_dashboard_listing_url(str(row["contest_name"]), year=int(row["contest_year"]))
            if contest_slug
            else ""
        )
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
    return _contest_year_heatmap_payload(rows, value_key="statement_count")


def _contest_year_heatmap_payload(
    rows: list[dict],
    *,
    value_key: str,
) -> dict[str, object]:
    if not rows:
        return {"max_value": 0, "series": [], "years": []}

    years = sorted({int(row["contest_year"]) for row in rows})
    value_by_contest_year: dict[str, dict[int, int]] = defaultdict(dict)
    contest_totals: dict[str, int] = defaultdict(int)

    for row in rows:
        contest_name = row["contest_name"]
        contest_year = int(row["contest_year"])
        value = int(row[value_key] or 0)
        value_by_contest_year[contest_name][contest_year] = value
        contest_totals[contest_name] += value

    ordered_contests = sorted(
        contest_totals,
        key=lambda contest_name: (-contest_totals[contest_name], contest_name),
    )
    max_value = max(int(row[value_key] or 0) for row in rows)

    return {
        "max_value": max_value,
        "series": [
            {
                "data": [
                    {
                        "x": str(year),
                        "y": value_by_contest_year[contest_name].get(year, 0),
                    }
                    for year in years
                ],
                "name": contest_name,
            }
            for contest_name in ordered_contests
        ],
        "years": [str(year) for year in years],
    }


def _contest_completion_heatmap_chart_payload(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    state_values = {
        "empty": 0,
        "unsolved": 1,
        "partial": 2,
        "solved": 3,
    }
    if not rows:
        return {"max_value": 3, "series": []}

    return {
        "max_value": 3,
        "series": [
            {
                "name": str(row["year"]),
                "data": [
                    {
                        "display": str(cell["display"]),
                        "state": str(cell["state"]),
                        "title": str(cell["title"]),
                        "x": str(cell["problem_code"]),
                        "y": state_values[str(cell["state"])],
                    }
                    for cell in row["cells"]
                ],
            }
            for row in rows
        ],
    }


def _contest_year_mohs_pivot_payload() -> dict[str, object]:
    statement_rows = list(
        _active_dashboard_statements().values(
            "contest_name",
            "contest_year",
            "problem_code",
            "problem_uuid",
            "mohs",
        ).order_by("contest_name", "-contest_year", "problem_code", "problem_uuid"),
    )
    if not statement_rows:
        return {
            "contest_names": [],
            "mohs_values": [],
            "table_rows": [],
            "year_values": [],
        }

    problem_by_uuid = {
        problem_row["problem_uuid"]: int(problem_row["mohs"])
        for problem_row in ProblemSolveRecord.objects.filter(
            problem_uuid__in=[row["problem_uuid"] for row in statement_rows],
        ).values("problem_uuid", "mohs")
    }
    statement_problem_code_counts = Counter(
        (
            row["contest_name"],
            int(row["contest_year"]),
            (row["problem_code"] or "").strip().upper(),
        )
        for row in statement_rows
    )
    statement_problem_keys = {
        (
            row["contest_name"],
            int(row["contest_year"]),
            (row["problem_code"] or "").strip().upper(),
        )
        for row in statement_rows
        if (row["problem_code"] or "").strip()
    }
    problem_by_statement_key = {
        (
            problem_row["contest"],
            int(problem_row["year"]),
            (problem_row["problem"] or "").strip().upper(),
        ): int(problem_row["mohs"])
        for problem_row in ProblemSolveRecord.objects.filter(
            year__in={key[1] for key in statement_problem_keys},
            contest__in={key[0] for key in statement_problem_keys},
            problem__in={key[2] for key in statement_problem_keys},
        ).values("contest", "year", "problem", "mohs")
    }

    mohs_values: set[int] = set()
    counts_by_contest_year_mohs: dict[tuple[str, int], Counter[int]] = defaultdict(Counter)
    ordered_contest_year_keys: list[tuple[str, int]] = []
    seen_contest_year_keys: set[tuple[str, int]] = set()
    ordered_contest_names: list[str] = []
    seen_contest_names: set[str] = set()
    seen_year_values: set[int] = set()

    for row in statement_rows:
        contest_name = row["contest_name"]
        contest_year = int(row["contest_year"])
        contest_year_key = (contest_name, contest_year)
        if contest_year_key not in seen_contest_year_keys:
            seen_contest_year_keys.add(contest_year_key)
            ordered_contest_year_keys.append(contest_year_key)
        if contest_name not in seen_contest_names:
            seen_contest_names.add(contest_name)
            ordered_contest_names.append(contest_name)
        seen_year_values.add(contest_year)

        problem_code = (row["problem_code"] or "").strip().upper()
        mohs = row.get("mohs")
        if mohs is None:
            mohs = problem_by_uuid.get(row["problem_uuid"])
        if mohs is None and problem_code:
            statement_problem_key = (contest_name, contest_year, problem_code)
            if statement_problem_code_counts[statement_problem_key] == 1:
                mohs = problem_by_statement_key.get(statement_problem_key)
        if mohs is None:
            continue

        mohs_values.add(mohs)
        counts_by_contest_year_mohs[contest_year_key][mohs] += 1

    table_rows = [
        {
            "contest_name": contest_name,
            "contest_year": contest_year,
            "contest_year_label": f"{contest_name} {contest_year}",
            "mohs_counts": {
                str(mohs): counts_by_contest_year_mohs[(contest_name, contest_year)].get(mohs, 0)
                for mohs in sorted(mohs_values)
            },
        }
        for contest_name, contest_year in ordered_contest_year_keys
    ]

    return {
        "contest_names": ordered_contest_names,
        "mohs_values": [str(mohs) for mohs in sorted(mohs_values)],
        "table_rows": table_rows,
        "year_values": [str(year) for year in sorted(seen_year_values, reverse=True)],
    }


def _completion_statement_label(completion: UserProblemCompletion) -> str:
    if completion.statement is not None:
        return completion.statement.contest_year_problem
    if completion.problem is not None:
        return completion.problem.contest_year_problem or (
            f"{completion.problem.contest} {completion.problem.year} {completion.problem.problem}"
        )
    return "Unknown statement"


def _completion_problem_record(completion: UserProblemCompletion) -> ProblemSolveRecord | None:
    if completion.statement is not None and completion.statement.linked_problem is not None:
        return completion.statement.linked_problem
    return completion.problem


def _user_statement_completion_rows(completions: list[UserProblemCompletion]) -> list[dict]:
    completed_statement_ids = {
        completion.statement_id
        for completion in completions
        if completion.statement_id is not None
    }
    legacy_problem_ids = {
        completion.problem_id
        for completion in completions
        if completion.statement_id is None and completion.problem_id is not None
    }
    if legacy_problem_ids:
        completed_statement_ids.update(
            ContestProblemStatement.objects.filter(linked_problem_id__in=legacy_problem_ids).values_list("id", flat=True),
        )
    completed_statement_ids = sorted(statement_id for statement_id in completed_statement_ids if statement_id is not None)
    if not completed_statement_ids:
        return []

    rows = list(
        ContestProblemStatement.objects.filter(id__in=completed_statement_ids)
        .values("contest_name", "contest_year")
        .annotate(completed_count=Count("id"))
        .order_by(
            "-contest_year",
            "contest_name",
        )
    )

    for row in rows:
        row["completed_count"] = int(row["completed_count"] or 0)
        row["contest_year_label"] = f"{row['contest_name']} {row['contest_year']}"

    rows.sort(
        key=lambda row: (
            -row["completed_count"],
            -int(row["contest_year"]),
            row["contest_name"],
        ),
    )
    return rows


def _dashboard_statement_problem_rows(base) -> list[dict]:
    statements = list(
        base.select_related("linked_problem").order_by(
            "-contest_year",
            "contest_name",
            "problem_code",
            "day_label",
            "-updated_at",
            "-id",
        ),
    )
    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    technique_counts_by_problem_id = {
        row["record_id"]: int(row["c"])
        for row in ProblemTopicTechnique.objects.filter(record_id__in=linked_problem_ids)
        .values("record_id")
        .annotate(c=Count("id"))
    }
    technique_counts_by_statement_id = {
        row["statement_id"]: int(row["c"])
        for row in StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values("statement_id")
        .annotate(c=Count("id"))
    }

    rows: list[dict] = []
    for statement in statements:
        linked_problem = statement.linked_problem
        eff_topic = effective_topic(statement)
        topic_label = display_topic_label(eff_topic) if eff_topic else "Unlinked"
        eff_mohs = effective_mohs(statement)
        tech_n = technique_counts_by_statement_id.get(statement.id, 0)
        if tech_n == 0 and linked_problem is not None:
            tech_n = technique_counts_by_problem_id.get(linked_problem.id, 0)
        rows.append(
            {
                "year": int(statement.contest_year),
                "topic": topic_label,
                "mohs": eff_mohs if eff_mohs is not None else "",
                "contest": statement.contest_name,
                "problem": statement.problem_code,
                "contest_year_problem": statement.contest_year_problem,
                "technique_count": tech_n,
            },
        )
    return rows


def _main_topic_code(topic: str) -> str:
    normalized = (topic or "").strip().upper()
    if not normalized:
        return "?"
    return MAIN_TOPIC_CODE_MAP.get(normalized, normalized[0])


def _main_topic_sort_key(topic_code: str) -> tuple[int, str]:
    if topic_code in MAIN_TOPIC_CODE_ORDER:
        return (MAIN_TOPIC_CODE_ORDER.index(topic_code), topic_code)
    return (len(MAIN_TOPIC_CODE_ORDER), topic_code)


def _user_topic_mohs_completion_heatmap_payload(
    completions: list[UserProblemCompletion],
) -> dict[str, object]:
    completion_problems = [problem for problem in (_completion_problem_record(c) for c in completions) if problem is not None]
    if not completion_problems:
        return {"max_value": 0, "mohs_values": [], "series": []}

    value_by_topic_mohs: dict[str, dict[int, int]] = defaultdict(dict)
    topic_totals: dict[str, int] = defaultdict(int)
    mohs_values = sorted({int(problem.mohs) for problem in completion_problems})

    for problem in completion_problems:
        topic_code = _main_topic_code(problem.topic)
        mohs = int(problem.mohs)
        current_value = value_by_topic_mohs[topic_code].get(mohs, 0) + 1
        value_by_topic_mohs[topic_code][mohs] = current_value
        topic_totals[topic_code] += 1

    ordered_topics = sorted(topic_totals, key=_main_topic_sort_key)
    max_value = max(
        value_by_topic_mohs[topic_code].get(mohs, 0)
        for topic_code in ordered_topics
        for mohs in mohs_values
    )

    return {
        "max_value": max_value,
        "mohs_values": [str(mohs) for mohs in mohs_values],
        "series": [
            {
                "data": [
                    {
                        "x": str(mohs),
                        "y": value_by_topic_mohs[topic_code].get(mohs, 0),
                    }
                    for mohs in mohs_values
                ],
                "name": display_topic_label(topic_code),
            }
            for topic_code in ordered_topics
        ],
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


def _month_starts_between(start_date: date, end_date: date) -> list[date]:
    if start_date > end_date:
        return []

    month_starts: list[date] = []
    current_month = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    while current_month <= end_month:
        month_starts.append(current_month)
        current_month = _shift_month(current_month, 1)
    return month_starts


def _pagination_suffix(params: dict[str, str]) -> str:
    query_string = urlencode({key: value for key, value in params.items() if value})
    return f"&{query_string}" if query_string else ""


def _completion_heatmap_level(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    return min(4, max(1, -(-count * 4 // max_count)))


def _solution_status_badge_class(status: str) -> str:
    return {
        ProblemSolution.Status.ARCHIVED: "text-bg-secondary",
        ProblemSolution.Status.DRAFT: "text-bg-warning",
        ProblemSolution.Status.PUBLISHED: "text-bg-success",
        ProblemSolution.Status.SUBMITTED: "text-bg-info",
    }.get(status, "text-bg-light")


def _user_completion_heatmap_payload(
    completion_dates: list[date],
    *,
    end_date: date,
    day_window: int = 365,
) -> dict[str, object]:
    start_date = end_date - timedelta(days=day_window - 1)
    grid_start = start_date - timedelta(days=start_date.weekday())
    grid_end = end_date + timedelta(days=(6 - end_date.weekday()))
    exact_counts_by_day = Counter(
        completion_date
        for completion_date in completion_dates
        if start_date <= completion_date <= end_date
    )
    max_count = max(exact_counts_by_day.values(), default=0)
    weeks: list[dict[str, object]] = []
    current_day = grid_start
    first_visible_month_labeled = False

    while current_day <= grid_end:
        week_days: list[dict[str, object]] = []
        week_dates = [current_day + timedelta(days=offset) for offset in range(7)]
        in_range_week_days = [
            week_day for week_day in week_dates if start_date <= week_day <= end_date
        ]
        month_label = ""
        if in_range_week_days:
            if not first_visible_month_labeled:
                month_label = in_range_week_days[0].strftime("%b")
                first_visible_month_labeled = True
            else:
                month_start_day = next(
                    (week_day for week_day in in_range_week_days if week_day.day == 1),
                    None,
                )
                if month_start_day is not None:
                    month_label = month_start_day.strftime("%b")
        for week_day in week_dates:
            in_range = start_date <= week_day <= end_date
            count = exact_counts_by_day.get(week_day, 0) if in_range else 0
            exact_count = exact_counts_by_day.get(week_day, 0) if in_range else 0
            tooltip = ""
            if in_range:
                tooltip = (
                    f"{week_day.strftime('%a, %d %b %Y')}: "
                    f"{count} completion{'s' if count != 1 else ''}"
                )
            week_days.append(
                {
                    "count": count,
                    "date": week_day.isoformat(),
                    "estimated_count": 0,
                    "exact_count": exact_count,
                    "display_date": week_day.isoformat(),
                    "in_range": in_range,
                    "is_blank": not in_range,
                    "is_today": week_day == end_date,
                    "label": week_day.strftime("%a"),
                    "level": _completion_heatmap_level(count, max_count) if in_range else -1,
                    "title": tooltip,
                    "value": count if in_range else None,
                },
            )
        weeks.append({"days": week_days, "month_label": month_label})
        current_day += timedelta(days=7)

    return {
        "day_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "end_label": end_date.isoformat(),
        "estimated_total": 0,
        "exact_total": sum(exact_counts_by_day.values()),
        "max_count": max_count,
        "start_label": start_date.isoformat(),
        "total_in_window": sum(exact_counts_by_day.values()),
        "uses_estimated_placements": False,
        "weeks": weeks,
    }


def _user_completion_monthly_bar_payload(
    completion_dates: list[date],
    *,
    end_date: date,
) -> dict[str, object]:
    start_date = end_date - timedelta(days=364)
    month_starts = _month_starts_between(start_date, end_date)
    exact_counts_by_month = Counter(
        date(completion_date.year, completion_date.month, 1)
        for completion_date in completion_dates
        if start_date <= completion_date <= end_date
    )
    return {
        "estimated_values": [0 for _month_start in month_starts],
        "exact_values": [exact_counts_by_month.get(month_start, 0) for month_start in month_starts],
        "labels": [month_start.strftime("%b %Y") for month_start in month_starts],
        "values": [exact_counts_by_month.get(month_start, 0) for month_start in month_starts],
    }


def _user_completion_window_options(
    *,
    latest_end_date: date,
    earliest_completion_date: date | None,
    day_window: int = 365,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    offset = 0

    while True:
        window_end = latest_end_date - timedelta(days=offset * day_window)
        window_start = window_end - timedelta(days=day_window - 1)
        label = f"{window_start.isoformat()} to {window_end.isoformat()}"
        if offset == 0:
            label = f"{label} (Latest)"
        options.append(
            {
                "end_label": window_end.isoformat(),
                "label": label,
                "start_label": window_start.isoformat(),
                "value": str(offset),
            },
        )
        if earliest_completion_date is None or earliest_completion_date >= window_start:
            break
        offset += 1

    return options


def _user_completion_heatmap_sections(
    completion_dates: list[date],
    *,
    latest_end_date: date,
    day_window: int = 365,
) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    window_options = _user_completion_window_options(
        latest_end_date=latest_end_date,
        earliest_completion_date=min(completion_dates, default=None),
        day_window=day_window,
    )

    for window_option in reversed(window_options):
        heatmap = _user_completion_heatmap_payload(
            completion_dates,
            end_date=date.fromisoformat(window_option["end_label"]),
            day_window=day_window,
        )
        if heatmap["exact_total"] <= 0:
            continue
        sections.append(
            {
                "heatmap": heatmap,
                "is_latest": window_option["value"] == "0",
            },
        )

    return sections


def _user_completion_table_rows(completions: list[UserProblemCompletion]) -> tuple[list[dict], dict[str, list]]:
    table_rows: list[dict] = []
    completion_years: set[str] = set()
    contests: set[str] = set()
    topics: set[str] = set()
    mohs_values: set[int] = set()
    has_known_dates = False
    has_unknown_dates = False

    for completion in completions:
        problem = _completion_problem_record(completion)
        statement = completion.statement
        problem_label = _completion_statement_label(completion)
        contest_name = statement.contest_name if statement is not None else (problem.contest if problem is not None else "")
        contest_year = statement.contest_year if statement is not None else (problem.year if problem is not None else "")
        problem_code = statement.problem_code if statement is not None else (problem.problem if problem is not None else "")
        problem_url = (
            reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
            if problem is not None
            else ""
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

        if contest_name:
            contests.add(contest_name)
        if problem is not None:
            topics.add(display_topic_label(problem.topic))
            mohs_values.add(problem.mohs)
        table_rows.append(
            {
                "completion_date": completion_date_label,
                "completion_date_sort": completion_date_sort,
                "completion_known": completion_known,
                "completion_year": completion_year,
                "contest": contest_name,
                "date_status": date_status,
                "mohs": problem.mohs if problem is not None else "",
                "problem_code": problem_code,
                "problem_label": problem_label,
                "problem_url": problem_url,
                "problem_uuid": str(problem.problem_uuid) if problem is not None else "",
                "statement_uuid": str(statement.statement_uuid) if statement is not None else "",
                "problem_year": contest_year,
                "topic": display_topic_label(problem.topic) if problem is not None else "Unlinked",
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


def _admin_completion_listing_rows() -> tuple[list[dict], dict[str, int]]:
    completions = list(
        UserProblemCompletion.objects.select_related("user", "problem", "statement", "statement__linked_problem").order_by(
            F("completion_date").desc(nulls_last=True),
            "-updated_at",
            "user__email",
            "statement__contest_name",
            "-statement__contest_year",
            "statement__problem_code",
            "problem__contest",
            "-problem__year",
            "problem__problem",
        ),
    )
    if not completions:
        return [], {
            "contest_total": 0,
            "known_date_total": 0,
            "record_total": 0,
            "solution_total": 0,
            "user_total": 0,
        }

    completion_problems = [
        problem for problem in (_completion_problem_record(completion) for completion in completions) if problem is not None
    ]
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [problem.contest for problem in completion_problems],
    )
    completion_user_ids = {completion.user_id for completion in completions}
    completion_problem_ids = {
        problem.id for problem in completion_problems
    }
    solution_rows = ProblemSolution.objects.filter(
        author_id__in=completion_user_ids,
        problem_id__in=completion_problem_ids,
    ).values("author_id", "problem_id", "status")
    solution_status_by_key = {
        (row["author_id"], row["problem_id"]): row["status"]
        for row in solution_rows
    }

    table_rows: list[dict] = []
    known_date_total = 0
    completion_with_solution_total = 0
    for completion in completions:
        problem = _completion_problem_record(completion)
        statement = completion.statement
        user = completion.user
        problem_label = _completion_statement_label(completion)
        contest_name = statement.contest_name if statement is not None else (problem.contest if problem is not None else "")
        contest_year = statement.contest_year if statement is not None else (problem.year if problem is not None else "")
        problem_code = statement.problem_code if statement is not None else (problem.problem if problem is not None else "")
        contest_slug = contest_to_slug.get(contest_name)
        archive_url = ""
        if contest_slug and contest_year and problem_code:
            archive_url = contest_dashboard_listing_url(contest_name, year=int(contest_year)) + "#" + _problem_anchor(
                problem_label,
                f"{contest_year}-{problem_code}",
            )
        solution_status = solution_status_by_key.get((user.id, problem.id), "") if problem is not None else ""
        if completion.completion_date is not None:
            known_date_total += 1
        if solution_status:
            completion_with_solution_total += 1
        table_rows.append(
            {
                "archive_url": archive_url,
                "completion_date": (
                    completion.completion_date.isoformat() if completion.completion_date is not None else "Unknown"
                ),
                "completion_date_sort": (
                    completion.completion_date.isoformat()
                    if completion.completion_date is not None
                    else "0000-00-00"
                ),
                "contest": contest_name,
                "mohs": problem.mohs if problem is not None else "",
                "problem": problem_code,
                "problem_label": problem_label,
                "problem_url": (
                    reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
                    if problem is not None
                    else ""
                ),
                "problem_uuid": str(problem.problem_uuid) if problem is not None else "",
                "statement_uuid": str(statement.statement_uuid) if statement is not None else "",
                "solution_status": solution_status,
                "solution_status_badge_class": (
                    _solution_status_badge_class(solution_status) if solution_status else "text-bg-light"
                ),
                "solution_status_label": (
                    ProblemSolution.Status(solution_status).label if solution_status else "No solution"
                ),
                "topic": display_topic_label(problem.topic) if problem is not None else "Unlinked",
                "updated_at": timezone.localtime(completion.updated_at).strftime("%Y-%m-%d %H:%M"),
                "updated_at_sort": completion.updated_at.isoformat(),
                "user_email": user.email,
                "user_label": user.name or user.email,
                "user_url": reverse("users:detail", args=[user.pk]),
                "year": contest_year,
            },
        )

    return table_rows, {
        "contest_total": len({row["contest"] for row in table_rows if row["contest"]}),
        "known_date_total": known_date_total,
        "record_total": len(completions),
        "solution_total": completion_with_solution_total,
        "user_total": len({completion.user_id for completion in completions}),
    }


def _admin_solution_listing_rows() -> tuple[list[dict], dict[str, int]]:
    solutions = list(
        ProblemSolution.objects.select_related("author", "problem")
        .annotate(block_count=Count("blocks", distinct=True))
        .order_by("-updated_at", "author__email", "problem__contest", "-problem__year", "problem__problem"),
    )
    if not solutions:
        return [], {
            "author_total": 0,
            "draft_total": 0,
            "problem_total": 0,
            "published_total": 0,
            "solution_total": 0,
        }

    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [solution.problem.contest for solution in solutions],
    )
    status_counts = Counter(solution.status for solution in solutions)
    table_rows: list[dict] = []
    for solution in solutions:
        problem = solution.problem
        author = solution.author
        problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
        contest_slug = contest_to_slug.get(problem.contest)
        archive_url = ""
        if contest_slug:
            archive_url = contest_dashboard_listing_url(problem.contest, year=int(problem.year)) + "#" + _problem_anchor(
                problem_label,
                f"{problem.year}-{problem.problem}",
            )
        table_rows.append(
            {
                "archive_url": archive_url,
                "block_count": int(solution.block_count or 0),
                "contest": problem.contest,
                "mohs": problem.mohs,
                "problem": problem.problem,
                "problem_label": problem_label,
                "problem_uuid": str(problem.problem_uuid),
                "published_at": (
                    timezone.localtime(solution.published_at).strftime("%Y-%m-%d %H:%M")
                    if solution.published_at is not None
                    else "—"
                ),
                "published_at_sort": solution.published_at.isoformat() if solution.published_at else "",
                "status": solution.status,
                "status_badge_class": _solution_status_badge_class(solution.status),
                "status_label": solution.get_status_display(),
                "summary_length": len((solution.summary or "").strip()),
                "solution_url": (
                    reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
                    + "?"
                    + urlencode({"solution": solution.id})
                    + f"#solution-{solution.id}"
                ),
                "title": solution.title or "Untitled solution",
                "topic": display_topic_label(problem.topic),
                "updated_at": timezone.localtime(solution.updated_at).strftime("%Y-%m-%d %H:%M"),
                "updated_at_sort": solution.updated_at.isoformat(),
                "user_email": author.email,
                "user_label": author.name or author.email,
                "user_url": reverse("users:detail", args=[author.pk]),
                "year": problem.year,
            },
        )

    return table_rows, {
        "author_total": len({solution.author_id for solution in solutions}),
        "draft_total": status_counts[ProblemSolution.Status.DRAFT],
        "problem_total": len({solution.problem_id for solution in solutions}),
        "published_total": status_counts[ProblemSolution.Status.PUBLISHED],
        "solution_total": len(solutions),
    }


def _admin_completion_listing_stats(rows: list[dict]) -> dict[str, int]:
    return {
        "contest_total": len({row["contest"] for row in rows}),
        "known_date_total": sum(1 for row in rows if row["completion_date"] != "Unknown"),
        "record_total": len(rows),
        "solution_total": sum(1 for row in rows if row["solution_status"]),
        "user_total": len({row["user_email"] for row in rows}),
    }


def _admin_solution_listing_stats(rows: list[dict]) -> dict[str, int]:
    return {
        "author_total": len({row["user_email"] for row in rows}),
        "draft_total": sum(1 for row in rows if row["status"] == ProblemSolution.Status.DRAFT),
        "problem_total": len({row["problem_uuid"] for row in rows}),
        "published_total": sum(1 for row in rows if row["status"] == ProblemSolution.Status.PUBLISHED),
        "solution_total": len(rows),
    }


def _coerce_year_filter(raw_value: str | None, available_years: set[int]) -> int | None:
    if not raw_value:
        return None
    try:
        year_value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return year_value if year_value in available_years else None


def _completion_board_state_kind(*, is_solved: bool, completion_date: date | None) -> str:
    if not is_solved:
        return "unsolved"
    if completion_date is None:
        return "unknown"
    return "solved"


def _completion_board_state_label(*, is_solved: bool, completion_date: date | None) -> str:
    if not is_solved:
        return "Unsolved"
    if completion_date is None:
        return "Solved without exact date"
    return f"Solved on {completion_date.isoformat()}"


def _completion_board_cell_title(
    *,
    problem_label: str,
    topic: str = "",
    mohs: int | None = None,
    is_solved: bool,
    completion_date: date | None,
) -> str:
    parts = [problem_label]
    if topic:
        parts.append(f"Topic {topic}")
    if mohs is not None:
        parts.append(f"MOHS {mohs}")
    parts.append(_completion_board_state_label(is_solved=is_solved, completion_date=completion_date))
    return " · ".join(parts)


def _completion_board_response_payload(
    *,
    statement: ContestProblemStatement | None,
    problem: ProblemSolveRecord | None,
    is_solved: bool,
    completion_date: date | None,
) -> dict[str, object]:
    problem_label = (
        statement.contest_year_problem
        if statement is not None
        else (problem.contest_year_problem if problem is not None else "")
    ) or (
        f"{problem.contest} {problem.year} {problem.problem}"
        if problem is not None
        else "Unknown statement"
    )
    topic = display_topic_label(problem.topic) if problem is not None else ""
    mohs = problem.mohs if problem is not None else None
    return {
        "completion_date": completion_date.isoformat() if completion_date else "",
        "is_solved": is_solved,
        "problem_label": problem_label,
        "problem_uuid": str(problem.problem_uuid) if problem is not None else "",
        "statement_id": statement.id if statement is not None else None,
        "statement_uuid": str(statement.statement_uuid) if statement is not None else "",
        "state_kind": _completion_board_state_kind(
            is_solved=is_solved,
            completion_date=completion_date,
        ),
        "state_label": _completion_board_state_label(
            is_solved=is_solved,
            completion_date=completion_date,
        ),
        "title": _completion_board_cell_title(
            problem_label=problem_label,
            topic=topic,
            mohs=mohs,
            is_solved=is_solved,
            completion_date=completion_date,
        ),
    }


def _completion_board_get_statement_problem(
    *,
    statement_uuid: str = "",
    problem_uuid: str = "",
) -> tuple[ContestProblemStatement | None, ProblemSolveRecord | None] | None:
    if statement_uuid:
        statement = (
            ContestProblemStatement.objects.select_related("linked_problem")
            .filter(statement_uuid=statement_uuid)
            .first()
        )
        if statement is None:
            return None
        return statement, statement.linked_problem

    if problem_uuid:
        statement = (
            ContestProblemStatement.objects.select_related("linked_problem")
            .filter(linked_problem__problem_uuid=problem_uuid)
            .first()
        )
        if statement is not None and statement.linked_problem is not None:
            return statement, statement.linked_problem

        problem = ProblemSolveRecord.objects.filter(problem_uuid=problem_uuid).first()
        if problem is None:
            return None
        return None, problem

    return None


def _completion_board_parse_requested_date(
    raw_completion_date: str,
    *,
    today: date,
) -> tuple[date | None, str | None]:
    if not raw_completion_date:
        return None, "Completion date is required."
    try:
        completion_date = date.fromisoformat(raw_completion_date)
    except ValueError:
        return None, "Completion date must be a valid YYYY-MM-DD value."
    if completion_date > today:
        return None, "Completion date cannot be in the future."
    return completion_date, None


def _completion_board_apply_action(
    *,
    action: str,
    statement: ContestProblemStatement | None,
    problem: ProblemSolveRecord | None,
    raw_completion_date: str,
    today: date,
    user,
) -> tuple[bool, date | None, str | None]:
    statement_completion = None
    legacy_problem_completion = None
    if statement is not None:
        statement_completion = UserProblemCompletion.objects.filter(
            user=user,
            statement=statement,
        ).first()
        if statement_completion is None and problem is not None:
            legacy_problem_completion = UserProblemCompletion.objects.filter(
                user=user,
                statement__isnull=True,
                problem=problem,
            ).first()
        completion = statement_completion or legacy_problem_completion
    else:
        completion = (
            UserProblemCompletion.objects.filter(
                user=user,
                problem=problem,
            ).first()
            if problem is not None
            else None
        )
    error_message: str | None = None

    def save_statement_completion(completion_date: date | None) -> None:
        assert statement is not None
        UserProblemCompletion.objects.update_or_create(
            user=user,
            statement=statement,
            defaults={
                "completion_date": completion_date,
                "problem": None,
            },
        )

    def can_clear_legacy_problem_completion() -> bool:
        if problem is None:
            return False
        return ContestProblemStatement.objects.filter(linked_problem_id=problem.id).count() <= 1

    if action in {"", "toggle"}:
        if completion is None:
            if statement is not None:
                save_statement_completion(today)
            elif problem is not None:
                completion = UserProblemCompletion.objects.create(
                    user=user,
                    problem=problem,
                    completion_date=today,
                )
            is_solved = True
            completion_date = today
        else:
            if statement is not None:
                if statement_completion is not None:
                    statement_completion.delete()
                    is_solved = False
                    completion_date = None
                elif legacy_problem_completion is not None and can_clear_legacy_problem_completion():
                    legacy_problem_completion.delete()
                    is_solved = False
                    completion_date = None
                else:
                    error_message = (
                        "This completion still comes from a legacy problem record. "
                        "Set an explicit statement completion first."
                    )
                    is_solved = completion is not None
                    completion_date = completion.completion_date if completion is not None else None
            else:
                completion.delete()
                is_solved = False
                completion_date = None
    elif action == "set_date":
        completion_date, error_message = _completion_board_parse_requested_date(
            raw_completion_date,
            today=today,
        )
        if error_message is None and completion_date is not None:
            if statement is not None:
                save_statement_completion(completion_date)
            elif problem is not None:
                UserProblemCompletion.objects.update_or_create(
                    user=user,
                    problem=problem,
                    defaults={"completion_date": completion_date},
                )
            is_solved = True
        else:
            is_solved = completion is not None
            completion_date = completion.completion_date if completion is not None else None
    elif action == "set_unknown":
        if statement is not None:
            save_statement_completion(None)
        elif problem is not None:
            UserProblemCompletion.objects.update_or_create(
                user=user,
                problem=problem,
                defaults={"completion_date": None},
            )
        is_solved = True
        completion_date = None
    elif action == "clear":
        if statement is not None:
            if statement_completion is not None:
                statement_completion.delete()
                is_solved = False
                completion_date = None
            elif legacy_problem_completion is not None and can_clear_legacy_problem_completion():
                legacy_problem_completion.delete()
                is_solved = False
                completion_date = None
            else:
                error_message = (
                    "This completion still comes from a legacy problem record. "
                    "Set an explicit statement completion first."
                )
                is_solved = completion is not None
                completion_date = completion.completion_date if completion is not None else None
        elif problem is not None:
            UserProblemCompletion.objects.filter(user=user, problem=problem).delete()
            is_solved = False
            completion_date = None
        else:
            is_solved = False
            completion_date = None
    else:
        error_message = "Unsupported completion action."

    return is_solved, completion_date, error_message


def _completion_board_slot_label(*, day_label: str, problem_code: str, duplicate_count: int) -> str:
    if duplicate_count <= 1:
        return problem_code
    return f"{day_label or 'Unlabeled'} · {problem_code}"


def _completion_board_slot_sort_key(
    slot_label: str,
) -> tuple[list[tuple[int, int | str]], list[tuple[int, int | str]]]:
    if " · " not in slot_label:
        return ([], _problem_sort_key(slot_label))
    day_label, problem_code = slot_label.split(" · ", 1)
    return (_problem_sort_key(day_label), _problem_sort_key(problem_code))


def _completion_board_parse_row_limit(raw_value: str | None) -> int | None:
    raw_text = (raw_value or "").strip().lower()
    if not raw_text:
        return COMPLETION_BOARD_INITIAL_ROW_LIMIT
    if raw_text == "all":
        return None
    try:
        parsed_value = int(raw_text)
    except (TypeError, ValueError):
        return COMPLETION_BOARD_INITIAL_ROW_LIMIT
    if parsed_value <= 0:
        return COMPLETION_BOARD_INITIAL_ROW_LIMIT
    return parsed_value


def _completion_board_payload(base, *, user, row_limit: int | None) -> dict[str, object]:
    statements = list(
        base.select_related("linked_problem").order_by(
            "-contest_year",
            "contest_name",
            "day_label",
            "problem_number",
            "problem_code",
        ),
    )
    if not statements:
        return {
            "problem_columns": [],
            "rows": [],
            "stats": {
                "contest_year_total": 0,
                "problem_column_total": 0,
                "statement_cell_total": 0,
                "solved_total": 0,
                "trackable_cell_total": 0,
                "unlinked_cell_total": 0,
                "unsolved_total": 0,
            },
        }

    completion_by_statement_id = _statement_completion_dates_by_statement_id(statements, user=user)
    solved_statement_ids = set(completion_by_statement_id)
    solved_statement_total = 0
    for statement in statements:
        if statement.id in solved_statement_ids:
            solved_statement_total += 1
    duplicate_counts = Counter(
        (
            statement.contest_name,
            statement.contest_year,
            statement.problem_code,
        )
        for statement in statements
    )
    problem_columns = sorted(
        {
            _completion_board_slot_label(
                day_label=statement.day_label,
                problem_code=statement.problem_code,
                duplicate_count=duplicate_counts[
                    (statement.contest_name, statement.contest_year, statement.problem_code)
                ],
            )
            for statement in statements
        },
        key=_completion_board_slot_sort_key,
    )

    grouped_rows: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for statement in statements:
        slot_label = _completion_board_slot_label(
            day_label=statement.day_label,
            problem_code=statement.problem_code,
            duplicate_count=duplicate_counts[(statement.contest_name, statement.contest_year, statement.problem_code)],
        )
        grouped_rows[(statement.contest_name, statement.contest_year)][slot_label] = statement

    ordered_row_keys = sorted(
        grouped_rows,
        key=lambda row_key: (-row_key[1], row_key[0].lower()),
    )
    visible_row_keys = ordered_row_keys if row_limit is None else ordered_row_keys[:row_limit]
    board_rows: list[dict[str, object]] = []
    for contest_name, contest_year in visible_row_keys:
        row_problem_map = grouped_rows[(contest_name, contest_year)]
        row_statement_total = 0
        row_solved_total = 0
        row_exact_solved_total = 0
        row_unknown_solved_total = 0
        cells: list[dict[str, object]] = []

        for slot_label in problem_columns:
            statement = row_problem_map.get(slot_label)
            if statement is None:
                cells.append(
                    {
                        "exists": False,
                        "problem_code": slot_label,
                    },
                )
                continue

            linked_problem = statement.linked_problem
            row_statement_total += 1
            problem_label = statement.contest_year_problem or linked_problem.contest_year_problem or (
                f"{statement.contest_name} {statement.contest_year} {statement.problem_code}"
            ) if linked_problem is not None else (
                f"{statement.contest_name} {statement.contest_year} {statement.problem_code}"
            )
            is_solved = statement.id in solved_statement_ids
            completion_date = completion_by_statement_id.get(statement.id) if is_solved else None
            if is_solved:
                row_solved_total += 1
                if completion_date is None:
                    row_unknown_solved_total += 1
                else:
                    row_exact_solved_total += 1

            state_kind = _completion_board_state_kind(
                is_solved=is_solved,
                completion_date=completion_date,
            )
            cells.append(
                {
                    "completion_date": completion_date.isoformat() if completion_date else "",
                    "exists": True,
                    "is_solved": is_solved,
                    "is_trackable": True,
                    "mohs": linked_problem.mohs if linked_problem is not None else None,
                    "problem_code": slot_label,
                    "problem_label": problem_label,
                    "problem_uuid": str(linked_problem.problem_uuid) if linked_problem is not None else "",
                    "statement_uuid": str(statement.statement_uuid),
                    "state_kind": state_kind,
                    "state_label": _completion_board_state_label(
                        is_solved=is_solved,
                        completion_date=completion_date,
                    ),
                    "title": _completion_board_cell_title(
                        problem_label=problem_label,
                        topic=display_topic_label(linked_problem.topic) if linked_problem is not None else "",
                        mohs=linked_problem.mohs if linked_problem is not None else None,
                        is_solved=is_solved,
                        completion_date=completion_date,
                    ),
                    "topic": (
                        display_topic_label(linked_problem.topic)
                        if linked_problem is not None
                        else "Unlinked"
                    ),
                },
            )

        statement_total = len(row_problem_map)
        board_rows.append(
            {
                "cells": cells,
                "completion_rate": round((row_solved_total / row_statement_total) * 100, 1)
                if row_statement_total
                else 0.0,
                "contest_name": contest_name,
                "contest_year": contest_year,
                "contest_year_label": f"{contest_name} {contest_year}",
                "exact_solved_total": row_exact_solved_total,
                "problem_total": row_statement_total,
                "solved_total": row_solved_total,
                "statement_total": statement_total,
                "trackable_total": row_statement_total,
                "unlinked_total": sum(
                    1 for statement in row_problem_map.values() if statement.linked_problem_id is None
                ),
                "unknown_solved_total": row_unknown_solved_total,
                "unsolved_total": row_statement_total - row_solved_total,
            },
        )

    return {
        "problem_columns": problem_columns,
        "rows": board_rows,
        "row_total": len(ordered_row_keys),
        "visible_row_total": len(board_rows),
        "stats": {
            "contest_year_total": len(ordered_row_keys),
            "problem_column_total": len(problem_columns),
            "statement_cell_total": len(statements),
            "solved_total": solved_statement_total,
            "trackable_cell_total": len(statements),
            "unlinked_cell_total": sum(1 for statement in statements if statement.linked_problem_id is None),
            "unsolved_total": len(statements) - solved_statement_total,
        },
    }


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

    rows = list(
        base.annotate(technique_count=Count("topic_techniques"))
        .values(*fields)
        .order_by("-year", "contest", "problem"),
    )
    for row in rows:
        row["topic"] = display_topic_label(row["topic"])
    return rows


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


def _contest_query_url(view_name: str, contest_name: str) -> str:
    return f"{reverse(view_name)}?{urlencode({'contest': contest_name})}"


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
                "metadata_exists": False,
                "metadata_updated_at": None,
                "metadata_updated_label": "",
                "metadata_full_name": "",
                "metadata_countries": [],
                "metadata_countries_label": "",
                "metadata_tags": [],
                "metadata_tags_label": "",
                "metadata_has_description": False,
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
                "metadata_exists": False,
                "metadata_updated_at": None,
                "metadata_updated_label": "",
                "metadata_full_name": "",
                "metadata_countries": [],
                "metadata_countries_label": "",
                "metadata_tags": [],
                "metadata_tags_label": "",
                "metadata_has_description": False,
            },
        )
        inventory_row["statement_count"] = row["statement_count"]
        inventory_row["statement_year_min"] = row["statement_year_min"]
        inventory_row["statement_year_max"] = row["statement_year_max"]

    for metadata in ContestMetadata.objects.order_by("contest"):
        inventory_row = inventory.setdefault(
            metadata.contest,
            {
                "contest": metadata.contest,
                "problem_count": 0,
                "problem_year_min": None,
                "problem_year_max": None,
                "statement_count": 0,
                "statement_year_min": None,
                "statement_year_max": None,
                "metadata_exists": False,
                "metadata_updated_at": None,
                "metadata_updated_label": "",
                "metadata_full_name": "",
                "metadata_countries": [],
                "metadata_countries_label": "",
                "metadata_tags": [],
                "metadata_tags_label": "",
                "metadata_has_description": False,
            },
        )
        inventory_row["metadata_exists"] = True
        inventory_row["metadata_updated_at"] = metadata.updated_at
        inventory_row["metadata_updated_label"] = timezone.localtime(metadata.updated_at).strftime("%Y-%m-%d")
        inventory_row["metadata_full_name"] = metadata.full_name
        inventory_row["metadata_countries"] = list(metadata.countries or [])
        inventory_row["metadata_countries_label"] = ", ".join(metadata.countries or [])
        inventory_row["metadata_tags"] = list(metadata.tags or [])
        inventory_row["metadata_tags_label"] = ", ".join(metadata.tags or [])
        inventory_row["metadata_has_description"] = bool(metadata.description_markdown)

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
            topic_list.append(display_topic_label(row["topic"]))

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
                "topic": display_topic_label(row["topic"]),
                "year": row["year"],
            },
        )

    for row in contest_rows:
        statement_row = statements_by_contest.get(row["contest"], {})
        row["slug"] = contest_to_slug[row["contest"]]
        row["dashboard_listing_url"] = contest_dashboard_listing_url(row["contest"])
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
        topic_label = display_topic_label(record.topic)
        bucket = buckets.setdefault(
            tag_row.technique,
            {
                "technique": tag_row.technique,
                "problem_count": 0,
                "contest_names": set(),
                "contest_counts": defaultdict(int),
                "topic_names": set(),
                "topic_counts": defaultdict(int),
                "domain_names": set(),
                "mohs_values": [],
                "year_values": set(),
            },
        )
        bucket["problem_count"] += 1
        if record.contest:
            bucket["contest_names"].add(record.contest)
            bucket["contest_counts"][record.contest] += 1
        if topic_label:
            bucket["topic_names"].add(topic_label)
            bucket["topic_counts"][topic_label] += 1
        bucket["domain_names"].update(domain_name for domain_name in (tag_row.domains or []) if domain_name)
        bucket["mohs_values"].append(record.mohs)
        bucket["year_values"].add(record.year)

    directory_rows: list[dict] = []
    for technique, bucket in buckets.items():
        contest_names = sorted(bucket["contest_names"])
        topic_names = sorted(bucket["topic_names"])
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
        sample_topics = [
            topic_name
            for topic_name, _count in sorted(
                bucket["topic_counts"].items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        ]
        directory_rows.append(
            {
                "technique": technique,
                "problem_count": bucket["problem_count"],
                "contest_count": len(contest_names),
                "contests": contest_names,
                "topic_count": len(topic_names),
                "topics": topic_names,
                "topics_label": ", ".join(topic_names),
                "sample_topics_label": ", ".join(sample_topics),
                "domain_count": len(domain_names),
                "domains": domain_names,
                "domains_label": ", ".join(domain_names),
                "active_years": len(year_values),
                "years": [str(year_value) for year_value in year_values],
                "year_min": year_min,
                "year_max": year_max,
                "year_span_label": _format_year_span_label(year_min, year_max) or "-",
                "avg_mohs": round(sum(bucket["mohs_values"]) / len(bucket["mohs_values"]), 2),
                "max_mohs": max(bucket["mohs_values"]),
                "sample_contests_label": ", ".join(sample_contests),
                "search_href": reverse("pages:problem_list") + f"?{urlencode({'q': technique})}",
            },
        )

    directory_rows.sort(key=lambda row: (-row["problem_count"], row["technique"]))
    return directory_rows


@login_required
def completion_board_view(request):
    """User-owned contest-year vs problem completion matrix."""
    statement_base = _active_dashboard_statements()
    statement_contest_years = [
        f"{contest_name} {contest_year}"
        for contest_name, contest_year in statement_base.values_list("contest_name", "contest_year")
        .distinct()
        .order_by("-contest_year", "contest_name")
    ]
    all_years = list(
        statement_base.values_list("contest_year", flat=True).distinct().order_by("-contest_year"),
    )
    available_years = set(all_years)
    search_query = (request.GET.get("q") or request.GET.get("contest") or "").strip()
    year_from = _coerce_year_filter(request.GET.get("year_from"), available_years)
    year_to = _coerce_year_filter(request.GET.get("year_to"), available_years)
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from, year_to = year_to, year_from

    base = statement_base
    if search_query:
        for token in search_query.split():
            token_filter = Q(contest_name__icontains=token)
            if token.isdigit():
                token_filter |= Q(contest_year=int(token))
            base = base.filter(token_filter)
    if year_from is not None:
        base = base.filter(contest_year__gte=year_from)
    if year_to is not None:
        base = base.filter(contest_year__lte=year_to)

    row_limit = _completion_board_parse_row_limit(request.GET.get("rows"))
    board_payload = _completion_board_payload(base, user=request.user, row_limit=row_limit)

    def build_completion_board_url(*, rows: int | str | None) -> str:
        params = request.GET.copy()
        if rows is None:
            params.pop("rows", None)
        else:
            params["rows"] = str(rows)
        query_string = params.urlencode()
        base_url = reverse("pages:completion_board")
        return f"{base_url}?{query_string}" if query_string else base_url

    has_more_rows = board_payload["visible_row_total"] < board_payload["row_total"]
    next_row_limit = None
    if has_more_rows and row_limit is not None:
        next_row_limit = min(board_payload["row_total"], row_limit + COMPLETION_BOARD_ROW_LOAD_STEP)

    context = {
        "completion_board_filters": {
            "search_query": search_query,
            "selected_year_from": str(year_from) if year_from is not None else "",
            "selected_year_to": str(year_to) if year_to is not None else "",
            "year_choices": all_years,
        },
        "completion_board_has_records": bool(all_years),
        "completion_board_problem_columns": board_payload["problem_columns"],
        "completion_board_rows": board_payload["rows"],
        "completion_board_row_window": {
            "has_more_rows": has_more_rows,
            "is_partial": row_limit is not None and has_more_rows,
            "loaded_row_total": board_payload["visible_row_total"],
            "remaining_row_total": board_payload["row_total"] - board_payload["visible_row_total"],
            "row_limit": row_limit,
            "show_all_url": build_completion_board_url(rows="all") if has_more_rows else "",
            "total_row_total": board_payload["row_total"],
            "next_rows_url": build_completion_board_url(rows=next_row_limit)
            if next_row_limit is not None
            else "",
        },
        "completion_board_statement_contest_years": statement_contest_years,
        "completion_board_stats": board_payload["stats"],
        "completion_board_bulk_url": reverse("pages:completion_board_bulk"),
        "completion_board_today": timezone.localdate().isoformat(),
        "completion_board_toggle_url": reverse("pages:completion_board_toggle"),
    }
    return render(request, "pages/completion-board.html", context)


@login_required
def completion_board_toggle_view(request):
    """Phase 2 completion controls with a phase 1 toggle fallback."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    statement_uuid = (request.POST.get("statement_uuid") or "").strip()
    problem_uuid = (request.POST.get("problem_uuid") or "").strip()
    if not statement_uuid and not problem_uuid:
        return JsonResponse({"error": "Statement UUID or Problem UUID is required."}, status=400)

    statement_problem = _completion_board_get_statement_problem(
        statement_uuid=statement_uuid,
        problem_uuid=problem_uuid,
    )
    if statement_problem is None:
        raise Http404
    statement, problem = statement_problem

    action = (request.POST.get("action") or "").strip().lower()
    today = timezone.localdate()
    is_solved, completion_date, error_message = _completion_board_apply_action(
        action=action,
        statement=statement,
        problem=problem,
        raw_completion_date=(request.POST.get("completion_date") or "").strip(),
        today=today,
        user=request.user,
    )

    if error_message is not None:
        return JsonResponse({"error": error_message}, status=400)
    return JsonResponse(
        _completion_board_response_payload(
            statement=statement,
            problem=problem,
            is_solved=is_solved,
            completion_date=completion_date,
        ),
    )


@login_required
def completion_board_bulk_view(request):
    """Apply one completion action to multiple selected statement-backed problems."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    raw_statement_uuids = [
        value.strip()
        for value in request.POST.getlist("statement_uuid")
        if value.strip()
    ]
    raw_problem_uuids = [
        value.strip()
        for value in request.POST.getlist("problem_uuid")
        if value.strip()
    ]
    if not raw_statement_uuids and not raw_problem_uuids:
        return JsonResponse({"error": "Select at least one statement first."}, status=400)

    unique_statement_uuids = list(dict.fromkeys(raw_statement_uuids))
    unique_problem_uuids = list(dict.fromkeys(raw_problem_uuids))
    resolved_entries: list[tuple[ContestProblemStatement | None, ProblemSolveRecord | None]] = []
    for statement_uuid_value in unique_statement_uuids:
        statement_problem = _completion_board_get_statement_problem(statement_uuid=statement_uuid_value)
        if statement_problem is None:
            raise Http404
        resolved_entries.append(statement_problem)
    for problem_uuid in unique_problem_uuids:
        statement_problem = _completion_board_get_statement_problem(problem_uuid=problem_uuid)
        if statement_problem is None:
            raise Http404
        resolved_entries.append(statement_problem)

    action = (request.POST.get("action") or "").strip().lower()
    raw_completion_date = (request.POST.get("completion_date") or "").strip()
    today = timezone.localdate()

    updated_payloads: list[dict[str, object]] = []
    with transaction.atomic():
        for statement, problem in resolved_entries:
            is_solved, completion_date, error_message = _completion_board_apply_action(
                action=action,
                statement=statement,
                problem=problem,
                raw_completion_date=raw_completion_date,
                today=today,
                user=request.user,
            )
            if error_message is not None:
                return JsonResponse({"error": error_message}, status=400)
            updated_payloads.append(
                _completion_board_response_payload(
                    statement=statement,
                    problem=problem,
                    is_solved=is_solved,
                    completion_date=completion_date,
                ),
            )

    return JsonResponse(
        {
            "updated": updated_payloads,
            "updated_count": len(updated_payloads),
        },
    )


@login_required
def user_activity_dashboard_view(request):
    """Logged-in user's personal completion dashboard."""
    completion_import_form = ProblemCompletionPasteForm()
    if request.method == "POST" and request.POST.get("action") == "import_completions":
        completion_import_form = ProblemCompletionPasteForm(request.POST)
        if completion_import_form.is_valid():
            result = import_problem_completion_text_for_user(
                request.user,
                completion_import_form.cleaned_data["source_text"],
            )
            if result.n_completions:
                success_message = f"Updated {result.n_completions} completion row(s)."
                if result.n_unknown_dates:
                    success_message += f" {result.n_unknown_dates} marked Done without an exact date."
                messages.success(request, success_message)
            else:
                messages.info(request, "No completion rows were updated.")
            _emit_warning_messages(
                request,
                result.warnings,
                overflow_label="completion import warnings",
            )
            return redirect("pages:user_activity_dashboard")

        messages.error(request, "Please fix the completion import form and try again.")

    completion_qs = UserProblemCompletion.objects.filter(user=request.user).select_related(
        "problem",
        "statement",
        "statement__linked_problem",
    ).order_by(
        F("completion_date").desc(nulls_last=True),
        "-updated_at",
        "statement__contest_name",
        "-statement__contest_year",
        "statement__problem_code",
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
    unknown_completion_total = len(completions) - len(dated_completion_dates)
    table_rows, filter_options = _user_completion_table_rows(completions)
    statement_completion_rows = _user_statement_completion_rows(completions)
    statement_completion_heatmap = _contest_year_heatmap_payload(
        statement_completion_rows,
        value_key="completed_count",
    )
    topic_mohs_completion_heatmap = _user_topic_mohs_completion_heatmap_payload(completions)
    current_year_total = sum(
        1
        for completion_date in dated_completion_dates
        if completion_date.year == today.year
    )
    activity_heatmap = _user_completion_heatmap_payload(
        dated_completion_dates,
        end_date=today,
    )
    activity_heatmap_sections = _user_completion_heatmap_sections(
        dated_completion_dates,
        latest_end_date=today,
    )
    chart_end_date = (
        date.fromisoformat(activity_heatmap_sections[-1]["heatmap"]["end_label"])
        if activity_heatmap_sections
        else today
    )
    activity_window_start = chart_end_date - timedelta(days=364)
    search_query = (request.GET.get("q") or "").strip()
    selected_completion_year = (request.GET.get("completion_year") or "").strip()
    selected_date_status = (request.GET.get("date_status") or "").strip()
    selected_contest = (request.GET.get("contest") or "").strip()
    selected_topic = (request.GET.get("topic") or "").strip()
    selected_mohs = (request.GET.get("mohs") or "").strip()

    filtered_table_rows = table_rows
    if selected_completion_year:
        filtered_table_rows = [
            row for row in filtered_table_rows if row["completion_year"] == selected_completion_year
        ]
    if selected_date_status:
        filtered_table_rows = [
            row for row in filtered_table_rows if row["date_status"] == selected_date_status
        ]
    if selected_contest:
        filtered_table_rows = [
            row for row in filtered_table_rows if row["contest"] == selected_contest
        ]
    if selected_topic:
        filtered_table_rows = [
            row for row in filtered_table_rows if row["topic"] == selected_topic
        ]
    if selected_mohs:
        filtered_table_rows = [
            row for row in filtered_table_rows if str(row["mohs"]) == selected_mohs
        ]
    if search_query:
        tokens = search_query.lower().split()
        filtered_table_rows = [
            row
            for row in filtered_table_rows
            if all(
                token in " ".join(
                    [
                        row["completion_date"],
                        row["contest"],
                        str(row["mohs"]),
                        row["problem_code"],
                        row["problem_label"],
                        str(row["problem_year"]),
                        row["topic"],
                    ],
                ).lower()
                for token in tokens
            )
        ]

    page_obj = Paginator(filtered_table_rows, 25).get_page(request.GET.get("page"))

    context = {
        "activity_total": len(completions),
        "activity_stats": {
            "contest_total": len({row["contest"] for row in table_rows if row["contest"]}),
            "current_year_total": current_year_total,
            "dated_total": len(dated_completion_dates),
            "latest_completion_date": max(dated_completion_dates, default=None),
            "unknown_date_total": unknown_completion_total,
        },
        "activity_filter_options": filter_options,
        "activity_heatmap": activity_heatmap,
        "activity_heatmap_sections": activity_heatmap_sections,
        "activity_month_window_label": (
            f"{date(activity_window_start.year, activity_window_start.month, 1).strftime('%b %Y')} - "
            f"{date(chart_end_date.year, chart_end_date.month, 1).strftime('%b %Y')}"
        ),
        "activity_statement_completion_heatmap": statement_completion_heatmap,
        "activity_statement_completion_stats": {
            "contest_year_total": len(statement_completion_rows),
            "statement_backed_completion_total": sum(
                row["completed_count"] for row in statement_completion_rows
            ),
        },
        "activity_topic_mohs_completion_heatmap": topic_mohs_completion_heatmap,
        "activity_topic_mohs_completion_stats": {
            "cell_total": sum(
                1
                for row in topic_mohs_completion_heatmap["series"]
                for cell in row["data"]
                if cell["y"] > 0
            ),
            "completion_total": len(completions),
            "mohs_total": len(topic_mohs_completion_heatmap["mohs_values"]),
            "topic_total": len(topic_mohs_completion_heatmap["series"]),
        },
        "completion_import_form": completion_import_form,
        "activity_charts_payload": {
            "completionsByMonth": _user_completion_monthly_bar_payload(
                dated_completion_dates,
                end_date=chart_end_date,
            ),
            "statementCompletionHeatmap": statement_completion_heatmap,
            "topicMohsCompletionHeatmap": topic_mohs_completion_heatmap,
        },
        "activity_filters": {
            "completion_year": selected_completion_year,
            "contest": selected_contest,
            "date_status": selected_date_status,
            "mohs": selected_mohs,
            "q": search_query,
            "topic": selected_topic,
        },
        "activity_filtered_total": len(filtered_table_rows),
        "activity_page_obj": page_obj,
        "activity_pagination_suffix": _pagination_suffix(
            {
                "completion_year": selected_completion_year,
                "contest": selected_contest,
                "date_status": selected_date_status,
                "mohs": selected_mohs,
                "q": search_query,
                "topic": selected_topic,
            },
        ),
        "activity_table_rows": filtered_table_rows,
    }
    return render(request, "pages/user-activity-dashboard.html", context)


@login_required
def completion_record_list_view(request):
    """Admin inventory of all saved user completion rows."""
    _require_admin_tools_access(request)
    completion_rows, _completion_stats = _admin_completion_listing_rows()
    search_query = (request.GET.get("q") or "").strip()
    selected_contest = (request.GET.get("contest") or "").strip()
    selected_user = (request.GET.get("user") or "").strip()
    selected_date_status = (request.GET.get("date_status") or "").strip()
    selected_solution_status = (request.GET.get("solution_status") or "").strip()

    completion_filter_options = {
        "contests": sorted({row["contest"] for row in completion_rows}),
        "date_statuses": [
            label
            for label, present in (
                ("known", any(row["completion_date"] != "Unknown" for row in completion_rows)),
                ("unknown", any(row["completion_date"] == "Unknown" for row in completion_rows)),
            )
            if present
        ],
        "solution_statuses": (
            (["none"] if any(not row["solution_status"] for row in completion_rows) else [])
            + [
                status
                for status, _label in ProblemSolution.Status.choices
                if any(row["solution_status"] == status for row in completion_rows)
            ]
        ),
        "users": [
            {
                "label": row["user_label"] if row["user_label"] == row["user_email"] else f"{row['user_label']} ({row['user_email']})",
                "value": row["user_email"],
            }
            for row in {
                row["user_email"]: {
                    "user_email": row["user_email"],
                    "user_label": row["user_label"],
                }
                for row in completion_rows
            }.values()
        ],
    }

    if selected_contest:
        completion_rows = [row for row in completion_rows if row["contest"] == selected_contest]
    if selected_user:
        completion_rows = [row for row in completion_rows if row["user_email"] == selected_user]
    if selected_date_status == "known":
        completion_rows = [row for row in completion_rows if row["completion_date"] != "Unknown"]
    elif selected_date_status == "unknown":
        completion_rows = [row for row in completion_rows if row["completion_date"] == "Unknown"]
    if selected_solution_status:
        completion_rows = [
            row
            for row in completion_rows
            if (row["solution_status"] or "none") == selected_solution_status
        ]
    if search_query:
        tokens = search_query.lower().split()
        completion_rows = [
            row
            for row in completion_rows
            if all(
                token
                in " ".join(
                    [
                        row["user_label"],
                        row["user_email"],
                        row["contest"],
                        str(row["year"]),
                        row["problem"],
                        row["problem_label"],
                        row["topic"],
                        row["completion_date"],
                        row["solution_status_label"],
                    ],
                ).lower()
                for token in tokens
            )
        ]

    completion_stats = _admin_completion_listing_stats(completion_rows)
    context = {
        "completion_record_filter_options": completion_filter_options,
        "completion_record_filters": {
            "date_status": selected_date_status,
            "q": search_query,
            "solution_status": selected_solution_status,
            "contest": selected_contest,
            "user": selected_user,
        },
        "completion_record_rows": completion_rows,
        "completion_record_stats": completion_stats,
    }
    return render(request, "pages/completion-record-list.html", context)


@login_required
def user_solution_record_list_view(request):
    """Admin inventory of all saved user-authored solutions."""
    _require_admin_tools_access(request)
    solution_rows, _solution_stats = _admin_solution_listing_rows()
    search_query = (request.GET.get("q") or "").strip()
    selected_contest = (request.GET.get("contest") or "").strip()
    selected_user = (request.GET.get("user") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()

    solution_filter_options = {
        "contests": sorted({row["contest"] for row in solution_rows}),
        "statuses": [
            status
            for status, _label in ProblemSolution.Status.choices
            if any(row["status"] == status for row in solution_rows)
        ],
        "users": [
            {
                "label": row["user_label"] if row["user_label"] == row["user_email"] else f"{row['user_label']} ({row['user_email']})",
                "value": row["user_email"],
            }
            for row in {
                row["user_email"]: {
                    "user_email": row["user_email"],
                    "user_label": row["user_label"],
                }
                for row in solution_rows
            }.values()
        ],
    }

    if selected_contest:
        solution_rows = [row for row in solution_rows if row["contest"] == selected_contest]
    if selected_user:
        solution_rows = [row for row in solution_rows if row["user_email"] == selected_user]
    if selected_status:
        solution_rows = [row for row in solution_rows if row["status"] == selected_status]
    if search_query:
        tokens = search_query.lower().split()
        solution_rows = [
            row
            for row in solution_rows
            if all(
                token
                in " ".join(
                    [
                        row["user_label"],
                        row["user_email"],
                        row["contest"],
                        str(row["year"]),
                        row["problem"],
                        row["problem_label"],
                        row["topic"],
                        row["title"],
                        row["status_label"],
                    ],
                ).lower()
                for token in tokens
            )
        ]

    solution_stats = _admin_solution_listing_stats(solution_rows)
    context = {
        "user_solution_record_filter_options": solution_filter_options,
        "user_solution_record_filters": {
            "contest": selected_contest,
            "q": search_query,
            "status": selected_status,
            "user": selected_user,
        },
        "user_solution_record_rows": solution_rows,
        "user_solution_record_stats": solution_stats,
    }
    return render(request, "pages/user-solution-record-list.html", context)


@login_required
def dashboard_analytics_view(request):
    """Problem analytics: charts plus searchable table."""
    _require_admin_tools_access(request)

    base = _active_dashboard_statements()
    total = base.count()

    base_eff = annotate_effective_statement_analytics(base)
    stats = base_eff.aggregate(
        year_min=Min("contest_year"),
        year_max=Max("contest_year"),
        contest_n=Count("contest_name", distinct=True),
    )
    stats["topic_n"] = (
        base_eff.exclude(_eff_topic="")
        .values("_eff_topic")
        .distinct()
        .count()
    )
    technique_total = base.aggregate(total=Count("statement_topic_techniques"))["total"] or 0

    by_year = list(base.values("contest_year").annotate(c=Count("id")).order_by("contest_year"))
    for row in by_year:
        row["year"] = row.pop("contest_year")
    by_topic = list(
        base_eff.exclude(_eff_topic="")
        .values("_eff_topic")
        .annotate(c=Count("id"))
        .order_by("-c", "_eff_topic")[:18]
    )
    for row in by_topic:
        raw_topic = row.pop("_eff_topic")
        row["topic"] = display_topic_label(raw_topic) if raw_topic else "Unlinked"
    by_contest = list(
        base.values("contest_name").annotate(c=Count("id")).order_by("-c", "contest_name")[:12]
    )
    for row in by_contest:
        row["contest"] = row.pop("contest_name")
    by_mohs = list(
        base_eff.filter(_eff_mohs__isnull=False)
        .values("_eff_mohs")
        .annotate(c=Count("id"))
        .order_by("_eff_mohs")
    )
    for row in by_mohs:
        row["mohs"] = row.pop("_eff_mohs")
    top_techniques = list(
        base.filter(statement_topic_techniques__technique__isnull=False)
        .exclude(statement_topic_techniques__technique="")
        .values("statement_topic_techniques__technique")
        .annotate(c=Count("id", distinct=True))
        .order_by("-c", "statement_topic_techniques__technique")[:18]
    )
    for row in top_techniques:
        row["technique"] = row.pop("statement_topic_techniques__technique")
    contest_year_mohs_pivot_table = _contest_year_mohs_pivot_payload()

    charts_payload = {
        "byYear": _rows_to_bar_payload(by_year, "year"),
        "byTopic": _rows_to_bar_payload(by_topic, "topic"),
        "byContest": _rows_to_bar_payload(by_contest, "contest"),
        "byMohs": _rows_to_bar_payload(by_mohs, "mohs"),
        "topTechniques": _rows_to_bar_payload(top_techniques, "technique"),
        "contestYearMohsPivotTable": contest_year_mohs_pivot_table,
    }

    table_rows = _dashboard_statement_problem_rows(base)

    context = {
        "analytics_total": total,
        "analytics_stats": stats,
        "analytics_technique_total": technique_total,
        "charts_payload": charts_payload,
        "table_rows": table_rows,
    }
    return render(request, "pages/dashboard-analytics.html", context)


@login_required
def problem_statement_linker_view(request):
    """Admin linking tool for connecting statement rows to tracked problem rows."""
    _require_admin_tools_access(request)

    if request.method == "POST":
        return _handle_problem_statement_linker_post(request)

    linker_payload = _statement_linker_payload()
    context = {
        "statement_linker_candidate_groups": linker_payload["candidate_groups"],
        "statement_linker_contest_names": linker_payload["contest_names"],
        "statement_linker_rows": linker_payload["rows"],
        "statement_linker_stats": linker_payload["stats"],
        "statement_linker_total": len(linker_payload["rows"]),
        "statement_linker_year_values": linker_payload["year_values"],
    }
    return render(request, "pages/problem-statement-linker.html", context)


@login_required
def problem_statement_editor_view(request):
    _require_admin_tools_access(request)
    editor_payload = _statement_editor_table_payload()
    context = {
        "statement_editor_contest_names": editor_payload["contest_names"],
        "statement_editor_rows": editor_payload["rows"],
        "statement_editor_stats": editor_payload["stats"],
        "statement_editor_total": len(editor_payload["rows"]),
        "statement_editor_year_values": editor_payload["year_values"],
    }
    return render(request, "pages/problem-statement-editor.html", context)


@login_required
def problem_statement_editor_update_view(request):
    _require_admin_tools_access(request)
    if request.method != "POST":
        return JsonResponse({"error": "POST required.", "ok": False}, status=405)

    form = ProblemStatementEditorUpdateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors, "ok": False}, status=400)

    try:
        statement = ContestProblemStatement.objects.select_related("linked_problem").get(
            pk=form.cleaned_data["statement_id"],
        )
    except ContestProblemStatement.DoesNotExist as exc:
        raise Http404 from exc

    proposed_contest_year = form.cleaned_data["contest_year"]
    proposed_contest_name = form.cleaned_data["contest_name"]
    proposed_day_label = form.cleaned_data["day_label"]
    proposed_problem_number = form.cleaned_data["problem_number"]
    proposed_problem_code = (
        (form.cleaned_data["problem_code"] or "").strip().upper() or f"P{proposed_problem_number}"
    )
    proposed_statement_latex = form.cleaned_data["statement_latex"]
    proposed_is_active = form.cleaned_data["is_active"]
    duplicate_message = (
        "A statement row with this contest year, contest name, day label and "
        "problem code already exists."
    )

    link_cleared = False
    if statement.linked_problem_id is not None:
        current_identity = (
            int(statement.contest_year),
            statement.contest_name,
            (statement.problem_code or "").strip().upper(),
        )
        proposed_identity = (
            proposed_contest_year,
            proposed_contest_name,
            proposed_problem_code,
        )
        if proposed_identity != current_identity:
            statement.linked_problem = None
            link_cleared = True

    statement.contest_year = proposed_contest_year
    statement.contest_name = proposed_contest_name
    statement.day_label = proposed_day_label
    statement.problem_number = proposed_problem_number
    statement.problem_code = proposed_problem_code
    statement.statement_latex = proposed_statement_latex
    statement.is_active = proposed_is_active

    duplicate_exists = (
        ContestProblemStatement.objects.exclude(pk=statement.pk)
        .filter(
            contest_year=statement.contest_year,
            contest_name=statement.contest_name,
            day_label=statement.day_label,
            problem_code=statement.problem_code,
        )
        .exists()
    )
    if duplicate_exists:
        form.add_error(None, duplicate_message)
        return JsonResponse({"errors": form.errors, "ok": False}, status=400)

    try:
        with transaction.atomic():
            statement.save()
    except IntegrityError:
        form.add_error(
            None,
            "Unable to save the statement row because of a data integrity conflict. Refresh and try again.",
        )
        return JsonResponse({"errors": form.errors, "ok": False}, status=400)

    message = "Statement row saved."
    if link_cleared:
        message = (
            "Statement row saved. The problem link was cleared because contest year, "
            "contest name, or problem code changed. Relink on Statement links when ready."
        )

    return JsonResponse(
        {
            "ok": True,
            "row": _statement_editor_row(statement),
            "message": message,
            "link_cleared": link_cleared,
        },
    )


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

    table_rows = _statement_table_rows(base, user=request.user) if statement_total else []
    table_rows = _json_script_safe(table_rows)
    _ = json.dumps(table_rows, cls=DjangoJSONEncoder, allow_nan=False)

    fq = (request.GET.get("q") or "").strip()
    fyear = (request.GET.get("year") or "").strip()
    ftopic = (request.GET.get("topic") or "").strip()
    fconfidence = (request.GET.get("confidence") or "").strip()
    fmohs_min = (request.GET.get("mohs_min") or "").strip()
    fmohs_max = (request.GET.get("mohs_max") or "").strip()

    filtered_rows = _filter_statement_table_rows(
        table_rows,
        q=fq,
        year=fyear,
        topic=ftopic,
        confidence=fconfidence,
        mohs_min=fmohs_min,
        mohs_max=fmohs_max,
    )
    filter_options = _problem_statement_list_filter_options(table_rows)
    statement_datatable_rows = _json_script_safe(filtered_rows)
    _ = json.dumps(statement_datatable_rows, cls=DjangoJSONEncoder, allow_nan=False)
    copy_tsv = _statement_table_rows_copy_tsv(filtered_rows)

    context = {
        "statement_total": statement_total,
        "statement_stats": {
            "contest_total": contest_total,
            "linked_total": linked_total,
            "unlinked_total": statement_total - linked_total,
            "year_range_label": year_range_label,
        },
        "statement_table_rows": table_rows,
        "statement_datatable_rows": statement_datatable_rows,
        "statement_filtered_total": len(filtered_rows),
        "statement_list_filters": {
            "q": fq,
            "year": fyear,
            "topic": ftopic,
            "confidence": fconfidence,
            "mohs_min": fmohs_min,
            "mohs_max": fmohs_max,
        },
        "statement_filter_years": filter_options["years"],
        "statement_filter_topics": filter_options["topics"],
        "statement_filter_confidences": filter_options["confidences"],
        "statement_copy_tsv": copy_tsv,
    }
    return render(request, "pages/problem-statement-list.html", context)


@login_required
def problem_statement_duplicate_view(request):
    """Admin duplicate detector for exact and high-similarity statement rows."""
    _require_admin_tools_access(request)

    statements = list(ContestProblemStatement.objects.select_related("linked_problem").all())
    duplicate_report = build_statement_duplicate_report(statements)

    context = {
        "statement_duplicate_stats": {
            "statement_total": duplicate_report["statement_total"],
            "exact_duplicate_group_total": duplicate_report["exact_duplicate_group_total"],
            "exact_duplicate_row_total": duplicate_report["exact_duplicate_row_total"],
            "similar_pair_total": duplicate_report["similar_pair_total"],
        },
        "statement_duplicate_exact_rows": duplicate_report["exact_duplicate_rows"],
        "statement_duplicate_similar_rows": duplicate_report["similar_pair_rows"],
        "statement_duplicate_similar_display_total": duplicate_report["similar_pair_display_total"],
        "statement_duplicate_similar_limit": duplicate_report["similar_pair_limit"],
    }
    return render(request, "pages/problem-statement-duplicates.html", context)


@login_required
def problem_statement_delete_by_uuid_view(request):
    """Admin tool: permanently remove one statement row by its immutable statement UUID."""
    _require_admin_tools_access(request)

    if request.method == "POST":
        form = ProblemStatementDeleteByUuidForm(request.POST)
        if form.is_valid():
            statement_uuid = form.cleaned_data["statement_uuid"]
            try:
                statement = ContestProblemStatement.objects.get(statement_uuid=statement_uuid)
            except ContestProblemStatement.DoesNotExist:
                form.add_error("statement_uuid", "No statement row has this statement UUID.")
            else:
                label = statement.contest_year_problem
                statement.delete()
                messages.success(
                    request,
                    f"Deleted statement row {label}. Statement UUID was {statement_uuid}.",
                )
                return redirect("pages:problem_statement_delete_by_uuid")
    else:
        form = ProblemStatementDeleteByUuidForm()

    return render(
        request,
        "pages/problem-statement-delete-by-uuid.html",
        {"form": form},
    )


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
    base = _active_problem_records()
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
def _build_contest_problem_listing_context(
    request,
    *,
    contest_name: str,
    contest_slug: str,
) -> dict[str, object]:
    contest_base = _active_problem_records().filter(contest=contest_name)
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
    selected_topic = display_topic_label((request.GET.get("topic") or "").strip())
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
    for row in problem_rows:
        row["topic"] = display_topic_label(row["topic"])
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
    solution_counts_by_problem_id = {
        row["problem_id"]: row["published_solution_total"]
        for row in ProblemSolution.objects.filter(
            problem__contest=contest_name,
            status=ProblemSolution.Status.PUBLISHED,
        )
        .values("problem_id")
        .annotate(published_solution_total=Count("id"))
    }
    my_solution_rows_by_problem_id = {
        row["problem_id"]: row
        for row in ProblemSolution.objects.filter(
            author=request.user,
            problem__contest=contest_name,
        ).values("problem_id", "status")
    }

    grouped_years: list[dict] = []
    for row in problem_rows:
        statement_data = statement_by_problem_id.get(row["id"])
        published_solution_total = solution_counts_by_problem_id.get(row["id"], 0)
        my_solution_row = my_solution_rows_by_problem_id.get(row["id"])
        label = row["contest_year_problem"] or f"{contest_name} {row['year']} {row['problem']}"
        completion_date = completion_by_problem_id.get(row["id"])
        is_completed = row["id"] in completion_by_problem_id
        completion_state_kind = _completion_board_state_kind(
            is_solved=is_completed,
            completion_date=completion_date,
        )
        completion_state_label = _completion_board_state_label(
            is_solved=is_completed,
            completion_date=completion_date,
        )
        topic_tags = topic_tags_by_problem_id.get(row["id"], [])
        problem_item = {
            "anchor": _problem_anchor(label, f"{row['year']}-{row['problem']}"),
            "confidence": row.get("confidence"),
            "completion_date": completion_date,
            "completion_display": (
                completion_date.isoformat()
                if completion_date is not None
                else ("Unknown date" if is_completed else "Unsolved")
            ),
            "completion_known": is_completed and completion_date is not None,
            "completion_state_kind": completion_state_kind,
            "completion_state_label": completion_state_label,
            "is_completed": is_completed,
            "imo_slot_guess_value": row.get("imo_slot_guess_value"),
            "label": label,
            "mohs": row["mohs"],
            "problem": row["problem"],
            "problem_uuid": str(row["problem_uuid"]),
            "published_solution_total": published_solution_total,
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
            "has_my_solution": my_solution_row is not None,
            "technique_count": row["technique_count"],
            "my_solution_status": my_solution_row["status"] if my_solution_row else "",
            "my_solution_status_badge_class": (
                _solution_status_badge_class(my_solution_row["status"])
                if my_solution_row is not None
                else ""
            ),
            "my_solution_status_label": (
                ProblemSolution.Status(my_solution_row["status"]).label
                if my_solution_row is not None
                else ""
            ),
            "solution_editor_url": reverse("solutions:problem_solution_edit", args=[row["problem_uuid"]]),
            "solutions_url": reverse("solutions:problem_solution_list", args=[row["problem_uuid"]]),
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
    for row in top_topics:
        row["topic"] = display_topic_label(row["topic"])

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
                dict.fromkeys(
                    display_topic_label(topic)
                    for topic in contest_base.values_list("topic", flat=True).distinct().order_by("topic")
                ),
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
    return context


def _build_dashboard_contest_statement_listing_context(
    request,
    *,
    contest_name: str,
    contest_slug: str,
) -> dict[str, object]:
    contest_base = _active_dashboard_statements().filter(contest_name=contest_name)
    contest_base_eff = annotate_effective_statement_analytics(contest_base)
    stats = contest_base_eff.aggregate(
        avg_mohs=Avg("_eff_mohs"),
        statement_n=Count("id"),
        linked_n=Count("id", filter=Q(linked_problem__isnull=False)),
        year_max=Max("contest_year"),
        year_min=Min("contest_year"),
    )
    if not stats["statement_n"]:
        msg = "Contest has no statements."
        raise Http404(msg)

    initial_search_query = (request.GET.get("q") or "").strip()
    selected_mohs = (request.GET.get("mohs") or "").strip()
    selected_year = (request.GET.get("year") or "").strip()
    selected_topic = display_topic_label((request.GET.get("topic") or "").strip())
    selected_tag = (request.GET.get("tag") or "").strip()

    statements = list(
        contest_base.select_related("linked_problem").order_by(
            "-contest_year",
            "day_label",
            "problem_number",
            "problem_code",
            "-updated_at",
            "-id",
        ),
    )
    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    topic_tag_rows = list(
        ProblemTopicTechnique.objects.filter(record_id__in=linked_problem_ids)
        .values("record_id", "technique", "domains")
        .order_by("technique", "record_id"),
    )
    stmt_topic_tag_rows = list(
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values("statement_id", "technique", "domains")
        .order_by("technique", "statement_id"),
    )
    topic_tags_by_problem_id: dict[int, list[dict]] = defaultdict(list)
    topic_tags_by_statement_id: dict[int, list[dict]] = defaultdict(list)
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
    for tag_row in stmt_topic_tag_rows:
        technique = tag_row["technique"]
        domains = tag_row.get("domains") or []
        topic_tags_by_statement_id[tag_row["statement_id"]].append(
            {
                "domains": domains,
                "domains_label": ", ".join(domains),
                "technique": technique,
            },
        )
        if technique not in seen_topic_tags:
            seen_topic_tags.add(technique)
            topic_tag_options.append(technique)

    completion_by_statement_id = _statement_completion_dates_by_statement_id(
        statements,
        user=request.user,
    )
    solution_counts_by_problem_id = {
        row["problem_id"]: row["published_solution_total"]
        for row in ProblemSolution.objects.filter(
            problem_id__in=linked_problem_ids,
            status=ProblemSolution.Status.PUBLISHED,
        )
        .values("problem_id")
        .annotate(published_solution_total=Count("id"))
    }
    my_solution_rows_by_problem_id = {
        row["problem_id"]: row
        for row in ProblemSolution.objects.filter(
            author=request.user,
            problem_id__in=linked_problem_ids,
        ).values("problem_id", "status")
    }

    problem_rows: list[dict[str, object]] = []
    for statement in statements:
        linked_problem = statement.linked_problem
        topic_tags = topic_tags_by_statement_id.get(statement.id, [])
        if not topic_tags:
            topic_tags = topic_tags_by_problem_id.get(statement.linked_problem_id, [])
        render_payload = _statement_render_payload(statement.statement_latex)
        is_linked = linked_problem is not None
        completion_date = completion_by_statement_id.get(statement.id)
        is_completed = statement.id in completion_by_statement_id
        completion_state_kind = _completion_board_state_kind(
            is_solved=is_completed,
            completion_date=completion_date,
        )
        completion_state_label = _completion_board_state_label(
            is_solved=is_completed,
            completion_date=completion_date,
        )
        if completion_date is not None:
            completion_display = completion_date.isoformat()
        elif is_completed:
            completion_display = "Unknown date"
        else:
            completion_display = "Unsolved"

        label = statement.contest_year_problem or f"{statement.contest_name} {statement.contest_year} {statement.problem_code}"
        eff_topic = effective_topic(statement)
        topic_label = display_topic_label(eff_topic) if eff_topic else ""
        published_solution_total = (
            solution_counts_by_problem_id.get(linked_problem.id, 0)
            if linked_problem is not None
            else 0
        )
        my_solution_row = (
            my_solution_rows_by_problem_id.get(linked_problem.id)
            if linked_problem is not None
            else None
        )
        problem_rows.append(
            {
                "anchor": _problem_anchor(label, f"statement-{statement.id}"),
                "completion_date": completion_date,
                "completion_display": completion_display,
                "completion_known": is_completed and completion_date is not None,
                "completion_state_kind": completion_state_kind,
                "completion_state_label": completion_state_label,
                "confidence": effective_confidence(statement),
                "has_my_solution": my_solution_row is not None,
                "has_statement": True,
                "imo_slot_guess_value": effective_imo_slot_guess_value(statement),
                "is_completed": is_completed,
                "is_linked": is_linked,
                "label": label,
                "mohs": effective_mohs(statement),
                "my_solution_status": my_solution_row["status"] if my_solution_row else "",
                "my_solution_status_badge_class": (
                    _solution_status_badge_class(my_solution_row["status"])
                    if my_solution_row is not None
                    else ""
                ),
                "my_solution_status_label": (
                    ProblemSolution.Status(my_solution_row["status"]).label
                    if my_solution_row is not None
                    else ""
                ),
                "problem": statement.problem_code,
                "problem_code": statement.problem_code,
                "problem_uuid": str(linked_problem.problem_uuid) if linked_problem is not None else "",
                "statement_uuid": str(statement.statement_uuid),
                "published_solution_total": published_solution_total,
                "solution_editor_url": (
                    reverse("solutions:problem_solution_edit", args=[linked_problem.problem_uuid])
                    if linked_problem is not None
                    else ""
                ),
                "solutions_url": (
                    reverse("solutions:problem_solution_list", args=[linked_problem.problem_uuid])
                    if linked_problem is not None
                    else ""
                ),
                "statement_day_label": statement.day_label or "",
                "statement_has_asymptote": render_payload["statement_has_asymptote"],
                "statement_id": statement.id,
                "statement_latex": statement.statement_latex,
                "statement_render_segments": render_payload["statement_render_segments"],
                "statement_updated_at_label": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d"),
                "technique_count": len(topic_tags),
                "topic": topic_label,
                "topic_tags": topic_tags,
                "year": int(statement.contest_year),
            },
        )

    problem_rows.sort(
        key=lambda row: (
            -int(row["year"]),
            _problem_sort_key(str(row["problem_code"])),
            str(row["statement_day_label"] or ""),
            str(row["label"]),
        ),
    )

    if selected_year:
        problem_rows = [row for row in problem_rows if str(row["year"]) == selected_year]

    if selected_mohs:
        problem_rows = [row for row in problem_rows if str(row.get("mohs") or "") == selected_mohs]

    if selected_topic:
        problem_rows = [row for row in problem_rows if row["topic"] == selected_topic]

    if selected_tag:
        problem_rows = [
            row
            for row in problem_rows
            if any(tag["technique"] == selected_tag for tag in row["topic_tags"])
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
                    str(row["problem_code"]),
                    str(row["topic"]),
                    str(row["label"]),
                    str(row.get("confidence") or ""),
                    str(row.get("imo_slot_guess_value") or ""),
                    str(row.get("statement_day_label") or ""),
                    *(
                        tag["technique"]
                        for tag in row["topic_tags"]
                    ),
                    *(
                        tag["domains_label"]
                        for tag in row["topic_tags"]
                        if tag["domains_label"]
                    ),
                ],
            ).lower()
        ]

    grouped_years: list[dict[str, object]] = []
    for row in problem_rows:
        if not grouped_years or grouped_years[-1]["year"] != row["year"]:
            grouped_years.append({"year": row["year"], "problems": [row]})
            continue
        grouped_years[-1]["problems"].append(row)

    top_topic_rows = list(
        contest_base_eff.filter(~Q(_eff_topic=""))
        .values("_eff_topic")
        .annotate(statement_count=Count("id"))
        .order_by("-statement_count", "_eff_topic")[:6]
    )
    top_topics = [
        display_topic_label(str(row["_eff_topic"]))
        for row in top_topic_rows
        if row["_eff_topic"]
    ]

    years = list(contest_base.values_list("contest_year", flat=True).distinct().order_by("-contest_year"))
    mohs_values = list(
        contest_base_eff.filter(_eff_mohs__isnull=False)
        .values_list("_eff_mohs", flat=True)
        .distinct()
        .order_by("_eff_mohs")
    )
    topics = list(
        dict.fromkeys(
            display_topic_label(topic)
            for topic in contest_base_eff.filter(~Q(_eff_topic=""))
            .values_list("_eff_topic", flat=True)
            .distinct()
            .order_by("_eff_topic")
            if topic
        ),
    )

    context = {
        "contest_problem_total": int(stats["statement_n"] or 0),
        "contest_problem_stats": {
            "avg_mohs": round(float(stats["avg_mohs"] or 0), 1),
            "statement_total": int(stats["statement_n"] or 0),
            "year_range_label": (
                str(stats["year_min"])
                if stats["year_min"] == stats["year_max"]
                else f"{stats['year_min']}-{stats['year_max']}"
            ),
        },
        "contest_slug": contest_slug,
        "contest_title": contest_name,
        "filter_options": {
            "mohs_values": [value for value in mohs_values if value is not None],
            "tags": topic_tag_options,
            "topics": topics,
            "years": years,
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
        "statement_rendering_enabled": bool(problem_rows),
        "top_topics": top_topics,
    }
    return context


@login_required
def contest_problem_list_view(request, contest_slug: str):
    """Legacy URL under /problems/contests/… redirects to dashboard contest listing."""
    contest_names = list(_active_problem_records().values_list("contest", flat=True).distinct())
    _contest_to_slug, slug_to_contest = _build_contest_slug_maps(contest_names)
    contest_name = slug_to_contest.get(contest_slug)
    if contest_name is None:
        msg = "Contest not found."
        raise Http404(msg)
    query = request.GET.copy()
    query["contest"] = contest_name
    return redirect(f"{reverse('pages:contest_dashboard_listing')}?{query.urlencode()}")


@login_required
def contest_dashboard_listing_view(request):
    """Dashboard contest listing drill-down selected by query string."""
    contest_choices = [
        {
            "contest": row["contest_name"],
            "problem_count": row["problem_count"],
        }
        for row in _active_dashboard_statements()
        .values("contest_name")
        .annotate(problem_count=Count("id"))
        .order_by("contest_name")
    ]
    if not contest_choices:
        msg = "Contest not found."
        raise Http404(msg)

    contest_names = [row["contest"] for row in contest_choices]
    selected_contest = (request.GET.get("contest") or "").strip() or contest_names[0]
    if selected_contest not in set(contest_names):
        msg = "Contest not found."
        raise Http404(msg)

    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(contest_names)
    context = _build_dashboard_contest_statement_listing_context(
        request,
        contest_name=selected_contest,
        contest_slug=contest_to_slug[selected_contest],
    )
    context.update(
        {
            "contest_choices": contest_choices,
            "contest_back_label": "Back to advanced analytics",
            "contest_back_url": (
                reverse("pages:contest_advanced_dashboard")
                + "?"
                + urlencode({"contest": selected_contest})
            ),
            "contest_listing_base_url": (
                reverse("pages:contest_dashboard_listing")
                + "?"
                + urlencode({"contest": selected_contest})
            ),
            "completion_board_today": timezone.localdate().isoformat(),
            "completion_board_toggle_url": reverse("pages:completion_board_toggle"),
            "contest_dashboard_bulk_update_url": reverse("pages:contest_dashboard_listing_bulk_update"),
            "contest_dashboard_current_url": request.get_full_path(),
            "selected_contest": selected_contest,
            "show_contest_dashboard_bulk": user_has_admin_role(request.user),
        },
    )
    return render(request, "pages/contest-dashboard-listing.html", context)


@login_required
def contest_dashboard_listing_bulk_update_view(request):
    """Apply bulk archive visibility actions for selected contest-listing rows."""
    _require_admin_tools_access(request)

    if request.method != "POST":
        return redirect("pages:contest_dashboard")

    redirect_url = (request.POST.get("next") or "").strip()
    if not redirect_url.startswith("/"):
        redirect_url = reverse("pages:contest_dashboard")

    action = (request.POST.get("action") or "").strip().lower()
    selected_contest = (request.POST.get("contest") or "").strip()
    selected_statement_ids: list[int] = []
    for raw_value in request.POST.getlist("statement_id"):
        try:
            selected_statement_ids.append(int(str(raw_value).strip()))
        except (TypeError, ValueError):
            continue
    if not selected_contest:
        messages.error(request, "Contest selection is missing from this bulk update.")
        return redirect(redirect_url)
    if not selected_statement_ids:
        messages.error(request, "Select at least one problem row first.")
        return redirect(redirect_url)

    selected_rows = list(
        _active_dashboard_statements().filter(
            contest_name=selected_contest,
            id__in=selected_statement_ids,
        ),
    )
    if not selected_rows:
        messages.error(request, "No active statement rows matched the current selection.")
        return redirect(redirect_url)

    if action != "set_inactive":
        messages.error(request, "Unsupported bulk contest listing action.")
        return redirect(redirect_url)

    updated_total = ContestProblemStatement.objects.filter(
        contest_name=selected_contest,
        id__in=[row.id for row in selected_rows],
        is_active=True,
    ).update(is_active=False)
    if updated_total and not _active_dashboard_statements().filter(contest_name=selected_contest).exists():
        redirect_url = reverse("pages:contest_dashboard")
    messages.success(
        request,
        f"Set {updated_total} statement row(s) inactive.",
    )
    return redirect(redirect_url)


@login_required
def problem_detail_view(request, problem_uuid: uuid.UUID):
    problem = _active_problem_records().filter(problem_uuid=problem_uuid).first()
    if problem is None:
        msg = "Problem not found."
        raise Http404(msg)
    has_visible_solution = ProblemSolution.objects.filter(problem=problem).filter(
        Q(author=request.user) | Q(status=ProblemSolution.Status.PUBLISHED),
    ).exists()
    if has_visible_solution:
        return redirect("solutions:problem_solution_list", problem.problem_uuid)
    return redirect("solutions:problem_solution_edit", problem.problem_uuid)


@login_required
def contest_analytics_view(request):
    """Contest analytics: contest-level summaries, charts, and ranked table."""
    _require_admin_tools_access(request)

    base = _active_dashboard_statements()
    problem_total = base.count()

    base_eff = annotate_effective_statement_analytics(base)
    contest_rows = list(
        base_eff.values("contest_name")
        .annotate(
            problem_count=Count("id"),
            year_min=Min("contest_year"),
            year_max=Max("contest_year"),
            active_years=Count("contest_year", distinct=True),
            distinct_topics=Count(
                "_eff_topic",
                filter=~Q(_eff_topic=""),
                distinct=True,
            ),
            avg_mohs=Avg("_eff_mohs"),
            max_mohs=Max("_eff_mohs"),
        )
        .order_by("-problem_count", "contest_name"),
    )
    technique_rows_by_contest = {
        row["contest_name"]: int(row["c"])
        for row in base.values("contest_name").annotate(c=Count("statement_topic_techniques"))
    }
    for row in contest_rows:
        row["contest"] = row.pop("contest_name")
        row["technique_rows"] = technique_rows_by_contest.get(row["contest"], 0)
        row["avg_mohs"] = round(float(row["avg_mohs"] or 0), 2)
        row["techniques_per_problem"] = round(row["technique_rows"] / row["problem_count"], 2)
        row["year_span_label"] = (
            str(row["year_min"])
            if row["year_min"] == row["year_max"]
            else f"{row['year_min']}-{row['year_max']}"
        )
        row["detail_url"] = _contest_query_url("pages:contest_advanced_dashboard", row["contest"])

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
def contest_advanced_analytics_view(request):
    """Drill-down analytics for one contest, selected by query string."""
    contest_choices = [
        {
            "contest": row["contest_name"],
            "problem_count": row["problem_count"],
        }
        for row in _active_dashboard_statements()
        .values("contest_name")
        .annotate(problem_count=Count("id"))
        .order_by("contest_name")
    ]
    if not contest_choices:
        return render(
            request,
            "pages/contest-advanced-analytics.html",
            {
                "contest_choices": [],
                "contest_completion_heatmap": {
                    "filled_cell_total": 0,
                    "has_partial_cells": False,
                    "problem_code_total": 0,
                    "problem_codes": [],
                    "rows": [],
                    "year_total": 0,
                },
                "has_contests": False,
                "selected_contest": "",
            },
        )

    contest_names = [row["contest"] for row in contest_choices]
    selected_contest = (request.GET.get("contest") or "").strip() or contest_names[0]
    if selected_contest not in set(contest_names):
        msg = "Contest not found."
        raise Http404(msg)

    contest_base = _active_dashboard_statements().filter(contest_name=selected_contest)
    contest_base_eff = annotate_effective_statement_analytics(contest_base)
    stats = contest_base_eff.aggregate(
        active_years=Count("contest_year", distinct=True),
        avg_mohs=Avg("_eff_mohs"),
        distinct_topics=Count(
            "_eff_topic",
            filter=~Q(_eff_topic=""),
            distinct=True,
        ),
        linked_statement_total=Count("id", filter=Q(linked_problem__isnull=False)),
        max_mohs=Max("_eff_mohs"),
        problem_count=Count("id"),
        year_max=Max("contest_year"),
        year_min=Min("contest_year"),
    )

    technique_row_total = (
        contest_base.aggregate(total=Count("statement_topic_techniques"))["total"] or 0
    )
    statement_row_total = int(stats["problem_count"] or 0)
    statement_problem_total = int(stats["linked_statement_total"] or 0)
    solution_problem_total = (
        contest_base.filter(linked_problem__solutions__isnull=False).distinct().count()
    )
    published_solution_total = contest_base.filter(
        linked_problem__solutions__status=ProblemSolution.Status.PUBLISHED,
    ).distinct().count()

    year_rows = list(
        annotate_effective_statement_analytics(contest_base)
        .values("contest_year")
        .annotate(
            avg_mohs=Avg("_eff_mohs"),
            distinct_topics=Count(
                "_eff_topic",
                filter=~Q(_eff_topic=""),
                distinct=True,
            ),
            max_mohs=Max("_eff_mohs"),
            linked_statement_total=Count(
                "id",
                filter=Q(linked_problem__isnull=False),
                distinct=True,
            ),
            problem_count=Count("id", distinct=True),
            solved_problem_total=Count(
                "id",
                filter=Q(user_completions__user=request.user)
                | Q(linked_problem__user_completions__user=request.user),
                distinct=True,
            ),
        )
        .order_by("-contest_year"),
    )
    for row in year_rows:
        row["year"] = int(row.pop("contest_year"))
        row["avg_mohs"] = (
            round(float(row["avg_mohs"]), 2) if row["avg_mohs"] is not None else None
        )
        row["statement_problem_total"] = int(row.get("linked_statement_total") or 0)
        row["solved_rate"] = round(
            (row["solved_problem_total"] / row["problem_count"]) * 100,
            1,
        ) if row["problem_count"] else 0.0
        year_int = int(row["year"])
        row["year_detail_url"] = contest_dashboard_listing_url(selected_contest, year=year_int)

    contest_statements = list(
        contest_base.select_related("linked_problem").values(
            "id",
            "linked_problem_id",
            "problem_code",
            "contest_year",
        ),
    )
    direct_solved_statement_ids = set(
        UserProblemCompletion.objects.filter(
            user=request.user,
            statement_id__in=[row["id"] for row in contest_statements],
        ).values_list("statement_id", flat=True),
    )
    legacy_solved_problem_ids = set(
        UserProblemCompletion.objects.filter(
            user=request.user,
            statement__isnull=True,
            problem__contest=selected_contest,
        ).values_list("problem_id", flat=True),
    )
    heatmap_problem_codes = sorted(
        {
            str(problem_code).strip()
            for problem_code in contest_base.values_list("problem_code", flat=True)
            if problem_code
        },
        key=_problem_sort_key,
    )
    heatmap_years = sorted(
        {
            int(year)
            for year in contest_base.values_list("contest_year", flat=True)
            if year is not None
        },
        reverse=True,
    )
    heatmap_counts: dict[tuple[int, str], dict[str, int]] = {}
    for record in contest_statements:
        problem_code = str(record["problem_code"] or "").strip()
        year = record["contest_year"]
        if not problem_code or year is None:
            continue
        heatmap_key = (int(year), problem_code)
        cell_counts = heatmap_counts.setdefault(
            heatmap_key,
            {
                "problem_total": 0,
                "solved_total": 0,
            },
        )
        cell_counts["problem_total"] += 1
        linked_problem_id = record["linked_problem_id"]
        if record["id"] in direct_solved_statement_ids or (
            linked_problem_id is not None and int(linked_problem_id) in legacy_solved_problem_ids
        ):
            cell_counts["solved_total"] += 1

    heatmap_rows: list[dict[str, object]] = []
    has_partial_heatmap_cells = False
    for year in heatmap_years:
        row_cells: list[dict[str, object]] = []
        for problem_code in heatmap_problem_codes:
            counts = heatmap_counts.get((year, problem_code))
            if counts is None:
                row_cells.append(
                    {
                        "display": "",
                        "problem_code": problem_code,
                        "state": "empty",
                        "title": f"{selected_contest} {year} {problem_code}: no statement row",
                    },
                )
                continue

            problem_total = int(counts["problem_total"])
            solved_total = int(counts["solved_total"])
            if solved_total == 0:
                state = "unsolved"
            elif solved_total == problem_total:
                state = "solved"
            else:
                state = "partial"
                has_partial_heatmap_cells = True

            rows_word = "statement row" if problem_total == 1 else "statement rows"
            row_cells.append(
                {
                    "display": (
                        "✓"
                        if problem_total == 1 and state == "solved"
                        else ("•" if problem_total == 1 else f"{solved_total}/{problem_total}")
                    ),
                    "problem_code": problem_code,
                    "state": state,
                    "title": (
                        f"{selected_contest} {year} {problem_code}: "
                        f"{solved_total} of {problem_total} {rows_word} solved by you"
                    ),
                },
            )

        heatmap_rows.append(
            {
                "cells": row_cells,
                "year": year,
            },
        )

    topic_rows = list(
        contest_base_eff.filter(~Q(_eff_topic=""))
        .values("_eff_topic")
        .annotate(
            avg_mohs=Avg("_eff_mohs"),
            max_mohs=Max("_eff_mohs"),
            problem_count=Count("id"),
        )
        .order_by("-problem_count", "_eff_topic"),
    )
    for row in topic_rows:
        raw_topic = row.pop("_eff_topic")
        row["topic"] = display_topic_label(raw_topic) if raw_topic else "Unlinked"
        row["avg_mohs"] = (
            round(float(row["avg_mohs"]), 2) if row["avg_mohs"] is not None else None
        )

    confidence_rows = list(
        contest_base_eff.exclude(_eff_confidence="")
        .values("_eff_confidence")
        .annotate(problem_count=Count("id"))
        .order_by("-problem_count", "_eff_confidence"),
    )
    for row in confidence_rows:
        row["confidence"] = row.pop("_eff_confidence")

    recent_statement_rows = [
        {
            "day_label": statement.day_label or "",
            "is_linked": statement.linked_problem_id is not None,
            "problem_code": statement.problem_code,
            "updated_at_label": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d"),
        }
        for statement in contest_base.order_by(
            "-updated_at",
            "-contest_year",
            "day_label",
            "problem_number",
        )[:8]
    ]

    public_contest_url = ""
    if _active_problem_records().filter(contest=selected_contest).exists():
        public_contest_url = contest_dashboard_listing_url(selected_contest)

    context = {
        "contest_choices": contest_choices,
        "contest_stats": {
            "active_years": stats["active_years"],
            "avg_mohs": round(float(stats["avg_mohs"] or 0), 2),
            "distinct_topics": stats["distinct_topics"],
            "linked_statement_total": statement_problem_total,
            "max_mohs": stats["max_mohs"] or 0,
            "problem_count": stats["problem_count"],
            "published_solution_total": published_solution_total,
            "solution_problem_total": solution_problem_total,
            "statement_problem_total": statement_problem_total,
            "statement_row_total": statement_row_total,
            "technique_rows": technique_row_total,
            "techniques_per_problem": round(
                technique_row_total / stats["problem_count"],
                2,
            )
            if stats["problem_count"]
            else 0.0,
            "year_span_label": _format_year_span_label(stats["year_min"], stats["year_max"]) or "-",
        },
        "confidence_rows": confidence_rows,
        "contest_completion_heatmap": {
            "chart": _contest_completion_heatmap_chart_payload(heatmap_rows),
            "filled_cell_total": len(heatmap_counts),
            "has_partial_cells": has_partial_heatmap_cells,
            "problem_code_total": len(heatmap_problem_codes),
            "problem_codes": heatmap_problem_codes,
            "rows": heatmap_rows,
            "year_total": len(heatmap_rows),
        },
        "has_contests": True,
        "public_contest_url": public_contest_url,
        "recent_statement_rows": recent_statement_rows,
        "selected_contest": selected_contest,
        "topic_rows": topic_rows,
        "year_rows": year_rows,
    }
    return render(request, "pages/contest-advanced-analytics.html", context)


@login_required
def topic_tag_analytics_view(request):
    """Technique analytics: coverage, breadth, and difficulty signals per parsed technique."""
    _require_admin_tools_access(request)

    tag_rows = list(
        ProblemTopicTechnique.objects.select_related("record")
        .all()
        .order_by("technique", "record__contest", "record__problem"),
    )
    tag_directory = _build_topic_tag_directory_rows(tag_rows)

    technique_total = len(tag_directory)
    technique_row_total = len(tag_rows)
    tagged_problem_total = len({tag_row.record_id for tag_row in tag_rows})
    distinct_contests = sorted({tag_row.record.contest for tag_row in tag_rows if tag_row.record.contest})
    distinct_domains = sorted(
        {
            domain_name
            for tag_row in tag_rows
            for domain_name in (tag_row.domains or [])
            if domain_name
        }
    )
    distinct_topics = sorted(
        {
            display_topic_label(tag_row.record.topic)
            for tag_row in tag_rows
            if display_topic_label(tag_row.record.topic)
        }
    )
    average_techniques_per_problem = (
        round(technique_row_total / tagged_problem_total, 2) if tagged_problem_total else 0.0
    )

    by_year_counter: Counter[int] = Counter()
    by_domain_counter: Counter[str] = Counter()
    for tag_row in tag_rows:
        if tag_row.record.year is not None:
            by_year_counter[int(tag_row.record.year)] += 1
        for domain_name in (tag_row.domains or []):
            if domain_name:
                by_domain_counter[domain_name] += 1

    year_activity_rows = [
        {"year": year_value, "c": by_year_counter[year_value]}
        for year_value in sorted(by_year_counter)
    ]
    domain_volume_rows = [
        {"domain": domain_name, "c": count}
        for domain_name, count in sorted(
            by_domain_counter.items(),
            key=lambda item: (-item[1], item[0]),
        )[:12]
    ]

    most_used_technique = tag_directory[0] if tag_directory else None
    broadest_contest_technique = (
        sorted(
            tag_directory,
            key=lambda row: (-row["contest_count"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    broadest_domain_technique = (
        sorted(
            tag_directory,
            key=lambda row: (-row["domain_count"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    widest_topic_technique = (
        sorted(
            tag_directory,
            key=lambda row: (-row["topic_count"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    longest_running_technique = (
        sorted(
            tag_directory,
            key=lambda row: (-row["active_years"], -row["problem_count"], row["technique"]),
        )[0]
        if tag_directory
        else None
    )
    highest_avg_mohs_technique = (
        sorted(
            tag_directory,
            key=lambda row: (-row["avg_mohs"], -row["problem_count"], row["technique"]),
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
        "byTopicBreadth": _rows_to_bar_payload(
            sorted(
                tag_directory,
                key=lambda row: (-row["topic_count"], -row["problem_count"], row["technique"]),
            )[:12],
            "technique",
            value_key="topic_count",
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
        "byYearActivity": _rows_to_bar_payload(year_activity_rows, "year"),
        "byDomainVolume": _rows_to_bar_payload(domain_volume_rows, "domain"),
    }

    context = {
        "technique_total": technique_total,
        "technique_row_total": technique_row_total,
        "tagged_problem_total": tagged_problem_total,
        "technique_stats": {
            "contest_total": len(distinct_contests),
            "domain_total": len(distinct_domains),
            "topic_total": len(distinct_topics),
            "average_techniques_per_problem": average_techniques_per_problem,
        },
        "technique_leaders": {
            "most_used": most_used_technique,
            "broadest_contest": broadest_contest_technique,
            "broadest_domain": broadest_domain_technique,
            "widest_topic": widest_topic_technique,
            "longest_running": longest_running_technique,
            "highest_avg_mohs": highest_avg_mohs_technique,
        },
        "technique_filter_options": {
            "contests": distinct_contests,
            "domains": distinct_domains,
            "topics": distinct_topics,
            "years": [str(year_value) for year_value in sorted(by_year_counter, reverse=True)],
        },
        "technique_rows": tag_directory,
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


def _export_problem_statement_workbook_response() -> HttpResponse:
    statements = (
        ContestProblemStatement.objects.select_related("linked_problem")
        .order_by("-contest_year", "contest_name", "day_label", "problem_number", "problem_code")
    )
    workbook_bytes = build_problem_statement_export_workbook_bytes(list(statements))
    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(workbook_bytes, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = (
        f'attachment; filename="asterproof-problem-statements-{timestamp}.xlsx"'
    )
    return response


def _export_statement_metadata_workbook_response() -> HttpResponse:
    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").order_by(
            "-contest_year",
            "contest_name",
            "day_label",
            "problem_number",
            "problem_code",
        ),
    )
    workbook_bytes = build_statement_metadata_export_workbook_bytes(statements)
    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(workbook_bytes, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = (
        f'attachment; filename="asterproof-statement-metadata-{timestamp}.xlsx"'
    )
    return response


def _statement_metadata_table_payload() -> dict[str, object]:
    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").order_by(
            "-contest_year",
            "contest_name",
            "day_label",
            "problem_number",
            "problem_code",
        ),
    )
    export_rows = build_statement_metadata_export_dataframe(statements).fillna("").to_dict(orient="records")

    contest_names: list[str] = []
    seen_contest_names: set[str] = set()
    year_values: list[str] = []
    seen_year_values: set[str] = set()
    table_rows: list[dict[str, object]] = []
    linked_total = 0
    ready_total = 0

    for statement, export_row in zip(statements, export_rows, strict=True):
        contest_name = statement.contest_name
        contest_year = int(statement.contest_year)
        contest_year_label = f"{contest_name} {contest_year}"
        year_value = str(contest_year)
        if contest_name not in seen_contest_names:
            seen_contest_names.add(contest_name)
            contest_names.append(contest_name)
        if year_value not in seen_year_values:
            seen_year_values.add(year_value)
            year_values.append(year_value)

        topic = str(export_row.get("TOPIC") or "")
        mohs = str(export_row.get("MOHS") or "")
        confidence = str(export_row.get("Confidence") or "")
        imo_slot_guess = str(export_row.get("IMO slot guess") or "")
        topic_tags = str(export_row.get("Topic tags") or "")
        has_metadata = bool(topic and mohs)
        is_linked = statement.linked_problem_id is not None
        linked_problem_label = ""
        if statement.linked_problem is not None:
            linked_problem_label = statement.linked_problem.contest_year_problem or (
                f"{statement.linked_problem.contest} "
                f"{statement.linked_problem.year} "
                f"{statement.linked_problem.problem}"
            )

        if has_metadata:
            ready_total += 1
        if is_linked:
            linked_total += 1

        day_label_display = statement.day_label or "Unlabeled"
        contest_problem_display = (
            f"{statement.contest_year_problem} · {day_label_display} · {statement.problem_code}"
        )
        table_rows.append(
            {
                "confidence": confidence,
                "contest_name": contest_name,
                "contest_problem": statement.contest_year_problem,
                "contest_problem_display": contest_problem_display,
                "contest_year": contest_year,
                "contest_year_label": contest_year_label,
                "day_label": day_label_display,
                "has_metadata": "yes" if has_metadata else "no",
                "imo_slot_guess": imo_slot_guess,
                "is_linked": is_linked,
                "link_status": "linked" if is_linked else "unlinked",
                "linked_problem_label": linked_problem_label,
                "metadata_status": "ready" if has_metadata else "missing",
                "mohs": mohs,
                "problem_code": statement.problem_code,
                "statement_uuid": str(statement.statement_uuid),
                "problem_uuid": str(statement.problem_uuid),
                "statement_id": statement.id,
                "statement_preview": _statement_preview_text(statement.statement_latex),
                "topic": topic,
                "topic_tags": topic_tags,
            },
        )

    year_values.sort(reverse=True)
    return {
        "contest_names": contest_names,
        "rows": table_rows,
        "stats": {
            "linked_total": linked_total,
            "missing_total": len(table_rows) - ready_total,
            "ready_total": ready_total,
            "statement_total": len(table_rows),
        },
        "year_values": year_values,
    }


def _statement_metadata_dataframe_from_post(post_data) -> tuple[object | None, str | None]:
    raw_statement_uuids = [str(value or "").strip() for value in post_data.getlist("statement_uuid")]
    raw_topics = post_data.getlist("topic")
    raw_mohs = post_data.getlist("mohs")
    raw_confidences = post_data.getlist("confidence")
    raw_imo_slot_guesses = post_data.getlist("imo_slot_guess")
    raw_topic_tags = post_data.getlist("topic_tags")

    if not raw_statement_uuids:
        return None, "Stage at least one metadata row before saving."

    expected_length = len(raw_statement_uuids)
    raw_column_lengths = {
        "topic": len(raw_topics),
        "mohs": len(raw_mohs),
        "confidence": len(raw_confidences),
        "imo_slot_guess": len(raw_imo_slot_guesses),
        "topic_tags": len(raw_topic_tags),
    }
    if any(length != expected_length for length in raw_column_lengths.values()):
        return None, "Submitted bulk metadata is incomplete. Please reload the page and try again."

    rows = [
        {
            "STATEMENT UUID": raw_statement_uuids[index],
            "TOPIC": raw_topics[index],
            "MOHS": raw_mohs[index],
            "Confidence": raw_confidences[index],
            "IMO slot guess": raw_imo_slot_guesses[index],
            "Topic tags": raw_topic_tags[index],
        }
        for index in range(expected_length)
    ]
    try:
        return statement_metadata_dataframe_from_rows(rows), None
    except StatementMetadataBackfillValidationError as exc:
        return None, str(exc)


def _apply_statement_metadata_import(
    request,
    *,
    metadata_df,
    replace_tags: bool,
    success_prefix: str,
    skipped_label: str,
) -> bool:
    try:
        result = import_statement_metadata_dataframe(
            metadata_df,
            replace_tags=replace_tags,
        )
    except StatementMetadataBackfillValidationError as exc:
        messages.error(request, str(exc))
        record_event(
            event_type=AuditEvent.EventType.IMPORT_FAILED,
            message=f"Statement metadata import failed validation: {exc}",
            request=request,
            metadata={"error": str(exc)},
        )
        return False

    messages.success(
        request,
        (
            f"{success_prefix} Processed {result.processed_count} row(s): "
            f"{result.created_count} created, {result.updated_count} updated, "
            f"{result.linked_count} linked, {result.technique_count} technique row(s) touched, "
            f"{result.skipped_count} {skipped_label} skipped."
        ),
    )
    record_event(
        event_type=AuditEvent.EventType.IMPORT_COMPLETED,
        message=(
            f"Imported statement metadata for {result.processed_count} row(s), "
            f"creating {result.created_count} problem row(s) and updating "
            f"{result.updated_count} existing row(s)."
        ),
        request=request,
        metadata={
            "created_count": result.created_count,
            "linked_count": result.linked_count,
            "processed_count": result.processed_count,
            "replace_tags": replace_tags,
            "skipped_count": result.skipped_count,
            "technique_count": result.technique_count,
            "updated_count": result.updated_count,
        },
    )
    return True


def _parse_statement_csv_uuid(raw_value: object, *, label: str, row_number: int) -> uuid.UUID | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        msg = f'Row {row_number}: "{label}" must be a valid UUID.'
        raise ProblemStatementCsvImportValidationError(msg) from exc


def _parse_statement_csv_problem_number(
    raw_value: object,
    *,
    problem_code: str,
    row_number: int,
) -> int:
    value = str(raw_value or "").strip()
    if value:
        try:
            problem_number = int(value)
        except ValueError as exc:
            msg = f'Row {row_number}: "PROBLEM NUMBER" must be an integer.'
            raise ProblemStatementCsvImportValidationError(msg) from exc
        if problem_number <= 0:
            msg = f'Row {row_number}: "PROBLEM NUMBER" must be greater than zero.'
            raise ProblemStatementCsvImportValidationError(msg)
        return problem_number

    match = re.fullmatch(r"P?(?P<number>\d+)", problem_code, flags=re.IGNORECASE)
    if not match:
        msg = (
            f'Row {row_number}: provide "PROBLEM NUMBER" or a parseable "PROBLEM CODE" '
            'like "P1".'
        )
        raise ProblemStatementCsvImportValidationError(msg)
    return int(match.group("number"))


def _prepare_statement_csv_row(raw_row: dict[str, object], *, row_number: int) -> dict[str, object]:
    contest_year_text = str(raw_row.get("CONTEST YEAR", "") or "").strip()
    if not contest_year_text:
        msg = f'Row {row_number}: "CONTEST YEAR" is required.'
        raise ProblemStatementCsvImportValidationError(msg)
    try:
        contest_year = int(contest_year_text)
    except ValueError as exc:
        msg = f'Row {row_number}: "CONTEST YEAR" must be an integer.'
        raise ProblemStatementCsvImportValidationError(msg) from exc

    contest_name = normalize_contest_name(str(raw_row.get("CONTEST NAME", "") or ""))
    if not contest_name:
        msg = f'Row {row_number}: "CONTEST NAME" is required.'
        raise ProblemStatementCsvImportValidationError(msg)

    day_label = normalize_contest_name(str(raw_row.get("DAY LABEL", "") or ""))
    problem_code = re.sub(r"\s+", "", str(raw_row.get("PROBLEM CODE", "") or "")).upper()
    problem_number = _parse_statement_csv_problem_number(
        raw_row.get("PROBLEM NUMBER", ""),
        problem_code=problem_code,
        row_number=row_number,
    )
    normalized_problem_code = problem_code or f"P{problem_number}"

    statement_latex = str(raw_row.get("STATEMENT LATEX", "") or "")
    if not statement_latex.strip():
        msg = f'Row {row_number}: "STATEMENT LATEX" is required.'
        raise ProblemStatementCsvImportValidationError(msg)

    problem_uuid_value = _parse_statement_csv_uuid(
        raw_row.get("PROBLEM UUID", ""),
        label="PROBLEM UUID",
        row_number=row_number,
    )
    linked_problem_uuid = _parse_statement_csv_uuid(
        raw_row.get("LINKED PROBLEM UUID", ""),
        label="LINKED PROBLEM UUID",
        row_number=row_number,
    )

    return {
        "contest_name": contest_name,
        "contest_year": contest_year,
        "day_label": day_label,
        "linked_problem_uuid": linked_problem_uuid,
        "problem_code": normalized_problem_code,
        "problem_number": problem_number,
        "problem_uuid": problem_uuid_value,
        "statement_latex": statement_latex.strip(),
    }


@transaction.atomic
def _import_problem_statement_csv(uploaded_file) -> int:
    try:
        decoded = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = "Please upload a UTF-8 CSV file."
        raise ProblemStatementCsvImportValidationError(msg) from exc

    stream = StringIO(decoded, newline="")
    reader = csv.reader(stream)
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        msg = "The CSV file is empty."
        raise ProblemStatementCsvImportValidationError(msg) from exc

    headers = [str(header or "").strip() for header in raw_headers]
    missing_columns = sorted(STATEMENT_CSV_REQUIRED_COLUMNS.difference(headers))
    if missing_columns:
        missing_label = ", ".join(f'"{column}"' for column in missing_columns)
        msg = f"Missing required column(s): {missing_label}."
        raise ProblemStatementCsvImportValidationError(msg)

    dict_reader = csv.DictReader(stream, fieldnames=headers)
    imported_count = 0

    for row_number, raw_row in enumerate(dict_reader, start=2):
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue

        prepared_row = _prepare_statement_csv_row(raw_row, row_number=row_number)
        linked_problem = None
        linked_problem_uuid = prepared_row["linked_problem_uuid"]
        if linked_problem_uuid is not None:
            linked_problem = ProblemSolveRecord.objects.filter(problem_uuid=linked_problem_uuid).first()
            if linked_problem is None:
                msg = f'Row {row_number}: linked problem "{linked_problem_uuid}" was not found.'
                raise ProblemStatementCsvImportValidationError(msg)

        problem_uuid_value = prepared_row["problem_uuid"]
        statement = None
        if problem_uuid_value is not None:
            statement = ContestProblemStatement.objects.filter(problem_uuid=problem_uuid_value).first()
        if statement is None:
            statement = ContestProblemStatement.objects.filter(
                contest_year=prepared_row["contest_year"],
                contest_name=prepared_row["contest_name"],
                day_label=prepared_row["day_label"],
                problem_code=prepared_row["problem_code"],
            ).first()

        if statement is None:
            statement = ContestProblemStatement(
                problem_uuid=problem_uuid_value or uuid.uuid4(),
            )
        elif (
            problem_uuid_value is not None
            and statement.problem_uuid != problem_uuid_value
            and statement.linked_problem_id is None
        ):
            statement.problem_uuid = problem_uuid_value

        statement.linked_problem = linked_problem
        if problem_uuid_value is not None and linked_problem is None:
            statement.problem_uuid = problem_uuid_value
        statement.contest_year = prepared_row["contest_year"]
        statement.contest_name = prepared_row["contest_name"]
        statement.day_label = prepared_row["day_label"]
        statement.problem_number = prepared_row["problem_number"]
        statement.problem_code = prepared_row["problem_code"]
        statement.statement_latex = prepared_row["statement_latex"]
        try:
            statement.save()
        except IntegrityError as exc:
            msg = f"Row {row_number}: could not save statement row because it conflicts with an existing entry."
            raise ProblemStatementCsvImportValidationError(msg) from exc
        imported_count += 1

    if imported_count == 0:
        msg = "The CSV file did not contain any statement rows."
        raise ProblemStatementCsvImportValidationError(msg)

    return imported_count


def _preview_contest_names(contests: tuple[str, ...]) -> str:
    preview_limit = 3
    preview = ", ".join(f'"{contest}"' for contest in contests[:preview_limit])
    if len(contests) > preview_limit:
        return f"{preview}, and {len(contests) - preview_limit} more"
    return preview


def _contest_choice_rows(inventory_rows: list[dict]) -> list[tuple[str, str]]:
    return [
        (
            row["contest"],
            (
                f'{row["contest"]} '
                f'({row["problem_count"]} problems, {row["statement_count"]} statements)'
            ),
        )
        for row in inventory_rows
    ]


def _resolve_selected_contest_name(request, contest_choices: list[tuple[str, str]]) -> str:
    available_contests = {choice[0] for choice in contest_choices}
    requested_contest = normalize_contest_name(
        request.POST.get("contest") or request.GET.get("contest") or "",
    )
    if requested_contest in available_contests:
        return requested_contest
    if contest_choices:
        return contest_choices[0][0]
    return ""


def _contest_metadata_form_initial(selected_contest: str, metadata: ContestMetadata | None) -> dict[str, object]:
    initial: dict[str, object] = {"contest": selected_contest}
    if metadata is None:
        return initial

    initial.update(
        {
            "countries_text": "\n".join(metadata.countries or []),
            "description_markdown": metadata.description_markdown,
            "full_name": metadata.full_name,
            "tags_text": "\n".join(metadata.tags or []),
        },
    )
    return initial


@login_required
def contest_details_view(request):
    _require_admin_tools_access(request)

    inventory_rows = _contest_inventory_rows()
    contest_choices = _contest_choice_rows(inventory_rows)
    selected_contest = _resolve_selected_contest_name(request, contest_choices)
    selected_inventory_row = next(
        (row for row in inventory_rows if row["contest"] == selected_contest),
        None,
    )
    selected_metadata = (
        ContestMetadata.objects.filter(contest=selected_contest).first()
        if selected_contest
        else None
    )

    if request.method == "POST":
        form = ContestMetadataForm(request.POST, contest_choices=contest_choices)
        if form.is_valid():
            contest_name = form.cleaned_data["contest"]
            metadata, _created = ContestMetadata.objects.get_or_create(contest=contest_name)
            metadata.full_name = form.cleaned_data["full_name"]
            metadata.countries = form.cleaned_data["countries_text"]
            metadata.tags = form.cleaned_data["tags_text"]
            metadata.description_markdown = form.cleaned_data["description_markdown"]
            metadata.save()
            messages.success(request, f'Saved contest details for "{contest_name}".')
            return redirect(f'{reverse("pages:contest_details")}?{urlencode({"contest": contest_name})}')

        selected_contest = normalize_contest_name(form["contest"].value() or selected_contest)
        selected_inventory_row = next(
            (row for row in inventory_rows if row["contest"] == selected_contest),
            None,
        )
        selected_metadata = (
            ContestMetadata.objects.filter(contest=selected_contest).first()
            if selected_contest
            else None
        )
    else:
        form = ContestMetadataForm(
            contest_choices=contest_choices,
            initial=_contest_metadata_form_initial(selected_contest, selected_metadata),
        )

    unique_countries = sorted(
        {
            country
            for row in inventory_rows
            for country in row["metadata_countries"]
        },
    )
    unique_tags = sorted(
        {
            tag
            for row in inventory_rows
            for tag in row["metadata_tags"]
        },
    )

    return render(
        request,
        "pages/contest-details.html",
        {
            "contest_choices": contest_choices,
            "contest_detail_stats": {
                "contest_total": len(inventory_rows),
                "country_total": len(unique_countries),
                "description_total": sum(1 for row in inventory_rows if row["metadata_has_description"]),
                "metadata_total": sum(1 for row in inventory_rows if row["metadata_exists"]),
                "tag_total": len(unique_tags),
            },
            "form": form,
            "inventory_rows": inventory_rows,
            "selected_contest": selected_contest,
            "selected_inventory_row": selected_inventory_row,
            "selected_metadata": selected_metadata,
        },
    )


@login_required
def contest_rename_view(request):
    _require_admin_tools_access(request)

    inventory_rows = _contest_inventory_rows()
    contest_choices = _contest_choice_rows(inventory_rows)

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

    if request.method == "GET":
        export_action = request.GET.get("action")
        if export_action == "export":
            return _export_problem_workbook_response()
        if export_action in {"export_statement_csv", "export_statement_xlsx"}:
            return _export_problem_statement_workbook_response()

    replace_tags_initial = request.method == "POST" and bool(request.POST.get("problem-replace_tags"))
    preview_payload: dict | None = None

    problem_form = ProblemXlsxImportForm(
        initial={"replace_tags": replace_tags_initial},
        prefix="problem",
    )
    statement_csv_form = ProblemStatementCsvImportForm(prefix="statement_csv")

    if request.method == "POST":
        action = request.POST.get("action") or "import"

        if action in {"preview", "import"}:
            problem_form = ProblemXlsxImportForm(request.POST, request.FILES, prefix="problem")
            if problem_form.is_valid():
                replace_tags = problem_form.cleaned_data["replace_tags"]
                replace_tags_initial = replace_tags

                try:
                    workbook_df = dataframe_from_excel(problem_form.cleaned_data["file"].read())
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
                problem_form = ProblemXlsxImportForm(
                    initial={"replace_tags": replace_tags_initial},
                    prefix="problem",
                )
        elif action == "import_statement_csv":
            statement_csv_form = ProblemStatementCsvImportForm(
                request.POST,
                request.FILES,
                prefix="statement_csv",
            )
            if statement_csv_form.is_valid():
                try:
                    imported_count = _import_problem_statement_csv(
                        statement_csv_form.cleaned_data["file"],
                    )
                except ProblemStatementCsvImportValidationError as exc:
                    messages.error(request, str(exc))
                    record_event(
                        event_type=AuditEvent.EventType.IMPORT_FAILED,
                        message=f"Statement CSV import failed validation: {exc}",
                        request=request,
                        metadata={"error": str(exc)},
                    )
                else:
                    messages.success(
                        request,
                        f"Imported {imported_count} problem statement row(s) from CSV.",
                    )
                    record_event(
                        event_type=AuditEvent.EventType.IMPORT_COMPLETED,
                        message=f"Imported {imported_count} problem statement row(s) from CSV.",
                        request=request,
                        metadata={"statement_row_count": imported_count},
                    )
                    statement_csv_form = ProblemStatementCsvImportForm(prefix="statement_csv")
        else:
            messages.error(request, "Unknown import action.")

    return render(
        request,
        "pages/problem-import.html",
        {
            "preview_payload": preview_payload,
            "problem_form": problem_form,
            "statement_csv_form": statement_csv_form,
        },
    )


@login_required
def problem_statement_metadata_view(request):
    _require_admin_tools_access(request)

    if request.method == "GET" and request.GET.get("action") == "export":
        return _export_statement_metadata_workbook_response()

    form = StatementMetadataWorkbookForm()
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "save_grid":
            metadata_df, validation_error = _statement_metadata_dataframe_from_post(request.POST)
            if validation_error is not None:
                messages.error(request, validation_error)
                record_event(
                    event_type=AuditEvent.EventType.IMPORT_FAILED,
                    message=f"Statement metadata import failed validation: {validation_error}",
                    request=request,
                    metadata={"error": validation_error},
                )
            else:
                replace_tags = bool(request.POST.get("replace_tags"))
                if _apply_statement_metadata_import(
                    request,
                    metadata_df=metadata_df,
                    replace_tags=replace_tags,
                    success_prefix="Statement metadata save finished.",
                    skipped_label="untouched staged row(s)",
                ):
                    return redirect("pages:problem_statement_metadata")
        else:
            form = StatementMetadataWorkbookForm(request.POST, request.FILES)
            if form.is_valid():
                replace_tags = form.cleaned_data["replace_tags"]
                try:
                    uploaded_file = form.cleaned_data["file"]
                    source_text = form.cleaned_data["source_text"]
                    if uploaded_file is not None:
                        metadata_df = statement_metadata_dataframe_from_excel(uploaded_file.read())
                    else:
                        metadata_df = statement_metadata_dataframe_from_text(source_text)
                except StatementMetadataBackfillValidationError as exc:
                    messages.error(request, str(exc))
                    record_event(
                        event_type=AuditEvent.EventType.IMPORT_FAILED,
                        message=f"Statement metadata import failed validation: {exc}",
                        request=request,
                        metadata={"error": str(exc)},
                    )
                else:
                    if _apply_statement_metadata_import(
                        request,
                        metadata_df=metadata_df,
                        replace_tags=replace_tags,
                        success_prefix="Statement metadata import finished.",
                        skipped_label="untouched import row(s)",
                    ):
                        return redirect("pages:problem_statement_metadata")

    table_payload = _statement_metadata_table_payload()
    return render(
        request,
        "pages/problem-statement-metadata.html",
        {
            "form": form,
            "statement_metadata_contest_names": table_payload["contest_names"],
            "statement_metadata_rows": table_payload["rows"],
            "statement_metadata_stats": table_payload["stats"],
            "statement_metadata_total": len(table_payload["rows"]),
            "statement_metadata_year_values": table_payload["year_values"],
        },
    )
