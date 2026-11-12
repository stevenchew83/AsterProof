from django.http import HttpRequest
from django.http import HttpResponseBadRequest
from django.template.loader import render_to_string


def bad_request(request: HttpRequest, exception: Exception | None = None) -> HttpResponseBadRequest:
    # An early rejection can happen before authentication middleware sets request.user.
    return HttpResponseBadRequest(render_to_string("400.html"))
