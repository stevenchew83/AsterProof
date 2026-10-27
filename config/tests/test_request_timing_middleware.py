# ruff: noqa: EM101, FBT003, PLR2004
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db import connections
from django.http import HttpResponse
from django.http import StreamingHttpResponse
from django.test import RequestFactory

from config.middleware import RequestTimingMiddleware
from config.middleware import SQLTiming


@pytest.fixture(autouse=True)
def enabled_timing(settings):
    settings.REQUEST_TIMING_LOG = True


def test_disabled_timing_has_no_headers_or_logs(settings, caplog):
    settings.REQUEST_TIMING_LOG = False
    caplog.set_level(logging.INFO, logger="config.middleware")
    response = RequestTimingMiddleware(lambda request: HttpResponse("ok"))(RequestFactory().get("/private/"))
    assert "Server-Timing" not in response
    assert "X-Request-ID" not in response
    assert not caplog.records


@pytest.mark.parametrize("path", ["/static/app.js", "/media/private.png", "/healthz/"])
def test_infrastructure_endpoints_skip_timing(path, caplog):
    caplog.set_level(logging.INFO, logger="config.middleware")
    response = RequestTimingMiddleware(lambda request: HttpResponse("ok"))(RequestFactory().get(path))
    assert "Server-Timing" not in response
    assert not caplog.records


def test_logs_only_route_identity_and_aggregate_timings(caplog):
    caplog.set_level(logging.INFO, logger="config.middleware")
    request = RequestFactory().get("/users/private-identity/?token=secret", HTTP_X_REQUEST_ID="untrusted-secret")
    request.resolver_match = SimpleNamespace(view_name="users:detail")

    class UnusedUser:
        @property
        def pk(self):
            pytest.fail("Timing must not evaluate user identities")

    request.user = UnusedUser()
    response = RequestTimingMiddleware(lambda request: HttpResponse("ok", status=201))(request)
    message = caplog.records[0].getMessage()
    assert "route=users:detail method=GET status=201" in message
    assert "sql_count=0" in message
    assert re.search(r"duration_ms=\d+\.\d+ sql_count=0 sql_ms=\d+\.\d+", message)
    assert "private-identity" not in message
    assert "secret" not in message
    assert "user_id" not in message
    assert re.fullmatch(r"[0-9a-f]{32}", response["X-Request-ID"])
    assert response["X-Request-ID"] in message
    assert response["Server-Timing"].startswith("app;dur=")


@pytest.mark.django_db
def test_real_queries_are_counted_without_recording_sql_or_values(settings, caplog):
    settings.DEBUG = False
    caplog.set_level(logging.INFO, logger="config.middleware")
    original_wrappers = list(connection.execute_wrappers)
    original_debug = connection.force_debug_cursor

    def view(request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT %s", ["private-sql-value"])
            assert cursor.fetchone()[0] == "private-sql-value"
            cursor.execute("SELECT 1")
        return HttpResponse("ok")

    response = RequestTimingMiddleware(view)(RequestFactory().get("/private-query/"))
    assert 'desc="2 queries"' in response["Server-Timing"]
    assert "sql_count=2" in caplog.records[0].getMessage()
    assert "private-sql-value" not in caplog.text
    assert "SELECT" not in caplog.text
    assert connection.execute_wrappers == original_wrappers
    assert connection.force_debug_cursor == original_debug


def test_sql_failure_is_timed_and_propagated(monkeypatch):
    moments = iter([1.0, 1.025])
    monkeypatch.setattr("config.middleware.time.perf_counter", lambda: next(moments))
    collector = SQLTiming()

    def fail(*args):
        raise ValueError("private-database-detail")

    with pytest.raises(ValueError, match="private-database-detail"):
        collector(fail, "private-query", ["private-value"], False, {})
    assert collector.count == 1
    assert collector.duration_ms == pytest.approx(25)
    assert set(vars(collector)) == {"count", "duration_ms"}


def test_every_database_alias_is_instrumented(monkeypatch):
    collectors = []

    class Wrapper:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Database:
        def execute_wrapper(self, collector):
            collectors.append(collector)
            return Wrapper()

    monkeypatch.setattr("config.middleware.connections", SimpleNamespace(all=lambda: [Database(), Database()]))
    RequestTimingMiddleware(lambda request: HttpResponse("ok"))(RequestFactory().get("/"))
    assert len(collectors) == 2
    assert collectors[0] is collectors[1]


def test_unhandled_view_error_is_logged_and_wrappers_are_removed(caplog):
    caplog.set_level(logging.INFO, logger="config.middleware")
    original_wrappers = list(connection.execute_wrappers)

    def view(request):
        raise ValueError("private-failure-detail")

    with pytest.raises(ValueError, match="private-failure-detail"):
        RequestTimingMiddleware(view)(RequestFactory().get("/error/"))
    assert connection.execute_wrappers == original_wrappers
    assert "status=500" in caplog.records[0].getMessage()
    assert "private-failure-detail" not in caplog.text


def test_preserves_existing_server_timing_and_marks_streaming(caplog):
    caplog.set_level(logging.INFO, logger="config.middleware")

    def view(request):
        response = StreamingHttpResponse(iter(["body"]))
        response["Server-Timing"] = "existing;dur=1"
        return response

    response = RequestTimingMiddleware(view)(RequestFactory().get("/stream/"))
    assert response["Server-Timing"].startswith("existing;dur=1, app;dur=")
    assert "streaming=True" in caplog.records[0].getMessage()
    assert b"".join(response.streaming_content) == b"body"


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_do_not_share_sql_counters():
    def perform(count):
        def view(request):
            with connection.cursor() as cursor:
                for _ in range(count):
                    cursor.execute("SELECT 1")
            return HttpResponse("ok")

        try:
            response = RequestTimingMiddleware(view)(RequestFactory().get("/parallel/"))
            assert not connection.execute_wrappers
            return response["Server-Timing"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(perform, [1, 3]))
    assert 'desc="1 queries"' in first
    assert 'desc="3 queries"' in second
