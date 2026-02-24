from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FeedbackItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "feedback_type",
                    models.CharField(
                        choices=[
                            ("feature", "Feature Request"),
                            ("bug", "Bug Report"),
                            ("problem_request", "Problem/Contest Request"),
                        ],
                        max_length=32,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("under_review", "Under Review"),
                            ("planned", "Planned"),
                            ("implemented", "Implemented"),
                            ("rejected", "Rejected"),
                        ],
                        default="new",
                        max_length=32,
                    ),
                ),
                ("admin_response", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="feedback_items",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="FeedbackStatusEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "previous_status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("new", "New"),
                            ("under_review", "Under Review"),
                            ("planned", "Planned"),
                            ("implemented", "Implemented"),
                            ("rejected", "Rejected"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "next_status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("under_review", "Under Review"),
                            ("planned", "Planned"),
                            ("implemented", "Implemented"),
                            ("rejected", "Rejected"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "feedback_item",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="status_events", to="feedback.feedbackitem"),
                ),
            ],
        ),
    ]
