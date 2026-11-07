"""Private Study Help endpoints and the prompt/aggregate reporting workspace."""

# ruff: noqa: EM101

import json
from datetime import date
from datetime import timedelta
from functools import wraps
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help import KUALA_LUMPUR
from inspinia.pages.study_help import RequestSpec
from inspinia.pages.study_help import StudyHelpError
from inspinia.pages.study_help import check_read
from inspinia.pages.study_help import enqueue
from inspinia.pages.study_help import policy_for
from inspinia.pages.study_help import record_event
from inspinia.pages.study_help import reveal
from inspinia.pages.study_help import status
from inspinia.pages.study_help import telemetry_available
from inspinia.pages.study_help_access import lock_study_help
from inspinia.pages.study_help_models import SOLUTION_ACTIONS
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpAdminEvent
from inspinia.pages.study_help_models import StudyHelpEvent
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_provider import HINT_PROMPT
from inspinia.pages.study_help_provider import MAX_PROMPT_CHARS
from inspinia.pages.study_help_provider import SOLUTION_PROMPT
from inspinia.pages.study_help_provider import input_messages
from inspinia.pages.study_help_provider import profile_digest
from inspinia.users.roles import user_has_admin_role

MAX_BODY_BYTES = 2_048
PREVIEW_STATEMENT = r"Prove that the sum of the first \(n\) odd positive integers is \(n^2\)."


def _json_action(view):
    @wraps(view)
    def handle(request, statement_uuid):
        if not request.user.is_authenticated:
            return JsonResponse({"code": "sign_in", "message": "Sign in to use AI study help."}, status=401)
        try:
            return view(request, statement_uuid)
        except StudyHelpError as error:
            payload = {"code": error.code, "message": str(error)}
            if error.code in {"stale_action", "hints_exhausted", "solutions_exhausted", "statement_limit"}:
                payload["status"] = status(request.user, statement_uuid)
            return JsonResponse(payload, status=error.status)
        except (ValueError, TypeError, KeyError, RecursionError):
            problem = StudyHelpError("invalid_request")
            return JsonResponse({"code": problem.code, "message": str(problem)}, status=problem.status)

    return never_cache(handle)


def _body(request):
    if (
        request.content_type != "application/json"
        or int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY_BYTES
        or len(request.body) > MAX_BODY_BYTES
    ):
        raise StudyHelpError("invalid_request")
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise StudyHelpError("invalid_request")
    return value


def _allowed_click(request, statement_uuid):
    lock_study_help()
    policy_for(request.user)
    statement = ContestProblemStatement.objects.filter(statement_uuid=statement_uuid).first()
    if statement is None:
        raise StudyHelpError("unavailable")
    check_read(request.user, statement)


@require_GET
@_json_action
def study_help_status(request, statement_uuid):
    return JsonResponse(status(request.user, statement_uuid))


@require_POST
@_json_action
def study_help_request(request, statement_uuid):
    spec = RequestSpec.parse(_body(request))
    if spec.action in SOLUTION_ACTIONS:
        with transaction.atomic():
            _allowed_click(request, statement_uuid)
            if not telemetry_available(request.user):
                raise StudyHelpError("interaction_limit")
            record_event(
                request.user,
                statement_uuid,
                spec.interaction_key,
                spec.action,
                StudyHelpEvent.Kind.CONFIRMED,
            )
    job, created = enqueue(request.user, statement_uuid, spec)
    return JsonResponse(
        {"id": str(job.pk), "state": job.state, "status": status(request.user, statement_uuid)},
        status=202 if created else 200,
    )


@require_POST
@_json_action
def study_help_reveal(request, statement_uuid):
    data = _body(request)
    result = reveal(
        request.user,
        statement_uuid,
        UUID(data["response_id"]),
        UUID(data["interaction_key"]),
        automatic=data.get("automatic") is True,
    )
    return JsonResponse({"response": result, "status": status(request.user, statement_uuid)})


@require_POST
@_json_action
def study_help_click(request, statement_uuid):
    data = _body(request)
    interaction, action = UUID(data["interaction_key"]), StudyHelpAction(data["action"])
    with transaction.atomic():
        _allowed_click(request, statement_uuid)
        if not telemetry_available(request.user):
            raise StudyHelpError("interaction_limit")
        job = StudyHelpRequest.objects.filter(
            owner=request.user,
            statement_uuid=statement_uuid,
            interaction_key=interaction,
            action=action,
        ).first()
        record_event(request.user, statement_uuid, interaction, action, StudyHelpEvent.Kind.CLICK, job)
    return JsonResponse({"recorded": True})


