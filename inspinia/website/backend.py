"""Newsletter workspace in the main application, restricted to app admins."""

from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.users.roles import user_has_admin_role

from . import automation
from . import bounces
from . import campaigns
from .forms import NewsletterAutomationForm
from .forms import NewsletterBounceApplyForm
from .forms import NewsletterBounceUploadForm
from .forms import NewsletterCampaignForm
from .forms import NewsletterHoldClearForm
from .forms import NewsletterScheduleForm
from .forms import NewsletterSendForm
from .models import NewsletterAutomation
from .models import NewsletterBounceReport
from .models import NewsletterCampaign
from .models import NewsletterDelivery
from .models import NewsletterLectureNotice
from .models import NewsletterSendingHold
from .models import NewsletterSubscriber
from .newsletter import unsubscribe


def newsletter_admin(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not user_has_admin_role(request.user):
            raise PermissionDenied
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        response["Referrer-Policy"] = "same-origin"
        return response
    return wrapped


def _page(request, template, *, tab="campaigns", **context):
    policy = NewsletterAutomation.objects.filter(pk=1).first()
    fresh = bool(
        policy and policy.worker_started_at and policy.worker_started_at > timezone.now() - timedelta(minutes=3),
    )
    return render(request, "website/backend/" + template + ".html", {
        "newsletter_tab": tab, "background_enabled": settings.NEWSLETTER_BACKGROUND_ENABLED,
        "worker_policy": policy, "worker_fresh": fresh, **context,
    })


def _paginate(request, rows, params):
    return {
        "page": Paginator(rows, 25).get_page(request.GET.get("page")),
        "pagination_query": urlencode({key: value for key, value in params.items() if value}),
    }


def _counts(campaign):
    counts = dict.fromkeys(NewsletterDelivery.Status.values, 0)
    counts.update(dict(campaign.deliveries.filter(kind=NewsletterDelivery.Kind.CAMPAIGN)
                       .values_list("status").annotate(total=Count("pk"))))
    counts["total"] = sum(counts.values())
    counts["processed"] = counts["total"] - counts["queued"] - counts["sending"]
    counts["percent"] = round(100 * counts["processed"] / counts["total"]) if counts["total"] else 0
    return counts


@newsletter_admin
@require_GET
def index(request):
    rows = NewsletterCampaign.objects.annotate(
        recipient_count=Count("deliveries", filter=Q(deliveries__kind=NewsletterDelivery.Kind.CAMPAIGN)),
        accepted_count=Count("deliveries", filter=Q(
            deliveries__kind=NewsletterDelivery.Kind.CAMPAIGN, deliveries__status=NewsletterDelivery.Status.ACCEPTED,
        )),
    ).order_by("-created_at", "-pk")
    return _page(
        request, "index", subscribed=campaigns.confirmed_subscribers().count(),
        pending=NewsletterSubscriber.objects.filter(status=NewsletterSubscriber.Status.PENDING).count(),
        draft_count=NewsletterCampaign.objects.filter(status=NewsletterCampaign.Status.DRAFT).count(),
        accepted=NewsletterDelivery.objects.filter(
            kind=NewsletterDelivery.Kind.CAMPAIGN, status=NewsletterDelivery.Status.ACCEPTED,
        ).count(),
        **_paginate(request, rows, {}),
    )


@newsletter_admin
@require_GET
def subscribers(request):
    query = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "")
    rows = NewsletterSubscriber.objects.annotate(is_suppressed=Exists(
        NewsletterSendingHold.objects.filter(email=Lower(OuterRef("email")), cleared_at__isnull=True),
    ))
    if query:
        rows = rows.filter(email__icontains=query)
    if status in NewsletterSubscriber.Status.values:
        rows = rows.filter(status=status)
    return _page(
        request, "subscribers", tab="subscribers", query=query, status=status,
        statuses=NewsletterSubscriber.Status.choices, **_paginate(request, rows, {"q": query, "status": status}),
    )


