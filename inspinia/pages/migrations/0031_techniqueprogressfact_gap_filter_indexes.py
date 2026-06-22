from django.db import migrations
from django.db import models

MAIN_TOPIC_LABELS_GIN_INDEX = "pages_tpf_main_labels_gin"
CANONICAL_SUBTOPIC_LABELS_GIN_INDEX = "pages_tpf_canon_labels_gin"
TECHNIQUE_PROGRESS_FACT_TABLE = "pages_techniqueprogressfact"


def create_postgres_gin_indexes(_apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{MAIN_TOPIC_LABELS_GIN_INDEX}" '
            f'ON "{TECHNIQUE_PROGRESS_FACT_TABLE}" USING GIN ("main_topic_labels")',
        )
        cursor.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{CANONICAL_SUBTOPIC_LABELS_GIN_INDEX}" '
            f'ON "{TECHNIQUE_PROGRESS_FACT_TABLE}" USING GIN ("canonical_subtopic_labels")',
        )


def drop_postgres_gin_indexes(_apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{CANONICAL_SUBTOPIC_LABELS_GIN_INDEX}"')
        cursor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{MAIN_TOPIC_LABELS_GIN_INDEX}"')


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("pages", "0030_techniqueprogresscatalogstate_techniqueprogressfact"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="techniqueprogressfact",
            index=models.Index(fields=["layer", "main_topic"], name="pages_tpf_layer_main_idx"),
        ),
        migrations.AddIndex(
            model_name="techniqueprogressfact",
            index=models.Index(fields=["layer", "canonical_subtopic"], name="pages_tpf_layer_canon_idx"),
        ),
        migrations.RunPython(create_postgres_gin_indexes, drop_postgres_gin_indexes),
    ]
