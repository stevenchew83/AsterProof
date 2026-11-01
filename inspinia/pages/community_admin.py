from django.contrib import admin

from inspinia.users.roles import user_has_admin_role

from .community_models import StatementReviewPolicy


@admin.register(StatementReviewPolicy)
class StatementReviewPolicyAdmin(admin.ModelAdmin):
    readonly_fields = ("lease_until", "lease_job_id", "updated_at")
    list_display = ("enabled", "model", "daily_request_limit", "daily_budget_micros", "pricing_verified_at")

    def has_module_permission(self, request):
        return user_has_admin_role(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return user_has_admin_role(request.user) and super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return user_has_admin_role(request.user) and super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        return (
            user_has_admin_role(request.user)
            and not StatementReviewPolicy.objects.exists()
            and super().has_add_permission(request)
        )

    def has_delete_permission(self, request, obj=None):
        return False
