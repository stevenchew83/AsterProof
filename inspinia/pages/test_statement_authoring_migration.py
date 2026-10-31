"""The authoring upgrade preserves existing records and catalogue invalidation."""

import os
import subprocess
import sys


def test_statement_authoring_upgrade_preserves_records_and_revision_triggers(tmp_path):
    script = r"""
from django.conf import settings
import os
settings.DATABASES['default']['NAME'] = os.environ['AUTHORING_UPGRADE_DATABASE']
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
old = ('pages', '0039_catalogue_revision_triggers')
executor.migrate([old])
apps = executor.loader.project_state([old]).apps
User = apps.get_model('users', 'User')
Problem = apps.get_model('pages', 'ProblemSolveRecord')
Statement = apps.get_model('pages', 'ContestProblemStatement')
Solution = apps.get_model('solutions', 'ProblemSolution')
user = User.objects.create(email='authoring-upgrade@example.test')
problem = Problem.objects.create(year=2025, contest='Preserved Cup', problem='P1', topic='NT', mohs=12)
Statement.objects.create(contest_name='Preserved Cup', contest_year=2025, day_label='Day 1',
    problem_number=1, problem_code='P1', statement_latex='Preserve this statement.',
    linked_problem_id=problem.pk, problem_uuid=problem.problem_uuid)
Solution.objects.create(problem_id=problem.pk, author_id=user.pk, title='Preserve this private solution.')
labels = [('users', 'User'), ('pages', 'ProblemSolveRecord'), ('pages', 'ContestProblemStatement'),
    ('solutions', 'ProblemSolution')]
before = {name: list(apps.get_model(app, name).objects.order_by('pk').values()) for app, name in labels}
with connection.cursor() as cursor:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
    original_triggers = cursor.fetchall()
executor = MigrationExecutor(connection)
new = ('pages', '0040_statement_authoring_metadata')
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
after = {name: list(apps.get_model(app, name).objects.order_by('pk').values()) for app, name in labels}
assert before == after, 'Existing identity, statement, solution or author changed.'
with connection.cursor() as cursor:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
    assert cursor.fetchall() == original_triggers, 'Catalogue triggers were lost or duplicated.'
State = apps.get_model('pages', 'CatalogueState')
state, _ = State.objects.get_or_create(singleton_key=1)
revision = state.source_revision
Problem = apps.get_model('pages', 'ProblemSolveRecord')
new_problem = Problem.objects.create(year=2025, contest='Standalone Cup', problem='P1', topic='', mohs=None)
new_problem.refresh_from_db()
assert new_problem.mohs is None, 'Unknown difficulty was replaced by an invented number.'
state.refresh_from_db()
assert state.source_revision > revision, 'Catalogue invalidation stopped after the table rebuild.'
print('Upgrade preserves existing records, unknown difficulty, and all catalogue triggers.')
"""
    result = subprocess.run(  # noqa: S603 - fixed script with an isolated temporary database.
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_READ_DOT_ENV_FILE": "false",
            "AUTHORING_UPGRADE_DATABASE": str(tmp_path / "authoring-upgrade.sqlite3"),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
