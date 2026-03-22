from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg
from django.db.models import Count
from django.db.models import F
from django.db.models import Max
from django.db.models import Min
from django.db.models import Q
from django.db.models import QuerySet
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView
from django.views.generic import RedirectView
from django.views.generic import UpdateView

from inspinia.pages.forms import ProblemCompletionPasteForm
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.topic_labels import display_topic_label
from inspinia.users.forms import UserProfileForm
from inspinia.users.models import AuditEvent
from inspinia.users.models import User
from inspinia.users.models import UserSession
from inspinia.users.monitoring import record_event
from inspinia.users.monitoring import revoke_tracked_session
from inspinia.users.monitoring import sync_expired_sessions
from inspinia.users.roles import user_has_admin_role


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "id"
    slug_url_kwarg = "id"


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet | None=None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class PublicProfileView(LoginRequiredMixin, DetailView):
    model = User
    context_object_name = "profile_user"
    template_name = "users/profile_home.html"

    def get_object(self, queryset: QuerySet | None=None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        completion_qs = UserProblemCompletion.objects.filter(user=self.object).select_related("problem")
        today = timezone.localdate()
        last_30_days = today - timedelta(days=30)
        last_90_days = today - timedelta(days=90)
        completion_summary = completion_qs.aggregate(
            completed_total=Count("id"),
            dated_total=Count("id", filter=Q(completion_date__isnull=False)),
            unknown_date_total=Count("id", filter=Q(completion_date__isnull=True)),
            contest_total=Count("problem__contest", distinct=True),
            topic_total=Count("problem__topic", distinct=True),
            avg_mohs=Avg("problem__mohs"),
            max_mohs=Max("problem__mohs"),
            year_min=Min("problem__year"),
            year_max=Max("problem__year"),
            latest_completion_date=Max("completion_date"),
            recent_30d_total=Count("id", filter=Q(completion_date__gte=last_30_days)),
            recent_90d_total=Count("id", filter=Q(completion_date__gte=last_90_days)),
        )
        context["completion_import_form"] = kwargs.get(
            "completion_import_form",
            ProblemCompletionPasteForm(),
        )
        completion_import_stats = {
            "completed_total": completion_summary["completed_total"],
            "dated_total": completion_summary["dated_total"],
            "unknown_date_total": completion_summary["unknown_date_total"],
        }
        year_min = completion_summary["year_min"]
        year_max = completion_summary["year_max"]
        year_range_label = "No solved problems yet"
        if year_min is not None and year_max is not None:
            year_range_label = str(year_min) if year_min == year_max else f"{year_min}-{year_max}"
        context["completion_import_stats"] = completion_import_stats
        context["completion_analytics"] = {
            "completed_total": completion_summary["completed_total"],
            "dated_total": completion_summary["dated_total"],
            "unknown_date_total": completion_summary["unknown_date_total"],
            "contest_total": completion_summary["contest_total"],
            "topic_total": completion_summary["topic_total"],
            "avg_mohs": (
                round(float(completion_summary["avg_mohs"]), 1)
                if completion_summary["avg_mohs"] is not None
                else None
            ),
            "max_mohs": completion_summary["max_mohs"],
            "year_range_label": year_range_label,
            "latest_completion_date": completion_summary["latest_completion_date"],
            "recent_30d_total": completion_summary["recent_30d_total"],
            "recent_90d_total": completion_summary["recent_90d_total"],
        }

        top_contests = list(
            completion_qs.values("problem__contest")
            .annotate(total=Count("id"))
            .order_by("-total", "problem__contest")[:5],
        )
        top_topics = list(
            completion_qs.values("problem__topic")
            .annotate(total=Count("id"))
            .order_by("-total", "problem__topic")[:5],
        )
        for row in top_topics:
            row["problem__topic"] = display_topic_label(row["problem__topic"])
        by_mohs = list(
            completion_qs.values("problem__mohs")
            .annotate(total=Count("id"))
            .order_by("problem__mohs"),
        )
        year_breakdown = list(
            completion_qs.values("problem__year")
            .annotate(total=Count("id"))
            .order_by("-problem__year")[:6],
        )

        def _with_bar_width(
            rows: list[dict],
            label_key: str,
            *,
            label_prefix: str | None=None,
        ) -> list[dict]:
            if not rows:
                return []
            max_total = max(row["total"] for row in rows) or 1
            return [
                {
                    "label": (
                        f"{label_prefix} {row[label_key]}"
                        if label_prefix
                        else str(row[label_key])
                    ),
                    "total": row["total"],
                    "width_pct": max(16, round((row["total"] / max_total) * 100)),
                }
                for row in rows
            ]

        context["completion_dashboards"] = {
            "top_contests": _with_bar_width(top_contests, "problem__contest"),
            "top_topics": _with_bar_width(top_topics, "problem__topic"),
            "by_mohs": _with_bar_width(by_mohs, "problem__mohs", label_prefix="MOHS"),
            "year_breakdown": _with_bar_width(year_breakdown, "problem__year"),
        }
        recent_completion_items = []
        recent_completion_qs = completion_qs.order_by(
            F("completion_date").desc(nulls_last=True),
            "-updated_at",
            "problem__contest",
            "-problem__year",
            "problem__problem",
        )[:24]
        for completion in recent_completion_qs:
            problem = completion.problem
            recent_completion_items.append(
                {
                    "completion_date": completion.completion_date,
                    "completion_known": completion.completion_date is not None,
                    "display_label": (
                        problem.contest_year_problem
                        or f"{problem.contest} {problem.year} {problem.problem}"
                    ),
                    "problem": problem.problem,
                    "problem_uuid": str(problem.problem_uuid),
                    "topic": display_topic_label(problem.topic),
                    "updated_at": completion.updated_at,
                    "year": problem.year,
                },
            )
        context["recent_completion_items"] = recent_completion_items
        context["recent_completion_hidden_count"] = max(
            completion_import_stats["completed_total"] - len(recent_completion_items),
            0,
        )
        return context

    def post(self, request, *args, **kwargs):
        messages.info(request, "Completion import moved to My activity.")
        return redirect("pages:user_activity_dashboard")


public_profile_view = PublicProfileView.as_view()


class PublicProfileUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    success_message = _("Information successfully updated")
    template_name = "users/profile_edit.html"

    def get_success_url(self) -> str:
        return reverse("users:profile")

    def get_object(self, queryset: QuerySet | None=None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


public_profile_update_view = PublicProfileUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        return reverse("users:profile")


user_redirect_view = UserRedirectView.as_view()


def _require_app_admin(request) -> None:
    if not user_has_admin_role(request.user):
        raise PermissionDenied


def _pagination_suffix(params: dict[str, str]) -> str:
    query_string = urlencode({key: value for key, value in params.items() if value})
    return f"&{query_string}" if query_string else ""


def _url_with_query(url_name: str, params: dict[str, str]) -> str:
    query_string = urlencode({key: value for key, value in params.items() if value})
    base_url = reverse(url_name)
    return f"{base_url}?{query_string}" if query_string else base_url


@login_required
@require_http_methods(["GET", "POST"])
def manage_user_roles_view(request):
    """Assign application roles (admin / moderator / trainer / normal). Admins only."""
    _require_app_admin(request)

    allowed_roles = {choice[0] for choice in User.Role.choices}

    if request.method == "POST":
        raw_id = request.POST.get("user_id")
        new_role = request.POST.get("role")
        try:
            target = User.objects.get(pk=int(raw_id)) if raw_id else None
        except (User.DoesNotExist, ValueError, TypeError):
            target = None

        if target is None or new_role not in allowed_roles:
            messages.error(request, _("Invalid user or role."))
        else:
            previous_role = target.role
            target.role = new_role
            target.save(update_fields=["role"])
            messages.success(
                request,
                _("Updated role for %(email)s to %(role)s.")
                % {"email": target.email, "role": target.get_role_display()},
            )
            if previous_role != new_role:
                record_event(
                    event_type=AuditEvent.EventType.ROLE_CHANGED,
                    message=(
                        f"Changed role for {target.email} from "
                        f"{User.Role(previous_role).label} to {target.get_role_display()}."
                    ),
                    request=request,
                    actor=request.user,
                    target_user=target,
                    metadata={
                        "from_role": previous_role,
                        "to_role": new_role,
                    },
                )
        return redirect("users:manage_roles")

    users_qs = User.objects.order_by("email")
    return render(
        request,
        "users/manage_roles.html",
        {
            "users": users_qs,
            "role_choices": User.Role.choices,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def session_monitor_view(request):
    _require_app_admin(request)
    sync_expired_sessions()

    status_filter = request.GET.get("status", "active")
    if status_filter not in {"active", "ended", "all"}:
        status_filter = "active"
    search_query = request.GET.get("q", "").strip()

    if request.method == "POST":
        session_key = request.POST.get("session_key", "")
        redirect_url = _url_with_query(
            "users:session_monitor",
            {"status": status_filter, "q": search_query},
        )

        tracked_session = (
            UserSession.objects.select_related("user")
            .filter(session_key=session_key)
            .first()
        )
        current_session_key = request.session.session_key or ""
        if tracked_session is None:
            messages.error(request, _("Session not found."))
        elif tracked_session.session_key == current_session_key:
            messages.error(request, _("You cannot revoke the current session from this page."))
        elif tracked_session.ended_at is not None:
            messages.info(request, _("That session has already ended."))
        else:
            revoke_tracked_session(
                tracked_session=tracked_session,
                request=request,
                actor=request.user,
            )
            messages.success(
                request,
                _("Revoked the session for %(email)s.") % {"email": tracked_session.user.email},
            )
        return redirect(redirect_url)

    sessions_qs = UserSession.objects.select_related("user")
    if status_filter == "active":
        sessions_qs = sessions_qs.filter(ended_at__isnull=True)
    elif status_filter == "ended":
        sessions_qs = sessions_qs.filter(ended_at__isnull=False)

    if search_query:
        sessions_qs = sessions_qs.filter(
            Q(user__email__icontains=search_query)
            | Q(user__name__icontains=search_query)
            | Q(user_agent__icontains=search_query),
        )

    page_obj = Paginator(sessions_qs, 25).get_page(request.GET.get("page"))
    today = timezone.localdate()
    day_ago = timezone.now() - timedelta(days=1)

    context = {
        "active_session_count": UserSession.objects.filter(ended_at__isnull=True).count(),
        "active_user_count": User.objects.filter(
            tracked_sessions__ended_at__isnull=True,
        ).distinct().count(),
        "new_session_count_24h": UserSession.objects.filter(created_at__gte=day_ago).count(),
        "ended_session_count_today": UserSession.objects.filter(ended_at__date=today).count(),
        "current_session_key": request.session.session_key or "",
        "page_obj": page_obj,
        "pagination_suffix": _pagination_suffix({"status": status_filter, "q": search_query}),
        "search_query": search_query,
        "status_filter": status_filter,
    }
    return render(request, "users/session_monitor.html", context)


@login_required
def event_log_view(request):
    _require_app_admin(request)

    event_type_filter = request.GET.get("event_type", "")
    valid_event_types = {choice[0] for choice in AuditEvent.EventType.choices}
    if event_type_filter not in valid_event_types:
        event_type_filter = ""
    search_query = request.GET.get("q", "").strip()

    events_qs = AuditEvent.objects.select_related("actor", "target_user")
    if event_type_filter:
        events_qs = events_qs.filter(event_type=event_type_filter)
    if search_query:
        events_qs = events_qs.filter(
            Q(message__icontains=search_query)
            | Q(path__icontains=search_query)
            | Q(actor__email__icontains=search_query)
            | Q(target_user__email__icontains=search_query),
        )

    page_obj = Paginator(events_qs, 50).get_page(request.GET.get("page"))
    day_ago = timezone.now() - timedelta(days=1)
    admin_action_types = {
        AuditEvent.EventType.ROLE_CHANGED,
        AuditEvent.EventType.SESSION_REVOKED,
        AuditEvent.EventType.IMPORT_COMPLETED,
    }
    context = {
        "event_type_choices": AuditEvent.EventType.choices,
        "event_total_24h": AuditEvent.objects.filter(created_at__gte=day_ago).count(),
        "login_count_24h": AuditEvent.objects.filter(
            created_at__gte=day_ago,
            event_type=AuditEvent.EventType.LOGIN_SUCCEEDED,
        ).count(),
        "failed_login_count_24h": AuditEvent.objects.filter(
            created_at__gte=day_ago,
            event_type=AuditEvent.EventType.LOGIN_FAILED,
        ).count(),
        "admin_action_count_24h": AuditEvent.objects.filter(
            created_at__gte=day_ago,
            event_type__in=admin_action_types,
        ).count(),
        "event_type_filter": event_type_filter,
        "page_obj": page_obj,
        "pagination_suffix": _pagination_suffix(
            {"event_type": event_type_filter, "q": search_query},
        ),
        "search_query": search_query,
    }
    return render(request, "users/event_log.html", context)
