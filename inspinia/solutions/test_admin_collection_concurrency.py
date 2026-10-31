"""Exercise real PostgreSQL source-row serialization through the sharing views."""

import threading
import time
import uuid
from http import HTTPStatus
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db import connections
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import admin_collections
from inspinia.solutions import views as solution_views
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.test_public_sharing import create_share
from inspinia.solutions.test_public_sharing import share_path
from inspinia.solutions.test_public_sharing import sharing_data
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Real source-row locking requires isolated PostgreSQL",
    ),
]
EVENT_TIMEOUT = 10
LOCK_OBSERVATION_SECONDS = 3
THREAD_JOIN_SECONDS = 12


@pytest.fixture(autouse=True)
def _require_isolated_postgresql():
    assert str(connection.settings_dict["NAME"]).startswith("test_"), "Use a disposable Django test database"
    host = connection.settings_dict["HOST"]
    local_socket = host.startswith(("/private/tmp/", "/tmp/"))  # noqa: S108 - validate a local test socket
    assert host in {"127.0.0.1", "localhost", "::1"} or local_socket, (
        "Source-row concurrency probes require a local disposable PostgreSQL instance"
    )


@pytest.fixture
def sources(client, settings):
    settings.PUBLIC_SITE_ORIGIN = "https://asterproof.example"
    author = UserFactory(name="Concurrent source owner")
    other_author = UserFactory(name="Other source owner")
    problem = ProblemSolveRecord.objects.create(
        contest="CONCURRENT CURATION", year=2026, problem="P1", topic="ALG", mohs=5,
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=problem.contest, contest_year=2026,
        problem_code="P1", problem_number=1, topic="ALG", statement_latex="Prove a square is nonnegative.",
    )
    shares, solutions, owner_clients = [], [], []
    for index, owner in enumerate([author, other_author], start=1):
        solution = ProblemSolution.objects.create(problem=problem, author=owner, title=f"Public proof {index}")
        ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source=f"SHARED-PROOF-{index}")
        owner_client = Client()
        owner_client.force_login(owner)
        shares.append(create_share(owner_client, solution))
        solutions.append(solution)
        owner_clients.append(owner_client)
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    # Reverse click order deliberately differs from the required source-lock order.
    data = {
        "title": "Concurrent curation", "introduction": "Compare both public copies.",
        "share": [f"{share.pk}:{share.token}" for share in shares[::-1]],
        "collection_revision": "", "flow": str(uuid.uuid4()), "action": "review",
    }
    path = reverse("solutions:admin_collection_create")
    response = client.post(path, data)
    assert response.status_code == HTTPStatus.OK
    data.update(action="publish", review_token=response.context["review_token"])
    return SimpleNamespace(
        shares=shares, solutions=solutions, owner_clients=owner_clients, data=data, path=path,
    )


def _start_post(client, path, data, name):
    state = SimpleNamespace(
        attempted=threading.Event(), finished=threading.Event(), pid=None,
        lock_sql="", status=None, error=None,
    )

    def observe(execute, sql, params, many, context):
        if "FOR UPDATE" in sql and '"solutions_problemsolution"' in sql:
            state.lock_sql = sql
            state.pid = context["connection"].connection.info.backend_pid
            state.attempted.set()
        return execute(sql, params, many, context)

    def post():
        try:
            with connections["default"].execute_wrapper(observe):
                state.status = client.post(path, data).status_code
        except Exception as exc:  # noqa: BLE001 - surface request-thread failures in the parent test
            state.error = exc
        finally:
            connections.close_all()
            state.finished.set()

    state.thread = threading.Thread(target=post, name=name, daemon=True)
    state.thread.start()
    return state


def _assert_waiting_for_lock(state):
    assert state.attempted.wait(EVENT_TIMEOUT), "Request did not reach its source-row lock"
    deadline = time.monotonic() + LOCK_OBSERVATION_SECONDS
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [state.pid])
            row = cursor.fetchone()
        if row == ("Lock",):
            assert not state.finished.is_set()
            return
        assert not state.finished.wait(0.02), f"Request finished without waiting: {state.error!r}"
    pytest.fail("PostgreSQL did not report the expected source-row lock wait")


