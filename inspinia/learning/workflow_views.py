"""Explicit contribution, curation and private pack-import interfaces."""

import uuid

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.learning.forms import IssueForm
from inspinia.learning.forms import NewDocumentForm
from inspinia.learning.forms import StyledForm
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentIssue
from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import require_contributor
from inspinia.learning.permissions import require_publisher
from inspinia.learning.publication import visible_publications
from inspinia.learning.revisions import LearningError
from inspinia.learning.views import _error_message
from inspinia.learning.views import _owned_draft
from inspinia.learning.views import workspace_view


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def report(request, document_id=None, kind=None, target_key=None):
    from inspinia.learning.issues import create_issue
    from inspinia.learning.issues import create_target_issue
    from inspinia.learning.issues import issue_context
    from inspinia.learning.issues import target_issue_context

    require_contributor(request.user)
    publication = (
        get_object_or_404(visible_publications(user=request.user), document_id=document_id) if document_id else None
    )
    if not publication and kind not in {"classification", "pathway"}:
        raise Http404
    try:
        token = (
            issue_context(publication.document, request.user)
            if publication
            else target_issue_context(user=request.user, kind=kind, target_key=target_key)
        )
    except LearningError as exc:
        raise Http404 from exc
    form = IssueForm(request.POST if request.method == "POST" else None, initial={"token": token})
    if request.method == "POST" and form.is_valid():
        try:
            values = {
                "user": request.user,
                "description": form.cleaned_data["description"],
                "token": form.cleaned_data["token"],
                "source_identity": request.META.get("REMOTE_ADDR", ""),
                "honeypot": form.cleaned_data.get("website", ""),
            }
            if publication:
                create_issue(document=publication.document, **values)
            else:
                create_target_issue(kind=kind, target_key=target_key, **values)
        except LearningError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(request.path + "?sent=1")
    return render(
        request,
        "learning/issue-form.html",
        {
            "form": form,
            "title": "Report a mathematical error" if publication else "Suggest an improvement",
            "sent": request.method == "GET" and request.GET.get("sent") == "1",
        },
    )


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def issues(request):
    from inspinia.learning.issues import review_issue

    require_publisher(request.user)
    if request.method == "POST":
        issue = get_object_or_404(ContentIssue, pk=request.POST.get("issue_id"))
        review_issue(issue=issue, user=request.user, closed=request.POST.get("action") == "close")
        return redirect("learning:issues")
    page = Paginator(ContentIssue.objects.order_by("-created_at"), 30).get_page(request.GET.get("page"))
    return render(request, "learning/issues.html", {"page": page})


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def rebase(request, draft_id):
    from inspinia.learning.drafts import editor_context
    from inspinia.learning.drafts import rebase_draft

    draft = _owned_draft(request, draft_id)
    publication = draft.document.publication
    if not publication.training_visible and not is_publisher(request.user):
        raise Http404
    error = ""
    if request.method == "POST":
        try:
            rebase_draft(
                draft=draft,
                user=request.user,
                base_version=int(request.POST.get("edit_version", "-1")),
                publication_version=int(request.POST.get("publication_version", "-1")),
                context=request.POST.get("context", ""),
                confirmed=request.POST.get("confirmed") == "on",
            )
        except (LearningError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("learning:edit", draft_id=draft.pk)
    return render(
        request,
        "learning/rebase.html",
        {
            "draft": draft,
            "publication": publication,
            "current_source": publication.revision.body_source if publication.revision else "",
            "context": editor_context(draft, request.user),
            "error": error,
        },
    )


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def packs(request, pack_key=None):
    from inspinia.training.content_packs import apply_content_pack
    from inspinia.training.content_packs import load_teaching_pack
    from inspinia.training.content_packs import preview_content_pack
    from inspinia.training.content_packs import rollout_manifest
    from inspinia.training.content_packs import teaching_packs

    require_publisher(request.user)
    if pack_key is None:
        return render(
            request,
            "learning/packs.html",
            {"packs": [{**pack, "file_key": pack["id"]} for pack in teaching_packs()], "manifest": rollout_manifest()},
        )
    try:
        pack = load_teaching_pack(pack_key)
        preview = preview_content_pack(pack=pack, user=request.user)
    except ValidationError as exc:
        raise Http404 from exc
    error = ""
    if request.method == "POST":
        try:
            drafts = apply_content_pack(
                pack=pack,
                user=request.user,
                preview_token=request.POST.get("preview_token", ""),
                selected_keys=request.POST.getlist("notes"),
            )
        except (ValidationError, LearningError) as exc:
            error = _error_message(exc)
        else:
            messages.success(
                request,
                f"{len(drafts)} private drafts are ready in My notes. They have not been approved or published.",
            )
            return redirect("learning:my_drafts")
    return render(request, "learning/pack.html", {"pack": pack, "preview": preview, "error": error})


class PrerequisiteForm(StyledForm):
    prerequisite_id = forms.CharField(max_length=160, label="Prerequisite canonical concept ID")
    dependent_id = forms.CharField(max_length=160, label="Dependent canonical concept ID")
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput())
    remove = forms.BooleanField(required=False, label="Remove this edge")


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def prerequisites(request):
    from inspinia.pages.prerequisite_models import CataloguePrerequisite
    from inspinia.pages.prerequisite_models import PrerequisiteGraphState
    from inspinia.pages.prerequisites import set_prerequisite

    require_publisher(request.user)
    version = PrerequisiteGraphState.objects.filter(pk=1).values_list("version", flat=True).first() or 0
    form = PrerequisiteForm(request.POST if request.method == "POST" else None, initial={"expected_version": version})
    if request.method == "POST" and form.is_valid():
        try:
            set_prerequisite(user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, _error_message(exc))
        else:
            return redirect("learning:prerequisites")
    return render(
        request,
        "learning/prerequisites.html",
        {"form": form, "edges": CataloguePrerequisite.objects.select_related("prerequisite", "dependent")},
    )


