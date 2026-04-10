import re

from django.db import models
from django.db.models import Q
from django.db.models import TextChoices
from django.utils import timezone


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_name(value: str) -> str:
    return normalize_whitespace(value).casefold()


def canonicalize_choice_token(value: str, aliases: dict[str, str]) -> str:
    token = normalize_whitespace(value).lower()
    return aliases.get(token, token)


ASSESSMENT_CATEGORY_ALIASES = {
    "exam": "test",
    "quiz": "test",
    "selection": "qualifier",
}

ASSESSMENT_RESULT_TYPE_ALIASES = {
    "percent": "score",
    "rank": "status",
}

RANKING_FORMULA_MISSING_SCORE_POLICY_ALIASES = {
    "skip": "skip_and_rescale",
    "require_all": "zero",
}

RANKING_FORMULA_ITEM_NORMALIZATION_METHOD_ALIASES = {
    "percent": "percent_of_max",
    "z_score": "zscore",
    "custom": "fixed_scale",
}


class School(models.Model):
    class SchoolType(TextChoices):
        DAY = "day", "Day School"
        BOARDING = "boarding", "Boarding School"
        INTERNATIONAL = "international", "International School"
        HOMESCHOOL = "homeschool", "Homeschool"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255, db_index=True)
    normalized_name = models.CharField(max_length=255, unique=True, db_index=True)
    short_name = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=64, blank=True, db_index=True)
    school_type = models.CharField(max_length=32, choices=SchoolType.choices, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.short_name or self.name

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_whitespace(self.name)
        self.normalized_name = normalize_name(self.name)
        self.short_name = normalize_whitespace(self.short_name)
        self.state = normalize_whitespace(self.state)
        self.school_type = (self.school_type or "").strip()

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "name",
                "normalized_name",
                "short_name",
                "state",
                "school_type",
            }

        super().save(*args, **kwargs)


class Student(models.Model):
    class Gender(TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        NON_BINARY = "non_binary", "Non-binary"
        OTHER = "other", "Other"
        PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"

    full_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    school = models.ForeignKey(
        School,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="students",
    )
    state = models.CharField(max_length=64, blank=True, db_index=True)
    masked_nric = models.CharField(max_length=32, blank=True)
    full_nric = models.CharField(max_length=32, blank=True, db_index=True)
    external_code = models.CharField(max_length=64, blank=True)
    legacy_code = models.CharField(max_length=64, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_code"],
                condition=~Q(external_code=""),
                name="rankings_student_unique_non_empty_external_code",
            ),
        ]
        indexes = [
            models.Index(fields=["normalized_name", "birth_year"], name="rank_stu_name_birth_idx"),
            models.Index(fields=["school", "normalized_name"], name="rank_stu_school_name_idx"),
        ]

    def __str__(self) -> str:
        return self.full_name

    def save(self, *args, **kwargs) -> None:
        self.full_name = normalize_whitespace(self.full_name)
        self.normalized_name = normalize_name(self.full_name)
        self.gender = (self.gender or "").strip()
        self.state = normalize_whitespace(self.state)
        self.masked_nric = normalize_whitespace(self.masked_nric)
        self.full_nric = normalize_whitespace(self.full_nric)
        self.external_code = normalize_whitespace(self.external_code).upper()
        self.legacy_code = normalize_whitespace(self.legacy_code)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "full_name",
                "normalized_name",
                "gender",
                "state",
                "masked_nric",
                "full_nric",
                "external_code",
                "legacy_code",
            }

        super().save(*args, **kwargs)


