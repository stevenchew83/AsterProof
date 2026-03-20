from django.contrib import admin

from .models import ContestProblemStatement
from .models import ProblemSolveRecord
from .models import ProblemTopicTechnique
from .models import UserProblemCompletion


class ProblemTopicTechniqueInline(admin.TabularInline):
    model = ProblemTopicTechnique
    extra = 0


@admin.register(ProblemSolveRecord)
class ProblemSolveRecordAdmin(admin.ModelAdmin):
    list_display = (
        "problem_uuid",
        "year",
        "topic",
        "mohs",
        "contest",
        "problem",
        "imo_slot_guess_value",
        "rationale_value",
        "pitfalls_value",
    )
    search_fields = ("problem_uuid", "contest", "problem", "contest_year_problem")
    list_filter = ("year", "topic", "contest")
    inlines = (ProblemTopicTechniqueInline,)


@admin.register(ProblemTopicTechnique)
class ProblemTopicTechniqueAdmin(admin.ModelAdmin):
    list_display = ("record", "technique", "domains")
    search_fields = ("technique",)


@admin.register(UserProblemCompletion)
class UserProblemCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "problem", "completion_date", "updated_at")
    search_fields = (
        "user__email",
        "problem__contest",
        "problem__problem",
        "problem__contest_year_problem",
        "problem__problem_uuid",
    )
    list_filter = ("completion_date", "problem__contest", "problem__year")


@admin.register(ContestProblemStatement)
class ContestProblemStatementAdmin(admin.ModelAdmin):
    list_display = (
        "problem_uuid",
        "contest_year_problem",
        "day_label",
        "linked_problem",
        "updated_at",
    )
    search_fields = (
        "problem_uuid",
        "contest_name",
        "contest_year_problem",
        "problem_code",
        "statement_latex",
        "linked_problem__contest_year_problem",
    )
    list_filter = ("contest_year", "contest_name", "day_label")
