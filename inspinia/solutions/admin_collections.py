"""Site-owned curation of existing public copies, with no private-source fallback."""

import json
import logging
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.db.models import TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from inspinia.solutions.collection_views import MAX_COLLECTION_BYTES
from inspinia.solutions.collection_views import MAX_COLLECTION_SOLUTIONS
from inspinia.solutions.forms import SolutionCollectionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionCollectionEntry
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.sharing import public_collection_url
from inspinia.solutions.sharing import snapshot_digest
from inspinia.solutions.sharing import whatsapp_share_url
from inspinia.users.roles import user_has_admin_role

logger = logging.getLogger(__name__)
PAGE_SIZE = 25
REVIEW_SALT = "solutions.admin-curated-collection-review"
MAX_SHARE_ID = (1 << 63) - 1


def parse_refs(values, *, allow_empty=True):
    """Validate and canonicalize bounded, generation-bound public-share references."""
    if len(values) > MAX_COLLECTION_SOLUTIONS or (not values and not allow_empty):
        message = f"Select between 1 and {MAX_COLLECTION_SOLUTIONS} public solutions."
        raise ValidationError(message)
    refs, ids = [], set()
    for value in values:
        try:
            raw_id, raw_token = value.split(":")
            share_id, token = int(raw_id), uuid.UUID(raw_token)
        except (AttributeError, TypeError, ValueError) as exc:
            message = "Choose solutions from the public solutions list."
            raise ValidationError(message) from exc
        if not 0 < share_id <= MAX_SHARE_ID or share_id in ids:
            message = "Select each public solution only once."
            raise ValidationError(message)
        refs.append(f"{share_id}:{token}")
        ids.add(share_id)
    return refs


def _ref_parts(ref):
    share_id, token = ref.split(":")
    return int(share_id), token


def _metadata():
    # Project individual JSON leaves, never proof bodies, images, or private titles.
    return SolutionPublicShare.objects.annotate(
        shared_title=Cast(KT("snapshot__title"), output_field=TextField()),
        shared_problem=Cast(KT("snapshot__problem__label"), output_field=TextField()),
        shared_author=Cast(KT("snapshot__author"), output_field=TextField()),
    )


def _metadata_values(queryset):
    return queryset.values("pk", "token", "is_active", "shared_title", "shared_problem", "shared_author")


def _metadata_row(row, ref):
    share_id, token = _ref_parts(ref)
    available = bool(row and row["is_active"] and str(row["token"]) == token)
    return {
        "ref": ref,
        "id": share_id,
        "label": row["shared_title"] or "Untitled solution" if available else "Unavailable shared solution",
        "shared_title": row["shared_title"] or "Untitled solution" if available else "",
        "shared_problem": row["shared_problem"] or "" if available else "",
        "author": row["shared_author"] or "" if available else "",
        "available": available,
        "public_url": settings.PUBLIC_SITE_ORIGIN.rstrip("/")
        + reverse("solutions:public_solution", args=[row["token"]]) if available else "",
    }


def selection_rows(refs):
    """Hydrate validated selection references using only saved public metadata."""
    ids = [_ref_parts(ref)[0] for ref in refs]
    by_id = {row["pk"]: row for row in _metadata_values(_metadata().filter(pk__in=ids))}
    return [_metadata_row(by_id.get(_ref_parts(ref)[0]), ref) for ref in refs]


def _require_admin(request, *, refresh=False):
    user = request.user
    if refresh:
        user = get_user_model().objects.filter(pk=user.pk).only("role", "is_superuser", "is_active").first()
    if not user_has_admin_role(user) or not user.is_active:
        raise PermissionDenied


def _response(request, template, context, *, status=200):
    response = render(request, template, context, status=status)
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _collections():
    return SolutionCollection.objects.filter(kind=SolutionCollection.Kind.ADMIN_CURATED, owner__isnull=True)


