from django.contrib import admin

from .models import AbusePolicy
from .models import BrandingConfig
from .models import ContentRevision
from .models import FeatureFlagConfig
from .models import ModerationLog
from .models import ProblemRequest
from .models import ProblemSubmission
from .models import PrivacyDefaultsConfig
from .models import RatingConfig
from .models import RatingRun
from .models import RatingRunEntry
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "reason_code", "status", "severity", "reporter", "assignee", "created_at")
    list_filter = ("status", "reason_code", "severity")
    search_fields = ("details", "reporter__email")


@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "actor", "target_user", "created_at")
    list_filter = ("action",)
    search_fields = ("reason", "actor__email", "target_user__email")


@admin.register(ContentRevision)
class ContentRevisionAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "edited_by", "created_at")
    search_fields = ("previous_text", "new_text", "edited_by__email")


@admin.register(ProblemRequest)
class ProblemRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "requested_contest", "requested_year", "status", "reviewer", "created_at")
    list_filter = ("status",)
    search_fields = ("requested_contest", "details")


@admin.register(ProblemSubmission)
class ProblemSubmissionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "reviewer", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "statement")


@admin.register(RatingRun)
class RatingRunAdmin(admin.ModelAdmin):
    list_display = ("id", "contest", "status", "is_rollback", "triggered_by", "created_at")
    list_filter = ("status", "is_rollback")


admin.site.register(RatingRunEntry)
admin.site.register(AbusePolicy)
admin.site.register(FeatureFlagConfig)
admin.site.register(PrivacyDefaultsConfig)
admin.site.register(BrandingConfig)
admin.site.register(RatingConfig)
