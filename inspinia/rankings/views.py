from __future__ import annotations

import csv
from decimal import Decimal

import pandas as pd
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Max
from django.db.models import Prefetch
from django.db.models import Q
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from openpyxl import Workbook

from inspinia.rankings.forms import AssessmentResultImportForm
from inspinia.rankings.forms import LegacyWideImportForm
from inspinia.rankings.forms import RankingTableFilterForm
from inspinia.rankings.forms import StudentMasterImportForm
from inspinia.rankings.imports.assessment_result_import import apply_assessment_result_import
from inspinia.rankings.imports.assessment_result_import import assessment_result_dataframe_from_source
from inspinia.rankings.imports.assessment_result_import import preview_assessment_result_import
from inspinia.rankings.imports.legacy_wide_import import apply_legacy_wide_import
from inspinia.rankings.imports.legacy_wide_import import preview_legacy_wide_import
from inspinia.rankings.imports.student_master_import import apply_student_master_import
from inspinia.rankings.imports.student_master_import import preview_student_master_import
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.rankings.services.privacy import mask_nric
from inspinia.rankings.services.privacy import user_can_view_full_nric
from inspinia.users.models import AuditEvent
from inspinia.users.monitoring import record_event
from inspinia.users.roles import user_has_admin_role

RANKING_TABLE_MAX_ROWS = 5000
IMPORT_BATCH_HISTORY_LIMIT = 20
MAX_DERIVED_AGE = 100


def _require_rankings_admin_access(request) -> None:
    if not settings.DEBUG and not user_has_admin_role(request.user):
        raise PermissionDenied


def _read_tabular_upload(upload) -> pd.DataFrame:
    if isinstance(upload, str):
        if upload.lower().endswith(".csv"):
            return pd.read_csv(upload)
        return pd.read_excel(upload)

    filename = (getattr(upload, "name", "") or "").lower()
    if hasattr(upload, "seek"):
        upload.seek(0)
    if filename.endswith(".csv"):
        return pd.read_csv(upload)
    return pd.read_excel(upload)


def _serialize_breakdown_values(snapshot: RankingSnapshot) -> dict[int, str]:
    raw_breakdown = snapshot.score_breakdown_json
    if not isinstance(raw_breakdown, dict):
        return {}

    by_assessment_id: dict[int, str] = {}
    for item in raw_breakdown.values():
        if not isinstance(item, dict):
            continue
        assessment_id = item.get("assessment_id")
        if assessment_id is None:
            continue
        try:
            assessment_id_int = int(assessment_id)
        except (TypeError, ValueError):
            continue

        value = item.get("normalized_score")
        if value is None:
            by_assessment_id[assessment_id_int] = ""
        elif isinstance(value, str):
            by_assessment_id[assessment_id_int] = value
        else:
            by_assessment_id[assessment_id_int] = str(value)

    return by_assessment_id


def _derived_age(birth_year: int | None) -> int | None:
    if birth_year is None:
        return None
    current_year = timezone.now().year
    age = current_year - birth_year
    if age < 0 or age > MAX_DERIVED_AGE:
        return None
    return age


def _pick_selection_status(snapshot: RankingSnapshot) -> str:
    exact_division_match = None
    season_match = None
    for status in snapshot.student.selection_statuses.all():
        if status.season_year != snapshot.season_year:
            continue
        if status.division == snapshot.division:
            exact_division_match = status
            break
        if not status.division:
            season_match = status

    selected = exact_division_match or season_match
    if selected is None:
        return ""
    return selected.get_status_display()


def _assessment_columns_for_formula(formula: RankingFormula | None) -> list[dict]:
    if formula is None:
        return []

    items = list(
        formula.items.select_related("assessment")
        .order_by("sort_order", "id")
        .all(),
    )
    return [
        {
            "assessment_id": item.assessment_id,
            "field": f"assessment_{item.assessment_id}",
            "label": item.assessment.display_name,
            "code": item.assessment.code,
            "weight": item.weight,
        }
        for item in items
    ]


def _resolve_formula(filter_data: dict) -> RankingFormula | None:
    formula_id = filter_data.get("formula")
    if formula_id:
        return RankingFormula.objects.filter(pk=formula_id).first()

    queryset = RankingFormula.objects.filter(is_active=True)
    season = filter_data.get("season")
    division = (filter_data.get("division") or "").strip()
    if season:
        queryset = queryset.filter(season_year=season)
    if division:
        queryset = queryset.filter(division=division)

    return queryset.order_by("-season_year", "division", "-version", "id").first()


