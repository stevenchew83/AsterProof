"""Human-only package curation; no provider dispatch or review activation."""

from django import forms
from django.contrib import admin

from inspinia.solutions.problem_evaluation_models import EvaluationPackageApproval
from inspinia.solutions.problem_evaluation_models import ProblemEvaluationPackage
from inspinia.users.roles import user_has_admin_role


class AttributedEvaluationAdmin(admin.ModelAdmin):
    actions = None

    def has_module_permission(self, request):
        return request.user.is_active and user_has_admin_role(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return (
            request.user.is_active and user_has_admin_role(request.user) and super().has_view_permission(request, obj)
        )

    def has_add_permission(self, request):
        return request.user.is_active and user_has_admin_role(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)
        actor_field = self.actor_field

        class AttributedForm(form_class):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                if obj is None:
                    setattr(self.instance, actor_field, request.user)

        return AttributedForm


@admin.register(ProblemEvaluationPackage)
class ProblemEvaluationPackageAdmin(AttributedEvaluationAdmin):
    actor_field = "created_by"
    readonly_fields = ("content_digest", "created_by", "created_at", "approval_status")
    list_display = ("id", "problem", "version", "approval_status", "created_at")
    raw_id_fields = ("problem",)


class ApprovalForm(forms.ModelForm):
    confirm_human_review = forms.BooleanField(
        label="I personally reviewed this exact package and recorded my decision and reasons.",
        required=True,
    )

    class Meta:
        model = EvaluationPackageApproval
        fields = ("package", "decision", "notes")


@admin.register(EvaluationPackageApproval)
class EvaluationPackageApprovalAdmin(AttributedEvaluationAdmin):
    actor_field = "reviewer"
    form = ApprovalForm
    readonly_fields = ("package_digest", "reviewer", "created_at")
    list_display = ("id", "package", "decision", "reviewer", "created_at")
    raw_id_fields = ("package",)