@login_required
@never_cache
@require_GET
def admin_collection_selection_view(request):
    """Rehydrate an ordered basket without loading any proof or private fields."""
    _require_admin(request)
    try:
        refs = parse_refs(request.GET.getlist("share"))
    except ValidationError as exc:
        response = JsonResponse({"error": " ".join(exc.messages)}, status=400)
    else:
        response = JsonResponse({"shares": selection_rows(refs)})
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@never_cache
@require_GET
def admin_collections_view(request):
    _require_admin(request)
    query = request.GET.get("q", "").strip()[:200]
    status_filter = request.GET.get("status", "")
    collections = _collections()
    if query:
        collections = collections.filter(title__icontains=query)
    if status_filter in {"active", "stopped"}:
        collections = collections.filter(is_active=status_filter == "active")
    else:
        status_filter = ""
    collections = collections.annotate(
        total_entries=Count("entries"),
        available_entries=Count("entries", filter=Q(
            entries__share__is_active=True, entries__share__token=F("entries__share_token"),
        )),
    ).only("pk", "title", "token", "is_active", "updated_at").order_by("-updated_at", "-pk")
    page = Paginator(collections, PAGE_SIZE).get_page(request.GET.get("page"))
    for collection in page:
        collection.public_url = public_collection_url(collection) if collection.is_active else ""
    return _response(request, "solutions/admin-collections.html", {
        "page_obj": page, "filters": {"q": query, "status": status_filter},
        "pagination_query": urlencode({"q": query, "status": status_filter}),
    })


def _collection(request, collection_pk, action):
    if collection_pk is None:
        return None
    queryset = _collections()
    if request.method == "POST" and action in {"publish", "stop"}:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=collection_pk)


def _existing_refs(collection):
    if collection is None:
        return []
    return [f"{share_id}:{token}" for share_id, token in collection.entries.values_list("share_id", "share_token")]


def _merge_refs(existing, incoming):
    by_id = {_ref_parts(ref)[0]: ref for ref in existing}
    merged = existing.copy()
    for ref in incoming:
        share_id = _ref_parts(ref)[0]
        if share_id in by_id:
            if by_id[share_id] != ref:
                message = "Remove the unavailable entry before selecting its new shared version."
                raise ValidationError(message)
            continue
        merged.append(ref)
        by_id[share_id] = ref
    if len(merged) > MAX_COLLECTION_SOLUTIONS:
        message = f"This would exceed {MAX_COLLECTION_SOLUTIONS} entries. Reduce your selection and try again."
        raise ValidationError(message)
    return merged


def _picker(data):
    query = data.get("picker_q", "").strip()[:200]
    sort = data.get("picker_sort", "updated")
    shares = _metadata().filter(is_active=True)
    if query:
        shares = shares.filter(
            Q(shared_title__icontains=query) | Q(shared_problem__icontains=query)
            | Q(solution__author__name__icontains=query) | Q(solution__author__email__icontains=query),
        )
    ordering = ("shared_title", "pk") if sort == "title" else ("-updated_at", "-pk")
    sort = "title" if sort == "title" else "updated"
    page = Paginator(_metadata_values(shares.order_by(*ordering)), PAGE_SIZE).get_page(data.get("picker_page"))
    page.object_list = [_metadata_row(row, f"{row['pk']}:{row['token']}") for row in page]
    return page, query, sort


def _review_rows(refs, *, lock=False):
    ids = [_ref_parts(ref)[0] for ref in refs]
    if lock:
        solution_ids = list(SolutionPublicShare.objects.filter(pk__in=ids).values_list("solution_id", flat=True))
        # Match single-share mutation locking, then discard all prior share state.
        list(ProblemSolution.objects.filter(pk__in=solution_ids).order_by("pk").select_for_update(
            of=("self",),
        ).values_list("pk", flat=True))
    by_id = {share.pk: share for share in SolutionPublicShare.objects.filter(pk__in=ids).only(
        "pk", "solution_id", "token", "revision", "is_active", "snapshot",
    )}
    rows, states, total_bytes = [], [], 0
    for ref in refs:
        share_id, token = _ref_parts(ref)
        share = by_id.get(share_id)
        if share is None or not share.is_active or str(share.token) != token:
            message = "A selected public copy is unavailable. Remove it or select its current shared version."
            raise ValidationError(message)
        total_bytes += len(json.dumps(share.snapshot, ensure_ascii=False).encode())
        if total_bytes > MAX_COLLECTION_BYTES:
            message = "This collection is too large. Select fewer solutions."
            raise ValidationError(message)
        rows.append({"share": share, "snapshot": share.snapshot, "anchor": f"review-share-{share.pk}"})
        states.append({
            "id": share.pk, "token": str(share.token), "revision": str(share.revision),
            "digest": snapshot_digest(share.snapshot),
        })
    return rows, states


