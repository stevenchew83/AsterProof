# ruff: noqa: EM101, TRY003 -- Validation errors are intentionally fixed, non-sensitive codes.
"""First-party, bounded learning activity; public/account/admin routes are excluded."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.utils import OperationalError
from django.db.utils import ProgrammingError
from django.http import HttpResponse
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from inspinia.pages.models import LearningPageAction
from inspinia.pages.models import LearningPageVisit
from inspinia.users.roles import user_can_access_app_features

TOKEN_SALT = "asterproof.learning-activity.v1"  # noqa: S105 -- Public signature namespace, not a secret.
TOKEN_MAX_AGE = 24 * 60 * 60
MAX_BODY_BYTES = 8192
MAX_VISIBLE_MS = 12 * 60 * 60 * 1000
MAX_CLICKS = 2000
MAX_SEQUENCE = 100000
MAX_TOKEN_LENGTH = 2048
MINUTE_SECONDS = 60
MAX_CLOCK_SKEW_MS = 2000
REQUESTS_PER_MINUTE = 120

LEARNING_PAGES = {
    "pages:archive_hub": "Archive",
    "pages:contest_papers": "Contest papers",
    "pages:user_activity_dashboard": "My activity",
    "pages:my_completion_progress_analytics": "My progress",
    "pages:completion_quick_update": "Record completions",
    "pages:completion_board": "Completion board",
    "pages:contest_advanced_dashboard": "Contest progress",
    "pages:contest_mohs_summary": "Contest MOHS",
    "pages:contest_dashboard_listing": "Contest problems",
    "pages:technique_benchmark_list": "Benchmark map",
    "pages:technique_dashboard": "Areas and concepts",
    "pages:technique_progress_topic_detail": "Topic progress",
    "pages:technique_progress_gaps": "Concept gaps",
    "pages:problem_statement_list": "Problem library",
    "pages:problem_statement_detail": "Problem statement",
    "pages:problem_statement_contest_year_master": "Contest-year problems",
    "pages:shared_progress": "Learner progress",
    "pages:shared_progress_section": "Learner progress section",
    "pages:shared_progress_comparison": "Compare progress",
    "pages:shared_progress_comparison_section": "Compare progress section",
    "pages:community_problem_list": "Community problems",
    "pages:community_problem_create": "Create community problem",
    "pages:community_problem_edit": "Edit community problem",
    "pages:community_problem_detail": "Community problem",
    "solutions:my_solution_list": "My solutions",
    "solutions:problem_solution_create": "New solution",
    "solutions:problem_solution_list": "Problem solutions",
    "solutions:problem_solution_edit": "Solution editor",
    "solutions:problem_solution_share": "Share solution",
    "solutions:collection_create": "New solution collection",
    "solutions:collection_edit": "Edit solution collection",
    "problemsets:my_lists": "My problem lists",
    "problemsets:discover": "Discover problem lists",
    "problemsets:create": "New problem list",
    "problemsets:detail": "Problem list",
    "problemsets:edit": "Problem list editor",
    "training:dashboard": "Training overview",
    "training:roadmap": "Training roadmap",
    "training:topic_detail": "Training topic",
    "training:subtopic_detail": "Training subtopic",
    "training:material_detail": "Training material",
    "training:problem_detail": "Training problem",
    "training:my_submissions": "My submissions",
    "training:submission_detail": "Submission details",
}

# Selectors and text matches are static vocabulary, never user-provided labels.
ACTION_RULES = [
    {
        "key": "import_completions",
        "label": "Import completions",
        "selector": "#activity-import-submit",
        "texts": ["import completions"],
    },
    {
        "key": "save_solution",
        "label": "Save solution",
        "selector": "#solution-save,[data-learning-action='save_solution']",
        "texts": ["save changes"],
    },
    {
        "key": "publish_solution",
        "label": "Publish solution",
        "selector": "button[name=action][value=publish]",
        "texts": ["publish solution"],
    },
    {
        "key": "save_draft",
        "label": "Save draft",
        "selector": "button[name=action][value=save_draft]",
        "texts": ["save as draft", "move to draft"],
    },
    {
        "key": "share_solution",
        "label": "Share solution",
        "selector": "[data-share-open],[data-share-fallback]",
        "texts": ["share solution", "share"],
    },
    {"key": "editor_preview", "label": "Preview solution", "selector": "[data-editor-view=preview]", "texts": []},
    {"key": "editor_write", "label": "Write mode", "selector": "[data-editor-view=write]", "texts": []},
    {"key": "editor_split", "label": "Split editor", "selector": "[data-editor-view=split]", "texts": []},
    {"key": "editor_feedback", "label": "View feedback", "selector": "[data-editor-view=feedback]", "texts": []},
    {
        "key": "add_problem",
        "label": "Add problem",
        "selector": "[data-add-problem],#problem-list-preview-add-button,[data-confirm-unlinked-add]",
        "texts": ["add problem", "add"],
    },
    {
        "key": "remove_problem",
        "label": "Remove problem",
        "selector": "[data-draft-action=remove]",
        "texts": ["remove"],
    },
    {"key": "move_up", "label": "Move problem up", "selector": "[data-draft-action=up]", "texts": ["move up"]},
    {"key": "move_down", "label": "Move problem down", "selector": "[data-draft-action=down]", "texts": ["move down"]},
    {
        "key": "edit_notes",
        "label": "Edit notes",
        "selector": "[data-draft-action=toggle-notes]",
        "texts": ["edit notes"],
    },
    {
        "key": "preview_problem",
        "label": "Preview problem",
        "selector": "[data-preview-problem]",
        "texts": ["preview problem"],
    },
    {
        "key": "save_list",
        "label": "Save problem list",
        "selector": "#problem-list-save-button",
        "texts": ["save list", "create list", "create problem list"],
    },
    {
        "key": "search",
        "label": "Search",
        "selector": "#problem-list-search-button",
        "texts": ["search", "find problems"],
    },
    {
        "key": "apply_filters",
        "label": "Apply filters",
        "selector": ".app-table-filters button[type=submit],[data-facet-field]",
        "texts": ["apply", "apply filters"],
    },
    {
        "key": "reset_filters",
        "label": "Reset filters",
        "selector": "[data-clear-filter]",
        "texts": ["reset", "reset filters", "clear filters"],
    },
    {
        "key": "load_more",
        "label": "Load more",
        "selector": "#problem-list-load-more",
        "texts": ["load more", "show more"],
    },
    {
        "key": "write_solution",
        "label": "Write solution",
        "selector": ".js-show-inline-draft",
        "texts": ["write a solution", "write solution", "start my draft", "edit my solution"],
    },
    {
        "key": "open_solution",
        "label": "Open solutions",
        "selector": "[data-learning-action='open_solution']",
        "texts": ["view solutions", "solutions", "read solution", "official solution"],
    },
    {
        "key": "download_pdf",
        "label": "Download PDF",
        "selector": "a[href*='/pdf/']",
        "texts": ["download pdf", "export pdf"],
    },
    {
        "key": "copy_link",
        "label": "Copy link",
        "selector": "[data-share-copy]",
        "texts": ["copy link", "copy share link"],
    },
    {
        "key": "mark_complete",
        "label": "Mark complete",
        "selector": "[data-learning-action='mark_complete']",
        "texts": ["mark complete", "mark as complete", "mark done"],
    },
    {
        "key": "record_completion",
        "label": "Record completion",
        "selector": (
            "#completion-board-save-date,#completion-board-save-unknown,"
            "#completion-board-bulk-save-date,#completion-board-bulk-save-unknown"
        ),
        "texts": ["record completion", "save date", "unknown date", "save completion"],
    },
    {
        "key": "submit_solution",
        "label": "Submit solution",
        "selector": "[data-learning-action='submit_solution']",
        "texts": ["submit solution"],
    },
    {
        "key": "open_filters",
        "label": "Open filters",
        "selector": "[data-bs-toggle=collapse]",
        "texts": ["filters", "advanced filters"],
    },
    {"key": "select_tab", "label": "Select tab", "selector": "[role=tab]", "texts": []},
    {
        "key": "close",
        "label": "Close or cancel",
        "selector": "[data-bs-dismiss],.btn-close",
        "texts": ["close", "cancel", "exit"],
    },
    {"key": "submit_form", "label": "Submit form", "selector": "button[type=submit],input[type=submit]", "texts": []},
    {"key": "open_page", "label": "Open linked page", "selector": "a.btn", "texts": []},
    {
        "key": "other_button",
        "label": "Other button (unclassified)",
        "selector": "button,[role=button],summary",
        "texts": [],
    },
]
ACTION_LABELS = {rule["key"]: rule["label"] for rule in ACTION_RULES}
SOLUTION_ONLY_ACTIONS = {"save_solution", "publish_solution", "save_draft", "share_solution"}


def _rules_for_page(page_name):
    return [
        {key: value for key, value in rule.items() if key != "label"}
        for rule in ACTION_RULES
        if rule["key"] not in SOLUTION_ONLY_ACTIONS or page_name.startswith("solutions:")
    ]


def learning_activity_context(request):
    match = getattr(request, "resolver_match", None)
    page_name = match.view_name if match else ""
    if (
        not settings.LEARNING_ACTIVITY_ENABLED
        or request.method not in {"GET", "POST"}
        or page_name not in LEARNING_PAGES
        or not user_can_access_app_features(getattr(request, "user", None))
    ):
        return {}
    payload = {
        "visit": str(uuid.uuid4()),
        "user": request.user.pk,
        "page": page_name,
        "path": request.path[:255],
        "issued": timezone.now().timestamp(),
    }
    return {
        "learning_activity_config": {
            "token": signing.dumps(payload, salt=TOKEN_SALT, compress=True),
            "endpoint": reverse("pages:learning_activity_collect"),
            "csrf": get_token(request),
            "rules": _rules_for_page(page_name),
        },
    }


def _rate_allowed(user_id):
    bucket = int(timezone.now().timestamp()) // MINUTE_SECONDS
    key = f"learning-activity:{user_id}:{bucket}"
    try:
        cache.add(key, 0, timeout=120)
        return cache.incr(key) <= REQUESTS_PER_MINUTE
    except (ValueError, OSError):
        return False


def _validate_payload(request):
    if len(request.body) > MAX_BODY_BYTES:
        raise ValueError("oversized")
    value = json.loads(request.body)
    if not isinstance(value, dict) or set(value) != {"token", "sequence", "visible_ms", "clicks"}:
        raise ValueError("fields")
    for field, maximum in (("sequence", MAX_SEQUENCE), ("visible_ms", MAX_VISIBLE_MS)):
        if type(value[field]) is not int or not 0 <= value[field] <= maximum:
            raise ValueError("number")
    if not isinstance(value["token"], str) or len(value["token"]) > MAX_TOKEN_LENGTH:
        raise ValueError("token")
    clicks = value["clicks"]
    if not isinstance(clicks, dict) or set(clicks) - ACTION_LABELS.keys():
        raise ValueError("actions")
    if any(type(count) is not int or not 0 <= count <= MAX_CLICKS for count in clicks.values()):
        raise ValueError("count")
    if sum(clicks.values()) > MAX_CLICKS:
        raise ValueError("total")
    context = signing.loads(value["token"], salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    if context["user"] != request.user.pk or context["page"] not in LEARNING_PAGES:
        raise ValueError("owner")
    return value, context


@login_required
@require_POST
def learning_activity_collect(request):  # noqa: C901, PLR0911 -- Explicit fail-closed request and ownership gates.
    if not settings.LEARNING_ACTIVITY_ENABLED or not user_can_access_app_features(request.user):
        return HttpResponse(status=403)
    if not _rate_allowed(request.user.pk):
        return HttpResponse(status=429)
    try:
        value, context = _validate_payload(request)
    except (ValueError, KeyError, TypeError, signing.BadSignature):
        return JsonResponse({"error": "Invalid activity snapshot."}, status=400)
    now = timezone.now()
    started_at = datetime.fromtimestamp(context["issued"], tz=now.tzinfo)
    elapsed_ms = max(0, int((now - started_at).total_seconds() * 1000))
    visible_ms = min(value["visible_ms"], elapsed_ms + MAX_CLOCK_SKEW_MS)
    try:
        with transaction.atomic():
            visit, _ = LearningPageVisit.objects.get_or_create(
                visit_uuid=context["visit"],
                defaults={
                    "user": request.user,
                    "page_name": context["page"],
                    "path": context["path"],
                    "started_at": started_at,
                },
            )
            visit = LearningPageVisit.objects.select_for_update().get(pk=visit.pk)
            if visit.user_id != request.user.pk:
                return HttpResponse(status=403)
            if value["sequence"] <= visit.sequence:
                return HttpResponse(status=204)
            existing = {action.action: action for action in visit.actions.all()}
            merged = {key: action.count for key, action in existing.items()}
            for key, count in value["clicks"].items():
                merged[key] = max(merged.get(key, 0), count)
            total = sum(merged.values())
            if total > MAX_CLICKS:
                return HttpResponse(status=400)
            for key, count in value["clicks"].items():
                previous = existing[key].count if key in existing else 0
                if count > previous:
                    LearningPageAction.objects.update_or_create(visit=visit, action=key, defaults={"count": count})
            visit.visible_ms = max(visit.visible_ms, visible_ms)
            visit.sequence = value["sequence"]
            visit.click_total = total
            visit.updated_at = now
            visit.save(update_fields=["visible_ms", "sequence", "click_total", "updated_at"])
    except (OperationalError, ProgrammingError):
        # Telemetry must not break a learning page while schema is unavailable.
        return HttpResponse(status=503)
    return HttpResponse(status=204)
