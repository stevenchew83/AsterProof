"""Reviewed presentation metadata; original assessment results remain authoritative."""

from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class EvidenceStatus(models.TextChoices):
    UNREVIEWED = "unreviewed", "Not reviewed"
    REPORTED = "reported", "Reported"
    PENDING = "pending", "Pending verification"
    VERIFIED = "verified", "Verified"
    CONFLICTING = "conflicting", "Conflicting evidence"


class EvidenceSource(models.TextChoices):
    UNKNOWN = "unknown", "Not recorded"
    ORGANIZER = "organizer", "Organizer result / certificate"
    NEWS = "news", "News report"
    FAMILY = "family", "Family record"
    RESEARCH = "research", "Supplied research"
    LEGACY = "legacy", "Legacy import"
    OTHER = "other", "Other source"


def validate_evidence_url(value):
    if value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme in {"http", "https"} and not (parsed.username or parsed.password):
                return
        except ValueError:
            pass
        message = "Use an HTTP or HTTPS source link without embedded credentials."
        raise ValidationError(message)


class ResultProfile(models.Model):
    class RecordType(models.TextChoices):
        UNKNOWN = "unknown", "Unclassified"
        ACHIEVEMENT = "achievement", "Achievement / recognition"
        PERFORMANCE = "performance", "Score / participation"
        SELECTION = "selection", "Group / selection"
        CONTEXT = "context", "Research / context"

    class Discipline(models.TextChoices):
        UNKNOWN = "unknown", "Not classified"
        MATHEMATICS = "mathematics", "Mathematics"
        COMPUTING = "computing", "Computing"
        SCHOOL = "school", "School recognition"
        MUSIC = "music", "Music"
        ENGLISH = "english", "English"
        COMMUNITY = "community", "Community contribution"
        OTHER = "other", "Other"

    class Scope(models.TextChoices):
        UNKNOWN = "unknown", "Scope not recorded"
        INTERNATIONAL = "international", "International"
        NATIONAL = "national", "National"
        REGIONAL = "regional", "Regional"
        SCHOOL = "school", "School"

    class Participation(models.TextChoices):
        UNKNOWN = "unknown", "Not recorded"
        INDIVIDUAL = "individual", "Individual"
        TEAM = "team", "Team"
        JOINT = "joint", "Joint contribution"

    result = models.OneToOneField("rankings.StudentResult", on_delete=models.CASCADE, related_name="profile")
    record_type = models.CharField(max_length=20, choices=RecordType.choices, default=RecordType.UNKNOWN)
    discipline = models.CharField(max_length=20, choices=Discipline.choices, default=Discipline.UNKNOWN)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.UNKNOWN)
    scope_detail = models.CharField(max_length=255, blank=True)
    participation = models.CharField(max_length=20, choices=Participation.choices, default=Participation.UNKNOWN)
    featured = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    result_fingerprint = models.CharField(max_length=64)
    reviewed_by = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(featured=False) | models.Q(record_type="achievement"),
                name="rank_profile_featured_achievement",
            ),
        ]

    def __str__(self):
        return f"Result {self.result_id} profile classification"

    def clean(self):
        super().clean()
        if self.featured and self.record_type != self.RecordType.ACHIEVEMENT:
            message = "Only achievement records can be selected as highlights."
            raise ValidationError({"featured": message})


class ResultClaim(models.Model):
    class ClaimType(models.TextChoices):
        AWARD = "award", "Award / recognition"
        SCORE = "score", "Score"
        RANKING = "ranking", "Ranking / placing"

    class AwardKind(models.TextChoices):
        UNKNOWN = "unknown", "Not classified"
        MEDAL = "medal", "Medal"
        CHAMPIONSHIP = "championship", "Championship / title"
        DISTINCTION = "distinction", "Distinction / special award"
        RECOGNITION = "recognition", "School / leadership recognition"
        CONTRIBUTION = "contribution", "Community contribution"
        OTHER = "other", "Other award"

    result = models.ForeignKey("rankings.StudentResult", on_delete=models.CASCADE, related_name="claims")
    claim_type = models.CharField(max_length=16, choices=ClaimType.choices)
    claim_label = models.CharField(max_length=255, blank=True)
    award_kind = models.CharField(max_length=16, choices=AwardKind.choices, default=AwardKind.UNKNOWN)
    verification_status = models.CharField(
        max_length=16,
        choices=EvidenceStatus.choices,
        default=EvidenceStatus.UNREVIEWED,
    )
    source_type = models.CharField(max_length=16, choices=EvidenceSource.choices, default=EvidenceSource.UNKNOWN)
    source_label = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=500, blank=True, validators=[validate_evidence_url])
    evidence = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    result_fingerprint = models.CharField(max_length=64)
    reviewed_by = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["claim_type", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["result", "claim_type"], name="rank_claim_unique_result_type"),
            models.CheckConstraint(
                condition=models.Q(claim_type="award") | models.Q(award_kind="unknown"),
                name="rank_claim_award_kind_only",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(active=False)
                    | ~models.Q(verification_status="verified")
                    | (
                        ~models.Q(evidence="")
                        & models.Q(source_type__in=["organizer", "news", "other"])
                        & (~models.Q(source_label="") | ~models.Q(source_url=""))
                    )
                ),
                name="rank_claim_verified_evidence",
            ),
        ]

    def __str__(self):
        return f"Result {self.result_id} / {self.get_claim_type_display()} evidence"

    def clean(self):
        super().clean()
        if self.active and not self.claim_label.strip():
            message = "Describe the specific claim being reviewed."
            raise ValidationError({"claim_label": message})
        if self.claim_type != self.ClaimType.AWARD and self.award_kind != self.AwardKind.UNKNOWN:
            message = "Award classification applies only to award claims."
            raise ValidationError({"award_kind": message})
        if (
            self.active
            and self.verification_status == EvidenceStatus.VERIFIED
            and (
                not self.evidence.strip()
                or not (self.source_label.strip() or self.source_url)
                or self.source_type not in {EvidenceSource.ORGANIZER, EvidenceSource.NEWS, EvidenceSource.OTHER}
            )
        ):
            message = "Verification needs a checked organizer, news or other source and supporting evidence."
            raise ValidationError(message)
