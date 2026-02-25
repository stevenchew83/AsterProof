from __future__ import annotations

import csv
import io
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import Group
from django.db.models import Avg
from django.db.models import Count
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

from inspinia.backoffice.models import AbusePolicy
from inspinia.backoffice.models import BrandingConfig
from inspinia.backoffice.models import FeatureFlagConfig
from inspinia.backoffice.models import ModerationAction
from inspinia.backoffice.models import ModerationLog
from inspinia.backoffice.models import ProblemIngestionStatus
from inspinia.backoffice.models import ProblemRequest
from inspinia.backoffice.models import ProblemSubmission
from inspinia.backoffice.models import PrivacyDefaultsConfig
from inspinia.backoffice.models import RatingConfig
from inspinia.backoffice.models import RatingRun
from inspinia.backoffice.models import Report
from inspinia.backoffice.models import ReportStatus
from inspinia.backoffice.services import apply_rating_run
from inspinia.backoffice.services import clear_user_state
from inspinia.backoffice.services import get_effective_feature_flags
from inspinia.backoffice.services import hide_target
from inspinia.backoffice.services import redact_target
from inspinia.backoffice.services import resolve_report
from inspinia.backoffice.services import rollback_rating_run
from inspinia.backoffice.services import set_user_state
from inspinia.backoffice.services import unhide_target
from inspinia.catalog.models import Contest
from inspinia.catalog.models import Problem
from inspinia.catalog.models import Tag
from inspinia.catalog.latex_utils import lint_statement_source
from inspinia.catalog.latex_utils import to_plaintext
from inspinia.community.models import Comment
from inspinia.community.models import PublicSolution
from inspinia.contests.models import ContestEvent
from inspinia.contests.models import Submission
from inspinia.core.permissions import ADMIN_GROUP
from inspinia.core.permissions import MODERATOR_GROUP
from inspinia.core.permissions import admin_required
from inspinia.core.permissions import is_admin
from inspinia.core.permissions import moderator_required
from inspinia.notes.models import PrivateNote
from inspinia.progress.models import ProblemProgress
from inspinia.users.models import User


def _bool_post(request, key: str) -> bool:  # noqa: ANN001
    return request.POST.get(key) in {"1", "true", "True", "on", "yes"}


def _parse_id_list(raw: str) -> list[int]:
    ids = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids


def _coerce_difficulty(raw: str | None, default: int = 3) -> int:
    try:
        value = int((raw or "").strip())
    except ValueError:
        return default
    return max(1, min(7, value))


