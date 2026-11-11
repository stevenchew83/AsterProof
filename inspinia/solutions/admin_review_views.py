"""Admin settings, review requests, and private solver feedback."""

import uuid
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import When
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

from inspinia.pages.study_help_views import study_help_prompt_context
from inspinia.pages.study_help_views import update_study_help_prompt
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
FEEDBACK_STYLES = {
    "brief-coaching": (
        "Brief coaching", "What earned credit, the main gap, and one next step.",
        "In a short paragraph, identify what earns credit and the most important gap, if any. "
        "Give one concrete next step.",
    ),
    "detailed-grading": (
        "Detailed grading", "A fuller explanation of the score and any deductions.",
        "Explain the score in detail using specific steps in the proof. Identify justified progress and explain each "
        "material deduction under the fixed rubric.",
    ),
    "proof-audit": (
        "Step-by-step proof audit", "A walkthrough that follows the order of the proof.",
        "Walk through the key steps in proof order. Distinguish valid deductions, missing justification, and false "
        "claims. Identify any relevant assumption, boundary case, or equality case the proof leaves unresolved.",
    ),
    "socratic-hints": (
        "Socratic hints", "Targeted questions that help the solver find the next step.",
        "Briefly explain the score. If there is a substantive gap, ask targeted questions that guide the solver "
        "toward repairing the first one. Leave the missing argument for the solver to discover.",
    ),
    "revision-checklist": (
        "Revision checklist", "A prioritized list of specific edits and checks.",
        "After a short score explanation, list actionable revisions in priority order. Name the step to revise "
        "and what the solver needs to establish. For a complete proof, offer an optional refinement only if useful.",
    ),
}
QUEUE_HISTORY_SIZE = 200


class QueueHistoryForm(forms.Form):
    date_from = forms.DateField(
        label="From", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={**INPUT, "type": "date"}),
    )
    date_to = forms.DateField(
        label="Through", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={**INPUT, "type": "date"}),
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", "Choose an end date on or after the start date.")
        return data