@newsletter_admin
@require_http_methods(["GET", "POST"])
def subscriber(request, pk):
    row = get_object_or_404(NewsletterSubscriber, pk=pk)
    if request.method == "POST":
        with transaction.atomic():
            row = NewsletterSubscriber.objects.select_for_update().get(pk=pk)
            if row.status != NewsletterSubscriber.Status.UNSUBSCRIBED:
                unsubscribe(row)
        messages.success(request, "This address is unsubscribed. A new signup requires email confirmation.")
        return redirect("website:newsletter_subscriber", pk=pk)
    return _page(
        request, "subscriber", tab="subscribers", subscriber=row,
        sending_holds=NewsletterSendingHold.objects.filter(email=row.email.casefold()).select_related("report"),
        hold_form=NewsletterHoldClearForm(),
        **_paginate(request, NewsletterDelivery.objects.filter(subscriber=row).select_related("campaign"), {}),
    )


def _campaign_context(campaign, form=None):
    return {
        "campaign": campaign,
        "form": form or NewsletterCampaignForm(instance=campaign),
        "counts": _counts(campaign),
        "test_ready": campaigns.has_current_test(campaign) if campaign.pk else False,
        "recent_deliveries": campaign.deliveries.select_related("campaign")[:25] if campaign.created_at else [],
        "inflight": campaign.deliveries.filter(status=NewsletterDelivery.Status.SENDING).exists(),
        "can_review_interrupted": campaign.deliveries.filter(
            status=NewsletterDelivery.Status.SENDING, attempted_at__lt=timezone.now() - timedelta(minutes=5),
        ).exists(),
    }


@transaction.non_atomic_requests
@newsletter_admin
@require_http_methods(["GET", "POST"])
def campaign_editor(request, pk=None):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk) if pk else NewsletterCampaign()
    form = NewsletterCampaignForm(request.POST or None, instance=campaign)
    if request.method == "POST":
        if not campaign.is_editable:
            raise PermissionDenied
        if form.is_valid():
            try:
                campaign = campaigns.save_draft(form, request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if request.POST.get("action") == "test":
                    try:
                        delivery = campaigns.send_test(request, campaign.pk, campaign.version)
                        if delivery.status == NewsletterDelivery.Status.ACCEPTED:
                            messages.success(
                                request, "Test email accepted for your signed-in email address. Check your inbox.",
                            )
                        else:
                            messages.warning(request, delivery.detail + " See delivery history before trying again.")
                    except ValidationError as error:
                        messages.warning(request, " ".join(error.messages))
                else:
                    messages.success(request, "Draft saved.")
                if request.POST.get("action") == "review":
                    return redirect("website:newsletter_send", pk=campaign.pk)
                return redirect(campaign)
    return _page(request, "campaign", **_campaign_context(campaign, form))


@newsletter_admin
@require_GET
@xframe_options_sameorigin
def campaign_preview(request, pk):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk)
    response = HttpResponse(campaigns.preview_html(campaign))
    response["Content-Security-Policy"] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; sandbox"
    )
    return response


def _json_requested(request):
    return "application/json" in request.headers.get("Accept", "")


def _runner_response(request, pk, error=None):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk)
    if _json_requested(request):
        return JsonResponse({
            "status": campaign.status, "counts": _counts(campaign), "error": error,
            "campaign_url": campaign.get_absolute_url(),
            "step_url": reverse("website:newsletter_send_next", kwargs={"pk": pk}),
            "pause_url": reverse("website:newsletter_pause", kwargs={"pk": pk}),
            "background": settings.NEWSLETTER_BACKGROUND_ENABLED,
            "status_url": reverse("website:newsletter_status", kwargs={"pk": pk}),
        }, status=400 if error else 200)
    if error:
        messages.warning(request, error)
    return redirect(campaign)


