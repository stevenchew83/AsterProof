# ruff: noqa: S603, E501
"""Exercise populated SQLite table rebuilding and the old ORM against the new schema."""

import os
import subprocess
import sys
from pathlib import Path


def test_populated_sqlite_migration_preserves_collections_and_old_inserts(tmp_path):
    script = r"""
import django
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATABASE_PATH}}
settings.CONCEPT_ASSIGNMENTS_ENABLED = False
django.setup()
from django.db import connection, transaction, IntegrityError
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != 'solutions'] + [('solutions','0007_solutioncollection_solutioncollectionentry')]
executor.migrate(targets)
old = executor.loader.project_state(targets).apps
User = old.get_model('users','User')
Problem = old.get_model('pages','ProblemSolveRecord')
Solution = old.get_model('solutions','ProblemSolution')
Share = old.get_model('solutions','SolutionPublicShare')
Collection = old.get_model('solutions','SolutionCollection')
Entry = old.get_model('solutions','SolutionCollectionEntry')
owner = User.objects.create(email='sqlite-migration@example.invalid')
other = User.objects.create(email='sqlite-other@example.invalid')
problem = Problem.objects.create(contest='SQLITE MIGRATION',year=2026,problem='P1',topic='ALG',mohs=5)
solution = Solution.objects.create(author=owner,problem=problem,title='Preserved private proof')
second = Solution.objects.create(author=other,problem=problem,title='Second private proof')
from django.utils import timezone
first_share = Share.objects.create(solution=solution,source_updated_at=timezone.now(),snapshot={'title':'First public copy'})
second_share = Share.objects.create(solution=second,source_updated_at=timezone.now(),snapshot={'title':'Second public copy'})
collection = Collection.objects.create(owner=owner,title='Preserved title',introduction='Preserved introduction')
entry = Entry.objects.create(collection=collection,share=first_share,position=2,share_token=first_share.token)
before = {key:value for key,value in Collection.objects.values().get(pk=collection.pk).items()}
entry_before = Entry.objects.values().get(pk=entry.pk)
executor = MigrationExecutor(connection)
executor.migrate(executor.loader.graph.leaf_nodes())
new = executor.loader.project_state().apps
NewCollection = new.get_model('solutions','SolutionCollection')
NewEntry = new.get_model('solutions','SolutionCollectionEntry')
actual = NewCollection.objects.values().get(pk=collection.pk)
assert actual.pop('kind') == 'personal'
assert actual == before
assert NewEntry.objects.values().get(pk=entry.pk) == entry_before
# The old ORM omits kind; its insertion must receive the persistent database default.
old_insert = Collection.objects.create(owner=owner,title='Old code still inserts')
assert NewCollection.objects.get(pk=old_insert.pk).kind == 'personal'
curated = NewCollection.objects.create(kind='admin_curated',owner=None,title='Site-owned')
NewEntry.objects.create(collection=curated,share_id=first_share.pk,position=1,share_token=first_share.token)
NewEntry.objects.create(collection=curated,share_id=second_share.pk,position=2,share_token=second_share.token)
for values in ({'kind':'personal','owner_id':None},{'kind':'admin_curated','owner_id':owner.pk},{'kind':'unknown','owner_id':None}):
    try:
        with transaction.atomic():
            NewCollection.objects.create(title='Invalid ownership',**values)
    except IntegrityError:
        pass
    else:
        raise AssertionError('Ownership/kind invariant did not reject '+repr(values))
creator = User.objects.create(email='former-curator@example.invalid')
creator.delete()
connection.check_constraints()
assert NewCollection.objects.filter(pk=curated.pk).exists()
assert curated.entries.count() == 2
# The old cascade collector must retain the ownerless container and other contributor.
owner.delete()
connection.check_constraints()
assert NewCollection.objects.filter(pk=curated.pk).exists()
assert list(curated.entries.values_list('share_id',flat=True)) == [second_share.pk]
assert not NewCollection.objects.filter(pk=collection.pk).exists()
connection.close()
"""
    code = "DATABASE_PATH = " + repr(str(tmp_path / "migration.sqlite3")) + "\n" + script
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[3],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test", "DJANGO_READ_DOT_ENV_FILE": "false"},
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
