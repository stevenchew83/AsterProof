"""No generic-admin write surface bypasses the learning review services."""

from django.contrib import admin

from inspinia.learning import models
from inspinia.learning.permissions import is_publisher


class LearningInspectionAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return is_publisher(request.user)

    def has_view_permission(self, request, obj=None):
        return is_publisher(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]  # noqa: SLF001 - Django admin model metadata.


for model in (
    models.ContentDocument,
    models.ContentRevision,
    models.ContentPublication,
    models.ContributionProposal,
    models.ContentIssue,
    models.LegacyContentLink,
):
    admin.site.register(model, LearningInspectionAdmin)
