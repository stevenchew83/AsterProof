import uuid

from django.db import migrations, models


def populate_statement_problem_uuid(apps, schema_editor) -> None:
    ContestProblemStatement = apps.get_model("pages", "ContestProblemStatement")

    for statement in ContestProblemStatement.objects.select_related("linked_problem").all():
        if statement.linked_problem_id is not None:
            problem_uuid = statement.linked_problem.problem_uuid
        else:
            problem_uuid = uuid.uuid4()
        ContestProblemStatement.objects.filter(pk=statement.pk).update(problem_uuid=problem_uuid)


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0009_contestproblemstatement"),
    ]

    operations = [
        migrations.AddField(
            model_name="contestproblemstatement",
            name="problem_uuid",
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(populate_statement_problem_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contestproblemstatement",
            name="problem_uuid",
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
