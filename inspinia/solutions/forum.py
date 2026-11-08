# ruff: noqa: EM101, EM102, TRY003
"""Transactional member discussion and independent, revision-bound human review."""

import hashlib
import json

from django.core.cache import cache
from django.db import transaction
from django.db.models import BigIntegerField
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import TextField
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.document_source import solution_source
from inspinia.solutions.forum_access import can_read_solution
from inspinia.solutions.forum_models import SolutionComment
from inspinia.solutions.forum_models import SolutionCommentEvent
from inspinia.solutions.forum_models import SolutionForumReport
from inspinia.solutions.forum_models import SolutionForumTarget
from inspinia.solutions.forum_models import SolutionHumanAssessment
from inspinia.solutions.forum_models import SolutionReviewRequest
from inspinia.solutions.forum_models import SolutionUpvote
from inspinia.solutions.forum_models import SolutionVerificationDecision
from inspinia.solutions.forum_models import Verdict
from inspinia.solutions.image_access import image_paths
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role

TEXT_LIMIT = 12_000
HOURLY_ACTION_LIMIT = 100
SUPPORTED_ACTIONS = frozenset({
    "upvote", "request_review", "assess", "verify", "adjudicate", "revoke",
    "comment", "edit_comment", "remove_comment", "hide_comment", "restore_comment", "report", "resolve_report",
})


class ForumError(ValueError):
    def __init__(self, message, status=422):
        self.message, self.status = message, status
        super().__init__(message)


def current_target_data(solution):
    statement = (
        ContestProblemStatement.objects.filter(linked_problem=solution.problem, is_active=True)
        .order_by(
            "-updated_at",
            "-pk",
        )
        .first()
    )
    source = solution_source(solution)
    paths = image_paths(source)
    statement_text = statement.statement_latex if statement else ""
    payload = {
        "version": 1,
        "title": solution.title,
        "summary": solution.summary,
        "document": {"source": source, "format": "latex"},
        "revision_id": str(solution.current_revision_id or ""),
        "edit_version": solution.edit_version,
        "saved_at": solution.updated_at.isoformat(),
        "statement": {"source": statement_text, "id": statement.pk if statement else None},
        "image_paths": paths,
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"key": key, "payload": payload, "revision_id": solution.current_revision_id}


def _latest_assessments(target):
    latest = {}
    for row in target.assessments.select_related("reviewer").order_by("sequence", "pk"):
        # Deleted reviewers remain distinct historical contributors.
        identity = row.reviewer_identity
        latest[identity] = row
    return list(latest.values())


def summary(solution):
    data = current_target_data(solution)
    target = solution.forum_targets.filter(key=data["key"]).first()
    assessments = _latest_assessments(target) if target else []
    substantive = {row.verdict for row in assessments if row.verdict != Verdict.UNDETERMINED}
    disputed = len(substantive) > 1
    label = "Not assessed"
    if disputed:
        label = "Trainer disagreement"
    elif substantive:
        label = Verdict(next(iter(substantive))).label
    elif assessments:
        label = Verdict.UNDETERMINED.label
    decision = target.decisions.select_related("admin").last() if target else None
    basis = {str(pk) for pk in decision.assessment_basis} if decision else set()
    new_conflict = bool(decision) and any(
        row.verdict not in {Verdict.UNDETERMINED, decision.verdict} and str(row.pk) not in basis
        for row in assessments
    )
    verified = bool(
        decision
        and decision.action in {"verify", "adjudicate"}
        and decision.verdict == Verdict.CORRECT
        and not new_conflict,
    )
    verification_label = "Verified" if verified else "Unverified"
    if new_conflict:
        verification_label = "Verification needs review"
    elif not decision and solution.forum_targets.filter(decisions__verdict=Verdict.CORRECT).exists():
        verification_label = "Updated since verification"
    review_request = SolutionReviewRequest.objects.filter(target=target).first() if target else None
    return {
        "target": target,
        "target_key": data["key"],
        "assessments": assessments,
        "assessment_label": label,
        "disputed": disputed,
        "verified": verified,
        "verification_label": verification_label,
        "decision": decision,
        "request": review_request,
        "disagreement_resolved": bool(disputed and decision and not new_conflict and decision.action != "revoke"),
    }


