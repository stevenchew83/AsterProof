from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_problem_metadata_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="statement_format",
            field=models.CharField(
                choices=[
                    ("plain", "Plain text"),
                    ("latex", "LaTeX"),
                    ("markdown_tex", "Markdown + TeX"),
                ],
                default="plain",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="problem",
            name="statement_plaintext",
            field=models.TextField(blank=True),
        ),
    ]
