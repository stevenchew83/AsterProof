"""Private archive assistance, with provider accounting independent of accounts."""

# ruff: noqa: DJ008

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class StudyHelpAction(models.TextChoices):
    HINT = "hint", "Get a hint"
    STRONGER_HINT = "stronger_hint", "Stronger hint"
    SOLUTION = "solution", "Full solution"
    ALTERNATIVE = "alternative", "Try a different approach"


HINT_ACTIONS = (StudyHelpAction.HINT, StudyHelpAction.STRONGER_HINT)
SOLUTION_ACTIONS = (StudyHelpAction.SOLUTION, StudyHelpAction.ALTERNATIVE)


class StudyHelpPrompt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hint = models.TextField()
    solution = models.TextField()
    editor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class StudyHelpQualification(models.Model):
    prompt = models.ForeignKey(StudyHelpPrompt, on_delete=models.PROTECT)
    profile_digest = models.CharField(max_length=64)
    evidence = models.JSONField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["prompt", "profile_digest"], name="study_help_qualification_unique"),
        ]


class StudyHelpPolicy(models.Model):
    class Audience(models.TextChoices):
        COHORT = "cohort", "Enrolled accounts"
        ALL = "all", "All eligible accounts"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    generation_enabled = models.BooleanField(default=False)
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.COHORT)
    active_prompt = models.ForeignKey(StudyHelpPrompt, null=True, on_delete=models.PROTECT)
    model = models.CharField(max_length=100, blank=True)
    input_price = models.PositiveBigIntegerField(default=0, help_text="USD micros per million tokens.")
    output_price = models.PositiveBigIntegerField(default=0, help_text="USD micros per million tokens.")
    pricing_verified_at = models.DateTimeField(null=True)
    worker_checked_at = models.DateTimeField(null=True)
    request_cap = models.PositiveBigIntegerField(default=0, help_text="USD micros.")
    day_cap = models.PositiveBigIntegerField(default=0, help_text="USD micros.")
    month_cap = models.PositiveBigIntegerField(default=0, help_text="USD micros.")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="study_help_one_policy")]


class StudyHelpEnrollment(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class StudyHelpRestriction(models.Model):
    """A scoped rule follows the statement after a change of canonical UUID."""

    policy = models.ForeignKey("solutions.AssistancePolicy", on_delete=models.CASCADE)
    statement_uuid = models.UUIDField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["policy", "statement_uuid"], name="study_help_restriction_unique"),
        ]


class StudyHelpSpend(models.Model):
    """A receipt contains no user, statement, response body, or input text."""

    class State(models.TextChoices):
        RESERVED = "reserved"
        DISPATCHED = "dispatched"
        UNKNOWN = "unknown"
        SETTLED = "settled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.RESERVED)
    reserved_micros = models.PositiveBigIntegerField()
    input_price = models.PositiveBigIntegerField()
    output_price = models.PositiveBigIntegerField()
    actual_micros = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True)
    settled_at = models.DateTimeField(null=True)
    provider_request_id = models.CharField(max_length=160, blank=True)
    provider_response_id = models.CharField(max_length=160, blank=True)
    input_tokens = models.PositiveIntegerField(null=True)
    output_tokens = models.PositiveIntegerField(null=True)
    reconciliation_ref = models.CharField(max_length=160, blank=True)
    evaluation_key = models.CharField(max_length=64, null=True, unique=True)
    evaluation_batch = models.CharField(max_length=64, blank=True, db_index=True)
    evaluation_manifest = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [models.Index(fields=["state", "dispatched_at"], name="study_help_spend_window_idx")]


class StudyHelpRequest(models.Model):
    class State(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        READY = "ready"
        FAILED = "failed"
        UNKNOWN = "unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    request_key = models.UUIDField()
    interaction_key = models.UUIDField()
    statement_uuid = models.UUIDField()
    problem_uuid = models.UUIDField()
    revision = models.CharField(max_length=64)
    action = models.CharField(max_length=16, choices=StudyHelpAction.choices)
    slot = models.PositiveSmallIntegerField()
    prior_id = models.UUIDField(null=True)
    hint_day = models.DateField(null=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    prompt = models.ForeignKey(StudyHelpPrompt, on_delete=models.PROTECT)
    model = models.CharField(max_length=100)
    profile_digest = models.CharField(max_length=64)
    statement_text = models.TextField(blank=True)
    body = models.TextField(blank=True)
    method = models.CharField(max_length=100, blank=True)
    failure_code = models.CharField(max_length=32, blank=True)
    funding_source = models.CharField(max_length=16, default="asterproof")
    spend = models.OneToOneField(StudyHelpSpend, on_delete=models.PROTECT, related_name="generation")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    revealed_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "statement_uuid", "state"], name="study_help_owner_statement_idx"),
            models.Index(fields=["state", "created_at"], name="study_help_queue_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="study_help_request_key_unique"),
            models.UniqueConstraint(fields=["owner", "interaction_key"], name="study_help_interaction_unique"),
            models.UniqueConstraint(
                fields=["owner"],
                condition=Q(state__in=["queued", "running"]),
                name="study_help_one_inflight_per_owner",
            ),
            models.UniqueConstraint(
                fields=["owner", "statement_uuid", "slot"],
                condition=Q(action__in=SOLUTION_ACTIONS, state__in=["queued", "running", "ready"]),
                name="study_help_unique_solution_slot",
            ),
            models.UniqueConstraint(
                fields=["owner", "statement_uuid", "revision", "slot"],
                condition=Q(action__in=HINT_ACTIONS, state__in=["queued", "running", "ready"]),
                name="study_help_unique_hint_slot",
            ),
        ]


class StudyHelpEvent(models.Model):
    class Kind(models.TextChoices):
        CLICK = "click"
        CONFIRMED = "confirmed"
        ACCEPTED = "accepted"
        COMPLETED = "completed"
        FAILED = "failed"
        FIRST_REVEAL = "first_reveal", "First reveal"
        VIEW_CLICK = "view_click", "View saved response"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    statement_uuid = models.UUIDField()
    interaction_key = models.UUIDField()
    action = models.CharField(max_length=16, choices=StudyHelpAction.choices)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    generation = models.ForeignKey(StudyHelpRequest, null=True, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at", "action", "kind"], name="study_help_event_report_idx"),
            models.Index(fields=["owner", "created_at"], name="study_help_event_rate_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "statement_uuid", "interaction_key", "action", "kind"],
                name="study_help_event_unique",
            ),
        ]


class StudyHelpAdminEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=24)
    prompt = models.ForeignKey(StudyHelpPrompt, null=True, on_delete=models.PROTECT)
    reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
