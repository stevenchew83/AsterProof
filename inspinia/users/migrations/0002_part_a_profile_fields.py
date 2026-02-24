from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="avatars/"),
        ),
        migrations.AddField(
            model_name="user",
            name="bio",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="country",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="user",
            name="display_name",
            field=models.CharField(blank=True, max_length=255, verbose_name="Display name"),
        ),
        migrations.AddField(
            model_name="user",
            name="is_trusted_user",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="profile_visibility",
            field=models.CharField(
                choices=[("public", "Public"), ("semi_private", "Semi-private"), ("private", "Private")],
                default="public",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="rating",
            field=models.FloatField(default=1200),
        ),
        migrations.AddField(
            model_name="user",
            name="show_in_leaderboards",
            field=models.BooleanField(default=True),
        ),
    ]
