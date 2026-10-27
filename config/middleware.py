from __future__ import annotations

import logging
import time
import uuid
from contextlib import ExitStack
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import connections

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


class SQLTiming:
    """Keep only execution counts and elapsed time, never SQL or parameters."""

    def __init__(self):
        self.count = 0
        self.duration_ms = 0.0

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        self.count += 1
        try:
            return execute(sql, params, many, context)
        finally:
            self.duration_ms += (time.perf_counter() - started) * 1000


class RequestTimingMiddleware:
    """Measure synchronous request handling, including rendering and SQL round trips.

    Streaming bodies execute later and are explicitly marked in the log. Routing
    names identify endpoints without recording URL parameters or user identities.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "REQUEST_TIMING_LOG", False) or request.path_info.startswith(
            ("/static/", "/media/", "/healthz/"),
        ):
            return self.get_response(request)

        start = time.perf_counter()
        request.request_id = uuid.uuid4().hex
        sql_timing = SQLTiming()
        response = None
        try:
            with ExitStack() as wrappers:
                for connection in connections.all():
                    wrappers.enter_context(connection.execute_wrapper(sql_timing))
                response = self.get_response(request)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            route = getattr(getattr(request, "resolver_match", None), "view_name", None) or "unresolved"
            logger.info(
                "request_timing request_id=%s route=%s method=%s status=%s "
                "duration_ms=%.2f sql_count=%s sql_ms=%.2f streaming=%s",
                request.request_id,
                route,
                request.method,
                response.status_code if response is not None else 500,
                duration_ms,
                sql_timing.count,
                sql_timing.duration_ms,
                bool(response is not None and response.streaming),
            )
        timing = f'app;dur={duration_ms:.2f}, sql;dur={sql_timing.duration_ms:.2f};desc="{sql_timing.count} queries"'
        existing = response.get("Server-Timing")
        response["Server-Timing"] = f"{existing}, {timing}" if existing else timing
        response["X-Request-ID"] = request.request_id
        return response
