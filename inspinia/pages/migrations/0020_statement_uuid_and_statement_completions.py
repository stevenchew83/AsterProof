import uuid

from django.db import migrations
from django.db import models


def _populate_statement_uuids(apps, schema_editor):
    statement_model = apps.get_model("pages", "ContestProblemStatement")
    for statement in statement_model.objects.filter(statement_uuid__isnull=True).iterator():
        statement.statement_uuid = uuid.uuid4()
        statement.save(update_fields=["statement_uuid"])


def _migrate_problem_completions_to_statements(apps, schema_editor):
    statement_model = apps.get_model("pages", "ContestProblemStatement")
    completion_model = apps.get_model("pages", "UserProblemCompletion")
    statement_ids_by_problem_id: dict[int, list[int]] = {}

    completions = completion_model.objects.filter(
        statement_id__isnull=True,
        problem_id__isnull=False,
    )
    for completion in completions.iterator():
        if completion.problem_id not in statement_ids_by_problem_id:
            statement_ids_by_problem_id[completion.problem_id] = list(
                statement_model.objects.filter(linked_problem_id=completion.problem_id).values_list("id", flat=True),
            )
        statement_ids = statement_ids_by_problem_id[completion.problem_id]
        if not statement_ids:
            continue

        for statement_id in statement_ids:
            completion_model.objects.update_or_create(
                user_id=completion.user_id,
                statement_id=statement_id,
                defaults={
                    "completion_date": completion.completion_date,
                    "problem_id": None,
                },
            )
        completion.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0019_contestproblemstatement_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="contestproblemstatement",
            name="statement_uuid",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="userproblemcompletion",
            name="statement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="user_completions",
                to="pages.contestproblemstatement",
            ),
        ),
        migrations.AlterField(
            model_name="userproblemcompletion",
            name="problem",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="user_completions",
                to="pages.problemsolverecord",
            ),
        ),
        migrations.RunPython(_populate_statement_uuids, migrations.RunPython.noop),
        migrations.RunPython(_migrate_problem_completions_to_statements, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contestproblemstatement",
            name="statement_uuid",
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="userproblemcompletion",
            constraint=models.UniqueConstraint(
                fields=("user", "statement"),
                name="pages_userproblemcompletion_unique_user_statement",
            ),
        ),
        migrations.AddConstraint(
            model_name="userproblemcompletion",
            constraint=models.CheckConstraint(
                condition=models.Q(statement__isnull=False) | models.Q(problem__isnull=False),
                name="pages_userproblemcompletion_requires_statement_or_problem",
            ),
        ),
    ]
