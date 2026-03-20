from django.db import migrations, models


def sync_admin_roles_from_legacy(apps, schema_editor):
    User = apps.get_model("users", "User")
    Group = apps.get_model("auth", "Group")
    admin_pks = set(User.objects.filter(is_superuser=True).values_list("pk", flat=True))
    try:
        group = Group.objects.get(name="Admin")
        admin_pks |= set(group.user_set.values_list("pk", flat=True))
    except Group.DoesNotExist:
        pass
    User.objects.filter(pk__in=admin_pks).update(role="admin")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_admin_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("moderator", "Moderator"),
                    ("trainer", "Trainer"),
                    ("normal", "Normal user"),
                ],
                db_index=True,
                default="normal",
                max_length=20,
                verbose_name="Role",
            ),
        ),
        migrations.RunPython(sync_admin_roles_from_legacy, migrations.RunPython.noop),
    ]
