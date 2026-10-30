"""Read-only administration of shared snapshots and aggregate readership."""

from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.models import SolutionShareDailyViews
from inspinia.users.roles import user_has_admin_role

WINDOW_DAYS = 30
PAGE_SIZE = 25


def _filtered_shares(request):
    filters = {
        "q": request.GET.get("q", "").strip()[:200],
        "status": request.GET.get("status", ""),
        "topic": request.GET.get("topic", ""),
        "sort": request.GET.get("sort", "updated"),
    }
    if filters["status"] not in {"active", "stopped"}:
        filters["status"] = ""
    if filters["sort"] not in {"updated", "views"}:
        filters["sort"] = "updated"

    shares = SolutionPublicShare.objects.annotate(
        shared_title=Cast(KT("snapshot__title"), output_field=TextField()),
        shared_problem=Cast(KT("snapshot__problem__label"), output_field=TextField()),
        shared_topic=Cast(KT("snapshot__problem__topic"), output_field=TextField()),
        shared_mohs=Cast(KT("snapshot__problem__mohs"), output_field=TextField()),
    )
    topics = list(shares.filter(is_active=True).exclude(shared_topic__isnull=True).exclude(
        shared_topic="",
    ).order_by("shared_topic").values_list("shared_topic", flat=True).distinct())
    if filters["topic"] not in topics:
        filters["topic"] = ""
    if filters["status"]:
        shares = shares.filter(is_active=filters["status"] == "active")
    if filters["topic"]:
        shares = shares.filter(is_active=True, shared_topic=filters["topic"])
    if filters["q"]:
        query = filters["q"]
        shares = shares.filter(
            Q(shared_title__icontains=query, is_active=True)
            | Q(shared_problem__icontains=query, is_active=True)
            | Q(solution__author__name__icontains=query)
            | Q(solution__author__email__icontains=query),
        )
    return shares, filters, topics


@login_required
@never_cache
@require_GET
def admin_public_shares_view(request):
    if not user_has_admin_role(request.user):
        raise PermissionDenied

    today = timezone.localdate()
    first_day = today - timedelta(days=WINDOW_DAYS - 1)
    shares, filters, topics = _filtered_shares(request)

    metrics = shares.aggregate(
        active=Count("pk", filter=Q(is_active=True)),
        stopped=Count("pk", filter=Q(is_active=False)),
        authors=Count("solution__author_id", distinct=True, filter=Q(is_active=True)),
    )
    traffic = SolutionShareDailyViews.objects.filter(
        share_id__in=shares.values("pk"), day__range=(first_day, today),
    )
    metrics["views"] = traffic.aggregate(total=Sum("views"))["total"] or 0
    first_shares = dict(shares.filter(created_at__date__range=(first_day, today)).annotate(
        day=TruncDate("created_at"),
    ).values("day").annotate(total=Count("pk")).values_list("day", "total"))
    daily_views = dict(traffic.values("day").annotate(total=Sum("views")).values_list("day", "total"))
    trend = []
    for offset in range(WINDOW_DAYS):
        day = first_day + timedelta(days=offset)
        trend.append({"day": day, "shares": first_shares.get(day, 0), "views": daily_views.get(day, 0)})
    peak = max((row["views"] for row in trend), default=0) or 1
    for row in trend:
        row["width"] = round(row["views"] * 100 / peak, 1)
    topic_counts = list(shares.filter(is_active=True).values("shared_topic").annotate(
        total=Count("pk"),
    ).order_by("-total", "shared_topic"))

    per_share_views = traffic.filter(share_id=OuterRef("pk")).values("share_id").annotate(
        total=Sum("views"),
    ).values("total")
    rows = shares.annotate(views_30d=Coalesce(Subquery(per_share_views), 0, output_field=IntegerField())).values(
        "pk", "token", "is_active", "created_at", "updated_at", "source_updated_at",
        "shared_title", "shared_problem", "shared_topic", "shared_mohs", "views_30d",
        "solution__author__name", "solution__author__email",
    )
    ordering = ("-views_30d", "-updated_at", "-pk") if filters["sort"] == "views" else ("-updated_at", "-pk")
    page = Paginator(rows.order_by(*ordering), PAGE_SIZE).get_page(request.GET.get("page"))
    for row in page:
        row["author_name"] = row.pop("solution__author__name")
        row["author_email"] = row.pop("solution__author__email")
        # SQLite's JSON text extraction represents JSON null as the text "null".
        if row["shared_mohs"] == "null":
            row["shared_mohs"] = None
        if row["is_active"]:
            row["public_url"] = settings.PUBLIC_SITE_ORIGIN.rstrip("/") + reverse(
                "solutions:public_solution", args=[row["token"]],
            )

    response = render(request, "solutions/admin-public-shares.html", {
        "metrics": metrics, "filters": filters, "topics": topics, "topic_counts": topic_counts,
        "trend": trend, "page_obj": page, "first_day": first_day, "today": today,
        "first_share_count": sum(first_shares.values()),
        "report_timezone": timezone.get_current_timezone_name(),
        "pagination_query": urlencode({key: value for key, value in filters.items() if value}),
    })
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
