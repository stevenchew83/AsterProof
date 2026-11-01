from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import models

from inspinia.training.markdown import render_markdown

from .models import LibraryArea
from .models import LibraryConcept
from .models import LibraryLecture
from .models import NewsletterSubscriber


class EditorialAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_filter = ("is_published",)
    search_fields = ("title", "summary")
    readonly_fields = ("created_at", "updated_at", "formatted_preview")
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 16})}}
    view_on_site = True

    def _shared_authority(self, obj=None):
        from inspinia.learning.permissions import module_enabled
        from inspinia.website.learning import schema_ready

        if module_enabled():
            return True
        return bool(obj and schema_ready() and obj.__class__.objects.filter(
            pk=obj.pk, learning_link__is_cutover=True,
        ).exists())

    def has_add_permission(self, request):
        return not self._shared_authority() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not self._shared_authority(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._shared_authority(obj) and super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if self._shared_authority(obj):
            return (*[field.name for field in self.model._meta.fields],  # noqa: SLF001 - Django metadata.
                    *[field.name for field in self.model._meta.many_to_many], "formatted_preview")  # noqa: SLF001
        return super().get_readonly_fields(request, obj)

    def get_prepopulated_fields(self, request, obj=None):
        return {} if self._shared_authority(obj) else super().get_prepopulated_fields(request, obj)

    def _require_legacy_write(self, obj=None):
        if self._shared_authority(obj):
            message = "Mathematical Library changes use the shared contribution and Steven review workflow."
            raise PermissionDenied(message)

    def save_model(self, request, obj, form, change):
        self._require_legacy_write(obj)
        return super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        self._require_legacy_write(obj)
        return super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        self._require_legacy_write()
        from inspinia.website.learning import schema_ready

        if schema_ready() and queryset.filter(learning_link__is_cutover=True).exists():
            message = "Retained shared-content identities cannot be deleted through the legacy admin."
            raise PermissionDenied(message)
        return super().delete_queryset(request, queryset)

    @admin.display(description="Formatted preview")
    def formatted_preview(self, obj):
        return render_markdown(obj.body_markdown) if obj else "Save a draft to preview its Markdown."


@admin.register(LibraryArea)
class LibraryAreaAdmin(EditorialAdmin):
    list_display = ("title", "subject", "catalogue_area", "is_published", "order")
    list_filter = ("subject", "is_published")


@admin.register(LibraryConcept)
class LibraryConceptAdmin(EditorialAdmin):
    list_display = ("title", "area", "catalogue_concept", "is_published", "order")
    list_filter = ("area__subject", "area", "is_published")
    autocomplete_fields = ("area", "prerequisites")


@admin.register(LibraryLecture)
class LibraryLectureAdmin(EditorialAdmin):
    list_display = ("title", "concept", "estimated_minutes", "is_published", "order")
    list_filter = ("concept__area__subject", "is_published")
    autocomplete_fields = ("concept",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "status", "requested_at", "confirmed_at", "unsubscribed_at")
    list_filter = ("status",)
    search_fields = ("email",)
    readonly_fields = (
        "email",
        "status",
        "requested_at",
        "confirmed_at",
        "unsubscribed_at",
        "consent_version",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        # Subscription consent must come from the public confirmation flow.
        return False
