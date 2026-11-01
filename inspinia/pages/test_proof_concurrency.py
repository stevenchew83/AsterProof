"""PostgreSQL interleavings preserve private drafts and explicit proof publication."""

import threading
import time
from http import HTTPStatus
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db import connections
from django.db import transaction
from django.test import Client
from django.urls import reverse

from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.proof_library import ensure_statement_revision
from inspinia.pages.proof_library import public_solutions
from inspinia.pages.proof_library import publish_solution
from inspinia.pages.proof_library import save_attempt
from inspinia.pages.proof_library import share_problem
from inspinia.pages.proof_models import CommunityAttempt
from inspinia.pages.proof_models import CommunitySolution
from inspinia.pages.proof_models import CommunitySolutionRevision
from inspinia.pages.proof_models import ModerationEvent
from inspinia.pages.proof_models import ProblemPublication
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires PostgreSQL row locks and deferred FKs"),
]
EVENT_TIMEOUT = 10
LOCK_OBSERVATION_SECONDS = 3
THREAD_JOIN_SECONDS = 12
OLD_BODY = r"Since $(a-b)^2\geq0$, the conclusion follows."
NEW_BODY = "A later private argument that was never selected for publication."


@pytest.fixture(autouse=True)
def _require_local_test_database(settings):
    assert str(connection.settings_dict["NAME"]).startswith("test_"), "Use a disposable Django test database"
    host = connection.settings_dict["HOST"]
    local_socket = host.startswith(("/private/tmp/", "/tmp/"))  # noqa: S108 - disposable local test socket
    assert host in {"127.0.0.1", "localhost", "::1"} or local_socket
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_REVIEW_ENABLED = False


@pytest.fixture
def publication():
    owner = UserFactory(name="Concurrent problem author")
    solver = UserFactory(name="Concurrent proof author")
    reviewer = UserFactory(role=User.Role.ADMIN, name="Concurrent publication reviewer")
    problem = CommunityProblem.objects.create(
        author=owner, title="Concurrent community problem", statement_latex="Prove a square is nonnegative.",
        topic="ALG", source_kind="original", source_details="Synthetic concurrency example", status="approved",
        similarity_snapshot={"content_digest": "0" * 64},
    )
    with transaction.atomic():
        locked = CommunityProblem.objects.select_for_update().get(pk=problem.pk)
        revision = ensure_statement_revision(locked)
        ModerationEvent.objects.create(
            problem=problem, statement_revision=revision, actor=reviewer, action="statement_approved",
        )
    data = {
        "version": 0, "visibility": "unlisted", "public_credit": "Problem contributor",
        "statement_revision": revision.pk, "consent": True,
    }
    _, _, token = share_problem(owner, problem.pk, data, action="preview")
    shared, _, _ = share_problem(owner, problem.pk, data, action="publish", token=token)
    return SimpleNamespace(owner=owner, solver=solver, reviewer=reviewer, problem=problem,
                           revision=revision, publication=shared)


def _draft_data(revision, *, version=0, body=OLD_BODY):
    return {"version": version, "statement_revision": revision.pk, "title": "A selected proof", "body_source": body}


def _proof_data(attempt):
    return {
        "version": attempt.version, "title": "A selected proof", "summary": "A direct argument.",
        "public_credit": "Proof contributor", "consent": True,
    }


def _saved_attempt(state):
    return save_attempt(state.solver, state.revision, _draft_data(state.revision))


def _proof_preview(state, attempt):
    data = _proof_data(attempt)
    _, token = publish_solution(state.solver, attempt.pk, data, action="preview")
    return data, token


def _start_operation(operation, *, lock_table, pause_after_lock=False):
    state = SimpleNamespace(
        attempted=threading.Event(), locked=threading.Event(), release=threading.Event(),
        finished=threading.Event(), pid=None, locks=[], result=None, error=None,
    )

    def observe(execute, sql, params, many, context):
        is_lock = "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql
        target = is_lock and f'"{lock_table}"' in sql
        if is_lock:
            state.locks.append(sql)
        if target:
            state.pid = context["connection"].connection.info.backend_pid
            state.attempted.set()
        result = execute(sql, params, many, context)
        if target and not state.locked.is_set():
            state.locked.set()
            if pause_after_lock:
                assert state.release.wait(EVENT_TIMEOUT), "Test did not release the acquired source lock"
        return result

    def run():
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '8s'")
                cursor.execute("SET lock_timeout = '5s'")
            with connections["default"].execute_wrapper(observe):
                state.result = operation()
        except Exception as error:  # noqa: BLE001 - return worker failures to the parent test
            state.error = error
        finally:
            connections.close_all()
            state.finished.set()

    state.thread = threading.Thread(target=run, name="community-proof-concurrency", daemon=True)
    state.thread.start()
    return state