def _build_ranking_queryset(*, filter_data: dict, formula: RankingFormula | None):
    queryset = RankingSnapshot.objects.select_related(
        "student",
        "student__school",
        "ranking_formula",
    ).prefetch_related(
        Prefetch(
            "student__selection_statuses",
            queryset=StudentSelectionStatus.objects.order_by("-season_year", "division", "status", "id"),
        ),
    )

    if formula is not None:
        queryset = queryset.filter(ranking_formula=formula)

    season = filter_data.get("season")
    if season:
        queryset = queryset.filter(season_year=season)

    division = (filter_data.get("division") or "").strip()
    if division:
        queryset = queryset.filter(division=division)

    school = (filter_data.get("school") or "").strip()
    if school:
        queryset = queryset.filter(student__school__name__icontains=school)

    state = (filter_data.get("state") or "").strip()
    if state:
        queryset = queryset.filter(student__state__iexact=state)

    selection_status = (filter_data.get("selection_status") or "").strip()
    if selection_status:
        queryset = queryset.filter(student__selection_statuses__status=selection_status).distinct()

    active_flag = (filter_data.get("active") or "").strip()
    if active_flag in {"0", "1"}:
        queryset = queryset.filter(student__active=active_flag == "1")

    search_text = (filter_data.get("q") or "").strip()
    if search_text:
        queryset = queryset.filter(
            Q(student__full_name__icontains=search_text)
            | Q(student__school__name__icontains=search_text),
        )

    return queryset.order_by("rank_overall", "student__normalized_name", "student_id")


def _build_ranking_rows(
    *,
    snapshots: list[RankingSnapshot],
    assessment_columns: list[dict],
    request_user,
) -> list[dict]:
    can_view_nric = user_can_view_full_nric(request_user)
    rows: list[dict] = []
    for snapshot in snapshots:
        student = snapshot.student
        breakdown_values = _serialize_breakdown_values(snapshot)
        nric_value = student.full_nric if can_view_nric else mask_nric(student.masked_nric or student.full_nric)
        assessment_scores = {
            column["field"]: breakdown_values.get(column["assessment_id"], "")
            for column in assessment_columns
        }
        assessment_score_list = [assessment_scores[column["field"]] for column in assessment_columns]
        rows.append(
            {
                "snapshot": snapshot,
                "rank_overall": snapshot.rank_overall,
                "student_id": student.id,
                "student_name": student.full_name,
                "birth_year": student.birth_year,
                "age": _derived_age(student.birth_year),
                "school_name": student.school.name if student.school else "",
                "state": student.state,
                "selection_status": _pick_selection_status(snapshot),
                "total_score": snapshot.total_score,
                "nric": nric_value,
                "assessment_scores": assessment_scores,
                "assessment_score_list": assessment_score_list,
                "last_updated": snapshot.updated_at,
            },
        )
    return rows


def _ranking_filters_context() -> dict:
    return {
        "season_options": list(
            RankingSnapshot.objects.order_by("-season_year").values_list("season_year", flat=True).distinct(),
        ),
        "division_options": [
            division
            for division in RankingSnapshot.objects.order_by("division").values_list("division", flat=True).distinct()
            if division
        ],
        "school_options": list(
            School.objects.filter(is_active=True).order_by("name").values_list("name", flat=True),
        ),
        "state_options": [
            state
            for state in Student.objects.order_by("state").values_list("state", flat=True).distinct()
            if state
        ],
        "formula_options": list(
            RankingFormula.objects.order_by("-season_year", "division", "name", "-version")
            .values("id", "name", "season_year", "division", "version", "is_active"),
        ),
    }


def _render_ranking_export_rows(*, request, queryset, formula: RankingFormula | None):
    assessment_columns = _assessment_columns_for_formula(formula)
    snapshots = list(queryset)
    rows = _build_ranking_rows(
        snapshots=snapshots,
        assessment_columns=assessment_columns,
        request_user=request.user,
    )
    return assessment_columns, rows


