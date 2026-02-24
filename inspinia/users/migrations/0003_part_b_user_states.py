from django.db import migrations
from django.db import models
from django.utils.text import slugify


def _candidate_base(user):
    if user.display_name:
        base = slugify(user.display_name)
    elif user.name:
        base = slugify(user.name)
    elif user.email:
        base = slugify(user.email.split("@", maxsplit=1)[0])
    else:
        base = "user"
    if not base:
        base = "user"
    return base[:48]


def backfill_handles(apps, schema_editor):  # noqa: ARG001
    User = apps.get_model("users", "User")
    used = set(User.objects.exclude(handle__isnull=True).values_list("handle", flat=True))

    for user in User.objects.order_by("id"):
        if user.handle:
            used.add(user.handle)
            continue
        base = _candidate_base(user)
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base}-{suffix}"[:64]
        user.handle = candidate
        user.save(update_fields=["handle"])
        used.add(candidate)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_part_a_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="handle",
            field=models.SlugField(blank=True, max_length=64, null=True, unique=True, verbose_name="Handle"),
        ),
        migrations.AddField(
            model_name="user",
            name="is_banned",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="mute_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="is_readonly",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="is_shadow_banned",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="is_profile_hidden",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_handles, migrations.RunPython.noop),
    ]
