"""Training reading, private authoring and explicit review/publication actions."""

import difflib
import json
import uuid
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.learning.catalogue import catalogue_context
from inspinia.learning.catalogue import subject_rows
from inspinia.learning.drafts import checkpoint_draft
from inspinia.learning.drafts import create_draft
from inspinia.learning.drafts import editor_context
from inspinia.learning.drafts import save_draft
from inspinia.learning.forms import DocumentEditForm
from inspinia.learning.forms import NewDocumentForm
from inspinia.learning.forms import PathwayForm
from inspinia.learning.models import ContentAction
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContributionProposal
from inspinia.learning.permissions import can_review
from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import module_enabled
from inspinia.learning.permissions import require_contributor
from inspinia.learning.permissions import require_publisher
from inspinia.learning.publication import publish_proposal
from inspinia.learning.publication import review_context
from inspinia.learning.publication import review_proposal
from inspinia.learning.publication import submit_draft
from inspinia.learning.publication import visible_publications
from inspinia.learning.publication import withdraw_document
from inspinia.learning.rendering import render_draft
from inspinia.learning.rendering import render_revision
from inspinia.learning.revisions import LearningConflict
from inspinia.learning.revisions import LearningError
from inspinia.learning.templates import TEACHING_TEMPLATES
from inspinia.pages.catalogue_browser import canonical_concept
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.users.roles import user_can_access_app_features


def workspace_view(view):
    @login_required
    @wraps(view)
    def checked(request, *args, **kwargs):
        if not module_enabled():
            raise Http404
        if not user_can_access_app_features(request.user):
            message = "Approved workspace access is required."
            raise PermissionDenied(message)
        return view(request, *args, **kwargs)

    return checked


REQUEST_LIMIT = 150_000
SOURCE_LIMIT = 64_000


def _payload(request):
    if int(request.META.get("CONTENT_LENGTH") or 0) > REQUEST_LIMIT:
        message = "The document request is too large."
        raise LearningError(message)
    if request.content_type == "application/json":
        try:
            value = json.loads(request.body)
        except (ValueError, UnicodeDecodeError) as exc:
            message = "The editor request is not valid JSON."
            raise LearningError(message) from exc
        if not isinstance(value, dict):
            message = "The editor request must contain document fields."
            raise LearningError(message)
        return value
    return request.POST


@workspace_view
@require_GET
@never_cache
def draft_status(request, draft_id):
    draft = _owned_draft(request, draft_id)
    operation_id = request.GET.get("operation_id", "")
    try:
        operation_id = str(uuid.UUID(operation_id))
    except ValueError:
        return JsonResponse({"found": False}, status=400)
    found = next((row for row in draft.save_receipts if row["id"] == operation_id), None)
    return JsonResponse(
        {
            "found": bool(found),
            "edit_version": draft.edit_version,
            "saved_operation_version": found["version"] if found else None,
            "editor_context": editor_context(draft, request.user),
            "title": draft.title,
            "summary": draft.summary,
            "body_source": draft.body_source,
            "metadata": draft.metadata,
        },
    )


