"""Shared mathematical documents; saved source and references are append-only."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def learning_asset_storage():
    from inspinia.learning.storage import LearningAssetStorage

    return LearningAssetStorage()


def learning_asset_path(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"assets/{instance.pk.hex}.{extension}"


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        message = "Saved content is immutable; create a new revision."
        raise ValidationError(message)

    def delete(self):
        message = "Retained content cannot be deleted through the application."
        raise ValidationError(message)

    def bulk_update(self, objs, fields, batch_size=None):
        message = "Saved content is immutable; create a new revision."
        raise ValidationError(message)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            message = "Saved content is immutable; create a new revision."
            raise ValidationError(message)
        return super().bulk_create(objs, **kwargs)


class ImmutableModel(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            message = "Saved content is immutable; create a new revision."
            raise ValidationError(message)
        # A new Python instance with an existing primary key must not fall through
        # Django's ordinary UPDATE-before-INSERT behavior.
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        message = "Retained content cannot be deleted through the application."
        raise ValidationError(message)


class ContentDocument(models.Model):
    class Kind(models.TextChoices):
        OVERVIEW = "overview", "Area overview"
        CONCEPT = "concept", "Concept explanation"
        LECTURE = "lecture", "Lecture"
        TECHNIQUE = "technique", "Technique guide"
        STANDALONE = "standalone", "Standalone editorial resource"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.LECTURE)
    canonical_area = models.ForeignKey(
        "pages.CatalogueArea",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_documents",
    )
    canonical_concept = models.ForeignKey(
        "pages.CatalogueConcept",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_documents",
    )
    slug = models.SlugField(max_length=180, blank=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="learning_documents_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="overview", canonical_area__isnull=False, canonical_concept__isnull=True)
                    | Q(kind="concept", canonical_concept__isnull=False, canonical_area__isnull=True)
                    | Q(kind__in=["lecture", "technique", "standalone"])
                ),
                name="learning_document_canonical_identity",
            ),
            models.UniqueConstraint(
                fields=["canonical_area"],
                condition=Q(kind="overview"),
                name="learning_one_area_landing",
            ),
            models.UniqueConstraint(
                fields=["canonical_concept"],
                condition=Q(kind="concept"),
                name="learning_one_concept_landing",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.pk}"


class ContentDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="drafts")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="learning_drafts",
    )
    title = models.CharField(max_length=180, blank=True)
    summary = models.CharField(max_length=320, blank=True)
    body_source = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    base_revision = models.ForeignKey(
        "ContentRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="branched_drafts",
    )
    base_publication_version = models.PositiveIntegerField(default=0)
    edit_version = models.PositiveIntegerField(default=0)
    is_archived = models.BooleanField(default=False, db_index=True)
    save_receipts = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["document", "author"], name="learning_draft_author_document")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentRevision(ImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="revisions")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="learning_revisions",
    )
    base_revision = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derived_revisions",
    )
    sequence = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=320, blank=True)
    body_source = models.TextField()
    metadata = models.JSONField(default=dict)
    body_format = models.CharField(max_length=32, default="markdown_latex_v1")
    source_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["document", "sequence"], name="learning_revision_sequence"),
            models.CheckConstraint(condition=Q(sequence__gte=1), name="learning_revision_positive_sequence"),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class RevisionConcept(ImmutableModel):
    class Role(models.TextChoices):
        PRIMARY = "primary", "Primary"
        SUPPORTING = "supporting", "Supporting"

    revision = models.ForeignKey(ContentRevision, on_delete=models.PROTECT, related_name="concept_links")
    concept = models.ForeignKey(
        "pages.CatalogueConcept",
        on_delete=models.PROTECT,
        related_name="teaching_revision_links",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.SUPPORTING)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "concept"], name="learning_revision_concept")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentAsset(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        DELETING = "deleting", "Deleting"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="learning_assets",
    )
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="assets")
    file = models.FileField(storage=learning_asset_storage, upload_to=learning_asset_path)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    sha256 = models.CharField(max_length=64)
    byte_size = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=48)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentAssetGrant(ImmutableModel):
    asset = models.ForeignKey(ContentAsset, on_delete=models.PROTECT, related_name="reuse_grants")
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="asset_grants")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["asset", "document"], name="learning_asset_document_grant")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class RevisionAsset(ImmutableModel):
    revision = models.ForeignKey(ContentRevision, on_delete=models.PROTECT, related_name="asset_links")
    asset = models.ForeignKey(ContentAsset, on_delete=models.PROTECT, related_name="revision_links")
    alt_text = models.CharField(max_length=500)
    caption = models.CharField(max_length=1000, blank=True)
    credit = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "asset"], name="learning_revision_asset")]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContributorPermission(ImmutableModel):
    revision = models.OneToOneField(ContentRevision, on_delete=models.PROTECT, related_name="permission")
    contributor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    agreement_version = models.CharField(max_length=64)
    source_digest = models.CharField(max_length=64)
    rights_declaration = models.JSONField(default=dict)
    public_credit = models.CharField(max_length=180, blank=True)
    accepted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentPublication(models.Model):
    document = models.OneToOneField(
        ContentDocument,
        primary_key=True,
        on_delete=models.PROTECT,
        related_name="publication",
    )
    revision = models.ForeignKey(
        ContentRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_publications",
    )
    version = models.PositiveIntegerField(default=0)
    training_visible = models.BooleanField(default=False)
    public_visible = models.BooleanField(default=False)
    announcement_disposition = models.CharField(max_length=16, default="excluded", editable=False)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(public_visible=False) | Q(training_visible=True),
                name="learning_public_implies_training",
            ),
            models.CheckConstraint(
                condition=(Q(revision__isnull=False) | Q(training_visible=False, public_visible=False)),
                name="learning_visible_requires_revision",
            ),
            models.CheckConstraint(
                condition=Q(announcement_disposition="excluded"),
                name="learning_announcement_excluded",
            ),
        ]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContributionProposal(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        DECLINED = "declined", "Declined"
        APPROVED = "approved", "Approved"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="proposals")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="learning_proposals",
    )
    revision = models.ForeignKey(ContentRevision, on_delete=models.PROTECT, related_name="proposals")
    base_publication_version = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED)
    review_digest = models.CharField(max_length=64)
    feedback = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="learning_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentAction(ImmutableModel):
    operation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="actions")
    action = models.CharField(max_length=32)
    payload_digest = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ProtectedLegacyQuerySet(models.QuerySet):
    def delete(self):
        message = "Retire a legacy mapping through the reviewed transition workflow."
        raise ValidationError(message)


class LegacyContentLink(models.Model):
    objects = ProtectedLegacyQuerySet.as_manager()

    document = models.ForeignKey(ContentDocument, on_delete=models.PROTECT, related_name="legacy_links")
    material = models.OneToOneField(
        "training.Material",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_link",
    )
    area = models.OneToOneField(
        "website.LibraryArea",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_link",
    )
    concept = models.OneToOneField(
        "website.LibraryConcept",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_link",
    )
    lecture = models.OneToOneField(
        "website.LibraryLecture",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_link",
    )
    source_fingerprint = models.CharField(max_length=64)
    is_cutover = models.BooleanField(default=False)
    announcement_excluded = models.BooleanField(default=True, editable=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(material__isnull=False, area__isnull=True, concept__isnull=True, lecture__isnull=True)
                    | Q(material__isnull=True, area__isnull=False, concept__isnull=True, lecture__isnull=True)
                    | Q(material__isnull=True, area__isnull=True, concept__isnull=False, lecture__isnull=True)
                    | Q(material__isnull=True, area__isnull=True, concept__isnull=True, lecture__isnull=False)
                ),
                name="learning_legacy_one_source",
            ),
        ]

    def delete(self, *args, **kwargs):
        message = "Retire a legacy mapping through the reviewed transition workflow."
        raise ValidationError(message)

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"


class ContentIssue(models.Model):
    class Kind(models.TextChoices):
        MATHEMATICAL = "mathematical", "Mathematical error"
        CLASSIFICATION = "classification", "Classification suggestion"
        PATHWAY = "pathway", "Pathway suggestion"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission_id = models.UUIDField(unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MATHEMATICAL)
    document = models.ForeignKey(
        ContentDocument,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    revision = models.ForeignKey(ContentRevision, null=True, blank=True, on_delete=models.PROTECT)
    target_key = models.CharField(max_length=180, blank=True)
    description = models.CharField(max_length=2000)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, default="open", choices=[("open", "Open"), ("closed", "Closed")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{type(self).__name__} {self.pk}"
