from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ContestEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("slug", models.SlugField(unique=True)),
                (
                    "contest_kind",
                    models.CharField(
                        choices=[("official", "Official"), ("practice", "Practice"), ("virtual", "Virtual")],
                        default="official",
                        max_length=16,
                    ),
                ),
                (
                    "visibility_state",
                    models.CharField(
                        choices=[("draft", "Draft"), ("internal", "Internal"), ("public", "Public")],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField()),
                ("is_rated", models.BooleanField(default=False)),
                ("rules", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="ContestRegistration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contest",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="registrations", to="contests.contestevent"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="contest_registrations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("user", "contest")}},
        ),
        migrations.CreateModel(
            name="ContestProblem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=1)),
                ("max_score", models.PositiveIntegerField(default=7)),
                (
                    "contest",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="contest_problems", to="contests.contestevent"),
                ),
                ("problem", models.ForeignKey(on_delete=models.CASCADE, to="catalog.problem")),
            ],
            options={"ordering": ["position"], "unique_together": {("contest", "problem")}},
        ),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.TextField(blank=True)),
                ("pdf", models.FileField(blank=True, null=True, upload_to="submissions/")),
                ("score", models.FloatField(default=0)),
                (
                    "marking_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("partial", "Partial"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("grader_note", models.TextField(blank=True)),
                ("graded_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contest",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="submissions", to="contests.contestevent"),
                ),
                (
                    "graded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="graded_submissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("problem", models.ForeignKey(on_delete=models.CASCADE, to="catalog.problem")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="submissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ScoreEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.FloatField(default=0)),
                ("rank", models.PositiveIntegerField(default=0)),
                ("rating_delta", models.FloatField(default=0)),
                (
                    "contest",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="score_entries", to="contests.contestevent"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="contest_scores",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("contest", "user")}},
        ),
        migrations.CreateModel(
            name="RatingSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.FloatField(default=1200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="rating_snapshots",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="RatingDelta",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_rating", models.FloatField()),
                ("new_rating", models.FloatField()),
                ("delta", models.FloatField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contest",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="rating_deltas", to="contests.contestevent"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="rating_deltas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