def _error_message(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


def _json_error(exc):
    return JsonResponse({"error": _error_message(exc)}, status=409 if isinstance(exc, LearningConflict) else 400)


def _owned_draft(request, draft_id):
    require_contributor(request.user)
    return get_object_or_404(
        ContentDraft.objects.select_related("document", "base_revision"),
        pk=draft_id,
        author=request.user,
    )


def _form_initial(draft, user):
    return {
        "title": draft.title,
        "summary": draft.summary,
        "body_source": draft.body_source,
        "metadata": draft.metadata,
        "edit_version": draft.edit_version,
        "editor_context": editor_context(draft, user),
        "operation_id": uuid.uuid4(),
    }


def _save_bound_form(form, draft, user):
    data = form.cleaned_data
    # Imported provenance is server-owned; editing the note cannot forge or erase it.
    editable = {
        "concepts",
        "assets",
        "audience",
        "level",
        "objectives",
        "attribution",
        "source_url",
        "estimated_minutes",
    }
    metadata = {key: value for key, value in draft.metadata.items() if key not in editable}
    metadata.update({key: value for key, value in data["metadata"].items() if key in editable})
    return save_draft(
        draft=draft,
        user=user,
        title=data["title"],
        summary=data["summary"],
        source=data["body_source"],
        metadata=metadata,
        base_version=data["edit_version"],
        context=data["editor_context"],
        operation_id=data.get("operation_id"),
    )


@workspace_view
@require_GET
def learn(request):
    from inspinia.training.pathways import published_pathways

    paths = list(published_pathways())
    return render(
        request,
        "learning/learn.html",
        {
            "subjects": subject_rows(),
            "paths": paths,
            "is_publisher": is_publisher(request.user),
            "foundations": next((path for path in paths if path.is_foundations), None),
            "area_total": CatalogueArea.objects.count(),
            "concept_total": CatalogueConcept.objects.filter(redirect__isnull=True).count(),
        },
    )


@workspace_view
@require_GET
def explore(request):
    return render(request, "learning/explore.html", catalogue_context(request.GET, request.user))


@workspace_view
@require_GET
def area_detail(request, area_id):
    area = get_object_or_404(CatalogueArea.objects.select_related("subject"), pk=area_id)
    context = catalogue_context({**request.GET.dict(), "area": area.pk}, request.user)
    context["publications"] = (
        visible_publications(user=request.user)
        .filter(
            Q(document__canonical_area=area) | Q(revision__concept_links__concept__memberships__area=area),
        )
        .distinct()
        .select_related("document", "revision")
    )
    return render(request, "learning/area.html", context)


@workspace_view
@require_GET
def concept_detail(request, concept_id):
    from inspinia.pages.prerequisites import prerequisite_context

    concept = canonical_concept(concept_id)
    if concept is None:
        raise Http404
    if concept.pk != concept_id:
        return redirect("learning:concept", concept_id=concept.pk)
    return render(
        request,
        "learning/concept.html",
        {
            "concept": concept,
            "areas": concept.memberships.select_related("area__subject"),
            "publications": visible_publications(user=request.user)
            .filter(
                revision__concept_links__concept=concept,
            )
            .distinct()
            .select_related("document", "revision"),
            "prerequisites": prerequisite_context(concept.pk),
        },
    )


@workspace_view
@require_GET
@never_cache
def document_read(request, document_id):
    publication = get_object_or_404(
        visible_publications(user=request.user).select_related("document", "revision"),
        document_id=document_id,
    )
    return render(
        request,
        "learning/read.html",
        {
            "publication": publication,
            "revision": publication.revision,
            "rendered_content": render_revision(publication.revision, request.user),
            "public_credit": _public_credit(publication.revision),
            "operation_id": uuid.uuid4(),
        },
    )


def _public_credit(revision):
    try:
        return revision.permission.public_credit
    except AttributeError:
        return ""


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def new_document(request):
    require_contributor(request.user)
    initial = {key: request.GET[key] for key in ("kind", "area", "concept") if key in request.GET}
    form = NewDocumentForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        metadata = {"concepts": [{"id": data["concept"].pk, "role": "primary"}]} if data["concept"] else {}
        try:
            draft = create_draft(
                user=request.user,
                kind=data["kind"],
                title=data["title"],
                area_id=data["area"].pk if data["area"] and data["kind"] != "concept" else None,
                concept_id=data["concept"].pk if data["concept"] and data["kind"] != "overview" else None,
                source=TEACHING_TEMPLATES[data["kind"]] if data["use_template"] else "",
                metadata=metadata,
            )
        except (LearningError, ValidationError) as exc:
            form.add_error(None, _error_message(exc))
        else:
            return redirect("learning:edit", draft_id=draft.pk)
    return render(request, "learning/new.html", {"form": form})


@workspace_view
@require_GET
@never_cache
def my_drafts(request):
    require_contributor(request.user)
    return render(
        request,
        "learning/my-drafts.html",
        {
            "drafts": ContentDraft.objects.filter(author=request.user, is_archived=False).select_related("document"),
            "archived_drafts": ContentDraft.objects.filter(author=request.user, is_archived=True).select_related(
                "document",
            ),
            "proposals": ContributionProposal.objects.filter(author=request.user).select_related(
                "revision",
                "document",
            ),
        },
    )


@workspace_view
@require_POST
@never_cache
def branch_document(request, document_id):
    publication = get_object_or_404(visible_publications(user=request.user), document_id=document_id)
    draft = create_draft(user=request.user, document=publication.document)
    return redirect("learning:edit", draft_id=draft.pk)


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def document_edit(request, draft_id):
    draft = _owned_draft(request, draft_id)
    if draft.is_archived:
        messages.info(request, "Reopen this archived draft from My notes before editing.")
        return redirect("learning:my_drafts")
    form = DocumentEditForm(
        request.POST if request.method == "POST" else None,
        initial=_form_initial(draft, request.user),
    )
    saved = False
    if request.method == "POST" and form.is_valid():
        try:
            draft = _save_bound_form(form, draft, request.user)
            saved = True
            action = request.POST.get("action", "save")
            if action == "submit":
                proposal = submit_draft(
                    draft=draft,
                    user=request.user,
                    agreement_version=getattr(settings, "LEARNING_AGREEMENT_VERSION", ""),
                    rights_confirmed=form.cleaned_data["rights_confirmed"],
                    public_credit=form.cleaned_data["public_credit"],
                    base_version=draft.edit_version,
                    operation_id=form.cleaned_data.get("operation_id"),
                    declaration={
                        "editorial_changes_allowed": form.cleaned_data["editorial_changes_allowed"],
                        "sources": form.cleaned_data["source_permissions"],
                    },
                )
                return redirect("learning:proposal", proposal_id=proposal.pk)
            if action == "checkpoint":
                checkpoint_draft(
                    draft=draft,
                    user=request.user,
                    base_version=draft.edit_version,
                    operation_id=form.cleaned_data.get("operation_id"),
                )
            messages.success(request, "Your private draft was saved.")
            return redirect("learning:edit", draft_id=draft.pk)
        except (LearningError, ValidationError) as exc:
            if saved:
                # Retry the failed checkpoint/submission against the successfully saved text.
                # A save conflict never receives a fresh token for stale text.
                form.data = form.data.copy()
                form.data["edit_version"] = draft.edit_version
                form.data["editor_context"] = editor_context(draft, request.user)
                form.data["operation_id"] = str(uuid.uuid4())
            form.add_error(None, _error_message(exc))
    return render(
        request,
        "learning/editor.html",
        {
            "draft": draft,
            "form": form,
            "rendered_preview": render_draft(draft, request.user),
            "agreement_ready": bool(getattr(settings, "LEARNING_AGREEMENT_APPROVED", False)),
            "agreement_version": getattr(settings, "LEARNING_AGREEMENT_VERSION", ""),
            "editor_concepts": CatalogueConcept.objects.filter(redirect__isnull=True).order_by("name"),
        },
    )


@workspace_view
@require_POST
@never_cache
def draft_save(request, draft_id):
    draft = _owned_draft(request, draft_id)
    try:
        form = DocumentEditForm(_payload(request))
        if not form.is_valid():
            return JsonResponse({"error": "Check the document fields.", "errors": form.errors}, status=400)
        saved = _save_bound_form(form, draft, request.user)
        return JsonResponse(
            {
                "edit_version": saved.edit_version,
                "editor_context": editor_context(saved, request.user),
                "saved_at": saved.updated_at.isoformat(),
                "draft_id": str(saved.pk),
            },
        )
    except (LearningError, ValidationError) as exc:
        return _json_error(exc)


@workspace_view
@require_POST
@never_cache
def draft_preview(request, draft_id):
    draft = _owned_draft(request, draft_id)
    try:
        data = _payload(request)
        source = data.get("body_source", "")
        if not isinstance(source, str) or len(source) > SOURCE_LIMIT:
            message = "Keep the source within 64,000 characters."
            raise LearningError(message)  # noqa: TRY301 - Validate read-only preview inside its error boundary.
        # Preview is read-only and cannot attach another author's asset.

        from copy import copy

        preview = copy(draft)
        preview.body_source = source
        metadata = data.get("metadata", draft.metadata)
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, dict):
            message = "Invalid document details."
            raise LearningError(message)  # noqa: TRY301 - Validate preview metadata without persisting it.
        preview.metadata = metadata
        html = render_draft(preview, request.user)
        return JsonResponse({"html": str(html), "warnings": []})
    except (LearningError, ValidationError, ValueError) as exc:
        return _json_error(exc)