@transaction.non_atomic_requests
@newsletter_admin
@require_http_methods(["GET", "POST"])
def campaign_send(request, pk):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk)
    form = NewsletterSendForm(request.POST or None, initial={"version": campaign.version})
    if request.method == "POST" and form.is_valid():
        try:
            campaigns.start_campaign(pk, request.user, form.cleaned_data["version"])
            return _runner_response(request, pk)
        except ValidationError as error:
            if _json_requested(request):
                return _runner_response(request, pk, " ".join(error.messages))
            form.add_error(None, error)
    if request.method == "POST" and _json_requested(request):
        return _runner_response(request, pk, "Review this version and confirm before sending.")
    return _page(
        request, "send", campaign=campaign, form=form, test_ready=campaigns.has_current_test(campaign),
        recipient_count=campaigns.confirmed_subscribers().count(),
        schedule_form=NewsletterScheduleForm(initial={"version": campaign.version}),
    )


@newsletter_admin
@require_GET
def campaign_status(request, pk):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk)
    return JsonResponse({
        "status": campaign.status, "counts": _counts(campaign), "background": settings.NEWSLETTER_BACKGROUND_ENABLED,
        "campaign_url": campaign.get_absolute_url(),
        "status_url": reverse("website:newsletter_status", kwargs={"pk": pk}),
    })


@newsletter_admin
@require_POST
def campaign_schedule(request, pk):
    campaign = get_object_or_404(NewsletterCampaign, pk=pk)
    form = NewsletterScheduleForm(request.POST)
    if form.is_valid():
        try:
            campaigns.schedule_campaign(
                pk, request.user, form.cleaned_data["version"], form.cleaned_data["scheduled_at"],
            )
            messages.success(request, "Scheduled. The confirmed audience will be captured when sending starts.")
            return redirect(campaign)
        except ValidationError as error:
            form.add_error(None, error)
    return _page(
        request, "send", campaign=campaign,
        form=NewsletterSendForm(initial={"version": campaign.version}), schedule_form=form,
        test_ready=campaigns.has_current_test(campaign), recipient_count=campaigns.confirmed_subscribers().count(),
    )


