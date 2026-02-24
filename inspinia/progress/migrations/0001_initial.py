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
            name="ProblemProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("unattempted", "Unattempted"),
                            ("attempted", "Attempted"),
                            ("solved", "Solved"),
                            ("revisiting", "Revisiting"),
                        ],
                        default="unattempted",
                        max_length=16,
                    ),
                ),
                ("confidence", models.PositiveSmallIntegerField(default=0)),
                ("first_solved_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="progress_records", to="catalog.problem"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="problem_progress",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("user", "problem")}},
        ),
        migrations.CreateModel(
            name="ProblemFavourite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="favourites", to="catalog.problem"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="favourites", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"unique_together": {("user", "problem")}},
        ),
        migrations.CreateModel(
            name="ProblemDifficultyVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.PositiveSmallIntegerField(default=3)),
                ("created_at", models.DateTimeField(auto_now=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="difficulty_votes", to="catalog.problem"),
                ),
                ("user", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "problem")}},
        ),
        migrations.CreateModel(
            name="ProblemQualityVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.PositiveSmallIntegerField(default=3)),
                ("created_at", models.DateTimeField(auto_now=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="quality_votes", to="catalog.problem"),
                ),
                ("user", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "problem")}},
        ),
    ]
