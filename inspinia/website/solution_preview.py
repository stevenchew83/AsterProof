"""The public continuous editor: current-text PDF export and private handoff."""

import logging
import tempfile
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from inspinia.solutions.document_source import legacy_source
from inspinia.solutions.examples import INEQUALITY_BLOCKS
from inspinia.solutions.examples import INEQUALITY_STATEMENT
from inspinia.solutions.examples import INEQUALITY_TITLE
from inspinia.solutions.forms import PDF_DISPLAY_FIELDS
from inspinia.solutions.forms import SolutionPreviewBlockFormSet
from inspinia.solutions.forms import SolutionPreviewForm
from inspinia.solutions.forms import SolutionWriterHandoffBlockFormSet
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.pdf_latex import SolutionPdfError
from inspinia.solutions.pdf_latex import SolutionPdfToolError
from inspinia.solutions.pdf_latex import build_solution_tex_source
from inspinia.solutions.pdf_latex import compile_solution_tex_to_pdf
from inspinia.solutions.writer_drafts import get_writer_draft
from inspinia.solutions.writer_drafts import stage_writer_draft
from inspinia.solutions.writer_drafts import writer_document_source
from inspinia.solutions.writer_drafts import writer_handoff_url

from .solution_preview_latex import PUBLIC_PDF_CHARACTER_LIMIT
from .solution_preview_latex import PUBLIC_PDF_TIMEOUT
from .solution_preview_latex import public_pdf_slot
from .solution_preview_latex import validate_public_latex

logger = logging.getLogger(__name__)


def solution_preview_context(request):
    types = {row.slug: row for row in SolutionBlockType.objects.all()}
    example = legacy_source(
        [
            ProblemSolutionBlock(block_type=types.get(block["slug"]), body_format="latex", body_source=block["body"])
            for block in INEQUALITY_BLOCKS
        ],
    )
    resume = request.path == reverse("website:solution_preview") and request.GET.get("resume") == "1"
    draft = get_writer_draft(request) if resume else None
    document = (
        dict(draft["document"])
        if draft
        else {
            "title": INEQUALITY_TITLE,
            "problem_statement": INEQUALITY_STATEMENT,
            "body_source": example,
        }
    )
    if draft:
        document["body_source"] = writer_document_source(draft)
    data = request.POST if request.method == "POST" else None
    legacy = None
    if data is not None and "body_source" not in data:
        handoff = data.get("action") in {"continue_workspace", "continue_signup"}
        formset_type = SolutionWriterHandoffBlockFormSet if handoff else SolutionPreviewBlockFormSet
        legacy = formset_type(data, instance=ProblemSolution(), prefix="blocks")
        if legacy.is_valid():
            data = data.copy()
            data["body_source"] = legacy_source([row.save(commit=False) for row in legacy.ordered_forms])
    form = SolutionPreviewForm(data, initial=document)
    if legacy is not None and not legacy.is_valid():
        form.add_error(None, "Check your previous writing. The old block form could not be converted safely.")
    return {
        "form": form,
        "formset": legacy,
        "solution_block_type_slugs": {str(row.pk): {"slug": row.slug, "label": row.label} for row in types.values()},
        "pdf_date_label": timezone.localdate().isoformat(),
        "writer_draft_resumed": bool(draft),
    }


def _validate_fragments(form):
    valid = True
    for field in ("problem_statement", "body_source"):
        try:
            validate_public_latex(form.cleaned_data.get(field) or "")
        except ValidationError as error:
            form.add_error(field, error)
            valid = False
    total = sum(len(form.cleaned_data.get(field) or "") for field in ("problem_statement", "body_source"))
    if total > PUBLIC_PDF_CHARACTER_LIMIT:
        form.add_error(None, f"Keep this document within {PUBLIC_PDF_CHARACTER_LIMIT:,} characters.")
        valid = False
    if not (form.cleaned_data.get("body_source") or "").strip():
        form.add_error("body_source", "Write your solution before exporting a PDF.")
        valid = False
    return valid


def _download_pdf(context):
    form = context["form"]
    title = form.cleaned_data["title"] or "My solution"
    solution = ProblemSolution(
        updated_at=timezone.now(), **{name: form.cleaned_data[name] for name in PDF_DISPLAY_FIELDS},
    )
    block = ProblemSolutionBlock(position=1, body_format="latex", body_source=form.cleaned_data["body_source"])
    block.is_continuous_document = True
    with tempfile.TemporaryDirectory(prefix="ap_preview_media_") as media_root:
        tex_source = build_solution_tex_source(
            solution=solution,
            blocks=[block],
            media_root=Path(media_root),
            problem_label=title,
            problem_statement_latex=form.cleaned_data["problem_statement"],
            author_display=form.cleaned_data["author_name"],
        )
        pdf = compile_solution_tex_to_pdf(
            tex_source,
            timeout=min(settings.SOLUTION_PDF_LATEX_TIMEOUT, PUBLIC_PDF_TIMEOUT),
            latex_binary=settings.SOLUTION_PDF_LATEX_BINARY,
            restrict_file_access=True,
        )
    return FileResponse(
        BytesIO(pdf),
        as_attachment=True,
        filename=f"{slugify(title) or 'solution'}.pdf",
        content_type="application/pdf",
    )


def _continue_in_workspace(request, context):
    form = context["form"]
    if not form.is_valid():
        return None
    try:
        stage_writer_draft(request, form)
    except ValidationError as error:
        form.add_error(None, error)
        return None
    destination = writer_handoff_url()
    if request.user.is_authenticated:
        return redirect(destination)
    account_view = "account_signup" if request.POST.get("action") == "continue_signup" else "account_login"
    return redirect(reverse(account_view) + "?" + urlencode({"next": destination}))


@transaction.non_atomic_requests
@require_http_methods(["GET", "POST"])
def solution_preview_view(request):
    from .views import _page

    context = solution_preview_context(request)
    form = context["form"]
    response, status = None, 200
    if request.method == "POST" and request.POST.get("action") in {"continue_workspace", "continue_signup"}:
        response = _continue_in_workspace(request, context)
        if response is None:
            status = 400
    elif request.method == "POST":
        if form.is_valid() and _validate_fragments(form):
            with public_pdf_slot(request) as available:
                if not available:
                    form.add_error(None, "PDF exports are busy. Your writing is still here. Try again in a minute.")
                    status = 429
                else:
                    try:
                        response = _download_pdf(context)
                    except SolutionPdfToolError:
                        logger.warning("public_solution_pdf_tool_unavailable")
                        form.add_error(None, "PDF export is temporarily unavailable. Your writing is still here.")
                        status = 503
                    except SolutionPdfError:
                        logger.warning("public_solution_pdf_compile_failed")
                        form.add_error(None, "Could not compile the PDF. Check the LaTeX and try again.")
                        status = 400
        else:
            status = 400
    if response is None:
        response = _page(
            request,
            "solution_preview",
            page_title="Solution Writer",
            active_nav="tools",
            page_description=(
                "Write a continuous LaTeX solution, preview equations, "
                "and download a PDF without signing in."
            ),
            has_math=True,
            hide_newsletter=True,
            status=status,
            **context,
        )
    response["Cache-Control"] = "private, no-store"
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        response["Retry-After"] = "60"
    return response