def queue_solutions(state="requested", *, admin=False):
    """Filter current saved targets in SQL before pagination, never over all proof bodies."""
    # The statement subqueries below are correlated with ProblemSolution.problem_id.
    statements = ContestProblemStatement.objects.filter(
        linked_problem_id=OuterRef("problem_id"), is_active=True,
    ).order_by(
        "-updated_at",
        "-pk",
    )
    current = SolutionForumTarget.objects.annotate(
        statement_marker=Coalesce("statement_id_value", Value(0), output_field=BigIntegerField()),
    ).filter(
        solution_id=OuterRef("pk"),
        solution_version=OuterRef("edit_version"),
        solution_updated_at=OuterRef("updated_at"),
        statement_source=OuterRef("forum_statement"),
        statement_marker=OuterRef("forum_statement_id"),
    )
    queryset = (
        ProblemSolution.objects.filter(status=ProblemSolution.Status.PUBLISHED)
        .annotate(
            forum_statement=Coalesce(
                Subquery(statements.values("statement_latex")[:1]), Value(""), output_field=TextField(),
            ),
        forum_statement_id=Coalesce(Subquery(statements.values("pk")[:1]), Value(0), output_field=BigIntegerField()),
        )
        .annotate(forum_target_id=Subquery(current.values("pk")[:1]))
    )
    assessments = SolutionHumanAssessment.objects.filter(target_id=OuterRef("forum_target_id"))
    later = SolutionHumanAssessment.objects.filter(
        target_id=OuterRef("target_id"),
        reviewer_identity=OuterRef("reviewer_identity"),
        sequence__gt=OuterRef("sequence"),
    )
    active = (
        assessments.annotate(superseded=Exists(later)).filter(superseded=False).exclude(verdict=Verdict.UNDETERMINED)
    )
    verdict_counts = active.order_by().values("target_id").annotate(n=Count("verdict", distinct=True)).values("n")
    requests = SolutionReviewRequest.objects.filter(target_id=OuterRef("forum_target_id"), status="pending")
    decisions = SolutionVerificationDecision.objects.filter(target_id=OuterRef("forum_target_id")).order_by(
        "-created_at", "-pk",
    )
    queryset = queryset.annotate(
        forum_requested=Exists(requests),
        forum_assessed=Exists(assessments),
        forum_verdict_count=Coalesce(Subquery(verdict_counts[:1]), Value(0)),
        forum_decided=Exists(decisions),
        forum_decision_at=Subquery(decisions.values("created_at")[:1]),
        forum_decision_verdict=Subquery(decisions.values("verdict")[:1]),
        forum_decision_action=Subquery(decisions.values("action")[:1]),
    )
    new_conflict = active.filter(created_at__gt=OuterRef("forum_decision_at")).exclude(
        verdict=OuterRef("forum_decision_verdict"),
    )
    queryset = queryset.annotate(forum_new_conflict=Exists(new_conflict))
    if state == "requested":
        queryset = queryset.filter(forum_requested=True)
    elif state == "unassessed":
        queryset = queryset.filter(forum_assessed=False)
    elif state == "assessed":
        queryset = queryset.filter(forum_assessed=True)
    elif state == "disputed":
        queryset = queryset.filter(
            Q(forum_verdict_count__gt=1, forum_decided=False)
            | Q(forum_new_conflict=True)
            | Q(forum_verdict_count__gt=1, forum_decision_action="revoke"),
        )
    elif state in {"pending", "pending_verification"} and admin:
        queryset = queryset.filter(
            Q(forum_decided=False) | Q(forum_new_conflict=True) | Q(forum_decision_action="revoke"),
        )
    return queryset.select_related("author", "problem", "current_revision").order_by("-published_at", "-pk")


def _text(data, name, *, required=False):
    value = data.get(name, "")
    if not isinstance(value, str) or len(value) > TEXT_LIMIT or "\x00" in value:
        raise ForumError(f"Keep {name.replace('_', ' ')} within {TEXT_LIMIT:,} text characters.")
    value = value.strip()
    if required and not value:
        raise ForumError(f"Enter {name.replace('_', ' ')}.")
    return value


def _integer(data, name):
    try:
        value = int(data.get(name, ""))
    except (TypeError, ValueError) as error:
        raise ForumError("Submit a valid version or record identifier.") from error
    if not 1 <= value <= 2**63 - 1:
        raise ForumError("Submit a valid version or record identifier.")
    return value


def _head(data, name, latest):
    if str(data.get(name, "")) != str(latest.pk if latest else ""):
        raise ForumError("This discussion or assessment changed. Reload before submitting again.", 409)


