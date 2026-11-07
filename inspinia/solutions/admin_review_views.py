"""Admin settings, explicit generation and publication, and private solver feedback."""

import uuid

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.users.roles import user_has_admin_role

from . import admin_reviews
from . import forum
from .admin_review_models import EFFORT_CHOICES
from .admin_review_models import MODEL_CHOICES
from .admin_review_models import AdminSolutionReview
from .admin_review_models import AdminSolutionReviewSettings

INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}
LIMITS = [(4000, "4,000"), (8000, "8,000"), (16000, "16,000"), (25000, "25,000"), (32000, "32,000")]


class ReviewSettingsForm(forms.Form):
    version = forms.UUIDField(required=False, widget=forms.HiddenInput)
    api_key = forms.RegexField(
        r"\Ask-[A-Za-z0-9_-]+\Z", required=False, min_length=12, max_length=512,
        label="OpenAI API key",
        error_messages={"invalid": "Enter a valid OpenAI API key."},
        widget=forms.PasswordInput(attrs={
            **INPUT, "autocomplete": "new-password", "spellcheck": "false", "placeholder": "sk-…",
            "aria-describedby": "review-key-hint",
        }),
    )
    clear_key = forms.BooleanField(
        label="Remove the saved key", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    models_enabled = forms.MultipleChoiceField(
        label="Available models", choices=MODEL_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
    )
    effort = forms.ChoiceField(
        label="Thinking level", choices=EFFORT_CHOICES, widget=forms.Select(attrs=SELECT),
    )
    output_limit = forms.TypedChoiceField(
        label="Output token limit", choices=LIMITS, coerce=int, widget=forms.Select(attrs=SELECT),
    )
    daily_limit = forms.IntegerField(
        label="24-hour request limit", min_value=1, max_value=50, widget=forms.NumberInput(attrs=INPUT),
    )
    prompt = forms.CharField(
        label="Review prompt", max_length=12_000,
        widget=forms.Textarea(attrs={**INPUT, "rows": 8, "aria-describedby": "review-prompt-hint"}),
    )

    @sensitive_variables("data")
    def clean(self):
        data = super().clean()
        if data.get("api_key") and data.get("clear_key"):
            self.add_error("api_key", "Choose whether to replace or remove the saved key.")
        elif data.get("api_key") and not admin_reviews.credential_cipher():
            self.add_error("api_key", "Set up server credential storage before saving a key.")
        return data


@sensitive_variables("data")
@transaction.atomic
def _save_settings(form):
    data = form.cleaned_data
    config, created = AdminSolutionReviewSettings.objects.select_for_update().get_or_create(pk=1)
    if data["version"] != (None if created else config.version):
        transaction.set_rollback(True)
        form.add_error(None, "These settings changed in another tab. Reload before saving.")
        return False
    if data["api_key"] or data["clear_key"]:
        config.encrypted_key = (
            admin_reviews.credential_cipher().encrypt(data["api_key"].encode("ascii")) if data["api_key"] else b""
        )
        config.key_version = uuid.uuid4()
    for name in ("models_enabled", "effort", "output_limit", "daily_limit", "prompt"):
        setattr(config, name, data[name])
    config.version = uuid.uuid4()
    config.save()
    return True


@login_required
@never_cache
@sensitive_post_parameters("api_key")
@require_http_methods(["GET", "POST"])
def settings_view(request):
    admin_reviews.require_admin(request.user)
    saved = admin_reviews.review_settings()
    config = saved or AdminSolutionReviewSettings(models_enabled=["gpt-6.1-sol"])
    form = ReviewSettingsForm(
        request.POST if request.method == "POST" else None,
        initial={
            "version": saved.version if saved else None,
            "models_enabled": config.models_enabled, "effort": config.effort, "output_limit": config.output_limit,
            "daily_limit": config.daily_limit, "prompt": config.prompt,
        },
    )
    if form.is_bound and form.is_valid() and _save_settings(form):
        messages.success(request, "AI review settings saved.")
        return redirect("solutions:admin_ai_review_settings")
    return render(request, "solutions/admin-ai-review-settings.html", {
        "form": form,
        "key_saved": bool(config.encrypted_key),
        "key_ready": bool(admin_reviews.read_credential(config)),
        "encryption_ready": bool(admin_reviews.credential_cipher()),
        "generation_enabled": settings.ADMIN_SOLUTION_REVIEW_ENABLED,
        "review_rules": admin_reviews.REVIEW_RULES,
    }, status=400 if form.is_bound else 200)


def _detail_redirect(solution_pk):
    return redirect(reverse("solutions:solution_detail", args=[solution_pk]) + "#ai-review")


@login_required
@never_cache
@require_POST
def generate_view(request, solution_pk):
    try:
        created = admin_reviews.enqueue(request.user, solution_pk, request.POST)
    except forum.ForumError as error:
        messages.error(request, str(error))
    else:
        if created:
            messages.success(request, "AI reviews queued. Refresh this page to check for drafts.")
    return _detail_redirect(solution_pk)


@login_required
@never_cache
@require_POST
def publish_view(request, solution_pk, review_id):
    try:
        published = admin_reviews.publish(request.user, solution_pk, review_id)
    except forum.ForumError as error:
        messages.error(request, str(error))
    else:
        if published:
            messages.success(request, "Review published to the solver. Their notification email is queued.")
    return _detail_redirect(solution_pk)


@login_required
@never_cache
@require_GET
def progress_view(request, solution_pk, batch_id):
    admin_reviews.require_admin(request.user)
    reviews = AdminSolutionReview.objects.filter(
        target__solution_id=solution_pk, solver_id=F("target__solution__author_id"), batch_id=batch_id,
    ).only("status", "feedback").order_by("pk")
    return JsonResponse({"reviews": [
        {
            "id": str(row.pk),
            "status": row.get_status_display(),
            "active": row.is_live,
            "feedback": row.feedback if row.status == AdminSolutionReview.Status.RUNNING else "",
        }
        for row in reviews
    ]})


def review_context(request, solution, target):
    admin = user_has_admin_role(request.user)
    if not admin and solution.author_id != request.user.pk:
        return None
    label = admin_reviews.problem_label(solution)
    key = target["key"]
    reviews = AdminSolutionReview.objects.filter(target__solution=solution, solver_id=solution.author_id)
    current = Q(target__key=key, problem_label=label)
    if not admin:
        reviews = reviews.filter(published_at__isnull=False)
    # Include the email's linked review even if it is outside the recent history.
    try:
        linked_review = uuid.UUID(request.GET.get("ai_review", ""))
    except ValueError:
        linked_review = None
    history = list(reviews.exclude(current).select_related("target")[:10])
    if linked_review and all(review.pk != linked_review for review in history):
        linked = reviews.exclude(current).filter(pk=linked_review).select_related("target").first()
        if linked:
            history.insert(0, linked)
    recent = list(reviews.filter(current).order_by(
        "-published_at" if not admin else "-created_at", "-pk",
    )[:20])
    published = reviews.filter(current, published_at__isnull=False).first()
    if published and all(review.pk != published.pk for review in recent):
        recent.insert(0, published)
    if not (admin or recent or history):
        return None
    active = next((row for row in recent if row.is_live), None)
    context = {
        "admin": admin, "label": label, "recent": recent, "history": history,
        "active": active,
        "published": bool(published),
    }
    if admin:
        context.update(_admin_controls(solution, target["payload"]))
        if active:
            context["progress_url"] = reverse(
                "solutions:admin_ai_review_progress", args=[solution.pk, active.batch_id],
            )
    return context


def _admin_controls(solution, payload):
    config = admin_reviews.review_settings()
    blocker = admin_reviews.input_blocker(solution, payload)
    if not blocker:
        if not settings.ADMIN_SOLUTION_REVIEW_ENABLED:
            blocker = "AI review generation is currently disabled."
        elif not admin_reviews.read_credential(config):
            blocker = "Add an OpenAI API key in settings to generate reviews."
        elif not config.models_enabled:
            blocker = "Choose at least one model in AI review settings."
    return {
        "blocker": blocker,
        "batch_id": uuid.uuid4(),
        "settings_version": config.version if config else "",
        "effort": config.get_effort_display() if config else "",
        "choices": [(model, name) for model, name in MODEL_CHOICES if config and model in config.models_enabled],
    }
