"""Owner-only collection editing, with an explicit, version-bound sharing review."""

import json
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.solutions.forms import SolutionCollectionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionCollectionEntry
from inspinia.solutions.sharing import public_collection_url
from inspinia.solutions.sharing import snapshot_digest
from inspinia.solutions.sharing import whatsapp_share_url
from inspinia.solutions.views import _public_snapshot
from inspinia.solutions.views import _write_shared_snapshot

MAX_COLLECTION_SOLUTIONS = 20
MAX_COLLECTION_BYTES = 5 * 1024 * 1024
REVIEW_SALT = "solutions.collection-review"


def _solution_ids(values):
    if not 1 <= len(values) <= MAX_COLLECTION_SOLUTIONS:
        message = f"Select between 1 and {MAX_COLLECTION_SOLUTIONS} solutions."
        raise ValidationError(message)
    try:
        ids = [int(value) for value in values]
    except (TypeError, ValueError) as exc:
        message = "Choose solutions from your workspace."
        raise ValidationError(message) from exc
    if any(value <= 0 for value in ids) or len(set(ids)) != len(ids):
        message = "Select each solution only once."
        raise ValidationError(message)
    return ids


def _selected_solutions(owner, ids, *, lock=False):
    queryset = ProblemSolution.objects.filter(author=owner, pk__in=ids).select_related("author", "problem")
    if lock:
        # Serialize with the existing single-solution share actions.
        queryset = queryset.select_for_update(of=("self",))
    by_id = {solution.pk: solution for solution in queryset.order_by("pk")}
    if len(by_id) != len(ids):
        raise Http404
    return [by_id[pk] for pk in ids]


def _review(solutions):
    rows, states, total_bytes = [], [], 0
    for solution in solutions:
        share = getattr(solution, "public_share", None)
        active = bool(share and share.is_active)
        snapshot = share.snapshot if active else _public_snapshot(solution)
        total_bytes += len(json.dumps(snapshot, ensure_ascii=False).encode())
        if total_bytes > MAX_COLLECTION_BYTES:
            message = "This collection is too large. Select fewer solutions."
            raise ValidationError(message)
        states.append(
            {
                "id": solution.pk,
                "active": active,
                "revision": str(share.revision) if share else "",
                "token": str(share.token) if share else "",
                "source": "" if active else solution.updated_at.isoformat(),
                "digest": snapshot_digest(snapshot),
            },
        )
        rows.append(
            {
                "solution": solution,
                "snapshot": snapshot,
                "is_shared": active,
                "anchor": f"review-{solution.pk}",
                "share_manage_url": reverse("solutions:problem_solution_share", args=[solution.problem.problem_uuid]),
            },
        )
    return rows, states


def _review_payload(request, collection, form, states):
    return {
        "owner": request.user.pk,
        "collection": collection.pk if collection else None,
        "revision": str(collection.revision) if collection else "",
        "title": form.cleaned_data["title"],
        "introduction": form.cleaned_data["introduction"],
        "items": states,
    }


def _publish(request, collection, form, rows):
    if collection is None:
        collection = SolutionCollection(owner=request.user)
    elif not collection.is_active:
        collection.token = uuid.uuid4()
    collection.title = form.cleaned_data["title"]
    collection.introduction = form.cleaned_data["introduction"]
    collection.is_active = True
    collection.revision = uuid.uuid4()
    collection.save()
    keep = []
    for position, row in enumerate(rows, start=1):
        solution = row["solution"]
        share = getattr(solution, "public_share", None)
        if not row["is_shared"]:
            share = _write_shared_snapshot(solution, share, row["snapshot"])
        entry, _ = SolutionCollectionEntry.objects.update_or_create(
            collection=collection,
            share=share,
            defaults={"position": position, "share_token": share.token},
        )
        keep.append(entry.pk)
    collection.entries.exclude(pk__in=keep).delete()
    messages.success(request, "Your public collection is ready.")
    return redirect("solutions:collection_edit", collection_pk=collection.pk)


