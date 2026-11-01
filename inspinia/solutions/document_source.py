"""One continuous source for new documents and deterministic legacy conversion."""

import hashlib
import json

from django.core.exceptions import ValidationError

from inspinia.solutions.models import ProblemSolutionBlock

SYNTAX_VERSION = 1
CONVERSION_VERSION = 1
PDF_OPTION_FIELDS = ("pdf_show_author", "pdf_show_date", "pdf_show_footer")
_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
    "#": r"\#", "%": r"\%", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape_literal_text(value):
    return "".join(_TEXT_ESCAPES.get(character, character) for character in value or "")


def _environment(name, source, title=""):
    opening = rf"\begin{{{name}}}" + (f"[{title}]" if title else "")
    return "\n".join((opening, source, rf"\end{{{name}}}"))


def convert_legacy_block(block):  # noqa: PLR0911 - Each legacy structural type has its own representation.
    """Preserve legacy claim statements separately from their following proof."""
    body = block.body_source or ""
    title = block.title or ""
    plain_text = block.body_format == ProblemSolutionBlock.BodyFormat.PLAIN_TEXT
    if plain_text:
        body, title = escape_literal_text(body), escape_literal_text(title)
    block_type = block.block_type
    slug = block_type.slug if block_type else "plain"
    if slug == "plain":
        return "\n\n".join(value for value in (title, body) if value)
    if slug == "claim":
        if title and body:
            return _environment("claim", title) + "\n\n" + _environment("proof", body)
        return _environment("claim", title or body) if title or body else ""
    if slug == "proof":
        return _environment("proof", body, title) if title or body else ""
    if slug in {"observation", "remark"}:
        return _environment("fact" if slug == "observation" else "remark", "\n\n".join(
            value for value in (title, body) if value
        ))
    label = block_type.label if block_type else ""
    caption = title or escape_literal_text(label)
    if slug in {"section", "part"}:
        command = "section" if slug == "section" else "subsection"
        return rf"\{command}*{{{caption}}}" + ("\n\n" + body if body else "")
    if slug in {"case", "subcase", "idea", "computation", "conclusion"}:
        return rf"\textbf{{{caption.rstrip('.')}.}}" + ("\n\n" + body if body else "")
    # An unknown type still has a readable heading and its complete original body.
    heading = escape_literal_text(" — ".join(value for value in (label, block.title or "") if value))
    return rf"\paragraph{{{heading}}}" + ("\n\n" + body if body else "")


def legacy_source(blocks):
    return "\n\n".join(convert_legacy_block(block) for block in blocks)


def solution_source(solution):
    if solution.current_revision_id:
        if solution.current_revision.solution_id != solution.pk:
            message = "The current revision does not belong to this solution."
            raise ValidationError(message)
        return solution.current_revision.body_source
    if not solution.pk:
        return ""
    return legacy_source(solution.blocks.select_related("block_type").order_by("position", "id"))


def solution_blocks(solution):
    """Compatibility input for existing PDF consumers, without saving synthetic blocks."""
    if solution.current_revision_id:
        block = ProblemSolutionBlock(
            solution=solution, position=1, body_format=ProblemSolutionBlock.BodyFormat.LATEX,
            body_source=solution_source(solution),
        )
        block.is_continuous_document = True
        return [block]
    if not solution.pk:
        return []
    return list(solution.blocks.select_related("block_type").order_by("position", "id"))


def source_digest(body_source, title="", summary="", pdf_options=None):
    options = pdf_options or {}
    payload = {
        "body_source": body_source, "title": title, "summary": summary, "syntax_version": SYNTAX_VERSION,
        **{name: bool(options.get(name, True)) for name in PDF_OPTION_FIELDS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
