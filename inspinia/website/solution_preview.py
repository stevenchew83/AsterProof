"""The public, unsaved block editor and PDF download."""

import logging
import tempfile
from http import HTTPStatus
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from inspinia.solutions.examples import INEQUALITY_BLOCKS
from inspinia.solutions.examples import INEQUALITY_STATEMENT
from inspinia.solutions.examples import INEQUALITY_TITLE
from inspinia.solutions.forms import PDF_DISPLAY_FIELDS
from inspinia.solutions.forms import PREVIEW_BLOCK_LIMIT
from inspinia.solutions.forms import SolutionPreviewBlockFormSet
from inspinia.solutions.forms import SolutionPreviewForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.pdf_latex import SolutionPdfError
from inspinia.solutions.pdf_latex import SolutionPdfToolError
from inspinia.solutions.pdf_latex import build_solution_tex_source
from inspinia.solutions.pdf_latex import compile_solution_tex_to_pdf
from inspinia.solutions.pdf_latex import latex_escape_plain_text

from .solution_preview_latex import PUBLIC_PDF_CHARACTER_LIMIT
from .solution_preview_latex import PUBLIC_PDF_TIMEOUT
from .solution_preview_latex import public_pdf_slot
from .solution_preview_latex import validate_public_latex

logger = logging.getLogger(__name__)


def solution_preview_context(request):
    solution = ProblemSolution(updated_at=timezone.now())
    types = dict(SolutionBlockType.objects.values_list("slug", "pk"))
    initial = [
        {"block_type": types.get(block["slug"]), "body_format": "latex", "body_source": block["body"]}
        for block in INEQUALITY_BLOCKS
    ]
    form = SolutionPreviewForm(
        request.POST if request.method == "POST" else None,
        initial={"title": INEQUALITY_TITLE, "problem_statement": INEQUALITY_STATEMENT},
    )
    formset = SolutionPreviewBlockFormSet(
        request.POST if request.method == "POST" else None, instance=solution, prefix="blocks",
        queryset=ProblemSolutionBlock.objects.none(), initial=initial if request.method == "GET" else None,
    )
    if request.method == "GET":
        formset.extra = len(initial)
    return {
        "form": form, "formset": formset, "preview_block_limit": PREVIEW_BLOCK_LIMIT,
        "plain_block_type_id": types.get("plain", ""),
        "pdf_date_label": timezone.localdate().isoformat(),
    }


def _validate_fragments(form, block_forms):
    fields = [(form, "problem_statement")]
    fields.extend(
        (block_form, field) for block_form in block_forms for field in ("title", "body_source")
        if block_form.cleaned_data["body_format"] == ProblemSolutionBlock.BodyFormat.LATEX
    )
    valid = True
    for fragment_form, field in fields:
        try:
            validate_public_latex(fragment_form.cleaned_data.get(field) or "")
        except ValidationError as error:
            fragment_form.add_error(field, error)
            valid = False
    total = len(form.cleaned_data.get("problem_statement") or "") + sum(
        len(block_form.cleaned_data.get("body_source") or "") for block_form in block_forms
    )
    if total > PUBLIC_PDF_CHARACTER_LIMIT:
        form.add_error(None, f"Keep this document within {PUBLIC_PDF_CHARACTER_LIMIT:,} characters.")
        valid = False
    return valid


def _download_pdf(context):
    form, formset = context["form"], context["formset"]
    title = form.cleaned_data["title"] or "My solution"
    for field in PDF_DISPLAY_FIELDS:
        setattr(formset.instance, field, form.cleaned_data[field])
    blocks = [block_form.save(commit=False) for block_form in formset.ordered_forms]
    for block in blocks:
        if block.body_format == ProblemSolutionBlock.BodyFormat.PLAIN_TEXT:
            block.title = latex_escape_plain_text(block.title)
            block.body_source = latex_escape_plain_text(block.body_source)
    with tempfile.TemporaryDirectory(prefix="ap_preview_media_") as media_root:
        tex_source = build_solution_tex_source(
            solution=formset.instance, blocks=blocks, media_root=Path(media_root), problem_label=title,
            problem_statement_latex=form.cleaned_data["problem_statement"],
            author_display=form.cleaned_data["author_name"],
        )
        pdf = compile_solution_tex_to_pdf(
            tex_source, timeout=min(settings.SOLUTION_PDF_LATEX_TIMEOUT, PUBLIC_PDF_TIMEOUT),
            latex_binary=settings.SOLUTION_PDF_LATEX_BINARY, restrict_file_access=True,
        )
    return FileResponse(
        BytesIO(pdf), as_attachment=True,
        filename=f"{slugify(title) or 'solution'}.pdf", content_type="application/pdf",
    )


@transaction.non_atomic_requests
@require_http_methods(["GET", "POST"])
def solution_preview_view(request):
    from .views import _page

    context = solution_preview_context(request)
    form, formset = context["form"], context["formset"]
    response, status = None, 200
    if request.method == "POST":
        valid_form, valid_blocks = form.is_valid(), formset.is_valid()
        if valid_form and valid_blocks and _validate_fragments(form, list(formset.ordered_forms)):
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
            request, "solution_preview", page_title="Solution Writer", active_nav="tools",
            page_description=(
                "Write a solution in blocks, preview equations as you type, and convert LaTeX to PDF. "
                "Combine plain text with mathematical notation and download without signing in."
            ),
            has_math=True, hide_newsletter=True, status=status, **context,
        )
    response["Cache-Control"] = "private, no-store"
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        response["Retry-After"] = "60"
    return response