@login_required
def ranking_table_view(request):
    filter_form = RankingTableFilterForm(request.GET or None)
    filter_data = filter_form.cleaned_data if filter_form.is_valid() else {}
    formula = _resolve_formula(filter_data)

    queryset = _build_ranking_queryset(filter_data=filter_data, formula=formula)
    snapshots = list(queryset[:RANKING_TABLE_MAX_ROWS])
    assessment_columns = _assessment_columns_for_formula(formula)
    ranking_rows = _build_ranking_rows(
        snapshots=snapshots,
        assessment_columns=assessment_columns,
        request_user=request.user,
    )

    context = {
        "filter_form": filter_form,
        "formula": formula,
        "assessment_columns": assessment_columns,
        "ranking_rows": ranking_rows,
        "ranking_row_limit": RANKING_TABLE_MAX_ROWS,
        **_ranking_filters_context(),
    }
    return render(request, "pages/rankings/ranking-table.html", context)


@login_required
def ranking_export_csv_view(request):
    filter_form = RankingTableFilterForm(request.GET or None)
    filter_data = filter_form.cleaned_data if filter_form.is_valid() else {}
    formula = _resolve_formula(filter_data)
    queryset = _build_ranking_queryset(filter_data=filter_data, formula=formula)
    assessment_columns, rows = _render_ranking_export_rows(request=request, queryset=queryset, formula=formula)

    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="ranking-export-{timestamp}.csv"'

    writer = csv.writer(response)
    headers = [
        "rank",
        "student_name",
        "birth_year",
        "age",
        "school",
        "state",
        "selection_status",
        "nric",
        "total_score",
        "last_updated",
    ] + [column["code"] for column in assessment_columns]
    writer.writerow(headers)

    for row in rows:
        writer.writerow(
            [
                row["rank_overall"] or "",
                row["student_name"],
                row["birth_year"] or "",
                row["age"] or "",
                row["school_name"],
                row["state"],
                row["selection_status"],
                row["nric"],
                row["total_score"],
                row["last_updated"].strftime("%Y-%m-%d %H:%M"),
                *[row["assessment_scores"].get(column["field"], "") for column in assessment_columns],
            ],
        )

    return response


@login_required
def ranking_export_xlsx_view(request):
    filter_form = RankingTableFilterForm(request.GET or None)
    filter_data = filter_form.cleaned_data if filter_form.is_valid() else {}
    formula = _resolve_formula(filter_data)
    queryset = _build_ranking_queryset(filter_data=filter_data, formula=formula)
    assessment_columns, rows = _render_ranking_export_rows(request=request, queryset=queryset, formula=formula)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Ranking"

    headers = [
        "Rank",
        "Student Name",
        "Birth Year",
        "Age",
        "School",
        "State",
        "Selection Status",
        "NRIC",
        "Total Score",
        "Last Updated",
        *[column["code"] for column in assessment_columns],
    ]
    worksheet.append(headers)

    for row in rows:
        worksheet.append(
            [
                row["rank_overall"] or "",
                row["student_name"],
                row["birth_year"] or "",
                row["age"] or "",
                row["school_name"],
                row["state"],
                row["selection_status"],
                row["nric"],
                float(row["total_score"]) if isinstance(row["total_score"], Decimal) else row["total_score"],
                row["last_updated"].strftime("%Y-%m-%d %H:%M"),
                *[row["assessment_scores"].get(column["field"], "") for column in assessment_columns],
            ],
        )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="ranking-export-{timestamp}.xlsx"'
    workbook.save(response)
    return response


@login_required
def ranking_dashboard_view(request):
    filter_form = RankingTableFilterForm(request.GET or None)
    filter_data = filter_form.cleaned_data if filter_form.is_valid() else {}
    formula = _resolve_formula(filter_data)
    queryset = _build_ranking_queryset(filter_data=filter_data, formula=formula)

    snapshots = list(queryset[:200])
    top_rows = snapshots[:15]

    selected_count = 0
    watchlist_count = 0
    for snapshot in snapshots:
        status = _pick_selection_status(snapshot).lower()
        if status == StudentSelectionStatus.Status.TEAM:
            selected_count += 1
        elif status == StudentSelectionStatus.Status.WATCHLIST:
            watchlist_count += 1

    school_stats = list(
        queryset.values("student__school__name")
        .annotate(
            student_count=Count("student", distinct=True),
            average_total=Avg("total_score"),
        )
        .order_by("-student_count", "student__school__name")[:10],
    )

    state_stats = list(
        queryset.values("student__state")
        .annotate(student_count=Count("student", distinct=True))
        .order_by("-student_count", "student__state")[:10],
    )

    context = {
        "filter_form": filter_form,
        "formula": formula,
        "top_rows": top_rows,
        "selected_count": selected_count,
        "watchlist_count": watchlist_count,
        "school_stats": school_stats,
        "state_stats": state_stats,
        **_ranking_filters_context(),
    }
    return render(request, "pages/rankings/ranking-dashboard.html", context)


