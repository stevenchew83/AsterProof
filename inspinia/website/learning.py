"""Public reading adapters over approved shared revisions, never private drafts."""

from django.conf import settings
from django.db import connection
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from inspinia.learning.forms import IssueForm
from inspinia.learning.permissions import module_enabled
from inspinia.learning.publication import visible_publications
from inspinia.learning.rendering import render_revision
from inspinia.learning.revisions import LearningError


def schema_ready():
    # Recheck after connection or test database replacement; failures must not restore legacy text.
    return "learning_legacycontentlink" in connection.introspection.table_names()


def exclude_cutovers(queryset):
    if not schema_ready():
        return queryset
    return queryset.exclude(learning_link__is_cutover=True)


def public_notes(query=""):
    from django.db.models import Q

    from inspinia.learning.models import ContentPublication

    if not schema_ready():
        return ContentPublication.objects.none()
    rows = visible_publications(public=True).select_related(
        "document",
        "revision",
        "document__canonical_area__subject",
        "document__canonical_concept",
    )
    if query:
        rows = rows.filter(
            Q(revision__title__icontains=query)
            | Q(revision__summary__icontains=query)
            | Q(revision__body_source__icontains=query),
        )
    return rows.order_by("-published_at", "document_id")


def note_url(publication):
    return reverse("website:learning_note", args=[publication.document_id, publication.document.slug or "notes"])


def note_entries(query="", limit=12, subject=None):
    rows = public_notes(query)
    if subject:
        from django.db.models import Q

        rows = rows.filter(
            Q(document__canonical_area__subject_id=subject)
            | Q(document__canonical_concept__memberships__area__subject_id=subject)
            | Q(revision__concept_links__concept__memberships__area__subject_id=subject),
        ).distinct()
    entries = list(rows[:limit])
    for row in entries:
        row.public_url = note_url(row)
    return entries


def bridge_response(request, source):
    if not schema_ready():
        return None
    from inspinia.learning.legacy import legacy_publication

    cutover, publication = legacy_publication(source)
    if not cutover:
        return None
    # A disabled module or withdrawn shared revision cannot restore old body text.
    if not module_enabled() or not publication or not publication.public_visible or not publication.revision_id:
        raise Http404
    return learning_note(request, publication.document_id, publication.document.slug or "notes")


@require_GET
@never_cache
def learning_note(request, document_id, slug):
    from inspinia.website.views import _page

    publication = get_object_or_404(public_notes(), document_id=document_id)
    canonical = note_url(publication)
    if slug != (publication.document.slug or "notes"):
        return redirect(canonical)
    revision = publication.revision
    try:
        credit = revision.permission.public_credit
    except AttributeError:
        credit = ""
    response = _page(
        request,
        "learning_note",
        page_title=revision.title,
        active_nav="library",
        lecture=revision,
        publication=publication,
        revision=revision,
        public_credit=credit,
        rendered_content=render_revision(revision, request.user, public=True),
        has_math=False,
        learning_math=True,
        hide_newsletter=True,
        public_revision_id=str(revision.pk),
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET", "POST"])
@never_cache
def report_note(request, document_id):
    from inspinia.learning.issues import create_issue
    from inspinia.learning.issues import issue_context
    from inspinia.website.views import _page

    publication = get_object_or_404(public_notes(), document_id=document_id)
    try:
        initial = (
            {"token": issue_context(publication.document, request.user)}
            if getattr(settings, "LEARNING_CONTRIBUTIONS_ENABLED", False)
            else None
        )
    except LearningError:
        initial = None
    if initial is None:
        return _page(
            request,
            "learning_report",
            page_title="Report a mathematical error",
            closed=True,
            publication=publication,
            hide_newsletter=True,
            noindex=True,
            back_url=note_url(publication),
        )
    form = IssueForm(request.POST if request.method == "POST" else None, initial=initial)
    sent = request.method == "GET" and request.GET.get("sent") == "1"
    if request.method == "POST" and form.is_valid():
        try:
            create_issue(
                user=request.user,
                document=publication.document,
                description=form.cleaned_data["description"],
                token=form.cleaned_data["token"],
                source_identity=request.META.get("REMOTE_ADDR", "unknown"),
                honeypot=form.cleaned_data.get("website", ""),
            )
        except LearningError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(reverse("website:learning_report", args=[document_id]) + "?sent=1")
    return _page(
        request,
        "learning_report",
        page_title="Report a mathematical error",
        form=form,
        sent=sent,
        publication=publication,
        hide_newsletter=True,
        noindex=True,
        back_url=note_url(publication),
    )


@require_GET
@never_cache
def public_pathway(request, slug):
    from inspinia.learning.rendering import render_learning_markdown
    from inspinia.training.pathways import path_context
    from inspinia.training.pathways import published_pathways
    from inspinia.website.views import _page

    if not module_enabled():
        raise Http404
    path = get_object_or_404(published_pathways(public=True), slug=slug)
    context = path_context(path, public=True)
    for row in context["items"]:
        if row.get("revision"):
            row["public_url"] = reverse(
                "website:learning_note",
                args=[
                    row["revision"].document_id,
                    row["revision"].document.slug or "notes",
                ],
            )
        if row["kind"] == "exercise":
            row["rendered_exercise"] = render_learning_markdown(row["item"].exercise_source)
        row["rendered_hints"] = [render_learning_markdown(value) for value in row["item"].hints]
    return _page(
        request,
        "learning_pathway",
        page_title=path.current_revision.title,
        active_nav="library",
        has_math=False,
        learning_math=True,
        hide_newsletter=True,
        **context,
    )
