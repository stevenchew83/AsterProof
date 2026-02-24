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
            name="PublicSolution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "solution_type",
                    models.CharField(
                        choices=[
                            ("sketch", "Sketch"),
                            ("full", "Full solution"),
                            ("hints", "Hints"),
                            ("alternative", "Alternative"),
                        ],
                        default="sketch",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("content", models.TextField()),
                ("is_unlisted", models.BooleanField(default=False)),
                ("is_hidden", models.BooleanField(default=False)),
                ("is_moderator_edited", models.BooleanField(default=False)),
                ("helpful_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "problem",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="publicsolution",
                        to="catalog.problem",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SolutionVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_helpful", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "solution",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="votes", to="community.publicsolution"),
                ),
                ("user", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("solution", "user")}},
        ),
        migrations.CreateModel(
            name="Comment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.TextField()),
                ("is_hidden", models.BooleanField(default=False)),
                ("is_moderator_edited", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.CASCADE,
                        related_name="replies",
                        to="community.comment",
                    ),
                ),
                (
                    "problem",
                    models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to="catalog.problem"),
                ),
                (
                    "solution",
                    models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to="community.publicsolution"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CommentReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emoji", models.CharField(default="thanks", max_length=16)),
                (
                    "comment",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="reactions", to="community.comment"),
                ),
                ("user", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("comment", "user", "emoji")}},
        ),
        migrations.CreateModel(
            name="ContentReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "comment",
                    models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to="community.comment"),
                ),
                ("reporter", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
                (
                    "solution",
                    models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to="community.publicsolution"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TrustedSuggestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "suggestion_type",
                    models.CharField(
                        choices=[
                            ("tag", "Tag Improvement"),
                            ("duplicate", "Duplicate Link"),
                            ("difficulty", "Difficulty Suggestion"),
                            ("quality", "Quality Suggestion"),
                        ],
                        max_length=32,
                    ),
                ),
                ("payload", models.TextField(blank=True)),
                ("approved", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, to="catalog.problem"),
                ),
                ("user", models.ForeignKey(on_delete=models.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