def _legacy_source(kind, key):
    from inspinia.training.models import Material
    from inspinia.website.models import LibraryArea
    from inspinia.website.models import LibraryConcept
    from inspinia.website.models import LibraryLecture

    model = {"material": Material, "area": LibraryArea, "concept": LibraryConcept, "lecture": LibraryLecture}.get(kind)
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=key)


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def legacy_draft(request, kind, key):
    """Copy a reviewed legacy source into a private draft; never infer its catalogue mapping."""
    from inspinia.learning.drafts import create_draft
    from inspinia.learning.legacy import link_legacy
    from inspinia.learning.legacy import source_fingerprint
    from inspinia.users.roles import user_has_trainer_or_admin_role

    require_contributor(request.user)
    if not is_publisher(request.user) and not user_has_trainer_or_admin_role(request.user):
        raise Http404
    source = _legacy_source(kind, key)
    if kind != "material" and not is_publisher(request.user):
        raise Http404
    initial = {
        "title": source.title,
        "kind": "overview" if kind == "area" else "concept" if kind == "concept" else "lecture",
        "use_template": False,
    }
    form = NewDocumentForm(request.POST if request.method == "POST" else None, initial=initial)
    context = signing.dumps(
        {"kind": kind, "key": str(source.pk), "fingerprint": source_fingerprint(source), "user": str(request.user.pk)},
        salt="learning.legacy-form",
    )
    if request.method == "POST" and form.is_valid():
        try:
            checked = signing.loads(request.POST.get("source_context", ""), salt="learning.legacy-form", max_age=3600)
            if checked != {
                "kind": kind,
                "key": str(source.pk),
                "fingerprint": source_fingerprint(source),
                "user": str(request.user.pk),
            }:
                message = "The legacy source changed. Compare it again before drafting."
                raise LearningError(message)  # noqa: TRY301 - Signed source validation shares the form error boundary.
            data = form.cleaned_data
            try:
                document = source.learning_link.document
            except AttributeError:
                document = None
            draft = create_draft(
                user=request.user,
                document=document,
                title=data["title"],
                kind=data["kind"],
                area_id=data["area"].pk if data["area"] else None,
                concept_id=data["concept"].pk if data["concept"] else None,
                source=getattr(source, "content_markdown", getattr(source, "body_markdown", "")),
            )
            if not document and is_publisher(request.user):
                link_legacy(
                    user=request.user,
                    document=draft.document,
                    source=source,
                    expected_fingerprint=checked["fingerprint"],
                )
        except (LearningError, ValidationError, signing.BadSignature) as exc:
            form.add_error(None, _error_message(exc))
        else:
            return redirect("learning:edit", draft_id=draft.pk)
    return render(request, "learning/legacy.html", {"form": form, "source": source, "source_context": context})


@workspace_view
@require_http_methods(["POST"])
@never_cache
def legacy_cutover(request, kind, key):
    from inspinia.learning.legacy import link_legacy

    require_publisher(request.user)
    source = _legacy_source(kind, key)
    document = get_object_or_404(ContentDocument, pk=request.POST.get("document_id"))
    try:
        link_legacy(
            user=request.user,
            document=document,
            source=source,
            expected_fingerprint=request.POST.get("fingerprint", ""),
            cutover=True,
        )
    except LearningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "The legacy URL now uses the approved shared revision.")
    return redirect("learning:read", document_id=document.pk)


@workspace_view
@require_http_methods(["GET", "POST"])
@never_cache
def history(request, document_id):
    from inspinia.learning.publication import propose_restoration
    from inspinia.learning.publication import restoration_candidates

    require_publisher(request.user)
    document = get_object_or_404(ContentDocument, pk=document_id)
    publication = document.publication
    error = ""
    if request.method == "POST":
        try:
            proposal = propose_restoration(
                user=request.user,
                document=document,
                revision_id=request.POST.get("revision_id"),
                expected_version=int(request.POST.get("expected_version", "-1")),
                operation_id=request.POST.get("operation_id") or None,
            )
        except (LearningError, ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("learning:proposal", proposal_id=proposal.pk)
    return render(
        request,
        "learning/history.html",
        {
            "document": document,
            "publication": publication,
            "revisions": restoration_candidates(user=request.user, document=document),
            "error": error,
            "operation_id": uuid.uuid4(),
        },
    )


@workspace_view
@require_http_methods(["POST"])
@never_cache
def archive(request, draft_id):
    from inspinia.learning.drafts import archive_draft

    draft = _owned_draft(request, draft_id)
    try:
        archive_draft(
            draft=draft,
            user=request.user,
            archived=request.POST.get("action") != "reopen",
            base_version=int(request.POST.get("edit_version", "-1")),
            operation_id=request.POST.get("operation_id") or None,
        )
    except (LearningError, ValueError) as exc:
        messages.error(request, _error_message(exc))
    return redirect("learning:my_drafts")
