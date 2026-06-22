import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from inspinia.pages.analytics_field_parse import parse_core_ideas_value
from inspinia.pages.analytics_field_parse import parse_imo_slot_guess_value
from inspinia.pages.analytics_field_parse import parse_pitfalls_value
from inspinia.pages.analytics_field_parse import parse_rationale_value
from inspinia.pages.contest_names import PROJECT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.contest_names import normalize_text_list
from inspinia.pages.topic_tags_parse import clean_token
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import normalize_topic_tag

DIFFICULTY_RATING_MIN = 0
DIFFICULTY_RATING_MAX = 60
TOPIC_TAG_LAYER_FIELDS = (
    "object_tags",
    "technique_tags",
    "lemma_theorem_tags",
    "proof_roles",
)


def normalize_topic_tag_list(values) -> list[str]:
    if values is None:
        raw_values = []
    elif isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = values

    normalized_values: list[str] = []
    seen_values: set[str] = set()
    for raw_value in raw_values or []:
        normalized_value = normalize_topic_tag(raw_value)
        if not normalized_value:
            continue
        seen_key = normalized_value.casefold()
        if seen_key in seen_values:
            continue
        seen_values.add(seen_key)
        normalized_values.append(normalized_value)
    return normalized_values


def _normalize_topic_technique_model(instance: models.Model, save_kwargs: dict) -> None:
    normalized_values = {
        "technique": normalize_topic_tag(instance.technique),
        "domains": domains_dedup_preserve_order(instance.domains or []),
        "main_topic": normalize_topic_tag(instance.main_topic),
        "canonical_subtopic": clean_token(instance.canonical_subtopic),
        "raw_tag": clean_token(instance.raw_tag),
        "normalization_status": clean_token(instance.normalization_status).casefold(),
        "normalization_confidence": clean_token(instance.normalization_confidence).casefold(),
    }
    for field_name in TOPIC_TAG_LAYER_FIELDS:
        normalized_values[field_name] = normalize_topic_tag_list(getattr(instance, field_name, []))

    update_fields = save_kwargs.get("update_fields")
    normalized_update_fields = set(update_fields) if update_fields is not None else None

    for field_name, normalized_value in normalized_values.items():
        if field_name == "domains":
            current_value = list(instance.domains or [])
        elif field_name in TOPIC_TAG_LAYER_FIELDS:
            current_value = getattr(instance, field_name, [])
        else:
            current_value = getattr(instance, field_name)
        if current_value == normalized_value:
            continue
        setattr(instance, field_name, normalized_value)
        if normalized_update_fields is not None:
            normalized_update_fields.add(field_name)

    if normalized_update_fields is not None:
        save_kwargs["update_fields"] = normalized_update_fields


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
    core_ideas = models.TextField(null=True, blank=True)
    # Core ideas text with a leading "Core ideas:" prefix removed.
    core_ideas_value = models.TextField(null=True, blank=True)
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
        self.core_ideas_value = parse_core_ideas_value(self.core_ideas)
        self.rationale_value = parse_rationale_value(self.rationale)
        self.pitfalls_value = parse_pitfalls_value(self.pitfalls)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "imo_slot_guess_value",
                "core_ideas_value",
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
    main_topic = models.CharField(blank=True, max_length=16)
    canonical_subtopic = models.CharField(blank=True, max_length=160)
    raw_tag = models.CharField(blank=True, max_length=512)
    normalization_status = models.CharField(blank=True, max_length=24)
    normalization_confidence = models.CharField(blank=True, max_length=16)
    object_tags = models.JSONField(blank=True, default=list)
    technique_tags = models.JSONField(blank=True, default=list)
    lemma_theorem_tags = models.JSONField(blank=True, default=list)
    proof_roles = models.JSONField(blank=True, default=list)

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
        _normalize_topic_technique_model(self, kwargs)
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
    core_ideas = models.TextField(null=True, blank=True)
    core_ideas_value = models.TextField(null=True, blank=True)
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
        self.core_ideas_value = parse_core_ideas_value(self.core_ideas)
        self.rationale_value = parse_rationale_value(self.rationale)
        self.pitfalls_value = parse_pitfalls_value(self.pitfalls)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "contest_year_problem",
                "problem_uuid",
                "problem_code",
                "imo_slot_guess_value",
                "core_ideas_value",
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
    main_topic = models.CharField(blank=True, max_length=16)
    canonical_subtopic = models.CharField(blank=True, max_length=160)
    raw_tag = models.CharField(blank=True, max_length=512)
    normalization_status = models.CharField(blank=True, max_length=24)
    normalization_confidence = models.CharField(blank=True, max_length=16)
    object_tags = models.JSONField(blank=True, default=list)
    technique_tags = models.JSONField(blank=True, default=list)
    lemma_theorem_tags = models.JSONField(blank=True, default=list)
    proof_roles = models.JSONField(blank=True, default=list)

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
        _normalize_topic_technique_model(self, kwargs)
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