def _target(solution, data):
    current = current_target_data(solution)
    if data.get("target_key") != current["key"]:
        raise ForumError("The solution or statement changed. Review the latest version before submitting.", 409)
    payload = current["payload"]
    row, _created = SolutionForumTarget.objects.get_or_create(
        solution=solution,
        key=current["key"],
        defaults={
            "revision_id": current["revision_id"],
            "snapshot": payload,
            "image_paths": payload["image_paths"],
            "solution_version": solution.edit_version,
            "solution_updated_at": solution.updated_at,
            "statement_source": payload["statement"]["source"],
            "statement_id_value": payload["statement"]["id"],
        },
    )
    return row


def _rate_limit(user, action):
    key = f"solution-forum:{user.pk}:{action}:{timezone.now().strftime('%Y%m%d%H')}"
    if cache.add(key, 1, timeout=3600):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=3600)
        count = 1
    if count > HOURLY_ACTION_LIMIT:
        raise ForumError("Too many requests. Please try again later.", 429)


def _assess(user, solution, data, target):
    if not user_has_trainer_or_admin_role(user) or solution.author_id == user.pk:
        raise ForumError("An independent trainer or admin must assess this solution.", 403)
    latest = target.assessments.filter(reviewer=user).order_by("-sequence").first()
    _head(data, "assessment_head", latest)
    verdict = data.get("verdict")
    if verdict not in Verdict.values:
        raise ForumError("Choose a mathematical verdict.")
    assessment = SolutionHumanAssessment.objects.create(
        target=target,
        reviewer=user,
        reviewer_identity=user.pk,
        sequence=latest.sequence + 1 if latest else 1,
        verdict=verdict,
        feedback=_text(data, "feedback", required=True),
        gaps=_text(data, "gaps"),
        next_steps=_text(data, "next_steps"),
    )
    SolutionReviewRequest.objects.filter(target=target, status="pending").update(status="answered")
    return assessment


def _decide(user, solution, action, data, target):
    if not user_has_admin_role(user) or solution.author_id == user.pk:
        raise ForumError("An independent admin must make the verification decision.", 403)
    latest = target.decisions.last()
    _head(data, "decision_head", latest)
    assessments = _latest_assessments(target)
    expected_basis = ",".join(str(row.pk) for row in sorted(assessments, key=lambda row: row.pk))
    if data.get("assessment_basis", "") != expected_basis:
        raise ForumError("Trainer assessments changed. Read them before deciding.", 409)
    if action == "verify" and data.get("verdict", Verdict.CORRECT) != Verdict.CORRECT:
        raise ForumError("Choose Correct before marking this version Verified.")
    verdict = Verdict.CORRECT if action == "verify" else data.get("verdict", "")
    if action == "adjudicate" and verdict not in Verdict.values:
        raise ForumError("Choose the adjudicated mathematical verdict.")
    if action == "revoke":
        verdict = ""
    return SolutionVerificationDecision.objects.create(
        target=target,
        admin=user,
        action=action,
        verdict=verdict,
        reason=_text(data, "reason", required=True),
        assessment_basis=[row.pk for row in assessments],
    )


def _comment(user, solution, action, data):  # noqa: C901, PLR0912 - Explicit owner and moderation actions.
    if action == "comment":
        parent = None
        if data.get("parent_id"):
            parent = solution.forum_comments.filter(
                pk=_integer(data, "parent_id"), parent__isnull=True, state="visible",
            ).first()
            if parent is None:
                raise ForumError("Reply to a top-level comment on this solution.", 404)
        comment = SolutionComment.objects.create(
            solution=solution,
            author=user,
            parent=parent,
            body=_text(data, "body", required=True),
            created_revision_id=solution.current_revision_id,
        )
        SolutionCommentEvent.objects.create(
            comment=comment, actor=user, action="created", body=comment.body, version=1,
        )
        return comment
    comment = solution.forum_comments.select_for_update().filter(pk=_integer(data, "comment_id")).first()
    if comment is None:
        raise ForumError("Comment unavailable.", 404)
    if action == "report":
        if comment.state != "visible":
            raise ForumError("This comment is no longer visible.", 409)
        row, _created = SolutionForumReport.objects.get_or_create(
            comment=comment,
            reporter=user,
            status="open",
            defaults={"reason": _text(data, "reason", required=True)},
        )
        return row
    if action in {"hide_comment", "restore_comment"}:
        if not user_has_admin_role(user):
            raise ForumError("Only admins can moderate comments.", 403)
        reason = _text(data, "reason", required=True)
        if action == "restore_comment" and comment.state != "hidden":
            raise ForumError("Only hidden comments can be restored.", 409)
        if action == "hide_comment" and comment.state != "visible":
            raise ForumError("Only visible comments can be hidden.", 409)
        body, state = comment.body, "hidden" if action == "hide_comment" else "visible"
    else:
        if comment.author_id != user.pk or comment.state != "visible":
            raise ForumError("Only the author can change their visible comment.", 403)
        body = _text(data, "body", required=True) if action == "edit_comment" else comment.body
        state, reason = ("removed" if action == "remove_comment" else "visible"), ""
    if _integer(data, "version") != comment.version:
        raise ForumError("This comment changed. Reload before submitting.", 409)
    comment.body, comment.state, comment.version = body, state, comment.version + 1
    comment.save(update_fields=["body", "state", "version", "updated_at"])
    SolutionCommentEvent.objects.create(
        comment=comment,
        actor=user,
        action=action,
        body=body,
        reason=reason,
        version=comment.version,
    )
    return comment