def _date_range(request):
    today = timezone.now().astimezone(KUALA_LUMPUR).date()
    try:
        end = date.fromisoformat(request.GET.get("end", today.isoformat()))
        start = date.fromisoformat(request.GET.get("start", (end - timedelta(days=29)).isoformat()))
        if start <= end <= today and end - start < timedelta(days=366):
            return start, end
    except (ValueError, OverflowError):
        pass
    return today - timedelta(days=29), today


def _analytics(start, end):
    from datetime import datetime
    from datetime import time

    lo = datetime.combine(start, time.min, tzinfo=KUALA_LUMPUR)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=KUALA_LUMPUR)
    grouped = (
        StudyHelpEvent.objects.filter(created_at__gte=lo, created_at__lt=hi)
        .values("action", "kind")
        .annotate(
            count=Count("pk"),
        )
    )
    counts = {(row["action"], row["kind"]): row["count"] for row in grouped}
    return [
        (action.label, [counts.get((action, kind), 0) for kind in StudyHelpEvent.Kind]) for action in StudyHelpAction
    ]


@transaction.atomic
def _admin_submit(request):
    lock_study_help()
    if request.POST.get("operation") == "draft":
        hint, solution = (request.POST.get(name, "").strip() for name in ("hint", "solution"))
        if not all(0 < len(value) <= MAX_PROMPT_CHARS for value in (hint, solution)):
            messages.error(request, f"Enter both prompts, up to {MAX_PROMPT_CHARS} characters each.")
            return ""
        prompt = StudyHelpPrompt.objects.create(hint=hint, solution=solution, editor=request.user)
        StudyHelpAdminEvent.objects.create(actor=request.user, action="draft", prompt=prompt)
        messages.success(request, "Prompt draft saved.")
        return str(prompt.pk)
    if request.POST.get("operation") != "publish":
        raise PermissionDenied
    try:
        prompt = StudyHelpPrompt.objects.get(pk=UUID(request.POST["prompt"]))
    except (KeyError, ValueError, StudyHelpPrompt.DoesNotExist) as error:
        raise PermissionDenied from error
    policy = StudyHelpPolicy.objects.filter(pk=1).first()
    if (
        not policy
        or not StudyHelpQualification.objects.filter(
            prompt=prompt,
            profile_digest=profile_digest(prompt, policy.model),
        ).exists()
    ):
        messages.error(request, "This prompt must be qualified with the configured model before publication.")
        return str(prompt.pk)
    previous = policy.active_prompt_id
    policy.active_prompt = prompt
    policy.save(update_fields=["active_prompt"])
    StudyHelpAdminEvent.objects.create(
        actor=request.user,
        action="publish",
        prompt=prompt,
        reference=str(previous or ""),
    )
    messages.success(request, "Prompt version published.")
    return str(prompt.pk)


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def study_help_admin(request):
    if not user_has_admin_role(request.user):
        raise PermissionDenied
    if request.method == "POST":
        target = _admin_submit(request)
        url = redirect("pages:study_help_admin")
        if target:
            url["Location"] += "?prompt=" + target
        return url

    policy = StudyHelpPolicy.objects.filter(pk=1).first()
    versions = Paginator(StudyHelpPrompt.objects.select_related("editor").order_by("-created_at"), 15).get_page(
        request.GET.get("page"),
    )
    try:
        selected = StudyHelpPrompt.objects.filter(pk=UUID(request.GET.get("prompt", ""))).first()
    except ValueError:
        selected = None
    selected = selected or next(iter(versions), None)
    if selected:
        preview = [
            input_messages(action, PREVIEW_STATEMENT, selected)[0]["content"]
            for action in (StudyHelpAction.HINT, StudyHelpAction.SOLUTION)
        ]
    else:
        preview = []
    qualified = bool(
        selected
        and policy
        and StudyHelpQualification.objects.filter(
            prompt=selected,
            profile_digest=profile_digest(selected, policy.model),
        ).exists(),
    )
    start, end = _date_range(request)
    return render(
        request,
        "pages/study-help-admin.html",
        {
            "policy": policy,
            "versions": versions,
            "selected": selected,
            "preview": preview,
            "qualified": qualified,
            "hint_prompt": selected.hint if selected else HINT_PROMPT,
            "solution_prompt": selected.solution if selected else SOLUTION_PROMPT,
            "max_prompt_chars": MAX_PROMPT_CHARS,
            "preview_statement": PREVIEW_STATEMENT,
            "start": start,
            "end": end,
            "analytics": _analytics(start, end),
            "event_kinds": StudyHelpEvent.Kind.labels,
        },
    )
