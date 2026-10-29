from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Subject(models.TextChoices):
    ALGEBRA = "algebra", "Algebra"
    GEOMETRY = "geometry", "Geometry"
    NUMBER_THEORY = "number-theory", "Number theory"
    COMBINATORICS = "combinatorics", "Combinatorics"


class EditorialEntry(models.Model):
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    summary = models.CharField(max_length=320, blank=True)
    body_markdown = models.TextField(blank=True, help_text="Markdown with LaTeX: use $...$ or \\[...\\].")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["order", "title", "pk"]

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class LibraryArea(EditorialEntry):
    subject = models.CharField(max_length=24, choices=Subject.choices)
    catalogue_area = models.ForeignKey(
        "pages.CatalogueArea", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="public_pages",
        help_text="Optional existing area link. This editorial page does not change analytics taxonomy.",
    )

    class Meta(EditorialEntry.Meta):
        constraints = [models.UniqueConstraint(fields=["subject", "slug"], name="website_area_subject_slug")]

    def get_absolute_url(self):
        return reverse("website:library_area", kwargs={"subject": self.subject, "area_slug": self.slug})


class LibraryConcept(EditorialEntry):
    area = models.ForeignKey(LibraryArea, on_delete=models.PROTECT, related_name="concepts")
    catalogue_concept = models.ForeignKey(
        "pages.CatalogueConcept",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_pages",
        help_text="Optional canonical concept link. Analytics notes are never published automatically.",
    )
    prerequisites = models.ManyToManyField("self", symmetrical=False, blank=True)

    class Meta(EditorialEntry.Meta):
        constraints = [models.UniqueConstraint(fields=["area", "slug"], name="website_concept_area_slug")]

    def get_absolute_url(self):
        return reverse(
            "website:library_concept",
            kwargs={
                "subject": self.area.subject,
                "area_slug": self.area.slug,
                "concept_slug": self.slug,
            },
        )


class LibraryLecture(EditorialEntry):
    concept = models.ForeignKey(LibraryConcept, on_delete=models.PROTECT, related_name="lectures")
    estimated_minutes = models.PositiveSmallIntegerField(default=10)
    resource_url = models.URLField(
        blank=True,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text="Optional external reference, recording, or PDF. Files are not fetched or embedded automatically.",
    )
    attribution = models.CharField(max_length=255, blank=True, help_text="Author and source credit, where applicable.")

    class Meta(EditorialEntry.Meta):
        constraints = [models.UniqueConstraint(fields=["concept", "slug"], name="website_lecture_concept_slug")]

    def get_absolute_url(self):
        return reverse(
            "website:library_lecture",
            kwargs={
                "subject": self.concept.area.subject,
                "area_slug": self.concept.area.slug,
                "concept_slug": self.concept.slug,
                "lecture_slug": self.slug,
            },
        )


class NewsletterSubscriber(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting confirmation"
        CONFIRMED = "confirmed", "Subscribed"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    confirmation_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    requested_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=32, default="2026-10-29")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email

    @property
    def badge_class(self):
        return {
            self.Status.PENDING: "text-bg-warning",
            self.Status.CONFIRMED: "text-bg-success",
            self.Status.UNSUBSCRIBED: "text-bg-secondary",
        }[self.status]


class NewsletterCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENDING = "sending", "Sending"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.CharField(max_length=180)
    preheader = models.CharField(max_length=180, blank=True)
    body_markdown = models.TextField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="started_newsletters",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.subject

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT and self.started_at is None

    @property
    def badge_class(self):
        return {
            self.Status.DRAFT: "text-bg-secondary",
            self.Status.SENDING: "text-bg-primary",
            self.Status.PAUSED: "text-bg-warning",
            self.Status.COMPLETED: "text-bg-success",
        }[self.status]

    def get_absolute_url(self):
        return reverse("website:newsletter_campaign", kwargs={"pk": self.pk})


class NewsletterDelivery(models.Model):
    class Kind(models.TextChoices):
        TEST = "test", "Test"
        CAMPAIGN = "campaign", "Campaign"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "In progress"
        ACCEPTED = "accepted", "Accepted"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Needs review"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(NewsletterCampaign, on_delete=models.PROTECT, related_name="deliveries")
    subscriber = models.ForeignKey(NewsletterSubscriber, null=True, blank=True, on_delete=models.SET_NULL)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=180)
    consent_confirmed_at = models.DateTimeField(null=True, blank=True)
    campaign_version = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.CAMPAIGN)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True)
    detail = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "recipient_email"], condition=models.Q(kind="campaign"),
                name="website_campaign_recipient_once",
            ),
            models.UniqueConstraint(
                fields=["campaign"], condition=models.Q(status="sending"), name="website_campaign_one_inflight",
            ),
        ]

    def __str__(self):
        return f"{self.campaign_id}: {self.get_status_display()}"

    @property
    def badge_class(self):
        return {
            self.Status.QUEUED: "text-bg-secondary",
            self.Status.SENDING: "text-bg-info",
            self.Status.ACCEPTED: "text-bg-success",
            self.Status.FAILED: "text-bg-danger",
            self.Status.UNKNOWN: "text-bg-warning",
            self.Status.SKIPPED: "text-bg-secondary",
        }[self.status]
