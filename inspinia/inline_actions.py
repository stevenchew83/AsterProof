from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.cache import add_never_cache_headers


def wants_inline_action(request):
    return request.headers.get("Accept") == "application/json"


def inline_action_response(message, *, html=None, url=None, status=200):
    payload = {"message": message}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    response = JsonResponse(payload, status=status)
    add_never_cache_headers(response)
    return response


def inline_action_fragment(request, message, template, context, *, url=None):
    return inline_action_response(
        message, html=render_to_string(template, context, request=request), url=url,
    )
