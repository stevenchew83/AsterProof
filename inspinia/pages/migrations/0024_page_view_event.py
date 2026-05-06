import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0023_user_problem_difficulty_rating"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PageViewEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "view_type",
                    models.CharField(
                        choices=[
                            ("problem_statement", "Problem statement"),
                            ("solution", "Solution"),
                            ("list", "List"),
                            ("contest", "Contest"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("object_uuid", models.UUIDField(blank=True, db_index=True, null=True)),
                ("label", models.CharField(blank=True, max_length=160)),
                ("contest_name", models.CharField(blank=True, max_length=128)),
                ("contest_year", models.IntegerField(blank=True, null=True)),
                ("path", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="page_view_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="pageviewevent",
            index=models.Index(
                fields=["view_type", "-created_at"],
                name="pg_pv_type_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="pageviewevent",
            index=models.Index(
                fields=["object_uuid", "view_type"],
                name="pg_pv_object_type_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="pageviewevent",
            index=models.Index(
                fields=["contest_name", "-created_at"],
                name="pg_pv_contest_created_idx",
            ),
        ),
    ]
