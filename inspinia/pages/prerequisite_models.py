"""An advisory pedagogical graph; catalogue narrower/related edges stay unchanged."""

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models import Q


class PrerequisiteGraphState(models.Model):
    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveIntegerField(default=0)
    validated_catalogue_revision = models.PositiveBigIntegerField(null=True)
    is_valid = models.BooleanField(default=False)
    snapshot = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prerequisite graph version {self.version}"


class CataloguePrerequisite(models.Model):
    prerequisite = models.ForeignKey(
        "pages.CatalogueConcept", on_delete=models.PROTECT, related_name="pedagogical_dependents",
    )
    dependent = models.ForeignKey(
        "pages.CatalogueConcept", on_delete=models.PROTECT, related_name="pedagogical_prerequisites",
    )
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.prerequisite_id} → {self.dependent_id}"

    class Meta:
        ordering = ["prerequisite_id", "dependent_id"]
        constraints = [
            models.UniqueConstraint(fields=["prerequisite", "dependent"], name="pages_prerequisite_unique"),
            models.CheckConstraint(condition=~Q(prerequisite=F("dependent")), name="pages_prerequisite_not_self"),
        ]
