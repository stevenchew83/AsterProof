"""Community data preserves private ownership and immutable publication evidence."""

import hashlib
import os
import subprocess
import sys

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.proof_models import CommunityAttempt
from inspinia.pages.proof_models import CommunityContentReport
from inspinia.pages.proof_models import CommunityPrivateAsset
from inspinia.pages.proof_models import CommunityProblemRevision
from inspinia.pages.proof_models import CommunitySolution
from inspinia.pages.proof_models import CommunitySolutionAsset
from inspinia.pages.proof_models import CommunitySolutionRevision
from inspinia.pages.proof_models import ModerationEvent
from inspinia.pages.proof_models import ProblemPublication
from inspinia.users.tests.factories import UserFactory


@pytest.fixture
def proof_records(db):
    author = UserFactory()
    problem = CommunityProblem.objects.create(
        author=author, title="A community question", statement_latex="Prove $x^2 \\geq 0$.",
        topic="ALG", source_kind="original", source_details="Synthetic author",
        similarity_snapshot={"content_digest": "0" * 64},
    )
    statement = CommunityProblemRevision.objects.create(
        problem=problem, number=1, snapshot={"statement_latex": problem.statement_latex}, content_digest="1" * 64,
    )
    attempt = CommunityAttempt.objects.create(
        problem=problem, statement_revision=statement, owner=author, body_source="Private working.",
    )
    solution = CommunitySolution.objects.create(problem=problem, author=author)
    revision = CommunitySolutionRevision.objects.create(
        solution=solution, source_attempt=attempt, statement_revision=statement, number=1,
        title="A proof", body_source="Published proof.", public_credit="Synthetic learner",
        consented_at=timezone.now(), content_digest="2" * 64,
    )
    data = b"synthetic image bytes"
    checksum = hashlib.sha256(data).hexdigest()
    private_asset = CommunityPrivateAsset.objects.create(
        attempt=attempt, name="private.png", content_type="image/png", data=data, sha256=checksum,
    )
    public_asset = CommunitySolutionAsset.objects.create(
        revision=revision, name="public.png", content_type="image/png", data=data, sha256=checksum,
    )
    event = ModerationEvent.objects.create(
        problem=problem, solution=solution, statement_revision=statement,
        solution_revision=revision, actor=author, action="submit_solution",
    )
    return {
        "author": author, "problem": problem, "statement": statement, "attempt": attempt,
        "solution": solution, "proof": revision, "private_asset": private_asset,
        "public_asset": public_asset, "event": event,
    }


@pytest.mark.parametrize(
    ("record_name", "field", "replacement"),
    [
        ("statement", "content_digest", "f" * 64),
        ("proof", "body_source", "A replacement proof."),
        ("private_asset", "name", "replacement-private.png"),
        ("public_asset", "name", "replacement-public.png"),
        ("event", "reason", "A replacement audit reason."),
    ],
)
def test_saved_proof_evidence_rejects_mutation_and_direct_deletion(proof_records, record_name, field, replacement):
    record = proof_records[record_name]
    original = getattr(record, field)
    setattr(record, field, replacement)
    queryset = type(record).objects.filter(pk=record.pk)
    with pytest.raises(ValidationError):
        record.save()
    with pytest.raises(ValidationError):
        queryset.update(**{field: replacement})
    with pytest.raises(ValidationError):
        type(record).objects.bulk_update([record], [field])
    with pytest.raises(ValidationError):
        type(record).objects.bulk_create(
            [record], update_conflicts=True, update_fields=[field], unique_fields=["id"],
        )
    with pytest.raises(ValidationError):
        record.delete()
    with pytest.raises(ValidationError):
        queryset.delete()
    record.refresh_from_db()
    assert getattr(record, field) == original


@pytest.mark.parametrize("record_name", ["statement", "proof", "private_asset", "public_asset", "event"])
def test_reusing_an_immutable_uuid_cannot_overwrite_the_saved_record(proof_records, record_name):
    record = proof_records[record_name]
    data = type(record).objects.filter(pk=record.pk).values().get()
    duplicate = type(record)(**data)
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()
    assert type(record).objects.filter(pk=record.pk).count() == 1


