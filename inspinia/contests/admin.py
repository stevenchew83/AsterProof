from django.contrib import admin

from .models import ContestEvent
from .models import ContestProblem
from .models import ContestRegistration
from .models import RatingDelta
from .models import RatingSnapshot
from .models import ScoreEntry
from .models import Submission


@admin.register(ContestEvent)
class ContestEventAdmin(admin.ModelAdmin):
    list_display = ("title", "contest_kind", "visibility_state", "start_time", "end_time", "is_rated")
    list_filter = ("contest_kind", "visibility_state", "is_rated")
    search_fields = ("title", "slug")
    actions = ("set_public", "set_internal", "set_draft")

    @admin.action(description="Set selected events to public")
    def set_public(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="public")

    @admin.action(description="Set selected events to internal")
    def set_internal(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="internal")

    @admin.action(description="Set selected events to draft")
    def set_draft(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="draft")


@admin.register(ContestRegistration)
class ContestRegistrationAdmin(admin.ModelAdmin):
    list_display = ("user", "contest", "created_at")
    list_filter = ("contest",)
    search_fields = ("user__email", "contest__title")


@admin.register(ContestProblem)
class ContestProblemAdmin(admin.ModelAdmin):
    list_display = ("contest", "problem", "position", "max_score")
    list_filter = ("contest",)
    autocomplete_fields = ("contest", "problem")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "contest",
        "problem",
        "user",
        "score",
        "marking_status",
        "graded_by",
        "graded_at",
        "created_at",
    )
    list_filter = ("contest", "marking_status")
    search_fields = ("user__email", "problem__title", "content")
    autocomplete_fields = ("contest", "problem", "user", "graded_by")


@admin.register(ScoreEntry)
class ScoreEntryAdmin(admin.ModelAdmin):
    list_display = ("contest", "user", "score", "rank", "rating_delta")
    list_filter = ("contest",)
    search_fields = ("user__email", "contest__title")


@admin.register(RatingSnapshot)
class RatingSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "value", "created_at")
    search_fields = ("user__email",)


@admin.register(RatingDelta)
class RatingDeltaAdmin(admin.ModelAdmin):
    list_display = ("contest", "user", "previous_rating", "new_rating", "delta", "created_at")
    list_filter = ("contest",)
    search_fields = ("user__email", "contest__title")
