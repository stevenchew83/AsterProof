from __future__ import annotations

from inspinia.users.monitoring import touch_tracked_session


class TrackActiveSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "user", None) is not None and getattr(request.user, "is_authenticated", False):
            touch_tracked_session(request)
        return response