@workspace_view
@require_POST
@never_cache
def draft_upload(request, draft_id):
    from inspinia.learning.assets import asset_payload
    from inspinia.learning.assets import store_asset

    draft = _owned_draft(request, draft_id)
    upload = request.FILES.get("image")
    if upload is None:
        return JsonResponse({"error": "Choose an image to upload."}, status=400)
    try:
        return JsonResponse(asset_payload(store_asset(draft=draft, user=request.user, upload=upload)))
    except (LearningError, ValidationError) as exc:
        return _json_error(exc)


@workspace_view
@require_GET
@never_cache
def review_queue(request):
    require_publisher(request.user)
    page = Paginator(ContributionProposal.objects.select_related("revision", "document").order_by("-created_at"), 30)
    return render(request, "learning/review-queue.html", {"page": page.get_page(request.GET.get("page"))})


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def proposal_detail(request, proposal_id):
    proposal = get_object_or_404(
        ContributionProposal.objects.select_related("revision__base_revision", "document"),
        pk=proposal_id,
    )
    if not can_review(proposal, request.user):
        raise Http404
    error = ""
    if request.method == "POST":
        require_publisher(request.user)
        try:
            action = request.POST.get("action", "")
            if action == "publish":
                publish_proposal(
                    proposal=proposal,
                    user=request.user,
                    context=request.POST.get("context", ""),
                    expected_version=int(request.POST.get("expected_version", "-1")),
                    public=request.POST.get("public") == "on",
                    operation_id=request.POST.get("operation_id") or None,
                )
            else:
                review_proposal(
                    proposal=proposal,
                    user=request.user,
                    action=action,
                    feedback=request.POST.get("feedback", ""),
                    context=request.POST.get("context", ""),
                    operation_id=request.POST.get("operation_id") or None,
                )
            return redirect("learning:proposal", proposal_id=proposal.pk)
        except (LearningError, ValidationError, ValueError) as exc:
            error = _error_message(exc)
    proposal.refresh_from_db()
    base = proposal.revision.base_revision
    return render(
        request,
        "learning/proposal.html",
        {
            "proposal": proposal,
            "revision": proposal.revision,
            "error": error,
            "rendered_content": render_revision(proposal.revision, request.user),
            "source_diff": "\n".join(
                difflib.unified_diff(
                    (base.body_source if base else "").splitlines(),
                    proposal.revision.body_source.splitlines(),
                    fromfile="Base revision",
                    tofile="Proposed revision",
                    lineterm="",
                ),
            ),
            "review_context": review_context(proposal) if is_publisher(request.user) else "",
            "publication_impact": __import__(
                "inspinia.training.pathways",
                fromlist=["publication_impact"],
            ).publication_impact(proposal.document),
            "expected_version": proposal.document.publication.version,
            "operation_id": uuid.uuid4(),
            "is_publisher": is_publisher(request.user),
        },
    )