def _feedback_style_prefix(style):
    if not style:
        return ""
    guidance = FEEDBACK_STYLES[style][2]
    return f"Feedback presentation (use this style if the guidance below differs):\n{guidance}\n\n"


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
    feedback_style = forms.ChoiceField(
        label="Feedback style", required=False,
        choices=[("", "Use the review prompt")] + [(key, style[0]) for key, style in FEEDBACK_STYLES.items()],
        widget=forms.Select(attrs={**SELECT, "aria-describedby": "review-feedback-style-hint"}),
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
    for name in ("models_enabled", "effort", "output_limit"):
        setattr(config, name, data[name])
    config.prompt = _feedback_style_prefix(data["feedback_style"]) + data["prompt"]
    config.version = uuid.uuid4()
    config.save()
    return True


@login_required
@never_cache
@sensitive_post_parameters("api_key")
@require_http_methods(["GET", "POST"])
def settings_view(request):
    admin_reviews.require_admin(request.user)
    if request.method == "POST" and request.POST.get("operation") in {"hint_draft", "publish"}:
        target = update_study_help_prompt(request)
        url = reverse("solutions:admin_ai_review_settings")
        if target:
            url += f"?prompt={target}"
        return redirect(url + "#hint-settings")
    saved = admin_reviews.review_settings()
    config = saved or AdminSolutionReviewSettings(models_enabled=["gpt-6.1-sol"])
    # The worker reads the assembled prompt. Only separate a recognized preset from the editable text.
    prompt = config.prompt
    feedback_style = ""
    for style in FEEDBACK_STYLES:
        prefix = _feedback_style_prefix(style)
        if prompt.startswith(prefix):
            feedback_style = style
            prompt = prompt.removeprefix(prefix)
            break
    form = ReviewSettingsForm(
        request.POST if request.method == "POST" else None,
        initial={
            "version": saved.version if saved else None,
            "models_enabled": config.models_enabled, "effort": config.effort, "output_limit": config.output_limit,
            "feedback_style": feedback_style, "prompt": prompt,
        },
    )
    if form.is_bound and form.is_valid() and _save_settings(form):
        messages.success(request, "AI review settings saved.")
        return redirect("solutions:admin_ai_review_settings")
    key_ready = bool(admin_reviews.read_credential(config))
    return render(request, "solutions/admin-ai-review-settings.html", {
        **study_help_prompt_context(request),
        "form": form,
        "key_saved": bool(config.encrypted_key),
        "key_ready": key_ready,
        "library_suggestions_enabled": settings.PROBLEM_LIBRARY_AI_SUGGESTIONS_ENABLED,
        "library_suggestions_ready": bool(settings.OPENAI_API_KEY.strip()) or key_ready,
        "encryption_ready": bool(admin_reviews.credential_cipher()),
        "generation_enabled": settings.ADMIN_SOLUTION_REVIEW_ENABLED,
        "review_rules": admin_reviews.REVIEW_RULES,
        "feedback_styles": [(label, description) for label, description, _ in FEEDBACK_STYLES.values()],
    }, status=400 if form.is_bound else 200)


@login_required
@never_cache
@require_GET
def queue_view(request):
    admin_reviews.require_admin(request.user)
    status = AdminSolutionReview.Status
    rows = AdminSolutionReview.objects.select_related("target").only(
        "problem_label", "model", "status", "created_at", "score", "published_at",
        "taken_down_at", "notification", "target__solution_id",
    ).annotate(requested_by_solver=Q(self_request__isnull=False))
    active = Q(status__in=admin_reviews.LIVE_STATES)
    counts = rows.filter(active).aggregate(
        waiting=Count("pk", filter=Q(status=status.QUEUED)),
        reviewing=Count("pk", filter=Q(status=status.RUNNING)),
    )
    history = AdminSolutionReview.objects.exclude(active).order_by("-created_at", "-pk")
    history_form = QueueHistoryForm(request.GET)
    dates = {}
    if history_form.is_valid():
        if start := history_form.cleaned_data["date_from"]:
            history = history.filter(created_at__date__gte=start)
            dates["date_from"] = start.isoformat()
        if end := history_form.cleaned_data["date_to"]:
            history = history.filter(created_at__date__lte=end)
            dates["date_to"] = end.isoformat()
    page = Paginator(history, QUEUE_HISTORY_SIZE).get_page(request.GET.get("page"))
    # Read both groups together so a finishing request cannot appear twice.
    rows = rows.filter(active | Q(pk__in=Subquery(page.object_list.values("pk")))).annotate(
        can_publish=(
            Q(
                status=status.COMPLETED, published_at__isnull=True,
                solver_id=F("target__solution__author_id"),
                target__solution__status__in=admin_reviews.REVIEWABLE_STATES,
                target__solution_version=F("target__solution__edit_version"),
                target__solution_updated_at=F("target__solution__updated_at"),
            )
            & ~Exists(AdminSolutionReview.objects.filter(
                target_id=OuterRef("target_id"), problem_label=OuterRef("problem_label"), published_at__isnull=False,
            ))
        ),
    ).order_by(
        Case(When(status=status.RUNNING, then=0), When(status=status.QUEUED, then=1), default=2),
        Case(When(active, then=F("created_at"))), Case(When(active, then=F("pk"))), "-created_at", "-pk",
    )
    template = (
        "solutions/partials/admin-review-queue-table.html"
        if request.GET.get("fragment") == "1" else "solutions/admin-ai-review-queue.html"
    )
    return render(request, template, {
        "queue_rows": rows, "history_page": page, "history_form": history_form, "counts": counts,
        "history_query": urlencode(dates), "queue_query": urlencode({**dates, "page": page.number}),
        "generation_enabled": settings.ADMIN_SOLUTION_REVIEW_ENABLED,
    })


def _detail_redirect(solution_pk):
    return redirect(reverse("solutions:solution_detail", args=[solution_pk]) + "#ai-review")


def _queue_redirect(request):
    params = {key: request.GET[key] for key in ("date_from", "date_to", "page") if key in request.GET}
    return redirect(reverse("solutions:admin_ai_review_queue") + ("?" + urlencode(params) if params else ""))


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
            messages.success(request, "AI review queued. Follow its progress below.")
    return _detail_redirect(solution_pk)


@login_required
@never_cache
@require_POST
def publish_view(request, solution_pk, review_id):
    try:
        published = admin_reviews.publish(
            request.user, solution_pk, review_id, last_taken_down=request.POST.get("last_taken_down", ""),
        )
    except forum.ForumError as error:
        messages.error(request, str(error))
    else:
        if published:
            messages.success(request, "Review published to the solver.")
    if request.GET.get("from_queue") == "1":
        return _queue_redirect(request)
    return _detail_redirect(solution_pk)


@login_required
@never_cache
@require_POST
def take_down_view(request, solution_pk, review_id):
    try:
        removed = admin_reviews.take_down(request.user, solution_pk, review_id, request.POST.get("publication", ""))
    except forum.ForumError as error:
        messages.error(request, str(error))
    else:
        if removed:
            messages.success(request, "Review taken down. The solver's link no longer shows this review.")
    return _queue_redirect(request)


@login_required
@never_cache
@require_GET
def progress_view(request, solution_pk, batch_id):
    if not admin_reviews.approved_user(request.user):
        raise PermissionDenied
    reviews = AdminSolutionReview.objects.filter(
        target__solution_id=solution_pk, solver_id=F("target__solution__author_id"), batch_id=batch_id,
    ).order_by("pk")
    if user_has_admin_role(request.user):
        reviews = list(reviews.only("status", "feedback"))
    else:
        row = reviews.filter(solver=request.user, self_request__user=request.user).select_related(
            "target__solution__problem", "target__solution__current_revision",
        ).defer("response_text", "instructions", "target__snapshot").first()
        if row is None:
            raise PermissionDenied
        if row.is_live:
            solution = row.target.solution
            if (
                not settings.SELF_SOLUTION_REVIEW_ENABLED
                or solution.status not in admin_reviews.REVIEWABLE_STATES
                or row.problem_label != admin_reviews.problem_label(solution)
                or row.target.key != forum.current_target_data(solution)["key"]
                or admin_reviews.self_review_restricted(
                    request.user, solution.problem.problem_uuid, row.target.statement_id_value,
                )
            ):
                raise PermissionDenied
        reviews = [row]
    return JsonResponse({"reviews": [
        {
            "id": str(row.pk),
            "status": row.get_status_display(),
            "active": row.is_live,
            "feedback": row.feedback if row.status == AdminSolutionReview.Status.RUNNING else "",
        }
        for row in reviews
    ]})


def _linked_review_id(request):
    try:
        return uuid.UUID(request.GET.get("ai_review", ""))
    except ValueError:
        return None


def _review_history(reviews, current, linked_review):
    # Include the linked review even if it is outside the recent history.
    history = list(reviews.exclude(current).select_related("target")[:10])
    if linked_review and all(review.pk != linked_review for review in history):
        linked = reviews.exclude(current).filter(pk=linked_review).select_related("target").first()
        if linked:
            history.insert(0, linked)
    return history


def _owner_context(user, solution, payload, reviews, current):
    owner_request = reviews.filter(
        current, self_request__user=user, published_at__isnull=True,
    ).only("batch_id", "status", "problem_label", "feedback", "taken_down_at", "score", "error").first()
    reviews = reviews.filter(published_at__isnull=False)
    can_generate = settings.SELF_SOLUTION_REVIEW_ENABLED
    restricted = (
        (can_generate or reviews.filter(self_request__isnull=False).exists())
        and admin_reviews.self_review_restricted(user, solution.problem.problem_uuid, payload["statement"]["id"])
    )
    if owner_request and owner_request.is_live and (
        not can_generate or restricted or solution.status not in admin_reviews.REVIEWABLE_STATES
    ):
        owner_request = None
    context = {"owner_request": owner_request, "can_generate": can_generate}
    if owner_request and owner_request.error == admin_reviews.IMAGE_INPUT_ERROR:
        context["image_error"] = owner_request.error
    if restricted:
        reviews = reviews.filter(self_request__isnull=True)
    if context["can_generate"]:
        context.update(_review_controls(solution, payload, admin=False))
        allowance = admin_reviews.self_review_allowance(user, solution.problem.problem_uuid)
        context["allowance"] = allowance
        if restricted:
            context["blocker"] = "AI review is restricted for this problem."
        elif not context["blocker"]:
            context["blocker"] = admin_reviews.self_review_limit_blocker(allowance)
    return reviews, context


def review_context(request, solution, target):
    admin = user_has_admin_role(request.user)
    if not admin and (solution.author_id != request.user.pk or not admin_reviews.approved_user(request.user)):
        return None
    label = admin_reviews.problem_label(solution)
    reviews = AdminSolutionReview.objects.filter(target__solution=solution, solver_id=solution.author_id)
    current = Q(target__key=target["key"], problem_label=label)
    if admin:
        context = {"can_generate": True, **_review_controls(solution, target["payload"], admin=True)}
    else:
        reviews, context = _owner_context(request.user, solution, target["payload"], reviews, current)
    owner_request = context.get("owner_request")
    linked_review = _linked_review_id(request)
    history = _review_history(reviews, current, linked_review)
    recent = list(reviews.filter(current).order_by("-created_at" if admin else "-published_at", "-pk")[:20])
    if admin and linked_review and all(review.pk != linked_review for review in [*recent, *history]):
        linked = reviews.filter(current, pk=linked_review).first()
        if linked:
            recent.append(linked)
    published = reviews.filter(current, published_at__isnull=False).first()
    if published and all(review.pk != published.pk for review in recent):
        recent.insert(0, published)
    if not (recent or history or context["can_generate"] or owner_request):
        return None
    live = [row for row in recent if row.is_live]
    active = next((row for row in live if row.status == AdminSolutionReview.Status.RUNNING), None)
    active = active or (live[0] if live else None)
    if owner_request and owner_request.is_live:
        active = owner_request
    context.update({
        "admin": admin, "label": label, "recent": recent, "history": history,
        "active": active, "published": bool(published),
    })
    if active:
        context["progress_url"] = reverse(
            "solutions:admin_ai_review_progress", args=[solution.pk, active.batch_id],
        )
    return context


def _review_controls(solution, payload, *, admin):
    config = admin_reviews.review_settings()
    blocker = admin_reviews.input_blocker(solution, payload)
    if not blocker:
        if not settings.ADMIN_SOLUTION_REVIEW_ENABLED:
            blocker = "AI review generation is currently disabled."
        elif not admin_reviews.read_credential(config):
            blocker = (
                "Add an OpenAI API key in settings to generate reviews."
                if admin else "AI review is temporarily unavailable."
            )
        elif not config.models_enabled:
            blocker = "Choose at least one model in AI review settings." if admin else "No review model is available."
    return {
        "blocker": blocker,
        "batch_id": uuid.uuid4(),
        "settings_version": config.version if config else "",
        "effort": config.get_effort_display() if config else "",
        "choices": [(model, name) for model, name in MODEL_CHOICES if config and model in config.models_enabled],
    }
