import uuid

from django.conf import settings
from django.db import models

from inspinia.pages.analytics_field_parse import parse_imo_slot_guess_value
from inspinia.pages.analytics_field_parse import parse_pitfalls_value
from inspinia.pages.analytics_field_parse import parse_rationale_value
from inspinia.pages.contest_names import PROJECT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.contest_names import normalize_text_list
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import normalize_topic_tag


class ProblemSolveRecord(models.Model):
    """
    Stores one row from the Excel analytics sheet.

    Note: fields store the raw cell text for strings (including prefixes like
    "IMO slot guess:"), so we can parse/split them later without losing data.
    """

    problem_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    year = models.IntegerField()
    topic = models.CharField(max_length=32)
    mohs = models.IntegerField()

    contest = models.CharField(max_length=64)
    problem = models.CharField(max_length=64)

    # Second "CONTEST" column in the sample, e.g. "BMO SL 2020 P1".
    contest_year_problem = models.CharField(max_length=128, null=True, blank=True)

    confidence = models.TextField(null=True, blank=True)
    imo_slot_guess = models.TextField(null=True, blank=True)
    # Normalized candidate IMO slot numbers extracted from `imo_slot_guess`.
    # Examples:
    # - "IMO slot guess: P1/4" -> "4"
    # - "IMO slot guess: P1/4 - P2/5" -> "4,5"
    # - "IMO slot guess: -" -> NULL
    imo_slot_guess_value = models.TextField(null=True, blank=True)
    topic_tags = models.TextField(null=True, blank=True)
    rationale = models.TextField(null=True, blank=True)
    # Rationale text with prefixes removed (for example "Rationale:" / "Rationale (1-2 lines):").
    rationale_value = models.TextField(null=True, blank=True)
    # Pitfalls text with prefixes removed (e.g. strip "Common pitfalls:" prefix).
    pitfalls_value = models.TextField(null=True, blank=True)
    pitfalls = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "contest", "problem"]

    def __str__(self) -> str:
        return f"{self.year} {self.contest} {self.problem}"

    def save(self, *args, **kwargs) -> None:
        self.imo_slot_guess_value = parse_imo_slot_guess_value(self.imo_slot_guess)
        self.rationale_value = parse_rationale_value(self.rationale)
        self.pitfalls_value = parse_pitfalls_value(self.pitfalls)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "imo_slot_guess_value",
                "rationale_value",
                "pitfalls_value",
            }

        super().save(*args, **kwargs)


class ProblemTopicTechnique(models.Model):
    """
    One parsed technique tag for a problem row, with associated domain label(s).

    `domains` is a JSON list of strings (SQLite-friendly; on Postgres you may later
    migrate to ARRAY if desired).
    """

    record = models.ForeignKey(
        ProblemSolveRecord,
        on_delete=models.CASCADE,
        related_name="topic_techniques",
    )
    technique = models.CharField(max_length=512)
    domains = models.JSONField(blank=True, default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["record", "technique"],
                name="pages_problemtopictechnique_unique_record_technique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.record.pk}: {self.technique}"

    def save(self, *args, **kwargs) -> None:
        normalized_technique = normalize_topic_tag(self.technique)
        normalized_domains = domains_dedup_preserve_order(self.domains or [])

        update_fields = kwargs.get("update_fields")
        normalized_update_fields = set(update_fields) if update_fields is not None else None

        if self.technique != normalized_technique:
            self.technique = normalized_technique
            if normalized_update_fields is not None:
                normalized_update_fields.add("technique")

        if list(self.domains or []) != normalized_domains:
            self.domains = normalized_domains
            if normalized_update_fields is not None:
                normalized_update_fields.add("domains")

        if normalized_update_fields is not None:
            kwargs["update_fields"] = normalized_update_fields

        super().save(*args, **kwargs)


class ContestProblemStatement(models.Model):
    statement_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    problem_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    linked_problem = models.ForeignKey(
        ProblemSolveRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="statement_entries",
    )
    contest_year = models.IntegerField()
    contest_name = models.CharField(max_length=128)
    contest_year_problem = models.CharField(max_length=160, db_index=True)
    day_label = models.CharField(max_length=128, blank=True)
    problem_number = models.PositiveIntegerField()
    problem_code = models.CharField(max_length=16)
    statement_latex = models.TextField()
    is_active = models.BooleanField(default=True)
    # Analytics / workbook metadata (canonical on the statement row).
    topic = models.CharField(max_length=32, null=True, blank=True)
    mohs = models.IntegerField(null=True, blank=True)
    source_contest = models.CharField(max_length=64, null=True, blank=True)
    source_problem = models.CharField(max_length=64, null=True, blank=True)
    workbook_contest_year_problem = models.CharField(max_length=128, null=True, blank=True)
    confidence = models.TextField(null=True, blank=True)
    imo_slot_guess = models.TextField(null=True, blank=True)
    imo_slot_guess_value = models.TextField(null=True, blank=True)
    topic_tags = models.TextField(null=True, blank=True)
    rationale = models.TextField(null=True, blank=True)
    rationale_value = models.TextField(null=True, blank=True)
    pitfalls = models.TextField(null=True, blank=True)
    pitfalls_value = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-contest_year", "contest_name", "day_label", "problem_number", "problem_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["contest_year", "contest_name", "day_label", "problem_code"],
                name="pages_contestproblemstatement_unique_contest_day_problem_code",
            ),
        ]

    def __str__(self) -> str:
        return self.contest_year_problem

    def save(self, *args, **kwargs) -> None:
        if self.linked_problem_id is not None:
            linked_problem = self.linked_problem
            if linked_problem is not None:
                self.problem_uuid = linked_problem.problem_uuid

        self.problem_code = (self.problem_code or "").strip().upper() or f"P{self.problem_number}"
        self.contest_year_problem = f"{self.contest_name} {self.contest_year} {self.problem_code}"
        self.imo_slot_guess_value = parse_imo_slot_guess_value(self.imo_slot_guess)
        self.rationale_value = parse_rationale_value(self.rationale)
        self.pitfalls_value = parse_pitfalls_value(self.pitfalls)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "contest_year_problem",
                "problem_uuid",
                "problem_code",
                "imo_slot_guess_value",
                "rationale_value",
                "pitfalls_value",
            }

        super().save(*args, **kwargs)