class PageViewEvent(models.Model):
    class ViewType(models.TextChoices):
        PROBLEM_STATEMENT = "problem_statement", "Problem statement"
        SOLUTION = "solution", "Solution"
        LIST = "list", "List"
        CONTEST = "contest", "Contest"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="page_view_events",
    )
    view_type = models.CharField(max_length=32, choices=ViewType.choices, db_index=True)
    object_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    label = models.CharField(max_length=160, blank=True)
    contest_name = models.CharField(max_length=128, blank=True)
    contest_year = models.IntegerField(null=True, blank=True)
    path = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["view_type", "-created_at"], name="pg_pv_type_created_idx"),
            models.Index(fields=["object_uuid", "view_type"], name="pg_pv_object_type_idx"),
            models.Index(fields=["contest_name", "-created_at"], name="pg_pv_contest_created_idx"),
        ]

    def __str__(self) -> str:
        label = self.label or self.path or self.object_uuid or "page"
        return f"{self.get_view_type_display()}: {label}"


class UserProblemCompletion(models.Model):
    class Status(models.TextChoices):
        UNATTEMPTED = "unattempted", "Unattempted"
        ATTEMPTED = "attempted", "Attempted"
        SOLVED = "solved", "Solved"
        CHECKED = "checked", "Checked"
        WRITTEN = "written", "Written"
        PUBLISHED = "published", "Published"

    class MainObstacle(models.TextChoices):
        IDEA = "idea", "Idea"
        COMPUTATION = "computation", "Computation"
        PROOF_RIGOR = "proof_rigor", "Proof rigor"
        DIAGRAM = "diagram", "Diagram"
        CASEWORK = "casework", "Casework"

    class Confidence(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

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
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SOLVED, db_index=True)
    time_spent_minutes = models.PositiveIntegerField(null=True, blank=True)
    first_idea_found = models.BooleanField(null=True, blank=True)
    proof_completed = models.BooleanField(null=True, blank=True)
    main_obstacle = models.CharField(max_length=16, choices=MainObstacle.choices, blank=True)
    key_technique = models.CharField(max_length=160, blank=True)
    post_mortem = models.TextField(blank=True)
    reattempt_date = models.DateField(null=True, blank=True, db_index=True)
    confidence = models.CharField(max_length=8, choices=Confidence.choices, blank=True)
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


