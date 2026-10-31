import django.db.models.deletion
from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("solutions", "0007_solutioncollection_solutioncollectionentry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="solutioncollection",
            name="kind",
            field=models.CharField(
                choices=[("personal", "Personal"), ("admin_curated", "Admin curated")],
                db_default="personal",
                default="personal",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="solutioncollection",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="solution_collections",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="solutioncollection",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(kind="personal", owner__isnull=False)
                    | models.Q(kind="admin_curated", owner__isnull=True)
                ),
                name="solution_collection_kind_owner",
            ),
        ),
    ]