def test_unknown_answer_and_publication_defaults_do_not_publish_or_create_archive_rows(proof_records):
    problem = proof_records["problem"]
    problem.full_clean()
    assert problem.mohs is None
    assert not problem.solution_known
    assert not problem.legacy_member_visible
    assert not problem.topic_tags
    assert not problem.core_ideas
    assert not problem.rationale
    assert not ProblemPublication.objects.filter(problem=problem).exists()
    assert not ProblemSolveRecord.objects.filter(problem_uuid=problem.pk).exists()
    publication = ProblemPublication.objects.create(problem=problem)
    assert publication.visibility == ProblemPublication.Visibility.PRIVATE
    assert publication.statement_revision_id is None
    assert publication.consented_at is None
    assert not publication.is_held


def test_private_attempt_edits_and_deletion_do_not_change_published_copies(proof_records):
    attempt = proof_records["attempt"]
    proof = proof_records["proof"]
    asset = proof_records["public_asset"]
    attempt.body_source = "Changed private work and feedback."
    attempt.save()
    proof.refresh_from_db()
    assert proof.body_source == "Published proof."
    attempt.delete()
    proof.refresh_from_db()
    asset.refresh_from_db()
    assert proof.source_attempt_id is None
    assert proof.body_source == "Published proof."
    assert bytes(asset.data) == b"synthetic image bytes"
    assert not CommunityPrivateAsset.objects.filter(pk=proof_records["private_asset"].pk).exists()


@pytest.mark.parametrize("duplicate", ["statement", "attempt", "proof", "private_asset", "public_asset"])
def test_identity_constraints_reject_duplicate_versioned_content(proof_records, duplicate):
    record = proof_records[duplicate]
    values = type(record).objects.filter(pk=record.pk).values().get()
    values.pop("id")
    with pytest.raises(IntegrityError), transaction.atomic():
        type(record).objects.create(**values)


@pytest.mark.parametrize("model_name", ["publication", "attempt", "proof", "event", "report"])
def test_cross_problem_relations_fail_model_validation(proof_records, model_name):
    problem = proof_records["problem"]
    other_problem = CommunityProblem.objects.create(
        author=proof_records["author"], title="Another question", statement_latex="Find $x$.",
        topic="ALG", source_kind="original", source_details="Synthetic author",
    )
    other_revision = CommunityProblemRevision.objects.create(
        problem=other_problem, number=1, snapshot={}, content_digest="3" * 64,
    )
    records = {
        "publication": ProblemPublication(problem=problem, statement_revision=other_revision),
        "attempt": CommunityAttempt(
            problem=problem, statement_revision=other_revision, owner=proof_records["author"],
        ),
        "proof": CommunitySolutionRevision(solution=proof_records["solution"], statement_revision=other_revision),
        "event": ModerationEvent(problem=other_problem, solution=proof_records["solution"]),
        "report": CommunityContentReport(problem=other_problem, solution=proof_records["solution"]),
    }
    with pytest.raises(ValidationError):
        records[model_name].clean()


def test_current_proof_and_source_attempt_must_belong_to_the_contributor(proof_records):
    solution = proof_records["solution"]
    unrelated = CommunitySolution.objects.create(problem=solution.problem, author=UserFactory())
    unrelated.current_revision = proof_records["proof"]
    with pytest.raises(ValidationError):
        unrelated.clean()
    other_attempt = CommunityAttempt.objects.create(
        problem=solution.problem, statement_revision=proof_records["statement"], owner=unrelated.author,
    )
    proof_records["proof"].source_attempt = other_attempt
    with pytest.raises(ValidationError):
        proof_records["proof"].clean()