class TechniqueProgressFact(models.Model):
    class Layer(models.TextChoices):
        MAIN_TOPIC = "main_topic", "Main topic"
        SUBTOPIC = "subtopic", "Subtopic"
        TECHNIQUE = "technique", "Technique"
        OBJECT = "object", "Object"
        METHOD = "method", "Method"
        LEMMA = "lemma", "Lemma/Theorem"
        PROOF_ROLE = "proof_role", "Proof role"

    statement = models.ForeignKey(
        ContestProblemStatement,
        on_delete=models.CASCADE,
        related_name="technique_progress_facts",
    )
    linked_problem = models.ForeignKey(
        ProblemSolveRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="technique_progress_facts",
    )
    layer = models.CharField(max_length=16, choices=Layer.choices, db_index=True)
    label = models.CharField(max_length=512)
    label_key = models.CharField(max_length=512)
    canonical_subtopic = models.CharField(blank=True, max_length=160)
    canonical_subtopic_labels = models.JSONField(blank=True, default=list)
    main_topic = models.CharField(blank=True, max_length=32)
    main_topic_labels = models.JSONField(blank=True, default=list)
    search_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["layer", "label", "statement_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "layer", "label_key"],
                name="pages_techprogressfact_unique_statement_layer_label",
            ),
        ]
        indexes = [
            models.Index(fields=["layer", "label_key"], name="pages_tpf_layer_label_idx"),
            models.Index(fields=["linked_problem", "layer"], name="pages_tpf_problem_layer_idx"),
            models.Index(fields=["layer", "main_topic"], name="pages_tpf_layer_main_idx"),
            models.Index(fields=["layer", "canonical_subtopic"], name="pages_tpf_layer_canon_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.statement_id}: {self.layer} / {self.label}"

    def save(self, *args, **kwargs) -> None:
        self.label = (self.label or "").strip()
        self.label_key = (self.label_key or self.label).strip().casefold()

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"label", "label_key"}

        super().save(*args, **kwargs)


class TechniqueProgressCatalogState(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    needs_rebuild = models.BooleanField(default=True)
    fact_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Technique progress catalog state"
        verbose_name_plural = "Technique progress catalog state"

    def __str__(self) -> str:
        status = "needs rebuild" if self.needs_rebuild else "current"
        return f"Technique progress catalog: {status}"

    def save(self, *args, **kwargs) -> None:
        self.singleton_key = 1
        super().save(*args, **kwargs)


class TechniqueBenchmarkImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEWED = "previewed", "Previewed"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"
        RESTORED = "restored", "Restored"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="technique_benchmark_import_batches",
    )
    status = models.CharField(max_length=32, choices=Status.choices)
    source = models.CharField(max_length=64, default="chatgpt_copy_paste")
    prompt_text = models.TextField(blank=True)
    pasted_response = models.TextField(blank=True)
    rows_total = models.PositiveIntegerField(default=0)
    rows_valid = models.PositiveIntegerField(default=0)
    rows_invalid = models.PositiveIntegerField(default=0)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_unchanged = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    preview_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Technique benchmark import {self.pk or 'unsaved'} ({self.status})"


class TechniqueBenchmark(models.Model):
    class Kind(models.TextChoices):
        CANONICAL_SUBTOPIC = "canonical_subtopic", "Canonical subtopic"
        TECHNIQUE = "technique", "Technique"
        OBJECT = "object", "Object"
        METHOD = "method", "Method"
        LEMMA = "lemma", "Lemma/Theorem"
        PROOF_ROLE = "proof_role", "Proof role"
        PARENT_FAMILY = "parent_family", "Parent family"

    TRAINING_TYPES = {
        "Drill",
        "Deep block",
        "Mixed mock",
        "Review",
        "Postpone",
    }
    TARGET_LEVELS = {
        "Foundation",
        "JBMO",
        "National",
        "IMO/TST",
        "Specialist",
    }

    kind = models.CharField(max_length=32, choices=Kind.choices)
    label = models.CharField(max_length=255)
    label_key = models.CharField(max_length=255)
    normalized_label = models.CharField(max_length=255, blank=True)
    parent_family = models.CharField(max_length=255, blank=True)
    primary_area = models.CharField(max_length=64, blank=True)
    area_labels = models.JSONField(default=list, blank=True)

    syllabus_core = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    contest_frequency = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    transfer_value = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    prerequisite_value = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    concept_load = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    recognition_burden = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    execution_load = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    proof_fragility = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    cross_topic_dependency = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    difficulty_score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    importance_score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    typical_mohs_min = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(60)],
    )
    typical_mohs_max = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(60)],
    )
    typical_mohs_center = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    jbmo_weight = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    national_weight = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    imo_tst_weight = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))

    training_type = models.CharField(max_length=64, blank=True)
    target_level = models.CharField(max_length=64, blank=True)
    benchmark_confidence = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    rationale = models.TextField(blank=True)
    pitfalls = models.TextField(blank=True)
    recommended_sequence = models.TextField(blank=True)
    source_version = models.CharField(max_length=64, blank=True)
    imported_from_batch = models.ForeignKey(
        TechniqueBenchmarkImportBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="benchmarks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "label_key"],
                name="uniq_technique_benchmark_kind_label_key",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "label_key"], name="pages_tb_kind_label_idx"),
            models.Index(fields=["parent_family"], name="pages_tb_parent_family_idx"),
            models.Index(fields=["primary_area"], name="pages_tb_primary_area_idx"),
            models.Index(fields=["importance_score"], name="pages_tb_importance_idx"),
            models.Index(fields=["difficulty_score"], name="pages_tb_difficulty_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.label}"

    def save(self, *args, **kwargs) -> None:
        from inspinia.pages.technique_benchmarking.keys import normalize_benchmark_key
        from inspinia.pages.technique_benchmarking.scoring import calculate_static_difficulty_score
        from inspinia.pages.technique_benchmarking.scoring import calculate_static_importance_score

        self.label = (self.label or "").strip()
        self.label_key = normalize_benchmark_key(self.label_key or self.label)
        if not self.normalized_label:
            self.normalized_label = self.label
        self.importance_score = calculate_static_importance_score(self)
        self.difficulty_score = calculate_static_difficulty_score(self)
        if self.typical_mohs_min is not None and self.typical_mohs_max is not None:
            self.typical_mohs_center = Decimal(self.typical_mohs_min + self.typical_mohs_max) / Decimal("2")
        else:
            self.typical_mohs_center = None

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "label",
                "label_key",
                "normalized_label",
                "importance_score",
                "difficulty_score",
                "typical_mohs_center",
            }

        super().save(*args, **kwargs)


