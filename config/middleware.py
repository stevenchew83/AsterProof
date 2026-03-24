from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


class RequestTimingMiddleware:
    """Log request duration when settings.REQUEST_TIMING_LOG is True."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "REQUEST_TIMING_LOG", False):
            return self.get_response(request)

        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000
        user_id = getattr(getattr(request, "user", None), "pk", None)
        logger.info(
            "request_timing path=%s method=%s status=%s duration_ms=%.2f user_id=%s",
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            getattr(response, "status_code", 0),
            duration_ms,
            user_id,
        )
        return response
