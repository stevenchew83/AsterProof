from django.db import migrations
from django.db import models


CHOICES = [("active", "Active"), ("dismissed", "Dismissed"), ("not_enrolled", "Not enrolled")]


class Migration(migrations.Migration):
    dependencies = [("users", "0008_useraccesssettings")]

    operations = [
        # Preserve the landing page and avoid opening a tutorial for existing users.
        migrations.AddField(
            model_name="user",
            name="solution_guide_status",
            field=models.CharField(
                choices=CHOICES, default="not_enrolled", db_default="not_enrolled", editable=False, max_length=16,
                verbose_name="Solution getting-started guide",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="solution_guide_status",
            field=models.CharField(
                choices=CHOICES, default="active", db_default="not_enrolled", editable=False, max_length=16,
                verbose_name="Solution getting-started guide",
            ),
        ),
    ]
