from django.db import migrations
from django.db import models
from django.db.models import Q


def approve_existing_privileged_users(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(Q(is_superuser=True) | Q(role="admin")).update(is_approved=True)


def reverse_noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0006_user_country_user_postal_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_approved",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Unapproved users can sign in but cannot use AsterProof features.",
                verbose_name="Approved for app access",
            ),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("auth.login_succeeded", "Login succeeded"),
                    ("auth.login_failed", "Login failed"),
                    ("auth.logout", "Logout"),
                    ("auth.signup", "Signup"),
                    ("users.role_changed", "Role changed"),
                    ("users.approval_changed", "Approval changed"),
                    ("sessions.revoked", "Session revoked"),
                    ("imports.previewed", "Workbook previewed"),
                    ("imports.completed", "Workbook imported"),
                    ("imports.failed", "Workbook import failed"),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
        migrations.RunPython(approve_existing_privileged_users, reverse_noop),
    ]
