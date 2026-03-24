import logging
import re
from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from config.middleware import RequestTimingMiddleware


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


def test_request_timing_middleware_noop_when_disabled(settings, rf: RequestFactory):
    settings.REQUEST_TIMING_LOG = False

    def get_response(request):
        return HttpResponse("ok")

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/users/1/")
    response = mw(request)
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"ok"


def test_request_timing_middleware_logs_when_enabled(settings, rf: RequestFactory, caplog):
    settings.REQUEST_TIMING_LOG = True
    caplog.set_level(logging.INFO)

    def get_response(request):
        return HttpResponse("ok", status=HTTPStatus.CREATED)

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/test-path/")
    request.user = AnonymousUser()
    response = mw(request)
    assert response.status_code == HTTPStatus.CREATED
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(messages) == 1
    msg = messages[0]
    assert msg.startswith("request_timing ")
    assert "/test-path/" in msg
    assert "method=GET" in msg
    assert "status=201" in msg
    assert re.search(r"duration_ms=\d+\.\d+", msg)
    assert "user_id=None" in msg


def test_request_timing_middleware_log_includes_authenticated_user_id(settings, rf: RequestFactory, caplog):
    settings.REQUEST_TIMING_LOG = True
    caplog.set_level(logging.INFO)

    class _User:
        is_authenticated = True
        pk = 42

    def get_response(request):
        return HttpResponse("x")

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/x/")
    request.user = _User()
    mw(request)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(messages) == 1
    assert "user_id=42" in messages[0]
