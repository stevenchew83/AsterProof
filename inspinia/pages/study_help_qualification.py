"""Validate the exact text-only sample and the two-coach quality evidence."""

# ruff: noqa: EM101, PLR2004, TRY003

from collections import Counter
from uuid import UUID

from django.core.exceptions import ValidationError

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help_access import source_problem
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpAction

DOMAINS = ("algebra", "geometry", "number_theory", "combinatorics")
PRIMARY = (StudyHelpAction.HINT, StudyHelpAction.STRONGER_HINT, StudyHelpAction.SOLUTION)
OUTCOMES = {"usable", "unusable", "abstained", "spoiler", "material_error"}


def load_fixtures(rows, *, hint_pair=False):
    expected = 1 if hint_pair else 24
    if not isinstance(rows, list) or len(rows) != expected:
        noun = "fixture" if hint_pair else "fixtures"
        message = f"Provide exactly {expected} archive {noun}."
        raise ValidationError(message)
    keys = set()
    fixtures = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("alternative")) is not bool:
            raise ValidationError("Each fixture needs an explicit alternative flag.")
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
    if hint_pair:
        if rows[0]["alternative"]:
            raise ValidationError("A hint pair cannot include an alternative proof.")
        return fixtures
    counts = Counter(row["domain"] for _, row in fixtures)
    if any(counts[domain] != 6 for domain in DOMAINS) or sum(row["alternative"] for _, row in fixtures) != 8:
        raise ValidationError("Provide six fixtures per domain and eight marked for alternatives.")
    return fixtures


def summarize_reviews(evidence, fixtures):
    actions_by_key = {
        row["statement_uuid"]: (*PRIMARY, StudyHelpAction.ALTERNATIVE) if row["alternative"] else PRIMARY
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
                raise ValidationError("A reported spoiler or material proof error blocks qualification.")
            usable[action] += all(value == "usable" for value in pair)
    if any(usable[action] < 22 for action in PRIMARY) or usable[StudyHelpAction.ALTERNATIVE] < 7:
        raise ValidationError("The sample did not meet the minimum usable result thresholds.")
    return dict(usable)
