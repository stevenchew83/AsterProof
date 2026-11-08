from django.db import migrations
from django.db import models


class RemoveConstraintPreservingSQLiteTriggers(migrations.RemoveConstraint):
    """Preserve SQLite triggers when Django rebuilds the solution table."""

    def _change_constraint(self, operation, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "sqlite":
            return operation(app_label, schema_editor, from_state, to_state)
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return None
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND lower(sql) LIKE %s ORDER BY name",
                [f"%{model._meta.db_table.lower()}%"],
            )
            triggers = cursor.fetchall()
            cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = %s", [model._meta.db_table])
            sequence = cursor.fetchone()
        for name, _sql in triggers:
            schema_editor.execute(f"DROP TRIGGER {schema_editor.quote_name(name)}")
        operation(app_label, schema_editor, from_state, to_state)
        if sequence:
            schema_editor.execute(
                "UPDATE sqlite_sequence SET seq = MAX(seq, %s) WHERE name = %s",
                [sequence[0], model._meta.db_table],
            )
        for _name, sql in triggers:
            schema_editor.execute(sql, params=None)
        return None

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        return self._change_constraint(super().database_forwards, app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        return self._change_constraint(super().database_backwards, app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [
        ("solutions", "0016_admin_review_takedown"),
    ]

    operations = [
        migrations.AddField(
            model_name="problemsolution",
            name="additional_draft_key",
            field=models.UUIDField(null=True, editable=False),
        ),
        RemoveConstraintPreservingSQLiteTriggers(
            model_name="problemsolution",
            name="solutions_problemsolution_unique_problem_author",
        ),
        migrations.AddConstraint(
            model_name="problemsolution",
            constraint=models.UniqueConstraint(
                fields=["problem", "author"],
                condition=models.Q(additional_draft_key__isnull=True),
                name="solutions_unique_first_draft",
            ),
        ),
        migrations.AddConstraint(
            model_name="problemsolution",
            constraint=models.UniqueConstraint(
                fields=["problem", "author", "additional_draft_key"],
                condition=models.Q(additional_draft_key__isnull=False),
                name="solutions_unique_additional_draft",
            ),
        ),
    ]