@login_required
def students_list_view(request):
    queryset = Student.objects.select_related("school")

    school = (request.GET.get("school") or "").strip()
    if school:
        queryset = queryset.filter(school__name__icontains=school)

    state = (request.GET.get("state") or "").strip()
    if state:
        queryset = queryset.filter(state__iexact=state)

    birth_year = (request.GET.get("birth_year") or "").strip()
    if birth_year:
        queryset = queryset.filter(birth_year=birth_year)

    active = (request.GET.get("active") or "").strip()
    if active in {"0", "1"}:
        queryset = queryset.filter(active=active == "1")

    search_text = (request.GET.get("q") or "").strip()
    if search_text:
        queryset = queryset.filter(
            Q(full_name__icontains=search_text)
            | Q(external_code__icontains=search_text)
            | Q(school__name__icontains=search_text),
        )

    students = list(queryset.order_by("full_name", "id")[:500])
    context = {
        "students": students,
        "state_options": [
            state_value
            for state_value in Student.objects.order_by("state").values_list("state", flat=True).distinct()
            if state_value
        ],
        "school_options": list(
            School.objects.filter(is_active=True).order_by("name").values_list("name", flat=True),
        ),
    }
    return render(request, "pages/rankings/students-list.html", context)


@login_required
def student_detail_view(request, student_id: int):
    student = get_object_or_404(
        Student.objects.select_related("school"),
        pk=student_id,
    )
    results = list(
        student.results.select_related("assessment")
        .order_by(
            "-assessment__season_year",
            "-assessment__assessment_date",
            "assessment__sort_order",
            "assessment__id",
        ),
    )
    selection_statuses = list(
        student.selection_statuses.select_related("created_by")
        .order_by("-season_year", "division", "status", "id"),
    )
    ranking_history = list(
        student.ranking_snapshots.select_related("ranking_formula")
        .order_by("season_year", "division", "rank_overall", "id"),
    )

    trend_points = [
        {
            "label": f"{snapshot.season_year} {snapshot.division or 'overall'}",
            "score": float(snapshot.total_score),
        }
        for snapshot in ranking_history
    ]

    import_summary = list(
        student.results.exclude(source_file_name="")
        .values("source_file_name")
        .annotate(last_imported_at=Max("imported_at"), row_count=Count("id"))
        .order_by("-last_imported_at", "source_file_name")[:10],
    )

    context = {
        "student": student,
        "results": results,
        "selection_statuses": selection_statuses,
        "ranking_history": ranking_history,
        "trend_points": trend_points,
        "import_summary": import_summary,
    }
    return render(request, "pages/rankings/student-detail.html", context)


@login_required
def assessments_list_view(request):
    queryset = Assessment.objects.order_by("-season_year", "sort_order", "code")

    season = (request.GET.get("season") or "").strip()
    if season:
        queryset = queryset.filter(season_year=season)

    division = (request.GET.get("division") or "").strip()
    if division:
        queryset = queryset.filter(division_scope__iexact=division)

    active = (request.GET.get("active") or "").strip()
    if active in {"0", "1"}:
        queryset = queryset.filter(is_active=active == "1")

    search_text = (request.GET.get("q") or "").strip()
    if search_text:
        queryset = queryset.filter(
            Q(code__icontains=search_text)
            | Q(display_name__icontains=search_text)
            | Q(division_scope__icontains=search_text),
        )

    context = {
        "assessments": list(queryset[:500]),
        "season_options": list(
            Assessment.objects.order_by("-season_year").values_list("season_year", flat=True).distinct(),
        ),
    }
    return render(request, "pages/rankings/assessments-list.html", context)


@login_required
def formulas_list_view(request):
    formulas = list(
        RankingFormula.objects.prefetch_related("items__assessment")
        .order_by("-season_year", "division", "name", "-version", "id"),
    )
    context = {
        "formulas": formulas,
    }
    return render(request, "pages/rankings/formulas-list.html", context)


