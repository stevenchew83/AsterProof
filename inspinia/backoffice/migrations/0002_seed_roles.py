from django.db import migrations


def seed_roles_and_defaults(apps, schema_editor):  # noqa: ARG001
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    moderator_group, _ = Group.objects.get_or_create(name="moderator")
    admin_group, _ = Group.objects.get_or_create(name="admin")

    moderator_permissions = [
        ("backoffice", "view_report"),
        ("backoffice", "change_report"),
        ("backoffice", "view_moderationlog"),
        ("backoffice", "view_contentrevision"),
        ("community", "view_publicsolution"),
        ("community", "change_publicsolution"),
        ("community", "view_comment"),
        ("community", "change_comment"),
        ("catalog", "view_problem"),
        ("catalog", "change_problem"),
        ("users", "view_user"),
    ]

    for app_label, codename in moderator_permissions:
        perm = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
        if perm:
            moderator_group.permissions.add(perm)

    for perm in Permission.objects.all():
        admin_group.permissions.add(perm)

    FeatureFlagConfig = apps.get_model("backoffice", "FeatureFlagConfig")
    PrivacyDefaultsConfig = apps.get_model("backoffice", "PrivacyDefaultsConfig")
    BrandingConfig = apps.get_model("backoffice", "BrandingConfig")
    RatingConfig = apps.get_model("backoffice", "RatingConfig")
    AbusePolicy = apps.get_model("backoffice", "AbusePolicy")

    FeatureFlagConfig.objects.get_or_create(pk=1)
    PrivacyDefaultsConfig.objects.get_or_create(pk=1)
    BrandingConfig.objects.get_or_create(pk=1)
    RatingConfig.objects.get_or_create(pk=1)
    AbusePolicy.objects.get_or_create(pk=1)


def noop(apps, schema_editor):  # noqa: ARG001
    return


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_part_b_user_states"),
        ("backoffice", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles_and_defaults, noop),
    ]