class TechniqueBenchmarkAlias(models.Model):
    kind = models.CharField(max_length=32, choices=TechniqueBenchmark.Kind.choices)
    alias_label = models.CharField(max_length=255)
    alias_key = models.CharField(max_length=255)
    benchmark = models.ForeignKey(
        TechniqueBenchmark,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "alias_label"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "alias_key"],
                name="uniq_technique_benchmark_alias_kind_key",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "alias_key"], name="pages_tba_kind_key_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.alias_label} -> {self.benchmark}"

    def save(self, *args, **kwargs) -> None:
        from inspinia.pages.technique_benchmarking.keys import normalize_benchmark_key

        self.alias_label = (self.alias_label or "").strip()
        self.alias_key = normalize_benchmark_key(self.alias_key or self.alias_label)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"alias_label", "alias_key"}

        super().save(*args, **kwargs)


class UserProblemDifficultyRating(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_difficulty_ratings",
    )
    statement = models.ForeignKey(
        ContestProblemStatement,
        on_delete=models.CASCADE,
        related_name="difficulty_ratings",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(DIFFICULTY_RATING_MIN),
            MaxValueValidator(DIFFICULTY_RATING_MAX),
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "user_id", "statement_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "statement"],
                name="pages_userproblemdifficultyrating_unique_user_statement",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=DIFFICULTY_RATING_MIN, rating__lte=DIFFICULTY_RATING_MAX),
                name="pages_userproblemdifficultyrating_rating_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} rated {self.statement.contest_year_problem} as {self.rating}"