@transaction.atomic
def write(user, solution_id, action, data):  # noqa: C901, PLR0911, PLR0912 - One locked authorization boundary.
    if action not in SUPPORTED_ACTIONS:
        raise ForumError("Unknown forum action.", 404)
    if not getattr(user, "is_authenticated", False):
        raise ForumError("Sign in before using the solution forum.", 403)
    user = User.objects.select_for_update().filter(pk=user.pk).first()
    if user is None or not user.is_active or not user_can_access_app_features(user):
        raise ForumError("Account approval is required.", 403)
    problem_id = ProblemSolution.objects.filter(pk=solution_id).values_list("problem_id", flat=True).first()
    if problem_id is None:
        raise ForumError("Solution unavailable.", 404)
    if not ProblemSolveRecord.objects.select_for_update().filter(pk=problem_id).exists():
        raise ForumError("Solution unavailable.", 404)
    solution = (
        ProblemSolution.objects.select_for_update(of=("self",))
        .select_related(
            "problem",
            "current_revision",
        )
        .filter(pk=solution_id).first()
    )
    if solution is None or not can_read_solution(user, solution):
        raise ForumError("Solution unavailable.", 404)
    moderation = action in {"hide_comment", "restore_comment", "resolve_report"} and user_has_admin_role(user)
    if solution.status != ProblemSolution.Status.PUBLISHED and not moderation:
        raise ForumError("Publish this solution to members before using the forum.", 409)
    _rate_limit(user, action)
    if action == "upvote":
        if user.pk == solution.author_id:
            raise ForumError("You cannot upvote your own solution.", 403)
        if str(data.get("active", "")) not in {"0", "1"}:
            raise ForumError("Choose whether to upvote this solution.")
        if str(data["active"]) == "1":
            return SolutionUpvote.objects.get_or_create(solution=solution, user=user)[0]
        return SolutionUpvote.objects.filter(solution=solution, user=user).delete()
    if action in {"request_review", "assess", "verify", "adjudicate", "revoke"}:
        target = _target(solution, data)
        if action == "request_review":
            if solution.author_id != user.pk:
                raise ForumError("Only the author can request a review.", 403)
            request, _created = SolutionReviewRequest.objects.get_or_create(
                target=target,
                defaults={"requested_by": user, "status": "answered" if target.assessments.exists() else "pending"},
            )
            return request
        if action == "assess":
            return _assess(user, solution, data, target)
        return _decide(user, solution, action, data, target)
    if action in {"comment", "edit_comment", "remove_comment", "hide_comment", "restore_comment", "report"}:
        return _comment(user, solution, action, data)
    if action == "resolve_report":
        if not user_has_admin_role(user):
            raise ForumError("Only admins can resolve reports.", 403)
        report = (
            SolutionForumReport.objects.select_for_update()
            .filter(
                pk=_integer(data, "report_id"),
                comment__solution=solution,
            )
            .first()
        )
        if report is None:
            raise ForumError("Report unavailable.", 404)
        if report.status != "open":
            raise ForumError("This report was already resolved.", 409)
        report.status, report.resolved_by, report.resolved_at = "resolved", user, timezone.now()
        report.resolution = _text(data, "resolution", required=True)
        report.save()
        SolutionCommentEvent.objects.create(
            comment=report.comment,
            actor=user,
            action="report_resolved",
            reason=report.resolution,
            version=report.comment.version,
        )
        return report
    raise ForumError("Unknown forum action.", 404)
