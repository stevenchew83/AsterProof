from django.contrib import admin

from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.problemsets.models import ProblemListVote


class ProblemListItemInline(admin.TabularInline):
    model = ProblemListItem
    extra = 0
    fields = ("position", "problem", "custom_title")
    autocomplete_fields = ("problem",)


@admin.register(ProblemList)
class ProblemListAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "visibility",
        "item_count",
        "upvote_count",
        "downvote_count",
        "updated_at",
    )
    list_filter = (
        "visibility",
        "hide_source",
        "hide_topic",
        "hide_mohs",
        "hide_subtopics",
        "created_at",
        "updated_at",
    )
    search_fields = ("title", "description", "author__email", "author__name")
    readonly_fields = ("list_uuid", "share_token", "created_at", "updated_at", "published_at")
    inlines = (ProblemListItemInline,)

    @admin.display(description="Items")
    def item_count(self, obj: ProblemList) -> int:
        return obj.items.count()

    @admin.display(description="Upvotes")
    def upvote_count(self, obj: ProblemList) -> int:
        return obj.votes.filter(value=ProblemListVote.Value.UP).count()

    @admin.display(description="Downvotes")
    def downvote_count(self, obj: ProblemList) -> int:
        return obj.votes.filter(value=ProblemListVote.Value.DOWN).count()


@admin.register(ProblemListItem)
class ProblemListItemAdmin(admin.ModelAdmin):
    list_display = ("problem_list", "position", "problem", "custom_title", "updated_at")
    list_filter = ("problem__contest", "problem__year")
    search_fields = (
        "custom_title",
        "problem_list__title",
        "problem__contest",
        "problem__problem",
        "problem__contest_year_problem",
    )
    autocomplete_fields = ("problem_list", "problem")


@admin.register(ProblemListVote)
class ProblemListVoteAdmin(admin.ModelAdmin):
    list_display = ("problem_list", "user", "value", "updated_at")
    list_filter = ("value", "updated_at")
    search_fields = ("problem_list__title", "user__email", "user__name")
    autocomplete_fields = ("problem_list", "user")
