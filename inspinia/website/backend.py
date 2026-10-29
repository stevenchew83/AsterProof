"""Newsletter workspace in the main application, restricted to app admins."""

from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.db.models import Q
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

from . import campaigns
from .forms import NewsletterCampaignForm
from .forms import NewsletterSendForm
from .models import NewsletterCampaign
from .models import NewsletterDelivery
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
    return render(request, "website/backend/" + template + ".html", {"newsletter_tab": tab, **context})


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
    rows = NewsletterSubscriber.objects.all()
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
    )


@transaction.non_atomic_requests
@newsletter_admin
@require_POST
def campaign_step(request, pk):
    get_object_or_404(NewsletterCampaign, pk=pk)
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
    rows = NewsletterDelivery.objects.select_related("campaign")
    if query:
        rows = rows.filter(Q(recipient_email__icontains=query) | Q(subject__icontains=query))
    if status in NewsletterDelivery.Status.values:
        rows = rows.filter(status=status)
    if kind in NewsletterDelivery.Kind.values:
        rows = rows.filter(kind=kind)
    return _page(
        request, "history", tab="history", query=query, status=status, kind=kind,
        statuses=NewsletterDelivery.Status.choices, kinds=NewsletterDelivery.Kind.choices,
        **_paginate(request, rows, {"q": query, "status": status, "kind": kind}),
    )