def _join_requests(requests):
    for request in requests:
        request.thread.join(THREAD_JOIN_SECONDS)
        assert not request.thread.is_alive(), "Concurrent request exceeded its bounded timeout"
        assert request.error is None, repr(request.error)


@pytest.mark.parametrize("action", ["stop", "update"])
def test_publication_waits_for_author_then_rereads_changed_copy(client, sources, monkeypatch, action):
    solution, owner_client = sources.solutions[0], sources.owner_clients[0]
    if action == "update":
        solution.title = "Updated public proof"
        solution.save()
        solution.blocks.update(body_source="UPDATED-PUBLIC-PROOF")
    author_data = sharing_data(owner_client, solution, action)
    source_locked, release_author = threading.Event(), threading.Event()
    change_sharing = solution_views._change_solution_sharing  # noqa: SLF001 - hold an actual mutation boundary

    def hold_author(request, saved_solution, share):
        source_locked.set()
        assert release_author.wait(EVENT_TIMEOUT), "Author source lock was not released"
        return change_sharing(request, saved_solution, share)

    monkeypatch.setattr(solution_views, "_change_solution_sharing", hold_author)
    requests = []
    try:
        author = _start_post(owner_client, share_path(solution), author_data, "curated-source-author")
        requests.append(author)
        assert source_locked.wait(EVENT_TIMEOUT)
        publication = _start_post(client, sources.path, sources.data, "curated-publication")
        requests.append(publication)
        _assert_waiting_for_lock(publication)
        assert 'ORDER BY "solutions_problemsolution"."id" ASC' in publication.lock_sql
    finally:
        release_author.set()
        _join_requests(requests)
    assert author.status == HTTPStatus.FOUND
    assert publication.status == HTTPStatus.CONFLICT
    assert not SolutionCollection.objects.exists()
    sources.shares[0].refresh_from_db()
    if action == "stop":
        assert not sources.shares[0].is_active
        assert sources.shares[0].snapshot == {}
    else:
        assert sources.shares[0].snapshot["title"] == "Updated public proof"


def test_author_stop_waits_for_publication_and_revokes_its_guest_entry(client, sources, monkeypatch):
    solution, owner_client = sources.solutions[0], sources.owner_clients[0]
    author_data = sharing_data(owner_client, solution, "stop")
    publication_locked, release_publication = threading.Event(), threading.Event()
    publish = admin_collections._publish  # noqa: SLF001 - hold locks through actual collection persistence

    def hold_publication(*args, **kwargs):
        publication_locked.set()
        assert release_publication.wait(EVENT_TIMEOUT), "Publication source locks were not released"
        return publish(*args, **kwargs)

    monkeypatch.setattr(admin_collections, "_publish", hold_publication)
    requests = []
    try:
        publication = _start_post(client, sources.path, sources.data, "curated-publication")
        requests.append(publication)
        assert publication_locked.wait(EVENT_TIMEOUT)
        author = _start_post(owner_client, share_path(solution), author_data, "curated-source-author")
        requests.append(author)
        _assert_waiting_for_lock(author)
    finally:
        release_publication.set()
        _join_requests(requests)
    assert publication.status == HTTPStatus.FOUND
    assert author.status == HTTPStatus.FOUND
    collection = SolutionCollection.objects.get(kind=SolutionCollection.Kind.ADMIN_CURATED)
    assert list(collection.entries.values_list("share_id", flat=True)) == [share.pk for share in sources.shares[::-1]]
    response = Client().get(reverse("solutions:public_collection", args=[collection.token]))
    assert response.status_code == HTTPStatus.OK
    assert "SHARED-PROOF-1" not in response.content.decode()
    assert "SHARED-PROOF-2" in response.content.decode()
