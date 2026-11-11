from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [("pages", "0047_study_help")]

    operations = [
        migrations.AddField(
            model_name="contestproblemstatement",
            name="ai_concept_suggestions",
            field=models.JSONField(blank=True, editable=False, null=True),
        ),
    ]
