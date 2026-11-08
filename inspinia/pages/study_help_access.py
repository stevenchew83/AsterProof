"""Coordinate archive identity changes with assistance policy decisions."""

import hashlib
import re

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from inspinia.pages.study_help_models import HINT_ACTIONS
from inspinia.pages.study_help_models import StudyHelpEnrollment
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpRestriction
from inspinia.pages.study_help_pilot import PILOT_REVISION
from inspinia.pages.study_help_pilot import PILOT_STATEMENT
from inspinia.pages.study_help_pilot import draft_learner_audience
from inspinia.pages.study_help_pilot import learner_grant
from inspinia.pages.study_help_pilot import pilot_authorization
from inspinia.pages.study_help_pilot import pilot_lease
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role

DENY_MODES = ("restricted_assessment", "quarantine", "withdrawal")
MAX_STATEMENT_BYTES = 12_000
# PostgreSQL transaction lock shared by Study Help, archive identity changes, and policy writes.
LOCK_KEY = 816_357_293_021
UNSUPPORTED_SOURCE = re.compile(
    r"\[/?(?:asy|img)(?:\]|=)|!\[[^\]]*\]\s*[([]|<\s*(?:img|svg|figure|picture|iframe)\b"
    r"|\\(?:includegraphics|includesvg|input|include)\b|\\begin\s*\{(?:figure|tikzpicture|asy)"
    r"|\b(?:diagram|figure|picture|graph|image)\s+(?:below|above|shown|attached)\b"
    r"|\b(?:shown|indicated|illustrated)\s+in\s+(?:the\s+)?(?:diagram|figure|picture|graph|image)\b"
    r"|\b(?:attached|accompanying)\s+(?:file|diagram|figure|picture|graph|image)\b"
    r"|\b(?:see|refer to|using|in)\s+(?:the\s+)?(?:attached\s+)?(?:diagram|figure|picture|image)\b",
    re.IGNORECASE,
)


def lock_study_help():
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            msg = "Study Help requires a transaction."
            raise RuntimeError(msg)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])


def statement_revision(statement):
    return hashlib.sha256(statement.statement_latex.encode()).hexdigest()


def source_problem(statement):
    if not statement.is_active:
        return "inactive_statement"
    source = statement.statement_latex
    if not source.strip() or len(source.encode()) > MAX_STATEMENT_BYTES:
        return "unsupported_statement"
    if UNSUPPORTED_SOURCE.search(source):
        return "diagram_required"
    return ""


def hints_only_enabled():
    return settings.STUDY_HELP_HINTS_ONLY and not settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED


def generation_action_allowed(action):
    return not hints_only_enabled() or action in HINT_ACTIONS


def draft_pilot_statement(statement):
    return bool(
        statement.statement_uuid == PILOT_STATEMENT
        and statement_revision(statement) == PILOT_REVISION,
    )


def can_use_study_help(user, policy, *, allow_expired_pilot=False):
    if not (policy and user.is_active and user_can_access_app_features(user)):
        return False
    if draft_learner_audience(policy):
        return learner_grant() is not None
    if settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED:
        if not user_has_admin_role(user) or policy.audience != StudyHelpPolicy.Audience.COHORT:
            return False
        authorization = pilot_authorization() if allow_expired_pilot else pilot_lease()
        return (
            authorization is not None
            and authorization.actor_id == user.pk
            and StudyHelpEnrollment.objects.filter(user=user).exists()
        )
    return settings.STUDY_HELP_ENABLED and (
        policy.audience == StudyHelpPolicy.Audience.ALL or StudyHelpEnrollment.objects.filter(user=user).exists()
    )


def active_assistance_restrictions(user):
    now = timezone.now()
    return AssistancePolicy.objects.filter(
        Q(actor_id_scope=user.pk) | Q(actor_id_scope__isnull=True),
        mode__in=DENY_MODES,
        starts_at__lte=now,
        ends_at__gt=now,
    )


def assistance_restricted(user, problem_uuids, *, statement_uuid=None):
    scope = Q(problem_uuid__isnull=True) | Q(problem_uuid__in=problem_uuids)
    if statement_uuid is not None:
        scope |= Q(pk__in=StudyHelpRestriction.objects.filter(statement_uuid=statement_uuid).values("policy_id"))
    return active_assistance_restrictions(user).filter(scope).exists()


def bind_statement_restrictions(statement_uuid, problem_uuids):
    """Called under the shared lock before changing identity, including scheduled rules."""
    ids = AssistancePolicy.objects.filter(
        problem_uuid__in=problem_uuids,
        mode__in=DENY_MODES,
        ends_at__gt=timezone.now(),
    ).values_list("pk", flat=True)
    StudyHelpRestriction.objects.bulk_create(
        [StudyHelpRestriction(policy_id=pk, statement_uuid=statement_uuid) for pk in ids],
        ignore_conflicts=True,
    )
