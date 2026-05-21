from django.contrib import admin

from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingMaterialProblem
from inspinia.training.models import TrainingMaterialSubtopic
from inspinia.training.models import TrainingSubtopic
from inspinia.training.models import TrainingTopic


class TrainingSubtopicInline(admin.TabularInline):
    model = TrainingSubtopic
    extra = 0
    fields = ("title", "sort_order", "is_seeded", "is_active")


class TrainingMaterialSubtopicInline(admin.TabularInline):
    model = TrainingMaterialSubtopic
    extra = 0
    autocomplete_fields = ("subtopic",)


class TrainingMaterialProblemInline(admin.TabularInline):
    model = TrainingMaterialProblem
    extra = 0
    fields = ("position", "problem", "note")
    autocomplete_fields = ("problem",)


@admin.register(TrainingTopic)
class TrainingTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "sort_order", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "code", "description")
    readonly_fields = ("topic_uuid", "slug", "created_at", "updated_at")
    inlines = (TrainingSubtopicInline,)


@admin.register(TrainingSubtopic)
class TrainingSubtopicAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "sort_order", "is_seeded", "is_active", "updated_at")
    list_filter = ("topic", "is_seeded", "is_active")
    search_fields = ("title", "normalized_title", "description", "topic__title")
    readonly_fields = ("subtopic_uuid", "slug", "normalized_title", "created_at", "updated_at")
    autocomplete_fields = ("topic",)


@admin.register(TrainingMaterial)
class TrainingMaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "estimated_minutes", "published_at", "updated_at")
    list_filter = ("status", "published_at", "updated_at")
    search_fields = ("title", "summary", "body_source")
    readonly_fields = ("material_uuid", "slug", "created_at", "updated_at", "published_at")
    autocomplete_fields = ("created_by", "updated_by")
    inlines = (TrainingMaterialSubtopicInline, TrainingMaterialProblemInline)


@admin.register(TrainingMaterialSubtopic)
class TrainingMaterialSubtopicAdmin(admin.ModelAdmin):
    list_display = ("material", "subtopic", "created_at")
    search_fields = ("material__title", "subtopic__title", "subtopic__topic__title")
    autocomplete_fields = ("material", "subtopic")


@admin.register(TrainingMaterialProblem)
class TrainingMaterialProblemAdmin(admin.ModelAdmin):
    list_display = ("material", "position", "problem", "note", "updated_at")
    list_filter = ("problem__contest", "problem__year")
    search_fields = ("material__title", "note", "problem__contest_year_problem", "problem__problem_uuid")
    autocomplete_fields = ("material", "problem")

