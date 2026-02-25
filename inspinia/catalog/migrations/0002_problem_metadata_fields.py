from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="confidence",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="problem",
            name="imo_slot_guess",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="problem",
            name="mohs",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="problem",
            name="pitfalls",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="problem",
            name="rationale",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="problem",
            name="topic",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="problem",
            name="topic_tags",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
