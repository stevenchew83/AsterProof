"""Preserve full statement labels and unknown difficulty in legacy solution anchors."""

from importlib import import_module

from django.db import migrations
from django.db import models


def suspend_sqlite_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        import_module("inspinia.pages.migrations.0039_catalogue_revision_triggers").uninstall(apps, schema_editor)


def restore_sqlite_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        import_module("inspinia.pages.migrations.0039_catalogue_revision_triggers").install(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("pages", "0039_catalogue_revision_triggers")]

    operations = [
        # SQLite rebuilds the source table for AlterField; preserve the catalogue
        # revision triggers on this and all referencing tables across that rebuild.
        migrations.RunPython(suspend_sqlite_triggers, restore_sqlite_triggers),
        migrations.AlterField(
            model_name="problemsolverecord", name="mohs", field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="problemsolverecord", name="contest", field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="problemsolverecord", name="contest_year_problem",
            field=models.CharField(blank=True, max_length=160, null=True),
        ),
        migrations.RunPython(restore_sqlite_triggers, suspend_sqlite_triggers),
    ]
