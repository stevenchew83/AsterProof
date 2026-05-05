from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from inspinia.users.monitoring import touch_tracked_session
from inspinia.users.roles import user_can_access_app_features


class RequireApprovedUserMiddleware:
    exempt_path_prefixes = ("/accounts/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not getattr(user, "is_authenticated", False)
            or user_can_access_app_features(user)
            or self._is_exempt_path(request.path)
        ):
            return self.get_response(request)

        pending_url = reverse("users:approval_pending")
        if request.path == pending_url:
            return self.get_response(request)
        return redirect("users:approval_pending")

    def _is_exempt_path(self, path: str) -> bool:
        admin_path_prefix = f"/{settings.ADMIN_URL.strip('/')}/"
        return path.startswith((*self.exempt_path_prefixes, admin_path_prefix))


class TrackActiveSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "user", None) is not None and getattr(request.user, "is_authenticated", False):
            touch_tracked_session(request)
        return response
