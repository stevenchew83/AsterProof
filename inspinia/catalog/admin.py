from django.contrib import admin
from django.db import transaction

from .models import Contest
from .models import Problem
from .models import ProblemReference
from .models import RelatedProblem
from .models import Tag


@admin.register(Contest)
class ContestAdmin(admin.ModelAdmin):
    list_display = ("name", "short_code", "contest_type", "year", "round", "country", "visibility_state")
    list_filter = ("contest_type", "year", "visibility_state")
    search_fields = ("name", "short_code", "country")
    actions = ("set_public", "set_internal", "set_draft")

    @admin.action(description="Set selected contests to public")
    def set_public(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="public")

    @admin.action(description="Set selected contests to internal")
    def set_internal(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="internal")

    @admin.action(description="Set selected contests to draft")
    def set_draft(self, request, queryset):  # noqa: ANN001
        queryset.update(visibility_state="draft")


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "contest",
        "topic",
        "label",
        "title",
        "statement_format",
        "confidence",
        "imo_slot_guess",
        "status",
        "editorial_difficulty",
        "editorial_quality",
        "canonical_problem",
    )
    list_filter = ("status", "statement_format", "topic", "confidence", "editorial_difficulty", "editorial_quality", "contest")
    search_fields = (
        "title",
        "label",
        "statement",
        "statement_plaintext",
        "topic_tags",
        "rationale",
        "pitfalls",
        "contest__name",
        "contest__short_code",
    )
    autocomplete_fields = ("contest", "canonical_problem")
    actions = (
        "mark_active",
        "mark_hidden",
        "mark_experimental",
        "set_canonical_first_selected",
    )

    @admin.action(description="Mark selected problems as active")
    def mark_active(self, request, queryset):  # noqa: ANN001
        queryset.update(status="active")

    @admin.action(description="Mark selected problems as hidden")
    def mark_hidden(self, request, queryset):  # noqa: ANN001
        queryset.update(status="hidden")

    @admin.action(description="Mark selected problems as experimental")
    def mark_experimental(self, request, queryset):  # noqa: ANN001
        queryset.update(status="experimental")

    @admin.action(description="Set first selected as canonical for others")
    def set_canonical_first_selected(self, request, queryset):  # noqa: ANN001
        rows = list(queryset.order_by("id"))
        if len(rows) < 2:
            self.message_user(request, "Select at least two problems.", level="warning")
            return
        canonical = rows[0]
        ids = [row.id for row in rows[1:]]
        Problem.objects.filter(id__in=ids).update(canonical_problem=canonical)
        self.message_user(request, f"Assigned canonical problem #{canonical.id} to {len(ids)} problems.")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "category")
    search_fields = ("name", "slug")
    list_filter = ("category",)
    actions = ("merge_into_first_selected",)

    @admin.action(description="Merge selected tags into first selected")
    def merge_into_first_selected(self, request, queryset):  # noqa: ANN001
        tags = list(queryset.order_by("id"))
        if len(tags) < 2:
            self.message_user(request, "Select at least two tags to merge.", level="warning")
            return
        target = tags[0]
        merged = 0
        with transaction.atomic():
            for tag in tags[1:]:
                for problem in tag.problems.all():
                    problem.tags.add(target)
                    merged += 1
                tag.delete()
        self.message_user(request, f"Merged {len(tags) - 1} tags into '{target.name}' ({merged} problem links moved).")


@admin.register(ProblemReference)
class ProblemReferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "problem", "title", "url")
    search_fields = ("title", "url", "problem__title")


@admin.register(RelatedProblem)
class RelatedProblemAdmin(admin.ModelAdmin):
    list_display = ("id", "source_problem", "target_problem", "relation_type")
    list_filter = ("relation_type",)
    autocomplete_fields = ("source_problem", "target_problem")