def _base_import_center_context() -> dict:
    return {
        "student_master_form": StudentMasterImportForm(),
        "assessment_result_form": AssessmentResultImportForm(),
        "legacy_wide_form": LegacyWideImportForm(),
        "import_batches": list(
            ImportBatch.objects.select_related("created_by")
            .prefetch_related("row_issues")
            .order_by("-created_at", "-id")[:IMPORT_BATCH_HISTORY_LIMIT],
        ),
    }


def _create_import_batch(*, request, import_type: str, upload) -> ImportBatch:
    return ImportBatch.objects.create(
        import_type=import_type,
        uploaded_file=upload,
        original_filename=getattr(upload, "name", "upload"),
        status=ImportBatch.Status.UPLOADED,
        created_by=request.user,
    )


def _log_import_preview_event(*, request, batch: ImportBatch) -> None:
    record_event(
        event_type=AuditEvent.EventType.IMPORT_PREVIEWED,
        message=f"Previewed ranking import batch {batch.id}",
        request=request,
        metadata={"batch_id": batch.id, "import_type": batch.import_type},
    )


def _log_import_complete_event(*, request, batch: ImportBatch) -> None:
    record_event(
        event_type=AuditEvent.EventType.IMPORT_COMPLETED,
        message=f"Applied ranking import batch {batch.id}",
        request=request,
        metadata={"batch_id": batch.id, "import_type": batch.import_type},
    )


