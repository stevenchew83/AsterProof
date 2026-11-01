"""Public statement feedback and the private administrator review queue."""

import uuid
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import Q
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import StatementIssueReport
from inspinia.problemsets.models import ProblemList
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role

FORM_SALT = "pages.statement-report.v1"
FORM_MAX_AGE = 24 * 60 * 60
REPORTS_PER_HOUR = 10
REPORT_QUERY_MAX_LENGTH = 200
REPORT_PAGE_MAX_DIGITS = 6


class StatementReportForm(forms.Form):
    description = forms.CharField(
        label="What is incorrect?",
        max_length=2000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 5, "aria-describedby": "report-help"}),
    )
    token = forms.CharField(widget=forms.HiddenInput, max_length=1000)
    website = forms.CharField(required=False, widget=forms.HiddenInput, max_length=200)

    def clean_website(self):
        if self.cleaned_data["website"]:
            message = "The report could not be submitted."
            raise forms.ValidationError(message)
        return ""


def _report_context(request, statement):
    """Guests must still have access to the exact statement on a public list."""
    list_token = request.GET.get("list", "")
    if list_token:
        try:
            list_token = uuid.UUID(list_token)
        except ValueError as exc:
            raise Http404 from exc
        problem_list = get_object_or_404(
            ProblemList,
            share_token=list_token,
            visibility=ProblemList.Visibility.PUBLIC,
            items__problem_id=statement.linked_problem_id,
            items__problem__is_active=True,
        )
        latest_statement = ContestProblemStatement.objects.filter(
            linked_problem_id=statement.linked_problem_id,
            is_active=True,
        ).order_by("-updated_at", "-id").first()
        if latest_statement is None or latest_statement.pk != statement.pk:
            raise Http404
        item = problem_list.items.get(problem_id=statement.linked_problem_id)
        label = item.custom_title or (f"Problem {item.position}" if problem_list.hide_source else str(statement))
        return label, problem_list.public_url()
    if not user_can_access_app_features(request.user):
        raise Http404
    return str(statement), reverse("pages:problem_statement_detail", args=[statement.statement_uuid])


def _form_token(statement):
    return signing.dumps(
        {"statement": str(statement.statement_uuid), "submission": str(uuid.uuid4())},
        salt=FORM_SALT,
    )


def _submission_uuid(form, statement):
    try:
        payload = signing.loads(form.cleaned_data["token"], salt=FORM_SALT, max_age=FORM_MAX_AGE)
        if payload["statement"] == str(statement.statement_uuid):
            return uuid.UUID(payload["submission"])
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        pass
    form.add_error(None, "This form expired. Reload the page and submit your report again.")
    return None


def _consume_report_limit(request):
    # Do not trust forwarded client-IP headers. Store only an HMAC in the cache.
    identity = (
        f"user:{request.user.pk}" if request.user.is_authenticated else request.META.get("REMOTE_ADDR", "unknown")
    )
    key = "statement-report:" + salted_hmac(FORM_SALT, identity).hexdigest()
    try:
        cache.add(key, 0, timeout=3600)
        count = cache.incr(key)
        return isinstance(count, int) and count <= REPORTS_PER_HOUR
    except (ValueError, OSError):
        return False


