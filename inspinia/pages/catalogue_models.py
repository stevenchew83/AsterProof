"""Stable catalogue identities and disposable progress projections."""

import uuid

from django.conf import settings
from django.db import models


class CatalogueSubject(models.Model):
    id = models.SlugField(primary_key=True, max_length=40)
    name = models.CharField(max_length=64, unique=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name


class CatalogueArea(models.Model):
    id = models.CharField(primary_key=True, max_length=180)
    subject = models.ForeignKey(CatalogueSubject, on_delete=models.PROTECT, related_name="areas")
    # Historical area keys include spaces and retain their exact spelling.
    slug = models.CharField(max_length=120)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["subject", "slug"], name="pages_ca_subject_slug_uniq")]

    def __str__(self):
        return self.name


class CatalogueConcept(models.Model):
    id = models.CharField(primary_key=True, max_length=160)
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    roles = models.JSONField(default=list)
    # Retain original assessment references; no benchmark or source-tag mutation.
    metadata = models.JSONField(default=dict)
    redirect = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="legacy_ids")

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class CatalogueConceptArea(models.Model):
    concept = models.ForeignKey(CatalogueConcept, on_delete=models.PROTECT, related_name="memberships")
    area = models.ForeignKey(CatalogueArea, on_delete=models.PROTECT, related_name="memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["concept", "area"], name="pages_cca_concept_area_uniq")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class CatalogueConceptRelation(models.Model):
    class Kind(models.TextChoices):
        NARROWER = "narrower", "Narrower concept"
        RELATED = "related", "Related concept"

    source = models.ForeignKey(CatalogueConcept, on_delete=models.PROTECT, related_name="outgoing_relations")
    target = models.ForeignKey(CatalogueConcept, on_delete=models.PROTECT, related_name="incoming_relations")
    kind = models.CharField(max_length=16, choices=Kind.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "target", "kind"], name="pages_ccr_edge_uniq"),
            models.CheckConstraint(condition=~models.Q(source=models.F("target")), name="pages_ccr_no_self"),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class CatalogueConceptAlias(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    concept = models.ForeignKey(
        CatalogueConcept,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="aliases",
    )
    subject = models.ForeignKey(CatalogueSubject, on_delete=models.PROTECT)
    role = models.CharField(max_length=32)
    label = models.CharField(max_length=512)
    # Contextual/ambiguous/deprecated mappings remain qualified, never unconditional synonyms.
    resolution = models.CharField(max_length=24, default="EXACT")
    lifecycle = models.CharField(max_length=24, default="ACTIVE")
    rules = models.JSONField(default=dict)

    class Meta:
        ordering = ["label", "role", "id"]
        indexes = [models.Index(fields=["subject", "role"], name="pages_ccalias_scope_idx")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ConceptLibrarySnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_revision = models.PositiveBigIntegerField()
    catalogue_version = models.CharField(max_length=64)
    assignment_signature = models.CharField(max_length=64)
    totals = models.JSONField(default=dict)
    unmapped = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class CatalogueState(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, primary_key=True)
    catalogue_version = models.CharField(max_length=64)
    source_revision = models.PositiveBigIntegerField(default=0)
    snapshot = models.ForeignKey(ConceptLibrarySnapshot, null=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class CatalogueProblem(models.Model):
    snapshot = models.ForeignKey(ConceptLibrarySnapshot, on_delete=models.CASCADE, related_name="problems")
    problem_uuid = models.UUIDField()
    statement = models.ForeignKey("pages.ContestProblemStatement", null=True, on_delete=models.SET_NULL)
    problem = models.ForeignKey("pages.ProblemSolveRecord", null=True, on_delete=models.SET_NULL)
    statement_uuid = models.UUIDField(null=True)
    label = models.CharField(max_length=320)
    subject = models.CharField(max_length=64, blank=True)
    contest = models.CharField(max_length=128)
    year = models.IntegerField()
    mohs = models.IntegerField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "problem_uuid"], name="pages_cp_snapshot_uuid_uniq"),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class CatalogueProblemConcept(models.Model):
    problem = models.ForeignKey(CatalogueProblem, on_delete=models.CASCADE, related_name="concept_links")
    concept = models.ForeignKey(CatalogueConcept, on_delete=models.PROTECT, related_name="problem_links")
    area = models.ForeignKey(CatalogueArea, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["problem", "concept", "area"], name="pages_cpc_membership_uniq"),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class UserConceptProgressSummary(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    snapshot = models.ForeignKey(ConceptLibrarySnapshot, on_delete=models.CASCADE)
    completion_fingerprint = models.CharField(max_length=64)
    # Scope-keyed concept/area/subject counts, derived from existing completions.
    progress = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "snapshot", "completion_fingerprint"],
                name="pages_ucps_generation_uniq",
            ),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"
