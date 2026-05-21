from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0004_imo_syllabus_subtopics"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subtopic",
            name="is_imo_syllabus",
            field=models.BooleanField("IMO syllabus", db_index=True, default=False),
        ),
    ]