@login_required
def import_center_view(request):  # noqa: C901, PLR0911, PLR0915
    _require_rankings_admin_access(request)
    context = _base_import_center_context()

    if request.method == "GET":
        return render(request, "pages/rankings/import-center.html", context)

    action = (request.POST.get("action") or "").strip()

    if action == "student_master_preview":
        form = StudentMasterImportForm(request.POST, request.FILES)
        context["student_master_form"] = form
        if not form.is_valid():
            return render(request, "pages/rankings/import-center.html", context)

        upload = form.cleaned_data["file"]
        batch = _create_import_batch(
            request=request,
            import_type=ImportBatch.ImportType.STUDENT_MASTER,
            upload=upload,
        )
        preview = preview_student_master_import(import_batch=batch, actor=request.user)
        _log_import_preview_event(request=request, batch=batch)

        context.update(
            {
                "student_master_form": StudentMasterImportForm(),
                "student_master_batch": batch,
                "student_master_preview": preview,
            },
        )
        return render(request, "pages/rankings/import-center.html", context)

    if action == "student_master_apply":
        batch = get_object_or_404(
            ImportBatch,
            pk=request.POST.get("batch_id"),
            import_type=ImportBatch.ImportType.STUDENT_MASTER,
        )
        preview = preview_student_master_import(import_batch=batch, actor=request.user)
        result = apply_student_master_import(preview=preview, import_batch=batch, actor=request.user)
        _log_import_complete_event(request=request, batch=batch)
        messages.success(
            request,
            "Student master import applied: "
            f"{result.created} created, {result.updated} updated.",
        )
        return redirect("rankings:import_center")

    if action == "assessment_result_preview":
        form = AssessmentResultImportForm(request.POST, request.FILES)
        context["assessment_result_form"] = form
        if not form.is_valid():
            return render(request, "pages/rankings/import-center.html", context)

        upload = form.cleaned_data["file"]
        batch = _create_import_batch(
            request=request,
            import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS,
            upload=upload,
        )

        mapping = {
            "student_identifier": form.cleaned_data["student_identifier_column"],
            "raw_score": form.cleaned_data.get("raw_score_column") or "",
            "medal": form.cleaned_data.get("medal_column") or "",
            "band": form.cleaned_data.get("band_column") or "",
            "status_text": form.cleaned_data.get("status_text_column") or "",
            "remarks": form.cleaned_data.get("remarks_column") or "",
            "source_url": form.cleaned_data.get("source_url_column") or "",
        }
        assessment = form.cleaned_data.get("assessment")
        if assessment is None:
            assessment, _created = Assessment.objects.get_or_create(
                code=form.cleaned_data["assessment_code"],
                season_year=form.cleaned_data["season_year"],
                defaults={
                    "display_name": form.cleaned_data["assessment_display_name"],
                    "category": form.cleaned_data.get("category") or Assessment.Category.CONTEST,
                    "division_scope": form.cleaned_data.get("division_scope") or "",
                    "result_type": Assessment.ResultType.MIXED,
                },
            )

        dataframe = assessment_result_dataframe_from_source(upload)
        preview = preview_assessment_result_import(
            dataframe,
            batch=batch,
            assessment=assessment,
            column_map=mapping,
            source_file_name=getattr(upload, "name", None),
        )
        _log_import_preview_event(request=request, batch=batch)

        context.update(
            {
                "assessment_result_form": AssessmentResultImportForm(initial=form.cleaned_data),
                "assessment_result_batch": batch,
                "assessment_result_preview": preview,
                "assessment_result_assessment": assessment,
                "assessment_result_mapping": mapping,
            },
        )
        return render(request, "pages/rankings/import-center.html", context)

    if action == "assessment_result_apply":
        batch = get_object_or_404(
            ImportBatch,
            pk=request.POST.get("batch_id"),
            import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS,
        )
        assessment = get_object_or_404(Assessment, pk=request.POST.get("assessment_id"))
        mapping = {
            "student_identifier": (request.POST.get("student_identifier") or "").strip(),
            "raw_score": (request.POST.get("raw_score") or "").strip(),
            "medal": (request.POST.get("medal") or "").strip(),
            "band": (request.POST.get("band") or "").strip(),
            "status_text": (request.POST.get("status_text") or "").strip(),
            "remarks": (request.POST.get("remarks") or "").strip(),
            "source_url": (request.POST.get("source_url") or "").strip(),
        }
        dataframe = assessment_result_dataframe_from_source(batch.uploaded_file.path)
        result = apply_assessment_result_import(
            dataframe,
            batch=batch,
            assessment=assessment,
            imported_by=request.user,
            column_map=mapping,
            source_file_name=batch.original_filename,
        )
        _log_import_complete_event(request=request, batch=batch)
        messages.success(
            request,
            f"Assessment result import applied: {result.upserted_count} row(s) upserted.",
        )
        return redirect("rankings:import_center")

    if action == "legacy_wide_preview":
        form = LegacyWideImportForm(request.POST, request.FILES)
        context["legacy_wide_form"] = form
        if not form.is_valid():
            return render(request, "pages/rankings/import-center.html", context)

        upload = form.cleaned_data["file"]
        batch = _create_import_batch(
            request=request,
            import_type=ImportBatch.ImportType.LEGACY_WIDE_TABLE,
            upload=upload,
        )
        dataframe = _read_tabular_upload(upload)
        preview = preview_legacy_wide_import(dataframe=dataframe, import_batch=batch)
        _log_import_preview_event(request=request, batch=batch)

        context.update(
            {
                "legacy_wide_form": LegacyWideImportForm(initial=form.cleaned_data),
                "legacy_wide_batch": batch,
                "legacy_wide_preview": preview,
                "legacy_wide_season_year": form.cleaned_data["season_year"],
                "legacy_wide_default_division": form.cleaned_data.get("default_division") or "",
            },
        )
        return render(request, "pages/rankings/import-center.html", context)

    if action == "legacy_wide_apply":
        batch = get_object_or_404(
            ImportBatch,
            pk=request.POST.get("batch_id"),
            import_type=ImportBatch.ImportType.LEGACY_WIDE_TABLE,
        )
        season_year = request.POST.get("season_year")
        if not season_year:
            msg = "Missing season year for legacy apply."
            raise Http404(msg)

        dataframe = _read_tabular_upload(batch.uploaded_file.path)
        preview = preview_legacy_wide_import(dataframe=dataframe, import_batch=batch)
        result = apply_legacy_wide_import(
            preview=preview,
            import_batch=batch,
            actor=request.user,
            season_year=int(season_year),
        )
        _log_import_complete_event(request=request, batch=batch)
        messages.success(
            request,
            "Legacy wide import applied: "
            f"{result.created_results} result(s), "
            f"{result.created_statuses} status row(s), "
            f"{result.created_assessments} assessment(s).",
        )
        return redirect("rankings:import_center")

    record_event(
        event_type=AuditEvent.EventType.IMPORT_FAILED,
        message=f"Failed ranking import action: {action or 'unknown'}",
        request=request,
        metadata={"action": action},
    )
    msg = "Unsupported import action."
    raise Http404(msg)
