from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_user_is_approved_and_approval_audit_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAccessSettings",
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
                    "auto_approve_new_users",
                    models.BooleanField(
                        default=False,
                        help_text="New signups are approved automatically when enabled.",
                        verbose_name="Auto approve new users",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "User access settings",
                "verbose_name_plural": "User access settings",
            },
        ),
    ]
