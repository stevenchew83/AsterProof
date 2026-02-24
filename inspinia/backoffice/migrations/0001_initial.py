from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("catalog", "0001_initial"),
        ("contests", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AbusePolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("comment_limit_per_minute", models.PositiveIntegerField(default=10)),
                ("comment_limit_per_hour", models.PositiveIntegerField(default=120)),
                ("max_external_links_per_post", models.PositiveIntegerField(default=3)),
                ("bad_word_list", models.TextField(blank=True)),
                ("captcha_on_anonymous_suggestions", models.BooleanField(default=True)),
                ("captcha_new_account_threshold", models.PositiveIntegerField(default=5)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="BrandingConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "default_skin",
                    models.CharField(
                        choices=[
                            ("classic", "Classic"),
                            ("saas", "SaaS"),
                            ("modern", "Modern"),
                            ("material", "Material"),
                            ("minimal", "Minimal"),
                            ("flat", "Flat"),
                            ("galaxy", "Galaxy"),
                        ],
                        default="classic",
                        max_length=16,
                    ),
                ),
                ("logo_text", models.CharField(blank=True, max_length=255)),
                ("logo_image", models.ImageField(blank=True, null=True, upload_to="branding/")),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="FeatureFlagConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contests", models.BooleanField(default=True)),
                ("ratings", models.BooleanField(default=True)),
                ("public_dashboards", models.BooleanField(default=True)),
                ("problem_submissions", models.BooleanField(default=True)),
                ("advanced_analytics", models.BooleanField(default=False)),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="PrivacyDefaultsConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "default_profile_visibility",
                    models.CharField(
                        choices=[("public", "Public"), ("semi_private", "Semi-private"), ("private", "Private")],
                        default="public",
                        max_length=16,
                    ),
                ),
                ("default_solution_unlisted", models.BooleanField(default=False)),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="ProblemRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requested_contest", models.CharField(blank=True, max_length=255)),
                ("requested_year", models.PositiveIntegerField(blank=True, null=True)),
                ("source_url", models.URLField(blank=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="problem_requests/")),
                ("suggested_tags", models.CharField(blank=True, max_length=255)),
                ("suggested_difficulty", models.PositiveSmallIntegerField(default=3)),
                ("details", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("in_review", "In Review"),
                            ("accepted", "Accepted"),
                            ("rejected", "Rejected"),
                            ("duplicate", "Duplicate"),
                        ],
                        default="new",
                        max_length=16,
                    ),
                ),
                ("decision_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "duplicate_problem",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="duplicate_requests",
                        to="catalog.problem",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_problem_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ProblemSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("statement", models.TextField()),
                ("source_reference", models.URLField(blank=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="problem_submissions/")),
                ("proposed_tags", models.CharField(blank=True, max_length=255)),
                ("proposed_difficulty", models.PositiveSmallIntegerField(default=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("in_review", "In Review"),
                            ("accepted", "Accepted"),
                            ("rejected", "Rejected"),
                            ("duplicate", "Duplicate"),
                        ],
                        default="new",
                        max_length=16,
                    ),
                ),
                ("decision_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contest",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="catalog.contest"),
                ),
                (
                    "linked_problem",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ingested_submissions",
                        to="catalog.problem",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_problem_submissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submitter",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RatingConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_rating", models.FloatField(default=1200)),
                ("k_factor", models.PositiveIntegerField(default=24)),
                ("small_contest_threshold", models.PositiveIntegerField(default=5)),
                ("small_contest_k_multiplier", models.FloatField(default=0.75)),
                ("rating_floor", models.FloatField(blank=True, null=True)),
                ("rating_cap", models.FloatField(blank=True, null=True)),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="RatingRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("applied", "Applied"), ("rolled_back", "Rolled Back"), ("failed", "Failed")],
                        default="applied",
                        max_length=16,
                    ),
                ),
                ("is_rollback", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("config_snapshot", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("applied_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contest",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rating_runs", to="contests.contestevent"),
                ),
                (
                    "parent_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rollback_runs",
                        to="backoffice.ratingrun",
                    ),
                ),
                (
                    "triggered_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveBigIntegerField()),
                (
                    "reason_code",
                    models.CharField(
                        choices=[
                            ("spam", "Spam"),
                            ("harassment", "Harassment"),
                            ("plagiarism", "Plagiarism"),
                            ("hate", "Hate Speech"),
                            ("abuse", "Abusive Conduct"),
                            ("other", "Other"),
                        ],
                        max_length=32,
                    ),
                ),
                ("details", models.TextField(blank=True)),
                ("severity", models.PositiveSmallIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("in_review", "In Review"),
                            ("resolved", "Resolved"),
                            ("dismissed", "Dismissed"),
                            ("escalated", "Escalated"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("resolution_note", models.TextField(blank=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports_assigned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "content_type",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype"),
                ),
                (
                    "reporter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports_submitted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports_resolved",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ModerationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("hide", "Hide"),
                            ("unhide", "Unhide"),
                            ("redact", "Redact"),
                            ("warn", "Warn"),
                            ("mute", "Mute"),
                            ("ban", "Ban"),
                            ("shadow_ban", "Shadow Ban"),
                            ("dismiss", "Dismiss"),
                            ("resolve", "Resolve"),
                            ("escalate", "Escalate"),
                        ],
                        max_length=32,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="logs",
                        to="backoffice.report",
                    ),
                ),
                (
                    "target_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="moderation_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ContentRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveBigIntegerField()),
                ("previous_text", models.TextField()),
                ("new_text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "content_type",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype"),
                ),
                (
                    "edited_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "moderation_log",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="revisions",
                        to="backoffice.moderationlog",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RatingRunEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_rating", models.FloatField()),
                ("new_rating", models.FloatField()),
                ("delta", models.FloatField()),
                (
                    "run",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="backoffice.ratingrun"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"unique_together": {("run", "user")}},
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(fields=["status", "severity", "created_at"], name="backoffice_r_status_5f0347_idx"),
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(fields=["content_type", "object_id"], name="backoffice_r_content_a8f708_idx"),
        ),
        migrations.AddIndex(
            model_name="moderationlog",
            index=models.Index(fields=["target_user", "created_at"], name="backoffice_m_target__403f55_idx"),
        ),
        migrations.AddIndex(
            model_name="moderationlog",
            index=models.Index(fields=["action", "created_at"], name="backoffice_m_action_7934a8_idx"),
        ),
        migrations.AddIndex(
            model_name="contentrevision",
            index=models.Index(
                fields=["content_type", "object_id", "created_at"],
                name="backoffice_c_content_033f8f_idx",
            ),
        ),
    ]