def _review_payload(request, collection, form, states):
    return {
        "actor": request.user.pk, "kind": SolutionCollection.Kind.ADMIN_CURATED,
        "collection": collection.pk if collection else None,
        "revision": str(collection.revision) if collection else "",
        "title": form.cleaned_data["title"], "introduction": form.cleaned_data["introduction"],
        "items": states,
    }


def _validate_review(token, payload):
    try:
        reviewed = signing.loads(token, salt=REVIEW_SALT, max_age=3600)
    except signing.BadSignature as exc:
        message = "This review expired or is invalid. Review the collection again."
        raise ValidationError(message) from exc
    if reviewed != payload:
        message = "A selected public copy or the collection changed. Review the current copies again."
        raise ValidationError(message)


def _log_action(request, collection, action):
    actor_id, collection_id, revision = request.user.pk, collection.pk, str(collection.revision)
    transaction.on_commit(lambda: logger.info(
        "Curated collection action=%s actor_id=%s collection_id=%s revision=%s",
        action, actor_id, collection_id, revision,
    ))


def _manage_redirect(collection, flow):
    url = reverse("solutions:admin_collection_edit", args=[collection.pk])
    return redirect(url + "?" + urlencode({"completed_flow": flow}))


def _publish(request, collection, form, rows, flow):
    action = "create" if collection is None else "update" if collection.is_active else "reshare"
    if collection is None:
        collection = SolutionCollection(kind=SolutionCollection.Kind.ADMIN_CURATED, owner=None)
    elif not collection.is_active:
        collection.token = uuid.uuid4()
    collection.title = form.cleaned_data["title"]
    collection.introduction = form.cleaned_data["introduction"]
    collection.is_active = True
    collection.revision = uuid.uuid4()
    collection.save()
    existing = {entry.share_id: entry for entry in collection.entries.all()}
    keep = []
    for position, row in enumerate(rows, start=1):
        share = row["share"]
        entry = existing.get(share.pk)
        if entry is None:
            entry = SolutionCollectionEntry(collection=collection, share=share)
        elif entry.share_token != share.token:
            entry.anchor = uuid.uuid4()
        entry.position = position
        entry.share_token = share.token
        entry.save()
        keep.append(entry.pk)
    collection.entries.exclude(pk__in=keep).delete()
    _log_action(request, collection, action)
    messages.success(request, "The public curated collection is ready.")
    return _manage_redirect(collection, flow)


def _flow(data):
    try:
        return str(uuid.UUID(data.get("flow", "")))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid4())


def _target_redirect(request, incoming, flow):
    target_id = request.GET.get("target_collection", "")
    if not target_id.isdecimal() or len(target_id) > len(str(MAX_SHARE_ID)) or not 0 < int(target_id) <= MAX_SHARE_ID:
        message = "Choose a curated collection."
        raise ValidationError(message)
    target = get_object_or_404(_collections(), pk=target_id)
    _merge_refs(_existing_refs(target), incoming)
    query = urlencode({"share": incoming, "flow": flow}, doseq=True)
    return redirect(reverse("solutions:admin_collection_edit", args=[target.pk]) + "?" + query)