def _assert_waiting_for_lock(state):
    assert state.attempted.wait(EVENT_TIMEOUT), "Operation did not reach the expected source lock"
    deadline = time.monotonic() + LOCK_OBSERVATION_SECONDS
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [state.pid])
            row = cursor.fetchone()
        if row == ("Lock",):
            assert not state.finished.is_set()
            return
        assert not state.finished.wait(0.02), f"Operation finished before waiting: {state.error!r}"
    pytest.fail("PostgreSQL did not report the expected lock wait")


def _finish(operations):
    for operation in operations:
        operation.release.set()
    for operation in operations:
        operation.thread.join(THREAD_JOIN_SECONDS)
        assert not operation.thread.is_alive(), "Concurrent operation exceeded its bounded timeout"
        assert operation.error is None, repr(operation.error)


def test_first_saves_from_two_tabs_create_one_draft_and_reject_stale_content(publication):
    def save(body):
        try:
            attempt = save_attempt(
                publication.solver, publication.revision, _draft_data(publication.revision, body=body),
            )
        except ValidationError:
            return "stale"
        return attempt.pk

    operations = []
    try:
        first = _start_operation(lambda: save(OLD_BODY), lock_table="users_user", pause_after_lock=True)
        operations.append(first)
        assert first.locked.wait(EVENT_TIMEOUT)
        second = _start_operation(lambda: save(NEW_BODY), lock_table="users_user")
        operations.append(second)
        _assert_waiting_for_lock(second)
    finally:
        _finish(operations)
    attempt = CommunityAttempt.objects.get(owner=publication.solver, problem=publication.problem)
    assert first.result == attempt.pk
    assert second.result == "stale"
    assert attempt.version == 1
    assert attempt.body_source == OLD_BODY
    assert CommunityAttempt.objects.count() == 1
    assert not CommunitySolution.objects.exists()


@pytest.mark.parametrize("first_action", ["withdraw", "review"])
def test_withdrawal_and_review_serialize_without_reviving_withdrawn_proof(publication, first_action):
    attempt = _saved_attempt(publication)
    data, token = _proof_preview(publication, attempt)
    solution, _ = publish_solution(publication.solver, attempt.pk, data, action="submit", token=token)
    revision_id = solution.current_revision_id
    owner_client, admin_client = Client(), Client()
    owner_client.force_login(publication.solver)
    admin_client.force_login(publication.reviewer)
    owner_url = reverse("pages:proof_solution_owner", args=[solution.pk])
    review_url = reverse("pages:proof_solution_moderation", args=[solution.pk])
    review_data = {
        "version": solution.version, "action": "review", "decision": "approved", "notes": "Publication checks done.",
        "check_content": "on", "check_rights": "on", "check_embargo": "on",
    }

    def withdraw():
        return owner_client.post(owner_url, {"action": "withdraw", "version": solution.version}).status_code

    def review():
        return admin_client.post(review_url, review_data).status_code

    actions = {"withdraw": withdraw, "review": review}
    other_action = "review" if first_action == "withdraw" else "withdraw"
    operations = []
    try:
        first = _start_operation(actions[first_action], lock_table="pages_communityproblem", pause_after_lock=True)
        operations.append(first)
        assert first.locked.wait(EVENT_TIMEOUT)
        second = _start_operation(actions[other_action], lock_table="pages_communityproblem")
        operations.append(second)
        _assert_waiting_for_lock(second)
    finally:
        _finish(operations)
    assert first.result == HTTPStatus.FOUND
    solution.refresh_from_db()
    if first_action == "withdraw":
        assert second.result == HTTPStatus.OK
        assert solution.status == CommunitySolution.Status.WITHDRAWN
    else:
        assert second.result == HTTPStatus.CONFLICT
        assert solution.status == CommunitySolution.Status.APPROVED
        response = owner_client.post(owner_url, {"action": "withdraw", "version": solution.version})
        assert response.status_code == HTTPStatus.FOUND
        solution.refresh_from_db()
    assert solution.status == CommunitySolution.Status.WITHDRAWN
    assert solution.current_revision_id == revision_id
    assert not public_solutions(publication.publication).exists()
    rejected = admin_client.post(review_url, {**review_data, "version": solution.version})
    assert rejected.status_code == HTTPStatus.OK
    solution.refresh_from_db()
    assert solution.status == CommunitySolution.Status.WITHDRAWN
    assert CommunitySolutionRevision.objects.filter(solution=solution).count() == 1


