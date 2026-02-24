from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import NoReverseMatch
from django.urls import reverse


class BlockedUserMiddleware:
    def __init__(self, get_response):  # noqa: ANN001
        self.get_response = get_response

    def __call__(self, request):  # noqa: ANN001
        if getattr(request, "user", None) and request.user.is_authenticated and getattr(request.user, "is_banned", False):
            logout(request)
            try:
                return redirect(reverse("account_login"))
            except NoReverseMatch:
                return redirect("/")
        return self.get_response(request)