def _editor_context(request, collection, form, refs, flow):
    data = request.POST if request.method == "POST" else request.GET
    page, query, sort = _picker(data)
    share_url = public_collection_url(collection) if collection and collection.is_active else ""
    return {
        "collection": collection, "collection_revision": str(collection.revision) if collection else "",
        "form": form, "selected_shares": selection_rows(refs), "picker_page": page,
        "picker_q": query, "picker_sort": sort, "flow": flow,
        "other_collections": _collections().values("pk", "title", "is_active"),
        "target_collection": data.get("target_collection", ""),
        "max_collection_solutions": MAX_COLLECTION_SOLUTIONS,
        "share_url": share_url, "whatsapp_url": whatsapp_share_url(share_url) if share_url else "",
        "solution_media_url": settings.MEDIA_URL, "admin_user_id": request.user.pk,
        "completed_flow": request.GET.get("completed_flow", ""),
    }


def _editor_result(request, collection, context, refs, action):
    form = context["form"]
    context.update(review_rows=[], review_token="", conflict=False)
    current_revision = str(collection.revision) if collection else ""
    if request.method == "POST" and request.POST.get("collection_revision", "") != current_revision:
        context.update(
            conflict=True, collection_revision=request.POST.get("collection_revision", ""),
            selection_error=(
                "Another administrator changed this collection. Reload the latest version before reviewing."
            ),
        )
        return _response(request, "solutions/admin-collection-edit.html", context, status=409)
    if context["selection_error"]:
        return _response(request, "solutions/admin-collection-edit.html", context, status=400)
    if action in {"review", "publish"}:
        if not form.is_valid():
            return _response(request, "solutions/admin-collection-edit.html", context, status=400)
        try:
            parse_refs(refs, allow_empty=False)
            rows, states = _review_rows(refs, lock=action == "publish")
            if action == "publish":
                _require_admin(request, refresh=True)
            payload = _review_payload(request, collection, form, states)
            if action == "publish":
                _validate_review(request.POST.get("review_token", ""), payload)
            else:
                context.update(review_rows=rows, review_token=signing.dumps(payload, salt=REVIEW_SALT))
        except ValidationError as exc:
            context["selection_error"] = " ".join(exc.messages)
            return _response(
                request, "solutions/admin-collection-edit.html", context,
                status=409 if action == "publish" else 400,
            )
        if action == "publish":
            return _publish(request, collection, form, rows, context["flow"])
    return _response(request, "solutions/admin-collection-edit.html", context)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@transaction.atomic
def admin_collection_edit_view(request, collection_pk=None):
    _require_admin(request)
    action = request.POST.get("action", "") if request.method == "POST" else ""
    # Native paging buttons submit their page rather than an action. Infer the
    # read-only browse action without leaving hidden submit controls in history.
    if request.method == "POST" and not action and "picker_page" in request.POST:
        action = "browse"
    collection = _collection(request, collection_pk, action)
    data = request.POST if request.method == "POST" else request.GET
    flow = _flow(data)
    if action == "stop" and collection:
        if data.get("collection_revision", "") == str(collection.revision):
            _require_admin(request, refresh=True)
            collection.is_active = False
            collection.revision = uuid.uuid4()
            collection.save(update_fields=["is_active", "revision", "updated_at"])
            _log_action(request, collection, "stop")
            messages.success(request, "Collection sharing stopped. Individual solution links are unchanged.")
            return _manage_redirect(collection, flow)
    elif request.method == "POST" and action not in {"browse", "edit", "review", "publish"}:
        return HttpResponseBadRequest("Review the collection before sharing it.")
    form = SolutionCollectionForm(
        request.POST if request.method == "POST" and action != "stop" else None, instance=collection,
    )
    refs, incoming, error = [], [], ""
    try:
        incoming = parse_refs(data.getlist("share"))
        if request.method == "GET" and collection is None and data.get("target_collection"):
            return _target_redirect(request, incoming, flow)
        refs = _merge_refs(_existing_refs(collection), incoming) if request.method == "GET" else incoming
        if action == "stop":
            refs = _existing_refs(collection)
    except ValidationError as exc:
        refs = _existing_refs(collection) if collection else incoming
        error = " ".join(exc.messages)
    context = _editor_context(request, collection, form, refs, flow)
    context["selection_error"] = error
    return _editor_result(request, collection, context, refs, action)