@pytest.mark.parametrize("reshare", [False, True])
def test_old_proof_preview_waits_for_sharing_change_and_cannot_publish(publication, reshare):
    attempt = _saved_attempt(publication)
    data, old_token = _proof_preview(publication, attempt)
    previous_generation = publication.publication.generation

    def change_sharing():
        with transaction.atomic():
            stopped, _, _ = share_problem(
                publication.owner, publication.problem.pk,
                {"version": publication.publication.version, "visibility": "private"}, action="stop",
            )
            if reshare:
                settings = {
                    "version": stopped.version, "visibility": "unlisted", "public_credit": "Problem contributor",
                    "statement_revision": publication.revision.pk, "consent": True,
                }
                _, _, token = share_problem(publication.owner, publication.problem.pk, settings, action="preview")
                share_problem(publication.owner, publication.problem.pk, settings, action="publish", token=token)

    def publish_old_preview():
        try:
            publish_solution(publication.solver, attempt.pk, data, action="submit", token=old_token)
        except ValidationError:
            return "stale"
        return "published"

    operations = []
    try:
        sharing = _start_operation(change_sharing, lock_table="pages_communityproblem", pause_after_lock=True)
        operations.append(sharing)
        assert sharing.locked.wait(EVENT_TIMEOUT)
        publishing = _start_operation(publish_old_preview, lock_table="pages_communityproblem")
        operations.append(publishing)
        _assert_waiting_for_lock(publishing)
    finally:
        _finish(operations)
    assert publishing.result == "stale"
    assert not CommunitySolution.objects.exists()
    attempt.refresh_from_db()
    assert attempt.body_source == OLD_BODY
    shared = ProblemPublication.objects.get(problem=publication.problem)
    assert shared.generation != previous_generation
    assert shared.visibility == ("unlisted" if reshare else "private")
    if reshare:
        current_data, current_token = _proof_preview(publication, attempt)
        solution, _ = publish_solution(
            publication.solver, attempt.pk, current_data, action="submit", token=current_token,
        )
        assert solution.status == CommunitySolution.Status.PENDING


def test_publishing_while_draft_save_waits_does_not_deadlock_on_author_fk(publication):
    attempt = _saved_attempt(publication)
    data, token = _proof_preview(publication, attempt)

    def publish():
        solution, _ = publish_solution(publication.solver, attempt.pk, data, action="submit", token=token)
        return solution.pk

    def save():
        return save_attempt(
            publication.solver, publication.revision,
            _draft_data(publication.revision, version=attempt.version, body=NEW_BODY), attempt_id=attempt.pk,
        ).pk

    operations = []
    try:
        publishing = _start_operation(publish, lock_table="pages_communityattempt", pause_after_lock=True)
        operations.append(publishing)
        assert publishing.locked.wait(EVENT_TIMEOUT)
        saving = _start_operation(save, lock_table="pages_communityattempt")
        operations.append(saving)
        _assert_waiting_for_lock(saving)
    finally:
        _finish(operations)
    assert any('"users_user"' in sql and "FOR NO KEY UPDATE" in sql for sql in saving.locks)
    assert saving.result == attempt.pk
    published = CommunitySolution.objects.get(pk=publishing.result)
    attempt.refresh_from_db()
    assert attempt.body_source == NEW_BODY
    assert published.current_revision.body_source == OLD_BODY
