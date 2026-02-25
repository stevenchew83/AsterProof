from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_problem_statement_format_plaintext"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="problem_position",
            field=models.PositiveIntegerField(
                blank=True,
                db_index=True,
                help_text="Optional numeric position within a contest/problem set.",
                null=True,
            ),
        ),
    ]