def _existing_collection_redirect(request):
    target_id = request.GET["target_collection"]
    if not target_id.isdecimal():
        raise Http404
    target = get_object_or_404(SolutionCollection, pk=target_id, owner=request.user)
    return redirect(
        reverse("solutions:collection_edit", args=[target.pk])
        + "?"
        + urlencode(
            {"solution": request.GET.getlist("solution")},
            doseq=True,
        ),
    )


def _validate_review(request, payload):
    try:
        reviewed = signing.loads(request.POST.get("review_token", ""), salt=REVIEW_SALT, max_age=3600)
    except signing.BadSignature as exc:
        message = "This review expired or is invalid. Review the collection again."
        raise ValidationError(message) from exc
    if reviewed != payload:
        message = "A selected solution or collection changed. Review the current copies again."
        raise ValidationError(message)


def _owner_collection(request, collection_pk):
    if collection_pk is None:
        return None
    queryset = SolutionCollection.objects.filter(owner=request.user)
    if request.method == "POST":
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=collection_pk)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@transaction.atomic
def collection_edit_view(request, collection_pk=None):
    if request.method == "GET" and request.GET.get("target_collection"):
        return _existing_collection_redirect(request)
    collection = _owner_collection(request, collection_pk)
    current_revision = str(collection.revision) if collection else ""
    if request.method == "POST" and request.POST.get("collection_revision", "") != current_revision:
        return HttpResponseBadRequest(
            "This collection changed in another tab. Reload it before making changes.",
            status=409,
        )
    action = request.POST.get("action") if request.method == "POST" else None
    if action == "stop" and collection:
        collection.is_active = False
        collection.revision = uuid.uuid4()
        collection.save(update_fields=["is_active", "revision", "updated_at"])
        messages.success(request, "Collection sharing stopped. Individual solution links are unchanged.")
        return redirect("solutions:collection_edit", collection_pk=collection.pk)
    if request.method == "POST" and action not in {"edit", "review", "publish"}:
        return HttpResponseBadRequest("Review the collection before sharing it.")

    form = SolutionCollectionForm(request.POST or None, instance=collection)
    existing_ids = list(collection.entries.values_list("share__solution_id", flat=True)) if collection else []
    values = (
        request.POST.getlist("solution")
        if request.method == "POST"
        else list(
            dict.fromkeys(
                [
                    *map(str, existing_ids),
                    *request.GET.getlist("solution"),
                ],
            ),
        )
    )
    selected, review_rows, review_token, status = [], [], "", 200
    try:
        ids = _solution_ids(values) if values or request.method == "POST" else []
        selected = _selected_solutions(request.user, ids, lock=action == "publish")
        if action in {"review", "publish"} and form.is_valid():
            review_rows, states = _review(selected)
            payload = _review_payload(request, collection, form, states)
            if action == "publish":
                _validate_review(request, payload)
                return _publish(request, collection, form, review_rows)
            review_token = signing.dumps(payload, salt=REVIEW_SALT)
        elif action in {"review", "publish"}:
            status = 400
    except ValidationError as exc:
        # Bind an empty GET form as well so validation messages can be attached.
        if not form.is_bound:
            form = SolutionCollectionForm({"title": collection.title if collection else ""}, instance=collection)
        form.is_valid()
        form.add_error(None, exc)
        review_rows = []
        status = 409 if action == "publish" else 400

    catalogue = list(ProblemSolution.objects.filter(author=request.user).select_related("problem"))
    return render(
        request,
        "solutions/collection-edit.html",
        {
            "collection": collection,
            "collection_revision": current_revision,
            "form": form,
            "selected_solutions": selected,
            "available_solutions": catalogue,
            "other_collections": SolutionCollection.objects.filter(owner=request.user),
            "review_rows": review_rows if review_token else [],
            "review_token": review_token,
            "max_collection_solutions": MAX_COLLECTION_SOLUTIONS,
            "share_url": public_collection_url(collection) if collection and collection.is_active else "",
            "whatsapp_url": whatsapp_share_url(public_collection_url(collection))
            if collection and collection.is_active
            else "",
            "solution_media_url": settings.MEDIA_URL,
        },
        status=status,
    )
