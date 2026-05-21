from django.contrib import admin

from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import PointLedger
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import SubmissionAttachment
from inspinia.training.models import SubmissionComment
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_published")
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "description")


@admin.register(Subtopic)
class SubtopicAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "order", "is_published")
    list_filter = ("topic", "is_published")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "description", "topic__title")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "subtopic", "completion_points", "order", "is_published")
    list_filter = ("is_published", "subtopic__topic")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "content_markdown", "subtopic__title")


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ("title", "subtopic", "difficulty", "max_points", "is_published")
    list_filter = ("difficulty", "is_published", "subtopic__topic")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "statement_markdown", "source", "expected_method")


@admin.register(MaterialCompletion)
class MaterialCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "material", "points_awarded", "completed_at")
    list_filter = ("completed_at",)
    search_fields = ("user__email", "material__title")


class SubmissionAttachmentInline(admin.TabularInline):
    model = SubmissionAttachment
    extra = 0


class SubmissionCommentInline(admin.TabularInline):
    model = SubmissionComment
    extra = 0


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    inlines = [SubmissionAttachmentInline, SubmissionCommentInline]
    list_display = ("user", "problem", "status", "awarded_points", "reviewed_by", "updated_at")
    list_filter = ("status", "problem__subtopic__topic")
    search_fields = ("user__email", "problem__title", "solution_markdown")


@admin.register(PointLedger)
class PointLedgerAdmin(admin.ModelAdmin):
    list_display = ("user", "source_type", "source_id", "points", "created_by", "created_at")
    list_filter = ("source_type",)
    search_fields = ("user__email", "reason", "source_id")


@admin.register(LevelThreshold)
class LevelThresholdAdmin(admin.ModelAdmin):
    list_display = ("level_number", "name", "minimum_points")
    ordering = ("level_number",)