@workspace_view
@require_POST
@never_cache
def withdraw(request, document_id):
    require_publisher(request.user)
    document = get_object_or_404(ContentDocument, pk=document_id)
    try:
        withdraw_document(
            document=document,
            user=request.user,
            expected_version=int(request.POST.get("expected_version", "-1")),
            public_only=request.POST.get("public_only") == "on",
            operation_id=request.POST.get("operation_id") or None,
        )
    except (LearningError, ValueError) as exc:
        messages.error(request, _error_message(exc))
    return redirect("learning:my_drafts")


@workspace_view
@require_GET
@never_cache
def receipt(request, operation_id):
    action = get_object_or_404(ContentAction, operation_id=operation_id)
    if action.actor_id != request.user.pk and not is_publisher(request.user):
        raise Http404
    return JsonResponse({"operation_id": str(action.pk), "action": action.action, "result": action.result})


@workspace_view
@require_GET
def pathway_detail(request, slug):
    from inspinia.training.pathways import path_context
    from inspinia.training.pathways import published_pathways

    path = get_object_or_404(published_pathways(), slug=slug)
    context = path_context(path, user=request.user)
    from inspinia.learning.rendering import render_learning_markdown

    for row in context["items"]:
        row["rendered_hints"] = [render_learning_markdown(hint) for hint in row["item"].hints]
        if row["kind"] == "exercise":
            row["rendered_exercise"] = render_learning_markdown(row["item"].exercise_source)
        if row["kind"] == "problem":
            from inspinia.pages.catalogue_browser import concept_problem_url
            from inspinia.pages.models import ContestProblemStatement

            statement = ContestProblemStatement.objects.filter(
                problem_uuid=row["item"].problem_id,
                is_active=True,
            ).first()
            row["practice_url"] = concept_problem_url(
                {
                    "statement_uuid": statement.statement_uuid if statement else None,
                    "problem_uuid": row["item"].problem_id,
                },
            )
        if row.get("revision"):
            row["rendered"] = render_revision(row["revision"], request.user)
    return render(request, "learning/pathway.html", context)


