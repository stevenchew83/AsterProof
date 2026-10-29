"""Bounded, temporary Solution Writer handoffs owned by the current session."""

import json
import time
from secrets import token_hex
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.urls import reverse

from .forms import PDF_DISPLAY_FIELDS
from .models import SolutionBlockType

WRITER_DRAFT_SESSION_KEY = "solution_writer_handoff"
WRITER_DRAFT_TTL = 7 * 24 * 60 * 60
WRITER_DRAFT_MAX_BYTES = 384_000
WRITER_DRAFT_TOKEN_LENGTH = 32


def writer_handoff_url():
    return reverse("solutions:problem_solution_create") + "?" + urlencode({"from_writer": "1"})


def get_writer_draft(request):
    value = request.session.get(WRITER_DRAFT_SESSION_KEY)
    if not isinstance(value, dict):
        return None
    if (
        value.get("version") != 1
        or not isinstance(value.get("stored_at"), (int, float))
        or not 0 <= time.time() - value["stored_at"] < WRITER_DRAFT_TTL
        or not isinstance(value.get("document"), dict)
        or not isinstance(value.get("token"), str)
        or len(value["token"]) != WRITER_DRAFT_TOKEN_LENGTH
    ):
        request.session.pop(WRITER_DRAFT_SESSION_KEY, None)
        return None
    owner = str(request.user.pk) if request.user.is_authenticated else None
    if value.get("owner") is not None and value["owner"] != owner:
        return None
    if owner is not None and value.get("owner") is None:
        value = {**value, "owner": owner}
        request.session[WRITER_DRAFT_SESSION_KEY] = value
    return value


def stage_writer_draft(request, form, formset):
    document = {name: form.cleaned_data[name] for name in form.fields if name != "pdf_options_present"}
    document["blocks"] = [
        {
            "block_type": block.cleaned_data["block_type"].pk if block.cleaned_data["block_type"] else None,
            "title": block.cleaned_data["title"],
            "body_format": block.cleaned_data["body_format"],
            "body_source": block.cleaned_data["body_source"],
        }
        for block in formset.ordered_forms
    ]
    if len(json.dumps(document, ensure_ascii=False).encode()) > WRITER_DRAFT_MAX_BYTES:
        msg = "This document is too large to carry into your workspace. Shorten it and try again."
        raise ValidationError(msg)
    request.session[WRITER_DRAFT_SESSION_KEY] = {
        "version": 1, "token": token_hex(16), "stored_at": time.time(), "document": document,
        "owner": str(request.user.pk) if request.user.is_authenticated else None,
    }


def writer_editor_initial(draft):
    document = draft["document"]
    initial = {name: document[name] for name in ("title", *PDF_DISPLAY_FIELDS)}
    blocks = list(document["blocks"])
    if document.get("problem_statement"):
        section_type = SolutionBlockType.objects.filter(slug="section").values_list("pk", flat=True).first()
        blocks.insert(0, {
            "block_type": section_type, "title": "Original problem statement", "body_format": "latex",
            "body_source": document["problem_statement"],
        })
    return initial, blocks