@never_cache
@require_http_methods(["GET", "POST"])
def statement_report_create(request, statement_uuid):
    statement = get_object_or_404(ContestProblemStatement, statement_uuid=statement_uuid, is_active=True)
    label, back_url = _report_context(request, statement)
    form = StatementReportForm(
        request.POST if request.method == "POST" else None,
        initial={"token": _form_token(statement)},
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        submission_uuid = _submission_uuid(form, statement)
        if submission_uuid is not None:
            already_submitted = StatementIssueReport.objects.filter(submission_uuid=submission_uuid).exists()
            if already_submitted or _consume_report_limit(request):
                StatementIssueReport.objects.get_or_create(
                    submission_uuid=submission_uuid,
                    defaults={
                        "statement": statement,
                        "statement_uuid": statement.statement_uuid,
                        "problem_uuid": statement.problem_uuid,
                        "statement_label": str(statement),
                        "statement_snapshot": statement.statement_latex,
                        "description": form.cleaned_data["description"],
                        "reporter": request.user if request.user.is_authenticated else None,
                    },
                )
                query = {"sent": "1"}
                if request.GET.get("list"):
                    query["list"] = request.GET["list"]
                return redirect(request.path + "?" + urlencode(query))
            form.add_error(None, "Too many reports have been submitted. Please try again in an hour.")
            status = 429
    response = render(request, "pages/statement-report-form.html", {
        "form": form,
        "statement_label": label,
        "back_url": back_url,
        "report_sent": request.method == "GET" and request.GET.get("sent") == "1",
    }, status=status)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "same-origin"
    return response


def _require_report_admin(request):
    from inspinia.pages.views import _require_admin_tools_access

    _require_admin_tools_access(request)
    if not user_has_admin_role(request.user):
        raise PermissionDenied


@login_required
@never_cache
@require_http_methods(["GET"])
def statement_report_list(request):
    _require_report_admin(request)
    status = request.GET.get("status", StatementIssueReport.Status.OPEN)
    if status not in {"all", *StatementIssueReport.Status.values}:
        status = StatementIssueReport.Status.OPEN
    query = request.GET.get("q", "").strip()[:REPORT_QUERY_MAX_LENGTH]
    reports = StatementIssueReport.objects.select_related("statement", "reporter", "reviewed_by")
    if query:
        reports = reports.filter(Q(statement_label__icontains=query) | Q(description__icontains=query))
    counts = reports.aggregate(
        all=Count("pk"),
        **{value: Count("pk", filter=Q(status=value)) for value in StatementIssueReport.Status.values},
    )
    status_tabs = []
    for value, label in [*StatementIssueReport.Status.choices, ("all", "All reports")]:
        params = {"status": value, "q": query}
        status_tabs.append({
            "value": value, "label": label, "count": counts[value],
            "url": reverse("pages:statement_report_list") + "?" + urlencode(params),
        })
    if status != "all":
        reports = reports.filter(status=status)
    page = Paginator(reports, 25).get_page(request.GET.get("page"))
    return render(request, "pages/statement-report-list.html", {
        "reports": page,
        "selected_status": status,
        "status_tabs": status_tabs,
        "query": query,
        "pagination_query": urlencode({"status": status, "q": query}),
        "open_count": (
            StatementIssueReport.objects.filter(status=StatementIssueReport.Status.OPEN).count()
            if query else counts[StatementIssueReport.Status.OPEN]
        ),
    })


@login_required
@require_POST
def statement_report_update(request, report_id):
    _require_report_admin(request)
    status = request.POST.get("status")
    if status not in StatementIssueReport.Status.values:
        return HttpResponseBadRequest("Choose a valid review status.")
    report = get_object_or_404(StatementIssueReport, pk=report_id)
    report.status = status
    report.reviewed_by = request.user if status != StatementIssueReport.Status.OPEN else None
    report.reviewed_at = timezone.now() if status != StatementIssueReport.Status.OPEN else None
    report.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    messages.success(request, f"Report #{report.pk} marked {report.get_status_display().lower()}.")
    url = reverse("pages:statement_report_list")
    return_status = request.POST.get("return_status")
    if return_status in {"all", *StatementIssueReport.Status.values}:
        page = request.POST.get("return_page", "1")
        params = {
            "status": return_status,
            "q": request.POST.get("return_query", "").strip()[:REPORT_QUERY_MAX_LENGTH],
            "page": page if page.isdecimal() and len(page) <= REPORT_PAGE_MAX_DIGITS else "1",
        }
        url += "?" + urlencode(params)
    return redirect(url)