@workspace_view
@require_POST
@never_cache
def mark_read(request, slug, item_key):
    from inspinia.training.pathways import mark_read as record_read
    from inspinia.training.pathways import published_pathways

    path = get_object_or_404(published_pathways(), slug=slug)
    try:
        record_read(user=request.user, path=path, item_key=item_key, revision_id=request.POST.get("revision_id"))
    except ValidationError as exc:
        messages.error(request, _error_message(exc))
    return redirect("learning:pathway", slug=path.slug)


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def pathway_editor(request):
    from inspinia.training.pathways import pathway_preview
    from inspinia.training.pathways import save_pathway

    require_publisher(request.user)
    initial, template_status = {}, None
    if request.method == "GET" and request.GET.get("pack"):
        from inspinia.training.content_packs import load_pathway_template

        try:
            template_status = load_pathway_template(request.GET["pack"], user=request.user)
            initial = template_status["payload"]
        except ValidationError as exc:
            messages.error(request, _error_message(exc))
    elif request.method == "GET" and request.GET.get("slug"):
        from inspinia.training.pathway_models import LearningPath

        path = get_object_or_404(LearningPath.objects.select_related("current_revision"), slug=request.GET["slug"])
        if path.current_revision:
            from inspinia.training.pathways import pathway_edit_payload

            initial = pathway_edit_payload(path)
    form = PathwayForm(request.POST if request.method == "POST" else None, initial=initial)
    preview_token, preview_summary = "", ""
    if request.method == "POST" and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            if request.POST.get("action") == "publish":
                path = save_pathway(user=request.user, context=request.POST.get("preview_token", ""), **data)
                return redirect("learning:pathway", slug=path.slug)
            preview = pathway_preview(user=request.user, data=data)
            preview_token = preview["context"]
            preview_summary = (
                f"{len(preview['items'])} activities validated. "
                "Review their order, readiness and release channel before publishing."
            )
        except (ValidationError, LearningError) as exc:
            form.add_error(None, _error_message(exc))
    return render(
        request,
        "learning/pathway-editor.html",
        {
            "form": form,
            "preview_token": preview_token,
            "preview_summary": preview_summary,
            "template_status": template_status,
        },
    )