class Assessment(models.Model):
    class Category(TextChoices):
        CONTEST = "contest", "Contest"
        TEST = "test", "Test"
        QUALIFIER = "qualifier", "Qualifier"
        MOCK = "mock", "Mock"
        MONTHLY = "monthly", "Monthly"
        ENTRANCE = "entrance", "Entrance"
        OTHER = "other", "Other"

    class ResultType(TextChoices):
        SCORE = "score", "Score"
        BAND = "band", "Band"
        MEDAL = "medal", "Medal"
        STATUS = "status", "Status"
        TEXT = "text", "Text"
        MIXED = "mixed", "Mixed"

    code = models.CharField(max_length=32)
    display_name = models.CharField(max_length=255)
    season_year = models.PositiveSmallIntegerField(db_index=True)
    assessment_date = models.DateField(null=True, blank=True, db_index=True)
    category = models.CharField(max_length=32, choices=Category.choices)
    division_scope = models.CharField(max_length=32, blank=True, db_index=True)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default="100.00")
    default_weight = models.DecimalField(max_digits=8, decimal_places=4, default="1.0000")
    result_type = models.CharField(max_length=32, choices=ResultType.choices, default=ResultType.SCORE)
    is_active = models.BooleanField(default=True, db_index=True)
    is_ranked_by_default = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["season_year", "sort_order", "code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "season_year"],
                name="rankings_assessment_unique_code_season_year",
            ),
        ]
        indexes = [
            models.Index(fields=["season_year", "assessment_date"], name="rank_assess_year_date_idx"),
            models.Index(fields=["season_year", "division_scope"], name="rank_assess_year_div_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.season_year})"

    def save(self, *args, **kwargs) -> None:
        self.code = normalize_whitespace(self.code).upper()
        self.display_name = normalize_whitespace(self.display_name)
        self.category = canonicalize_choice_token(
            self.category,
            ASSESSMENT_CATEGORY_ALIASES,
        )
        self.division_scope = (self.division_scope or "").strip()
        self.result_type = canonicalize_choice_token(
            self.result_type,
            ASSESSMENT_RESULT_TYPE_ALIASES,
        )

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "code",
                "display_name",
                "category",
                "division_scope",
                "result_type",
            }

        super().save(*args, **kwargs)


class RankingFormula(models.Model):
    class Purpose(TextChoices):
        OVERALL = "overall", "Overall Ranking"
        SELECTION = "selection", "Selection"
        REPORTING = "reporting", "Reporting"
        OTHER = "other", "Other"

    class MissingScorePolicy(TextChoices):
        ZERO = "zero", "Treat as Zero"
        SKIP_AND_RESCALE = "skip_and_rescale", "Skip and Rescale"

    name = models.CharField(max_length=255)
    season_year = models.PositiveSmallIntegerField(db_index=True)
    division = models.CharField(max_length=32, blank=True, default="", db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices, default=Purpose.OVERALL)
    missing_score_policy = models.CharField(
        max_length=32,
        choices=MissingScorePolicy.choices,
        default=MissingScorePolicy.ZERO,
    )
    tiebreak_policy = models.JSONField(blank=True, default=dict)
    is_active = models.BooleanField(default=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["season_year", "division", "name", "version", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["season_year", "division", "purpose", "version"],
                name="rankings_formula_unique_scope_version",
            ),
        ]
        indexes = [
            models.Index(fields=["season_year", "division"], name="rankings_formula_year_div_idx"),
            models.Index(fields=["season_year", "purpose"], name="rank_formula_year_purp_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_whitespace(self.name)
        self.division = (self.division or "").strip()
        self.purpose = (self.purpose or "").strip()
        self.missing_score_policy = canonicalize_choice_token(
            self.missing_score_policy,
            RANKING_FORMULA_MISSING_SCORE_POLICY_ALIASES,
        )

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "name",
                "division",
                "purpose",
                "missing_score_policy",
            }

        super().save(*args, **kwargs)


class RankingFormulaItem(models.Model):
    class NormalizationMethod(TextChoices):
        RAW = "raw", "Raw Score"
        PERCENT_OF_MAX = "percent_of_max", "Percent of Max Score"
        ZSCORE = "zscore", "Z-Score"
        FIXED_SCALE = "fixed_scale", "Fixed Scale"

    ranking_formula = models.ForeignKey(
        RankingFormula,
        on_delete=models.CASCADE,
        related_name="items",
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="ranking_formula_items",
    )
    weight = models.DecimalField(max_digits=8, decimal_places=4, default="1.0000")
    is_required = models.BooleanField(default=False)
    normalization_method = models.CharField(
        max_length=32,
        choices=NormalizationMethod.choices,
        default=NormalizationMethod.RAW,
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ranking_formula", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ranking_formula", "assessment"],
                name="rankings_formulaitem_unique_formula_assessment",
            ),
        ]
        indexes = [
            models.Index(fields=["ranking_formula", "sort_order"], name="rank_formula_item_sort_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.ranking_formula} / {self.assessment}"

    def save(self, *args, **kwargs) -> None:
        self.normalization_method = canonicalize_choice_token(
            self.normalization_method,
            RANKING_FORMULA_ITEM_NORMALIZATION_METHOD_ALIASES,
        )

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"normalization_method"}

        super().save(*args, **kwargs)


class StudentResult(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="results",
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="results",
    )
    raw_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    normalized_score = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    medal = models.CharField(max_length=32, blank=True, db_index=True)
    band = models.CharField(max_length=32, blank=True, db_index=True)
    status_text = models.CharField(max_length=64, blank=True)
    remarks = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    source_file_name = models.CharField(max_length=255, blank=True)
    imported_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="imported_student_results",
    )
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["assessment", "student", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "assessment"],
                name="rank_sturesult_unique_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment"], name="rank_res_assess_idx"),
            models.Index(fields=["student"], name="rank_res_student_idx"),
            models.Index(fields=["raw_score"], name="rank_res_rawscore_idx"),
            models.Index(fields=["medal"], name="rank_res_medal_idx"),
            models.Index(fields=["band"], name="rank_res_band_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.student} / {self.assessment}"

    def save(self, *args, **kwargs) -> None:
        self.medal = normalize_whitespace(self.medal)
        self.band = normalize_whitespace(self.band)
        self.status_text = normalize_whitespace(self.status_text)
        self.source_url = normalize_whitespace(self.source_url)
        self.source_file_name = normalize_whitespace(self.source_file_name)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "medal",
                "band",
                "status_text",
                "source_url",
                "source_file_name",
            }

        super().save(*args, **kwargs)