class StatementTopicTechnique(models.Model):
    """Parsed technique tag for a statement row (parallel to ProblemTopicTechnique)."""

    statement = models.ForeignKey(
        ContestProblemStatement,
        on_delete=models.CASCADE,
        related_name="statement_topic_techniques",
    )
    technique = models.CharField(max_length=512)
    domains = models.JSONField(blank=True, default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "technique"],
                name="pages_statementtopictechnique_unique_statement_technique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.statement_id}: {self.technique}"

    def save(self, *args, **kwargs) -> None:
        normalized_technique = normalize_topic_tag(self.technique)
        normalized_domains = domains_dedup_preserve_order(self.domains or [])

        update_fields = kwargs.get("update_fields")
        normalized_update_fields = set(update_fields) if update_fields is not None else None

        if self.technique != normalized_technique:
            self.technique = normalized_technique
            if normalized_update_fields is not None:
                normalized_update_fields.add("technique")

        if list(self.domains or []) != normalized_domains:
            self.domains = normalized_domains
            if normalized_update_fields is not None:
                normalized_update_fields.add("domains")

        if normalized_update_fields is not None:
            kwargs["update_fields"] = normalized_update_fields

        super().save(*args, **kwargs)


class ContestMetadata(models.Model):
    contest_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    contest = models.CharField(max_length=PROJECT_CONTEST_NAME_MAX_LENGTH)
    full_name = models.CharField(max_length=255, blank=True)
    countries = models.JSONField(blank=True, default=list)
    description_markdown = models.TextField(blank=True)
    tags = models.JSONField(blank=True, default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["contest"]
        constraints = [
            models.UniqueConstraint(
                fields=["contest"],
                name="pages_contestmetadata_unique_contest",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name or self.contest

    def save(self, *args, **kwargs) -> None:
        update_fields = kwargs.get("update_fields")
        normalized_update_fields = set(update_fields) if update_fields is not None else None

        normalized_values = {
            "contest": normalize_contest_name(self.contest),
            "full_name": normalize_contest_name(self.full_name),
            "description_markdown": (self.description_markdown or "").strip(),
            "countries": normalize_text_list(self.countries or []),
            "tags": normalize_text_list(self.tags or []),
        }

        for field_name, normalized_value in normalized_values.items():
            if getattr(self, field_name) == normalized_value:
                continue
            setattr(self, field_name, normalized_value)
            if normalized_update_fields is not None:
                normalized_update_fields.add(field_name)

        if normalized_update_fields is not None:
            kwargs["update_fields"] = normalized_update_fields

        super().save(*args, **kwargs)


class UserProblemCompletion(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_completions",
    )
    statement = models.ForeignKey(
        ContestProblemStatement,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_completions",
    )
    problem = models.ForeignKey(
        ProblemSolveRecord,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_completions",
    )
    completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-completion_date", "user_id", "problem_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "statement"],
                name="pages_userproblemcompletion_unique_user_statement",
            ),
            models.UniqueConstraint(
                fields=["user", "problem"],
                name="pages_userproblemcompletion_unique_user_problem",
            ),
            models.CheckConstraint(
                condition=models.Q(statement__isnull=False) | models.Q(problem__isnull=False),
                name="pages_userproblemcompletion_requires_statement_or_problem",
            ),
        ]
        indexes = [
            models.Index(fields=["-updated_at", "-id"], name="pages_upc_updated_id_idx"),
        ]

    def __str__(self) -> str:
        if self.statement is not None:
            label = self.statement.contest_year_problem
        elif self.problem is not None:
            label = f"{self.problem.contest} {self.problem.year} {self.problem.problem}"
        else:
            label = "unknown problem"
        return (
            f"{self.user.email} completed {label} on "
            f"{self.completion_date.isoformat() if self.completion_date else 'unknown date'}"
        )
