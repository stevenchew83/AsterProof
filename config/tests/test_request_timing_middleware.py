import logging
from http import HTTPStatus

import pytest
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
        return HttpResponse("ok")

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/test-path/")
    response = mw(request)
    assert response.status_code == HTTPStatus.OK
    assert any("request_timing" in r.message for r in caplog.records)
    assert any("/test-path/" in r.message for r in caplog.records)