class StudentSelectionStatus(models.Model):
    class Status(TextChoices):
        TEAM = "team", "Team"
        SQUAD = "squad", "Squad"
        WATCHLIST = "watchlist", "Watchlist"
        SENIOR = "senior", "Senior"
        JUNIOR = "junior", "Junior"
        PRIMARY = "primary", "Primary"
        PIONEER = "pioneer", "Pioneer"
        BEGINNER = "beginner", "Beginner"
        NONE = "none", "None"

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="selection_statuses",
    )
    season_year = models.PositiveSmallIntegerField(db_index=True)
    division = models.CharField(max_length=32, blank=True, default="", db_index=True)
    status = models.CharField(max_length=32, db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_selection_statuses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-season_year", "division", "status", "student", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "season_year", "division", "status"],
                name="rank_selstatus_unique_scope",
            ),
        ]

    def __str__(self) -> str:
        scope = self.division or "overall"
        return f"{self.student} / {self.season_year} / {scope} / {self.status}"

    def save(self, *args, **kwargs) -> None:
        self.division = normalize_whitespace(self.division).lower()
        self.status = normalize_whitespace(self.status).lower()

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"division", "status"}

        super().save(*args, **kwargs)


class RankingSnapshot(models.Model):
    ranking_formula = models.ForeignKey(
        RankingFormula,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="ranking_snapshots",
    )
    season_year = models.PositiveSmallIntegerField(db_index=True)
    division = models.CharField(max_length=32, blank=True, default="", db_index=True)
    total_score = models.DecimalField(max_digits=12, decimal_places=4, db_index=True)
    rank_overall = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    rank_within_division = models.PositiveIntegerField(null=True, blank=True)
    score_breakdown_json = models.JSONField(default=dict, blank=True)
    last_computed_at = models.DateTimeField(default=timezone.now)
    formula_version_label = models.CharField(max_length=64, blank=True)
    formula_version_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["season_year", "division", "rank_overall", "student", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ranking_formula", "student"],
                name="rank_snapshot_unique_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["season_year"], name="rank_snap_season_idx"),
            models.Index(fields=["division"], name="rank_snap_div_idx"),
            models.Index(fields=["total_score"], name="rank_snap_score_idx"),
            models.Index(fields=["rank_overall"], name="rank_snap_rank_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.student} / {self.ranking_formula}"

    def save(self, *args, **kwargs) -> None:
        self.division = normalize_whitespace(self.division).lower()
        self.formula_version_label = normalize_whitespace(self.formula_version_label)
        self.formula_version_hash = normalize_whitespace(self.formula_version_hash)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "division",
                "formula_version_label",
                "formula_version_hash",
            }

        super().save(*args, **kwargs)


class ImportBatch(models.Model):
    class ImportType(TextChoices):
        STUDENT_MASTER = "student_master", "Student Master"
        ASSESSMENT_RESULTS = "assessment_results", "Assessment Results"
        LEGACY_WIDE_TABLE = "legacy_wide_table", "Legacy Wide Table"

    class Status(TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PREVIEWED = "previewed", "Previewed"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    import_type = models.CharField(max_length=32, choices=ImportType.choices, db_index=True)
    uploaded_file = models.FileField(upload_to="rankings/imports/%Y/%m/%d")
    original_filename = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.UPLOADED,
        db_index=True,
    )
    summary_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_import_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_import_type_display()} / {self.original_filename}"

    def save(self, *args, **kwargs) -> None:
        self.original_filename = normalize_whitespace(self.original_filename)
        self.import_type = normalize_whitespace(self.import_type).lower()
        self.status = normalize_whitespace(self.status).lower()

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "original_filename",
                "import_type",
                "status",
            }

        super().save(*args, **kwargs)


class ImportRowIssue(models.Model):
    class Severity(TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="row_issues",
    )
    row_number = models.PositiveIntegerField()
    severity = models.CharField(max_length=16, choices=Severity.choices, db_index=True)
    issue_code = models.CharField(max_length=64)
    message = models.TextField()
    raw_row_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["import_batch", "row_number", "id"]
        indexes = [
            models.Index(fields=["import_batch", "severity"], name="rank_issue_batch_sev_idx"),
            models.Index(fields=["import_batch", "row_number"], name="rank_issue_batch_row_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.import_batch_id} row {self.row_number} {self.severity}"

    def save(self, *args, **kwargs) -> None:
        self.severity = normalize_whitespace(self.severity).lower()
        self.issue_code = normalize_whitespace(self.issue_code)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"severity", "issue_code"}

        super().save(*args, **kwargs)
