from django.contrib import admin

from .models import ProblemSolveRecord, ProblemTopicTechnique


class ProblemTopicTechniqueInline(admin.TabularInline):
    model = ProblemTopicTechnique
    extra = 0


@admin.register(ProblemSolveRecord)
class ProblemSolveRecordAdmin(admin.ModelAdmin):
    list_display = (
        "year",
        "topic",
        "mohs",
        "contest",
        "problem",
        "solve_date",
        "imo_slot_guess_value",
        "rationale_value",
        "pitfalls_value",
    )
    search_fields = ("contest", "problem", "contest_year_problem")
    list_filter = ("year", "topic", "contest", "solve_date")
    inlines = (ProblemTopicTechniqueInline,)


@admin.register(ProblemTopicTechnique)
class ProblemTopicTechniqueAdmin(admin.ModelAdmin):
    list_display = ("record", "technique", "domains")
    search_fields = ("technique",)
