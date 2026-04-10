from django.contrib import admin
from django.contrib import messages
from django.db.models import Prefetch

from .models import Assessment
from .models import ImportBatch
from .models import ImportRowIssue
from .models import RankingFormula
from .models import RankingFormulaItem
from .models import RankingSnapshot
from .models import School
from .models import Student
from .models import StudentResult
from .models import StudentSelectionStatus
from .services.ranking_compute import compute_rank_rows
from .services.ranking_snapshot_store import store_ranking_snapshots


class RankingFormulaItemInline(admin.TabularInline):
    model = RankingFormulaItem
    extra = 0


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "state", "school_type", "is_active", "updated_at")
    search_fields = ("name", "short_name", "state")
    list_filter = ("school_type", "state", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "school", "birth_year", "external_code", "active", "updated_at")
    search_fields = ("full_name", "external_code", "legacy_code", "full_nric", "school__name")
    list_filter = ("active", "gender", "birth_year", "state", "school__state")
    autocomplete_fields = ("school",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "display_name",
        "season_year",
        "category",
        "division_scope",
        "result_type",
        "is_active",
    )
    search_fields = ("code", "display_name", "division_scope")
    list_filter = ("season_year", "category", "result_type", "division_scope", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RankingFormula)
class RankingFormulaAdmin(admin.ModelAdmin):
    list_display = ("name", "season_year", "division", "purpose", "version", "is_active", "updated_at")
    search_fields = ("name", "division", "notes")
    list_filter = ("season_year", "division", "purpose", "missing_score_policy", "is_active")
    readonly_fields = ("created_at", "updated_at")
    inlines = (RankingFormulaItemInline,)
    actions = ("recompute_selected_formulas",)

    @admin.action(description="Recompute ranking snapshots for selected formulas")
    def recompute_selected_formulas(self, request, queryset):
        snapshot_count = 0
        formula_count = 0

        for formula in queryset.order_by("season_year", "division", "id"):
            assessment_ids = list(
                formula.items.order_by("sort_order", "id").values_list("assessment_id", flat=True),
            )
            students = Student.objects.filter(active=True).prefetch_related(
                Prefetch(
                    "results",
                    queryset=StudentResult.objects.filter(assessment_id__in=assessment_ids).order_by(
                        "assessment_id",
                        "id",
                    ),
                ),
            )
            rows = compute_rank_rows(formula=formula, students=students)
            snapshot_count += store_ranking_snapshots(formula=formula, rows=rows)
            formula_count += 1

        self.message_user(
            request,
            f"Recomputed {formula_count} formula(s), stored {snapshot_count} snapshot(s).",
            level=messages.SUCCESS,
        )


@admin.register(StudentResult)
class StudentResultAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "assessment",
        "raw_score",
        "normalized_score",
        "medal",
        "band",
        "status_text",
        "imported_at",
    )
    search_fields = (
        "student__full_name",
        "assessment__display_name",
        "assessment__code",
        "status_text",
        "source_file_name",
        "imported_by__email",
    )
    list_filter = ("assessment__season_year", "assessment", "medal", "band", "imported_by")
    autocomplete_fields = ("student", "assessment", "imported_by")
    list_select_related = ("student", "assessment", "imported_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StudentSelectionStatus)
class StudentSelectionStatusAdmin(admin.ModelAdmin):
    list_display = ("student", "season_year", "division", "status", "created_by", "created_at")
    search_fields = ("student__full_name", "division", "status", "notes", "created_by__email")
    list_filter = ("season_year", "division", "status")
    autocomplete_fields = ("student", "created_by")
    list_select_related = ("student", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RankingSnapshot)
class RankingSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "ranking_formula",
        "season_year",
        "division",
        "total_score",
        "rank_overall",
        "rank_within_division",
        "last_computed_at",
    )
    search_fields = (
        "student__full_name",
        "ranking_formula__name",
        "division",
        "formula_version_label",
        "formula_version_hash",
    )
    list_filter = ("season_year", "division", "ranking_formula")
    autocomplete_fields = ("student", "ranking_formula")
    list_select_related = ("student", "ranking_formula")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "import_type", "original_filename", "status", "created_by", "created_at")
    search_fields = ("original_filename", "created_by__email", "uploaded_file")
    list_filter = ("import_type", "status", "created_at")
    autocomplete_fields = ("created_by",)
    list_select_related = ("created_by",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImportRowIssue)
class ImportRowIssueAdmin(admin.ModelAdmin):
    list_display = ("import_batch", "row_number", "severity", "issue_code", "created_at")
    search_fields = ("issue_code", "message", "import_batch__original_filename")
    list_filter = ("severity", "import_batch__import_type")
    autocomplete_fields = ("import_batch",)
    list_select_related = ("import_batch",)
    readonly_fields = ("created_at", "updated_at")
