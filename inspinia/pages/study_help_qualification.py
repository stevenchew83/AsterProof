"""Validate the exact text-only sample and the two-coach quality evidence."""

# ruff: noqa: EM101, PLR2004, TRY003

from collections import Counter
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import F
from django.db.models import Q
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help_access import DENY_MODES
from inspinia.pages.study_help_access import hints_only_enabled
from inspinia.pages.study_help_access import source_problem
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import HINT_ACTIONS
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpRestriction
from inspinia.solutions.evaluation_models import AssistancePolicy

DOMAINS = ("algebra", "geometry", "number_theory", "combinatorics")
PRIMARY = (*HINT_ACTIONS, StudyHelpAction.SOLUTION)
OUTCOMES = {"usable", "unusable", "abstained", "spoiler", "material_error"}


def qualification_scope():
    return "hints_only" if hints_only_enabled() else "full"


def validate_scope(packet):
    scope = qualification_scope()
    if packet.get("scope", "full") != scope:
        message = f"The packet must match the configured Study Help scope ({scope})."
        raise ValidationError(message)


def load_fixtures(rows, *, hint_pair=False):
    expected = 1 if hint_pair else 24
    if not isinstance(rows, list) or len(rows) != expected:
        noun = "fixture" if hint_pair else "fixtures"
        message = f"Provide exactly {expected} archive {noun}."
        raise ValidationError(message)
    hints_only = hints_only_enabled()
    keys = set()
    fixtures = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("Each fixture must be an object.")
        alternative = row.get("alternative", False if hints_only else None)
        if type(alternative) is not bool:
            raise ValidationError("The alternative flag must be a boolean.")
        if hints_only and alternative:
            raise ValidationError("Hints-only fixtures cannot include proofs.")
        key = UUID(row["statement_uuid"])
        statement = ContestProblemStatement.objects.filter(statement_uuid=key).first()
        if (
            key in keys
            or statement is None
            or source_problem(statement)
            or row["revision"] != statement_revision(statement)
            or row["domain"] not in DOMAINS
        ):
            raise ValidationError("Fixtures must be distinct, current, active text-only archive statements.")
        keys.add(key)
        fixtures.append((statement, row))
    _check_fixture_mix(fixtures, hint_pair=hint_pair)
    return fixtures


def _check_fixture_mix(fixtures, *, hint_pair):
    if hint_pair:
        if fixtures[0][1].get("alternative"):
            raise ValidationError("A hint pair cannot include an alternative proof.")
        return
    counts = Counter(row["domain"] for _, row in fixtures)
    if any(counts[domain] != 6 for domain in DOMAINS):
        raise ValidationError("Provide six fixtures per domain.")
    if hints_only_enabled():
        _check_fixture_restrictions(fixtures)
    elif sum(row["alternative"] for _, row in fixtures) != 8:
        raise ValidationError("Provide eight fixtures marked for alternatives.")


def _check_fixture_restrictions(fixtures):
    statement_ids = [statement.statement_uuid for statement, _ in fixtures]
    problem_ids = [statement.problem_uuid for statement, _ in fixtures]
    linked_policies = StudyHelpRestriction.objects.filter(statement_uuid__in=statement_ids).values("policy_id")
    if AssistancePolicy.objects.filter(
        Q(problem_uuid__isnull=True) | Q(problem_uuid__in=problem_ids) | Q(pk__in=linked_policies),
        mode__in=DENY_MODES,
        ends_at__gt=timezone.now(),
    ).filter(ends_at__gt=F("starts_at")).exists():
        raise ValidationError("Hints-only fixtures must have no active or scheduled assistance denial.")


def summarize_reviews(evidence, fixtures):
    primary = HINT_ACTIONS if hints_only_enabled() else PRIMARY
    actions_by_key = {
        row["statement_uuid"]: (*primary, StudyHelpAction.ALTERNATIVE) if row.get("alternative") else primary
        for _, row in fixtures
    }
    reviews = evidence["reviews"]
    if not isinstance(reviews, list) or len(reviews) != 2 or reviews[0]["reviewer_id"] == reviews[1]["reviewer_id"]:
        raise ValidationError("Two distinct reviewers are required.")
    usable = Counter()
    for review in reviews:
        if set(review["ratings"]) != set(actions_by_key):
            raise ValidationError("Each coach must rate every fixture.")
    for key, actions in actions_by_key.items():
        ratings = [review["ratings"][key] for review in reviews]
        if any(set(row) != set(actions) for row in ratings):
            raise ValidationError("Each coach must rate every requested action.")
        for action in actions:
            pair = [row[action] for row in ratings]
            if any(value not in OUTCOMES for value in pair):
                raise ValidationError("Unknown coach rating.")
            if any(value in {"spoiler", "material_error"} for value in pair):
                raise ValidationError("A reported spoiler or material mathematical error blocks qualification.")
            usable[action] += all(value == "usable" for value in pair)
    if any(usable[action] < 22 for action in primary) or (
        not hints_only_enabled() and usable[StudyHelpAction.ALTERNATIVE] < 7
    ):
        raise ValidationError("The sample did not meet the minimum usable result thresholds.")
    return dict(usable)
