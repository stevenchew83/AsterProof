# ruff: noqa: E501
"""Exercise the real upgrade on an isolated database containing existing records."""

import os
import subprocess
import sys


def test_catalogue_upgrade_preserves_existing_identity_and_user_records(tmp_path):
    script = r"""
import os
from pathlib import Path
from django.conf import settings
settings.DATABASES['default']['NAME'] = os.environ['CATALOGUE_UPGRADE_DATABASE']
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
old_target = ('pages', '0036_concept_assignment_reviews')
executor.migrate([old_target])
apps = executor.loader.project_state([old_target]).apps
User = apps.get_model('users', 'User')
Problem = apps.get_model('pages', 'ProblemSolveRecord')
Statement = apps.get_model('pages', 'ContestProblemStatement')
Completion = apps.get_model('pages', 'UserProblemCompletion')
Assignment = apps.get_model('pages', 'ProblemConceptAssignment')
user = User.objects.create(email='preserve@example.test', name='Preserved learner')
problem = Problem.objects.create(year=2026, contest='IMO', problem='P1', topic='ALG', mohs=20)
statement = Statement.objects.create(contest_name='IMO', contest_year=2026, problem_code='P1', problem_number=1, linked_problem_id=problem.pk, problem_uuid=problem.problem_uuid)
Completion.objects.create(user_id=user.pk, problem_id=problem.pk, status='written', post_mortem='Preserve this note.')
Completion.objects.create(user_id=user.pk, statement_id=statement.pk, status='attempted', time_spent_minutes=37)
Assignment.objects.create(problem_uuid=problem.problem_uuid, concept_id='am-gm', disposition='accepted', source_fingerprint='0'*64, concept_signature='1'*64)
models = ['User', 'ProblemSolveRecord', 'ContestProblemStatement', 'UserProblemCompletion', 'ProblemConceptAssignment']
labels = ['users', 'pages', 'pages', 'pages', 'pages']
before = {name: list(apps.get_model(label, name).objects.order_by('pk').values()) for label, name in zip(labels, models, strict=True)}
executor = MigrationExecutor(connection)
new_target = ('pages', '0039_catalogue_revision_triggers')
executor.migrate([new_target])
new_apps = executor.loader.project_state([new_target]).apps
after = {name: list(new_apps.get_model(label, name).objects.order_by('pk').values()) for label, name in zip(labels, models, strict=True)}
assert before == after, 'An original record changed during catalogue migration.'
Concept = new_apps.get_model('pages', 'CatalogueConcept')
assert Concept.objects.get(pk='am-gm').redirect_id is None
assert Concept.objects.get(pk='nt-powers-of-three').redirect_id
assert Concept.objects.count() == 1163
print('Upgrade preserved users, UUIDs, completions, notes and reviewed assignments byte-for-byte at the field level.')
"""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DJANGO_READ_DOT_ENV_FILE": "false",
        "CATALOGUE_UPGRADE_DATABASE": str(tmp_path / "upgrade.sqlite3"),
    }
    result = subprocess.run(  # noqa: S603 - fixed script, isolated temporary database.
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
