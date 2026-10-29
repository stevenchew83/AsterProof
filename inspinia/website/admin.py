from django import forms
from django.contrib import admin
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
