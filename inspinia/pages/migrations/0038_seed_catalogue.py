"""Freeze the reviewed catalogue without touching problem, assignment or user rows."""

import hashlib
import json
from pathlib import Path

from django.db import migrations


def seed_catalogue(apps, schema_editor):
    data = Path(__file__).with_name("0038_catalogue_seed.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != "e98f5329e697597ef4dcadeb77d912213237365b05d3207d76391581222386f6":
        message = "The frozen catalogue seed has changed."
        raise ValueError(message)
    seed = json.loads(data)
    db = schema_editor.connection.alias
    for model, key in (
        ("CatalogueSubject", "subjects"),
        ("CatalogueArea", "areas"),
        ("CatalogueConcept", "concepts"),
        ("CatalogueConceptArea", "memberships"),
        ("CatalogueConceptRelation", "relations"),
        ("CatalogueConceptAlias", "aliases"),
    ):
        cls = apps.get_model("pages", model)
        cls.objects.using(db).bulk_create([cls(**row) for row in seed[key]], batch_size=200)
    apps.get_model("pages", "CatalogueState").objects.using(db).create(
        singleton_key=1, catalogue_version=seed["version"],
    )


class Migration(migrations.Migration):
    dependencies = [("pages", "0037_catalogue_tables")]
    operations = [migrations.RunPython(seed_catalogue, migrations.RunPython.noop)]