def _normalize_statement_format(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    valid_formats = {choice[0] for choice in ProblemSubmission.StatementFormat.choices}
    if value in valid_formats:
        return value
    return ProblemSubmission.StatementFormat.PLAIN


def _resolve_import_contest(
    short_code: str | None,
    contest_name: str | None,
    contest_year: str | None,
    contest_cache: dict[str, Contest],
) -> Contest | None:
    normalized_short_code = (short_code or "").strip()[:64]
    if not normalized_short_code:
        return None

    if normalized_short_code in contest_cache:
        return contest_cache[normalized_short_code]

    contest = Contest.objects.filter(short_code=normalized_short_code).first()
    if contest is not None:
        contest_cache[normalized_short_code] = contest
        return contest

    year = timezone.now().year
    try:
        parsed_year = int((contest_year or "").strip())
        if parsed_year > 0:
            year = parsed_year
    except ValueError:
        pass

    normalized_name = ((contest_name or "").strip() or normalized_short_code)[:200]
    contest = Contest.objects.create(
        name=normalized_name,
        short_code=normalized_short_code,
        contest_type="custom",
        year=year,
    )
    contest_cache[normalized_short_code] = contest
    return contest


@moderator_required
def dashboard(request):
    return render(
        request,
        "backoffice/dashboard.html",
        {
            "open_reports": Report.objects.filter(status=ReportStatus.OPEN).count(),
            "escalated_reports": Report.objects.filter(status=ReportStatus.ESCALATED).count(),
            "pending_problem_requests": ProblemRequest.objects.filter(status=ProblemIngestionStatus.NEW).count(),
            "pending_problem_submissions": ProblemSubmission.objects.filter(status=ProblemIngestionStatus.NEW).count(),
        },
    )


@moderator_required
def public_access_pages(request):
    return render(request, "backoffice/public_access_pages.html")


@moderator_required
def moderation_report_list(request):
    reports = Report.objects.select_related("reporter", "assignee", "resolved_by", "content_type")
    status = request.GET.get("status")
    if status:
        reports = reports.filter(status=status)
    severity = request.GET.get("severity")
    if severity:
        reports = reports.filter(severity=severity)
    return render(request, "backoffice/moderation/report_list.html", {"reports": reports[:300], "status": status})


@moderator_required
def moderation_report_detail(request, report_id: int):
    report = get_object_or_404(Report.objects.select_related("reporter", "assignee", "content_type"), pk=report_id)
    logs = report.logs.select_related("actor", "target_user")[:200]
    return render(
        request,
        "backoffice/moderation/report_detail.html",
        {"report": report, "target": report.target, "logs": logs},
    )


@moderator_required
def moderation_report_action(request, report_id: int):
    if request.method != "POST":
        return redirect("backoffice:moderation_report_detail", report_id=report_id)

    report = get_object_or_404(Report, pk=report_id)
    target = report.target
    action = request.POST.get("action", "").strip()
    reason = request.POST.get("reason", "").strip()

    if action == "hide" and target is not None:
        hide_target(actor=request.user, target=target, reason=reason, report=report)
    elif action == "unhide" and target is not None:
        unhide_target(actor=request.user, target=target, reason=reason, report=report)
    elif action == "redact" and target is not None:
        redact_text = request.POST.get("redact_text", "[redacted by moderator]")
        redact_target(actor=request.user, target=target, replacement_text=redact_text, reason=reason, report=report)
    elif action == "warn":
        target_user = getattr(target, "author", None) or getattr(target, "user", None) or target
        if isinstance(target_user, User):
            set_user_state(actor=request.user, target_user=target_user, action=ModerationAction.WARN, reason=reason)
    elif action == "mute":
        target_user = getattr(target, "author", None) or getattr(target, "user", None) or target
        if isinstance(target_user, User):
            mute_days = int(request.POST.get("mute_days", "7"))
            mute_until = timezone.now() + timedelta(days=max(1, mute_days))
            set_user_state(
                actor=request.user,
                target_user=target_user,
                action=ModerationAction.MUTE,
                reason=reason,
                mute_until=mute_until,
            )
    elif action == "ban":
        if not is_admin(request.user):
            messages.error(request, "Only admins can ban users.")
            return redirect("backoffice:moderation_report_detail", report_id=report_id)
        target_user = getattr(target, "author", None) or getattr(target, "user", None) or target
        if isinstance(target_user, User):
            set_user_state(actor=request.user, target_user=target_user, action=ModerationAction.BAN, reason=reason)
    elif action == "shadow_ban":
        if not is_admin(request.user):
            messages.error(request, "Only admins can shadow-ban users.")
            return redirect("backoffice:moderation_report_detail", report_id=report_id)
        target_user = getattr(target, "author", None) or getattr(target, "user", None) or target
        if isinstance(target_user, User):
            set_user_state(actor=request.user, target_user=target_user, action=ModerationAction.SHADOW_BAN, reason=reason)
    elif action == "resolve":
        resolve_report(actor=request.user, report=report, status=ReportStatus.RESOLVED, note=reason)
    elif action == "dismiss":
        resolve_report(actor=request.user, report=report, status=ReportStatus.DISMISSED, note=reason)
    elif action == "escalate":
        resolve_report(actor=request.user, report=report, status=ReportStatus.ESCALATED, note=reason)

    return redirect("backoffice:moderation_report_detail", report_id=report_id)


@moderator_required
def moderation_logs(request):
    logs = ModerationLog.objects.select_related("actor", "target_user", "report")[:400]
    return render(request, "backoffice/moderation/logs.html", {"logs": logs})


@moderator_required
def users_list(request):
    users = User.objects.order_by("-date_joined")
    q = request.GET.get("q")
    if q:
        users = users.filter(email__icontains=q)
    return render(request, "backoffice/users/list.html", {"users": users[:300], "q": q or ""})


@moderator_required
def user_detail(request, user_id: int):
    user_obj = get_object_or_404(User, pk=user_id)
    logs = ModerationLog.objects.filter(target_user=user_obj).select_related("actor")[:200]
    reports_against = Report.objects.filter(object_id=user_obj.pk, content_type__app_label="users", content_type__model="user")[:200]
    reports_by = Report.objects.filter(reporter=user_obj)[:200]
    return render(
        request,
        "backoffice/users/detail.html",
        {
            "target_user": user_obj,
            "logs": logs,
            "reports_against": reports_against,
            "reports_by": reports_by,
        },
    )


@moderator_required
def user_action(request, user_id: int):
    if request.method != "POST":
        return redirect("backoffice:user_detail", user_id=user_id)
    target_user = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "")

    if action == "mute":
        mute_days = int(request.POST.get("mute_days", "7"))
        mute_until = timezone.now() + timedelta(days=max(1, mute_days))
        set_user_state(
            actor=request.user,
            target_user=target_user,
            action=ModerationAction.MUTE,
            reason=reason,
            mute_until=mute_until,
        )
    elif action == "unmute":
        clear_user_state(actor=request.user, target_user=target_user, action=ModerationAction.MUTE, reason=reason)
    elif action == "ban":
        if not is_admin(request.user):
            messages.error(request, "Only admins can ban users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        set_user_state(actor=request.user, target_user=target_user, action=ModerationAction.BAN, reason=reason)
    elif action == "unban":
        if not is_admin(request.user):
            messages.error(request, "Only admins can unban users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        clear_user_state(actor=request.user, target_user=target_user, action=ModerationAction.BAN, reason=reason)
    elif action == "shadow_ban":
        if not is_admin(request.user):
            messages.error(request, "Only admins can shadow-ban users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        set_user_state(actor=request.user, target_user=target_user, action=ModerationAction.SHADOW_BAN, reason=reason)
    elif action == "unshadow":
        if not is_admin(request.user):
            messages.error(request, "Only admins can unshadow users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        clear_user_state(actor=request.user, target_user=target_user, action=ModerationAction.SHADOW_BAN, reason=reason)
    elif action == "readonly_on":
        if not is_admin(request.user):
            messages.error(request, "Only admins can set read-only mode.")
            return redirect("backoffice:user_detail", user_id=user_id)
        target_user.is_readonly = True
        target_user.save(update_fields=["is_readonly"])
    elif action == "readonly_off":
        if not is_admin(request.user):
            messages.error(request, "Only admins can clear read-only mode.")
            return redirect("backoffice:user_detail", user_id=user_id)
        target_user.is_readonly = False
        target_user.save(update_fields=["is_readonly"])
    elif action == "promote_trusted":
        if not is_admin(request.user):
            messages.error(request, "Only admins can promote users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        target_user.is_trusted_user = True
        target_user.save(update_fields=["is_trusted_user"])
    elif action == "demote_trusted":
        if not is_admin(request.user):
            messages.error(request, "Only admins can demote users.")
            return redirect("backoffice:user_detail", user_id=user_id)
        target_user.is_trusted_user = False
        target_user.save(update_fields=["is_trusted_user"])
    elif action in {"promote_moderator", "demote_moderator", "promote_admin", "demote_admin"}:
        if not is_admin(request.user):
            messages.error(request, "Only admins can change staff roles.")
            return redirect("backoffice:user_detail", user_id=user_id)
        moderator_group, _ = Group.objects.get_or_create(name=MODERATOR_GROUP)
        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
        if action == "promote_moderator":
            target_user.groups.add(moderator_group)
            target_user.is_staff = True
            target_user.save(update_fields=["is_staff"])
        elif action == "demote_moderator":
            target_user.groups.remove(moderator_group)
            if not target_user.groups.filter(name__in=[MODERATOR_GROUP, ADMIN_GROUP]).exists():
                target_user.is_staff = False
                target_user.save(update_fields=["is_staff"])
        elif action == "promote_admin":
            target_user.groups.add(admin_group)
            target_user.groups.add(moderator_group)
            target_user.is_staff = True
            target_user.save(update_fields=["is_staff"])
        elif action == "demote_admin":
            target_user.groups.remove(admin_group)
            if not target_user.groups.filter(name=MODERATOR_GROUP).exists():
                target_user.is_staff = False
                target_user.save(update_fields=["is_staff"])

    return redirect("backoffice:user_detail", user_id=user_id)


@admin_required
def ingestion_problem_requests(request):
    rows = ProblemRequest.objects.select_related("requester", "reviewer", "duplicate_problem")
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    return render(request, "backoffice/ingestion/problem_requests.html", {"rows": rows[:300], "status": status})


@admin_required
def ingestion_problem_request_action(request, request_id: int):
    if request.method != "POST":
        return redirect("backoffice:ingestion_problem_requests")
    row = get_object_or_404(ProblemRequest, pk=request_id)
    action = request.POST.get("action")
    note = request.POST.get("decision_note", "")
    row.reviewer = request.user
    row.decision_note = note

    if action == "reject":
        row.status = ProblemIngestionStatus.REJECTED
    elif action == "duplicate":
        row.status = ProblemIngestionStatus.DUPLICATE
        dup_id = request.POST.get("duplicate_problem_id")
        if dup_id:
            row.duplicate_problem = Problem.objects.filter(pk=dup_id).first()
    elif action == "accept":
        row.status = ProblemIngestionStatus.ACCEPTED
        contest = None
        if row.requested_contest:
            year = row.requested_year or timezone.now().year
            short_code = f"{slugify(row.requested_contest)[:20]}-{year}"
            contest, _ = Contest.objects.get_or_create(
                short_code=short_code,
                defaults={
                    "name": row.requested_contest,
                    "contest_type": "custom",
                    "year": year,
                },
            )
        Problem.objects.create(
            contest=contest,
            label=f"REQ-{row.id}",
            title=row.requested_contest or f"Requested Problem {row.id}",
            statement=row.details or "Pending statement from request.",
            statement_format=Problem.StatementFormat.PLAIN,
            statement_plaintext=to_plaintext(row.details or "Pending statement from request.", Problem.StatementFormat.PLAIN),
            editorial_difficulty=row.suggested_difficulty,
        )
    row.save()
    return redirect("backoffice:ingestion_problem_requests")


@admin_required
def ingestion_problem_submissions(request):
    rows = ProblemSubmission.objects.select_related("submitter", "reviewer", "contest", "linked_problem")
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    return render(request, "backoffice/ingestion/problem_submissions.html", {"rows": rows[:300], "status": status})


@admin_required
def problem_bulk_operations(request):
    if request.method == "POST":
        operation = request.POST.get("operation", "")
        problem_ids = _parse_id_list(request.POST.get("problem_ids", ""))
        problems = Problem.objects.filter(id__in=problem_ids)
        if not problems.exists():
            messages.error(request, "No valid problems selected.")
            return redirect("backoffice:problem_bulk_operations")

        if operation in {"add_tags", "replace_tags"}:
            tag_names = [tag.strip() for tag in request.POST.get("tag_names", "").split(",") if tag.strip()]
            tags = []
            for tag_name in tag_names:
                tag_slug = slugify(tag_name)
                tag, _ = Tag.objects.get_or_create(slug=tag_slug, defaults={"name": tag_name})
                tags.append(tag)
            for problem in problems:
                if operation == "replace_tags":
                    problem.tags.clear()
                for tag in tags:
                    problem.tags.add(tag)
            messages.success(request, f"Updated tags for {problems.count()} problems.")
        elif operation == "move_contest":
            contest_id = request.POST.get("contest_id")
            contest = Contest.objects.filter(id=contest_id).first()
            if contest is None:
                messages.error(request, "Invalid contest ID.")
            else:
                problems.update(contest=contest)
                messages.success(request, f"Moved {problems.count()} problems to contest {contest}.")
        elif operation == "mark_duplicates":
            canonical_id = request.POST.get("canonical_problem_id")
            canonical = Problem.objects.filter(id=canonical_id).first()
            if canonical is None:
                messages.error(request, "Invalid canonical problem ID.")
            else:
                problems.exclude(id=canonical.id).update(canonical_problem=canonical)
                messages.success(request, f"Marked duplicates against canonical problem #{canonical.id}.")
        else:
            messages.error(request, "Unsupported operation.")
        return redirect("backoffice:problem_bulk_operations")

    return render(request, "backoffice/ingestion/problem_bulk_operations.html")


@admin_required
def problem_set_import(request):
    context = {
        "created_count": 0,
        "skipped_count": 0,
        "preview_rows": [],
        "skipped_rows": [],
    }
    if request.method != "POST":
        return render(request, "backoffice/ingestion/problem_set_import.html", context)

    upload = request.FILES.get("problem_csv")
    if upload is None:
        messages.error(request, "Please upload a CSV file.")
        return render(request, "backoffice/ingestion/problem_set_import.html", context)
    if not upload.name.lower().endswith(".csv"):
        messages.error(request, "Only CSV files are supported. Export your .xlsx file as CSV and try again.")
        return render(request, "backoffice/ingestion/problem_set_import.html", context)

    try:
        csv_text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, "Unable to read CSV. Please save it as UTF-8 and retry.")
        return render(request, "backoffice/ingestion/problem_set_import.html", context)

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [field.strip().lower() for field in (reader.fieldnames or []) if field and field.strip()]
    if not fieldnames:
        messages.error(request, "CSV must include a header row.")
        return render(request, "backoffice/ingestion/problem_set_import.html", context)

    required_fields = {"title", "statement"}
    missing_fields = sorted(required_fields - set(fieldnames))
    if missing_fields:
        messages.error(request, f"Missing required column(s): {', '.join(missing_fields)}.")
        return render(request, "backoffice/ingestion/problem_set_import.html", context)

    created_count = 0
    skipped_rows: list[str] = []
    preview_rows: list[dict[str, str | int]] = []
    contest_cache: dict[str, Contest] = {}

    for row_number, raw_row in enumerate(reader, start=2):
        row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()}
        if not any(row.values()):
            continue

        title = (row.get("title") or "")[:255]
        statement = row.get("statement") or ""
        if not title or not statement:
            skipped_rows.append(f"Row {row_number}: title and statement are required.")
            continue

        statement_format = _normalize_statement_format(row.get("statement_format"))
        lint_errors = lint_statement_source(statement, statement_format)
        if lint_errors:
            skipped_rows.append(f"Row {row_number}: {' '.join(lint_errors)}")
            continue

        source_reference = (row.get("source_reference") or "")[:200]
        if source_reference and not source_reference.startswith(("http://", "https://")):
            skipped_rows.append(f"Row {row_number}: source_reference must start with http:// or https://.")
            continue

        try:
            contest = _resolve_import_contest(
                short_code=row.get("contest_short_code"),
                contest_name=row.get("contest_name"),
                contest_year=row.get("contest_year"),
                contest_cache=contest_cache,
            )
            imported = ProblemSubmission.objects.create(
                submitter=request.user,
                title=title,
                statement=statement,
                statement_format=statement_format,
                statement_plaintext=to_plaintext(statement, statement_format),
                source_reference=source_reference,
                proposed_tags=(row.get("proposed_tags") or "")[:255],
                proposed_difficulty=_coerce_difficulty(row.get("proposed_difficulty"), default=3),
                contest=contest,
            )
        except Exception as exc:  # noqa: BLE001
            skipped_rows.append(f"Row {row_number}: import failed ({exc}).")
            continue

        created_count += 1
        if len(preview_rows) < 25:
            preview_rows.append(
                {
                    "id": imported.id,
                    "title": imported.title,
                    "statement_format": imported.get_statement_format_display(),
                    "difficulty": imported.proposed_difficulty,
                    "contest": str(imported.contest) if imported.contest else "-",
                },
            )

    if created_count:
        messages.success(request, f"Imported {created_count} problem submission(s).")
    else:
        messages.info(request, "No rows were imported.")
    if skipped_rows:
        messages.warning(request, f"Skipped {len(skipped_rows)} row(s).")

    context.update(
        {
            "created_count": created_count,
            "skipped_count": len(skipped_rows),
            "preview_rows": preview_rows,
            "skipped_rows": skipped_rows[:100],
        },
    )
    return render(request, "backoffice/ingestion/problem_set_import.html", context)


@admin_required
def ingestion_problem_submission_action(request, submission_id: int):
    if request.method != "POST":
        return redirect("backoffice:ingestion_problem_submissions")
    row = get_object_or_404(ProblemSubmission, pk=submission_id)
    action = request.POST.get("action")
    note = request.POST.get("decision_note", "")
    row.reviewer = request.user
    row.decision_note = note

    if action == "reject":
        row.status = ProblemIngestionStatus.REJECTED
    elif action == "duplicate":
        row.status = ProblemIngestionStatus.DUPLICATE
        dup_id = request.POST.get("duplicate_problem_id")
        if dup_id:
            row.linked_problem = Problem.objects.filter(pk=dup_id).first()
    elif action == "accept":
        row.status = ProblemIngestionStatus.ACCEPTED
        contest_id = request.POST.get("contest_id")
        if contest_id:
            row.contest = Contest.objects.filter(pk=contest_id).first()
        lint_errors = lint_statement_source(row.statement, row.statement_format)
        if lint_errors:
            messages.error(request, "Cannot accept submission: " + " ".join(lint_errors))
            return redirect("backoffice:ingestion_problem_submissions")
        problem = Problem.objects.create(
            contest=row.contest,
            label=f"SUB-{row.id}",
            title=row.title,
            statement=row.statement,
            statement_format=row.statement_format,
            statement_plaintext=to_plaintext(row.statement, row.statement_format),
            editorial_difficulty=row.proposed_difficulty,
        )
        row.linked_problem = problem

        if row.proposed_tags:
            for raw_tag in row.proposed_tags.split(","):
                tag_name = raw_tag.strip()
                if not tag_name:
                    continue
                tag_slug = slugify(tag_name)
                tag, _ = Tag.objects.get_or_create(slug=tag_slug, defaults={"name": tag_name})
                problem.tags.add(tag)

    row.save()
    return redirect("backoffice:ingestion_problem_submissions")


@admin_required
def settings_abuse_policy(request):
    policy = AbusePolicy.load()
    if request.method == "POST":
        policy.comment_limit_per_minute = int(request.POST.get("comment_limit_per_minute", policy.comment_limit_per_minute))
        policy.comment_limit_per_hour = int(request.POST.get("comment_limit_per_hour", policy.comment_limit_per_hour))
        policy.max_external_links_per_post = int(
            request.POST.get("max_external_links_per_post", policy.max_external_links_per_post),
        )
        policy.bad_word_list = request.POST.get("bad_word_list", policy.bad_word_list)
        policy.captcha_on_anonymous_suggestions = _bool_post(request, "captcha_on_anonymous_suggestions")
        policy.captcha_new_account_threshold = int(
            request.POST.get("captcha_new_account_threshold", policy.captcha_new_account_threshold),
        )
        policy.save()
        messages.success(request, "Abuse policy saved.")
        return redirect("backoffice:settings_abuse_policy")
    return render(request, "backoffice/settings/abuse_policy.html", {"policy": policy})


@admin_required
def settings_feature_flags(request):
    cfg = FeatureFlagConfig.load()
    if request.method == "POST":
        cfg.contests = _bool_post(request, "contests")
        cfg.ratings = _bool_post(request, "ratings")
        cfg.public_dashboards = _bool_post(request, "public_dashboards")
        cfg.problem_submissions = _bool_post(request, "problem_submissions")
        cfg.advanced_analytics = _bool_post(request, "advanced_analytics")
        cfg.save()
        messages.success(request, "Feature flags saved.")
        return redirect("backoffice:settings_feature_flags")
    return render(request, "backoffice/settings/feature_flags.html", {"cfg": cfg})


@admin_required
def settings_privacy_defaults(request):
    cfg = PrivacyDefaultsConfig.load()
    if request.method == "POST":
        cfg.default_profile_visibility = request.POST.get("default_profile_visibility", cfg.default_profile_visibility)
        cfg.default_solution_unlisted = _bool_post(request, "default_solution_unlisted")
        cfg.save()
        messages.success(request, "Privacy defaults saved.")
        return redirect("backoffice:settings_privacy_defaults")
    return render(request, "backoffice/settings/privacy_defaults.html", {"cfg": cfg})


@admin_required
def settings_branding(request):
    cfg = BrandingConfig.load()
    if request.method == "POST":
        cfg.default_skin = request.POST.get("default_skin", cfg.default_skin)
        cfg.logo_text = request.POST.get("logo_text", cfg.logo_text)
        if request.FILES.get("logo_image"):
            cfg.logo_image = request.FILES["logo_image"]
        cfg.save()
        messages.success(request, "Branding saved.")
        return redirect("backoffice:settings_branding")
    return render(request, "backoffice/settings/branding.html", {"cfg": cfg})


@admin_required
def settings_rating_config(request):
    cfg = RatingConfig.load()
    if request.method == "POST":
        cfg.base_rating = float(request.POST.get("base_rating", cfg.base_rating))
        cfg.k_factor = int(request.POST.get("k_factor", cfg.k_factor))
        cfg.small_contest_threshold = int(request.POST.get("small_contest_threshold", cfg.small_contest_threshold))
        cfg.small_contest_k_multiplier = float(
            request.POST.get("small_contest_k_multiplier", cfg.small_contest_k_multiplier),
        )
        floor_raw = request.POST.get("rating_floor", "")
        cap_raw = request.POST.get("rating_cap", "")
        cfg.rating_floor = float(floor_raw) if floor_raw else None
        cfg.rating_cap = float(cap_raw) if cap_raw else None
        cfg.save()
        messages.success(request, "Rating configuration saved.")
        return redirect("backoffice:settings_rating_config")
    return render(request, "backoffice/settings/rating_config.html", {"cfg": cfg})


@admin_required
def rating_runs(request):
    runs = RatingRun.objects.select_related("contest", "triggered_by", "parent_run")[:200]
    contests = ContestEvent.objects.order_by("-start_time")[:100]
    return render(request, "backoffice/ratings/runs.html", {"runs": runs, "contests": contests})


@admin_required
def contest_submissions(request):
    submissions = Submission.objects.select_related("contest", "problem", "user", "graded_by").order_by("-created_at")
    contest_id = request.GET.get("contest")
    problem_id = request.GET.get("problem")
    user_id = request.GET.get("user")
    status = request.GET.get("status")

    if contest_id:
        submissions = submissions.filter(contest_id=contest_id)
    if problem_id:
        submissions = submissions.filter(problem_id=problem_id)
    if user_id:
        submissions = submissions.filter(user_id=user_id)
    if status:
        submissions = submissions.filter(marking_status=status)

    contests = ContestEvent.objects.order_by("-start_time")[:100]
    return render(
        request,
        "backoffice/contests/submissions.html",
        {
            "submissions": submissions[:300],
            "contests": contests,
            "status": status or "",
            "contest_id": contest_id or "",
            "problem_id": problem_id or "",
            "user_id": user_id or "",
        },
    )


@admin_required
def grade_submission(request, submission_id: int):
    submission = get_object_or_404(Submission, pk=submission_id)
    if request.method == "POST":
        try:
            submission.score = float(request.POST.get("score", submission.score))
        except (TypeError, ValueError):
            pass
        status_value = request.POST.get("marking_status", submission.marking_status)
        valid_statuses = {choice[0] for choice in Submission.MarkingStatus.choices}
        if status_value in valid_statuses:
            submission.marking_status = status_value
        submission.grader_note = request.POST.get("grader_note", submission.grader_note)
        submission.graded_by = request.user
        submission.graded_at = timezone.now()
        submission.save(update_fields=["score", "marking_status", "grader_note", "graded_by", "graded_at"])
    return redirect("backoffice:contest_submissions")


@admin_required
def rating_recalculate(request, contest_id: int):
    contest = get_object_or_404(ContestEvent, pk=contest_id)
    if request.method == "POST":
        apply_rating_run(contest=contest, triggered_by=request.user)
        messages.success(request, "Rating recalculation complete.")
    return redirect("backoffice:rating_runs")


@admin_required
def rating_rollback(request, run_id: int):
    run = get_object_or_404(RatingRun.objects.select_related("contest"), pk=run_id)
    if request.method == "POST":
        rollback_rating_run(run=run, triggered_by=request.user)
        messages.success(request, "Rating rollback complete.")
    return redirect("backoffice:rating_runs")


@admin_required
def global_analytics(request):
    if not get_effective_feature_flags().get("advanced_analytics", False):
        return HttpResponseNotFound("Advanced analytics are disabled.")
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    new_users_week = User.objects.filter(date_joined__gte=week_ago).count()
    solved_week = ProblemProgress.objects.filter(status="solved", updated_at__gte=week_ago).count()
    notes_week = PrivateNote.objects.filter(updated_at__gte=week_ago).count()

    public_solutions = PublicSolution.objects.filter(is_hidden=False).count()
    public_comments = Comment.objects.filter(is_hidden=False).count()

    flagged_volume = Report.objects.filter(created_at__gte=week_ago).count()
    resolved = Report.objects.filter(status=ReportStatus.RESOLVED, resolved_at__isnull=False)
    resolution_hours = [
        (row.resolved_at - row.created_at).total_seconds() / 3600
        for row in resolved[:200]
    ]

    disagreement_qs = Problem.objects.annotate(avg_vote=Avg("difficulty_votes__value")).exclude(avg_vote__isnull=True)
    disagreement = sorted(disagreement_qs, key=lambda p: abs(float(p.avg_vote) - p.editorial_difficulty), reverse=True)[:20]

    low_engagement = Problem.objects.annotate(
        solution_count=Count("publicsolution", distinct=True),
        comment_count=Count("comment", distinct=True),
    ).filter(solution_count=0, comment_count=0)[:20]

    rated_contests = ContestEvent.objects.filter(is_rated=True).count()
    avg_participation = ContestEvent.objects.annotate(participants=Count("registrations", distinct=True)).aggregate(
        avg=Avg("participants"),
    )["avg"]

    return render(
        request,
        "backoffice/analytics/global.html",
        {
            "new_users_week": new_users_week,
            "solved_week": solved_week,
            "notes_week": notes_week,
            "public_solutions": public_solutions,
            "public_comments": public_comments,
            "flagged_volume": flagged_volume,
            "resolution_hours_count": len(resolution_hours),
            "resolution_hours_avg": (sum(resolution_hours) / len(resolution_hours)) if resolution_hours else None,
            "disagreement": disagreement,
            "low_engagement": low_engagement,
            "rated_contests": rated_contests,
            "avg_participation": avg_participation,
        },
    )
