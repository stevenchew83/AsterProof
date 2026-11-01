"""Explicit operating policy; saved proofs and provider payloads stay out of admin lists."""

from django.contrib import admin

from inspinia.users.roles import user_has_admin_role

from .review_models import SolutionReviewPolicy


@admin.register(SolutionReviewPolicy)
class SolutionReviewPolicyAdmin(admin.ModelAdmin):
    readonly_fields = ("worker_seen_at", "lease_token", "lease_until", "updated_at")
    list_display = ("enabled", "model", "user_daily_limit", "global_daily_limit", "worker_seen_at")

    def has_module_permission(self, request):
        return user_has_admin_role(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return user_has_admin_role(request.user) and super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return user_has_admin_role(request.user) and super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        return (
            user_has_admin_role(request.user)
            and not SolutionReviewPolicy.objects.exists()
            and super().has_add_permission(request)
        )

    def has_delete_permission(self, request, obj=None):
        return False
