from django.db import models


class ContestType(models.TextChoices):
    IMO = "imo", "IMO"
    SHORTLIST = "shortlist", "Shortlist"
    APMO = "apmo", "APMO"
    RMM = "rmm", "RMM"
    EGMO = "egmo", "EGMO"
    TST = "tst", "TST"
    TRAINING = "training", "Training"
    CUSTOM = "custom", "Custom"


class VisibilityState(models.TextChoices):
    DRAFT = "draft", "Draft"
    INTERNAL = "internal", "Internal"
    PUBLIC = "public", "Public"


class Contest(models.Model):
    name = models.CharField(max_length=200)
    short_code = models.CharField(max_length=64, unique=True)
    contest_type = models.CharField(max_length=32, choices=ContestType.choices)
    year = models.PositiveIntegerField()
    round = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    official_url = models.URLField(blank=True)
    official_pdf_url = models.URLField(blank=True)
    visibility_state = models.CharField(max_length=16, choices=VisibilityState.choices, default=VisibilityState.PUBLIC)

    class Meta:
        ordering = ["-year", "short_code"]

    def __str__(self):
        return f"{self.short_code} ({self.year})"


class Tag(models.Model):
    class TagCategory(models.TextChoices):
        TOPIC = "topic", "Topic"
        TECHNIQUE = "technique", "Technique"
        THEME = "theme", "Theme"

    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=16, choices=TagCategory.choices, default=TagCategory.TOPIC)

    def __str__(self):
        return self.name


class Problem(models.Model):
    class ProblemStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        HIDDEN = "hidden", "Hidden"
        EXPERIMENTAL = "experimental", "Experimental"

    contest = models.ForeignKey(
        Contest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="problems",
    )
    label = models.CharField(max_length=64, help_text="P1-P6 or custom label")
    title = models.CharField(max_length=255, blank=True)
    statement = models.TextField()
    editorial_difficulty = models.PositiveSmallIntegerField(default=3)
    editorial_quality = models.PositiveSmallIntegerField(default=3)
    status = models.CharField(max_length=16, choices=ProblemStatus.choices, default=ProblemStatus.ACTIVE)
    canonical_problem = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
    )
    tags = models.ManyToManyField(Tag, through="ProblemTag", related_name="problems")

    class Meta:
        unique_together = ("contest", "label")
        ordering = ["contest__year", "label"]

    def __str__(self):
        contest_code = self.contest.short_code if self.contest else "Standalone"
        return f"{contest_code} {self.label}"


class ProblemTag(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("problem", "tag")


class ProblemReference(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="references")
    title = models.CharField(max_length=255)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.title


class RelationType(models.TextChoices):
    SIMILAR = "similar", "Similar to"
    GENERALISATION = "generalisation", "Generalisation of"
    USES_LEMMA = "uses_lemma", "Uses lemma from"


class RelatedProblem(models.Model):
    source_problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        related_name="related_from",
    )
    target_problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        related_name="related_to",
    )
    relation_type = models.CharField(max_length=32, choices=RelationType.choices)

    class Meta:
        unique_together = ("source_problem", "target_problem", "relation_type")