def test_proof_library_upgrade_preserves_legacy_audience_and_existing_records(tmp_path):
    script = r"""
import os
from django.conf import settings
settings.DATABASES['default']['NAME'] = os.environ['PROOF_UPGRADE_DATABASE']
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
old = ('pages', '0044_learning_page_activity')
executor = MigrationExecutor(connection)
executor.migrate([old])
apps = executor.loader.project_state([old]).apps
User = apps.get_model('users', 'User')
user = User.objects.create(email='proof-upgrade@example.test', name='Preserved learner')
Problem = apps.get_model('pages', 'ProblemSolveRecord')
archive = Problem.objects.create(year=2026, contest='Preserved Cup', problem='P1', topic='ALG', mohs=12)
Statement = apps.get_model('pages', 'ContestProblemStatement')
statement = Statement.objects.create(contest_name='Preserved Cup', contest_year=2026, problem_code='P1',
    problem_number=1, linked_problem_id=archive.pk, problem_uuid=archive.problem_uuid, statement_latex='Original.')
Solution = apps.get_model('solutions', 'ProblemSolution')
Solution.objects.create(problem_id=archive.pk, author_id=user.pk, title='Private archive proof.')
Community = apps.get_model('pages', 'CommunityProblem')
legacy = Community.objects.create(author_id=user.pk, title='Existing community post', statement_latex='Unchanged.',
    topic='ALG', mohs=15, topic_tags='AM-GM', core_ideas='Preserve idea.', rationale='Preserve rationale.',
    source_kind='original', source_details='Preserve credit.', solution_outline='Private outline.',
    review_notes='Legacy member-visible note.')
Review = apps.get_model('pages', 'CommunityProblemReview')
Review.objects.create(problem_id=legacy.pk, version=1, reviewer_id=user.pk,
    decision='changes_requested', notes='Preserve review.', content_snapshot={'title':'Original title'})
labels = [('users','User'), ('pages','ProblemSolveRecord'), ('pages','ContestProblemStatement'),
    ('solutions','ProblemSolution'), ('pages','CommunityProblem'), ('pages','CommunityProblemReview')]
fields = {name:[field.attname for field in apps.get_model(app,name)._meta.concrete_fields] for app,name in labels}
before = {name:list(apps.get_model(app,name).objects.order_by('pk').values(*fields[name])) for app,name in labels}
with connection.cursor() as cursor:
    cursor.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
    triggers = cursor.fetchall()
new = ('pages', '0045_community_proof_library')
executor = MigrationExecutor(connection)
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
after = {name:list(apps.get_model(app,name).objects.order_by('pk').values(*fields[name])) for app,name in labels}
assert before == after, 'Existing source records, identities, or private content changed.'
Community = apps.get_model('pages','CommunityProblem')
legacy = Community.objects.get(pk=legacy.pk)
assert legacy.legacy_member_visible is True
assert legacy.solution_known is False and legacy.public_hint == '' and legacy.embargo_until is None
created = Community.objects.create(author_id=user.pk, title='New private problem', statement_latex='Find $x$.',
    topic='ALG', source_kind='original', source_details='New author.')
assert created.legacy_member_visible is False and created.mohs is None
for name in ('ProblemPublication','CommunityAttempt','CommunityProblemRevision','CommunitySolution',
    'CommunitySolutionRevision','CommunityPrivateAsset','CommunitySolutionAsset','ModerationEvent','CommunityContentReport'):
    assert not apps.get_model('pages',name).objects.exists(), f'Migration unexpectedly created {name} data.'
with connection.cursor() as cursor:
    cursor.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
    assert cursor.fetchall() == triggers, 'Existing invalidation triggers changed.'
    cursor.execute('PRAGMA foreign_key_check')
    assert not cursor.fetchall(), 'The migration broke existing foreign keys.'
print('Legacy audience and prior records preserved; new posts private; no public content or consent backfill.')
"""
    result = subprocess.run(  # noqa: S603 - fixed script and isolated SQLite database.
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_READ_DOT_ENV_FILE": "false",
            "DATABASE_URL": "sqlite:///:memory:",
            "PROOF_UPGRADE_DATABASE": str(tmp_path / "proof-upgrade.sqlite3"),
        },
        capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