@newsletter_admin
@require_POST
def campaign_cancel_schedule(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
    try:
        campaigns.cancel_schedule(pk)
        messages.success(request, "Schedule cancelled. Review and test the draft again before sending.")
    except ValidationError as error:
        messages.warning(request, " ".join(error.messages))
    return redirect("website:newsletter_campaign", pk=pk)


@newsletter_admin
@require_http_methods(["GET", "POST"])
def automation_settings(request):
    policy = NewsletterAutomation.objects.filter(pk=1).first() or NewsletterAutomation()
    form = NewsletterAutomationForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        try:
            automation.configure_lectures(
                enabled=form.cleaned_data["lecture_enabled"], template=form.cleaned_data["lecture_template"],
                digest_time=form.cleaned_data["digest_time"],
            )
            messages.success(request, "Lecture notification settings saved.")
            return redirect("website:newsletter_automation")
        except ValidationError as error:
            form.add_error(None, error)
    return _page(
        request, "automation", tab="automation", form=form, policy=policy,
        notices=NewsletterLectureNotice.objects.select_related("campaign")[:25],
    )


@newsletter_admin
@require_http_methods(["GET", "POST"])
def bounce_import(request):
    upload = NewsletterBounceUploadForm()
    review, apply_form = None, None
    if request.method == "POST":
        if request.POST.get("action") == "apply":
            apply_form = NewsletterBounceApplyForm(request.POST)
            if apply_form.is_valid():
                try:
                    report, created = bounces.apply_report(apply_form.cleaned_data["token"], request.user)
                    messages.success(
                        request, "Bounce report recorded." if created else "This report was already imported.",
                    )
                    return redirect("website:newsletter_bounces")
                except (ValidationError, NewsletterDelivery.DoesNotExist) as error:
                    detail = (
                        " ".join(error.messages) if isinstance(error, ValidationError)
                        else "The delivery is no longer available."
                    )
                    apply_form.add_error(None, detail)
        else:
            upload = NewsletterBounceUploadForm(request.POST, request.FILES)
            if upload.is_valid():
                try:
                    review = bounces.preview_report(upload.cleaned_data["report"].read(bounces.MAX_BYTES + 1))
                    apply_form = NewsletterBounceApplyForm(initial={"token": review["token"]})
                except ValidationError as error:
                    upload.add_error("report", error)
    return _page(
        request, "bounces", tab="bounces", upload_form=upload, review=review, apply_form=apply_form,
        **_paginate(request, NewsletterBounceReport.objects.select_related("delivery__campaign", "imported_by"), {}),
    )


@newsletter_admin
@require_POST
def clear_sending_hold(request, pk):
    get_object_or_404(NewsletterSendingHold, pk=pk)
    form = NewsletterHoldClearForm(request.POST)
    if form.is_valid():
        bounces.clear_hold(pk, request.user, form.cleaned_data["reason"])
        messages.success(request, "Sending hold cleared. Newsletter consent is still required.")
    else:
        messages.warning(request, "Confirm and record a reason before restoring sending.")
    return redirect("website:newsletter_bounces")


@transaction.non_atomic_requests
@newsletter_admin
@require_POST
def campaign_step(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
    if settings.NEWSLETTER_BACKGROUND_ENABLED:
        return _runner_response(request, pk, "The background worker handles sending. Refresh to see progress.")
    try:
        campaigns.send_next(request, pk)
    except ValidationError as error:
        return _runner_response(request, pk, " ".join(error.messages))
    return _runner_response(request, pk)


@transaction.non_atomic_requests
@newsletter_admin
@require_POST
def campaign_resume(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
    try:
        campaigns.set_paused(pk, paused=False)
    except ValidationError as error:
        return _runner_response(request, pk, " ".join(error.messages))
    return _runner_response(request, pk)


@transaction.non_atomic_requests
@newsletter_admin
@require_POST
def campaign_pause(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
    try:
        campaigns.set_paused(pk, paused=True)
    except ValidationError as error:
        return _runner_response(request, pk, " ".join(error.messages))
    return _runner_response(request, pk)


@newsletter_admin
@require_POST
def campaign_interrupted(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
    try:
        campaigns.mark_interrupted(pk)
        messages.info(request, "Interrupted delivery marked for review. Its recipient will not be retried.")
    except ValidationError as error:
        messages.warning(request, " ".join(error.messages))
    return redirect("website:newsletter_campaign", pk=pk)


@newsletter_admin
@require_POST
def campaign_duplicate(request, pk):
    source = get_object_or_404(NewsletterCampaign, pk=pk)
    campaign = NewsletterCampaign.objects.create(
        created_by=request.user, **{field: getattr(source, field) for field in campaigns.CONTENT_FIELDS},
    )
    messages.success(request, "Copied to a new draft. Send a test email before starting a new campaign.")
    return redirect(campaign)


@newsletter_admin
@require_GET
def history(request):
    query = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "")
    kind = request.GET.get("kind", "")
    result = request.GET.get("result", "")
    rows = NewsletterDelivery.objects.select_related("campaign")
    if query:
        rows = rows.filter(Q(recipient_email__icontains=query) | Q(subject__icontains=query))
    if status in NewsletterDelivery.Status.values:
        rows = rows.filter(status=status)
    if kind in NewsletterDelivery.Kind.values:
        rows = rows.filter(kind=kind)
    if result in NewsletterDelivery.Result.values:
        rows = rows.filter(delivery_result=result)
    return _page(
        request, "history", tab="history", query=query, status=status, kind=kind,
        statuses=NewsletterDelivery.Status.choices, kinds=NewsletterDelivery.Kind.choices,
        results=NewsletterDelivery.Result.choices, result=result,
        **_paginate(request, rows, {"q": query, "status": status, "kind": kind, "result": result}),
    )
