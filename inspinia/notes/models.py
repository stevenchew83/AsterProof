from django.conf import settings
from django.db import models


class PrivateNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="private_notes")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, related_name="private_notes")
    content = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "problem")

    def __str__(self):
        return f"Note #{self.pk}"
