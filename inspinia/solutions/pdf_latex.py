"""Build LaTeX source and compile solution PDFs with vendored ``evan.sty``."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inspinia.solutions.models import ProblemSolution
    from inspinia.solutions.models import ProblemSolutionBlock

logger = logging.getLogger(__name__)

EVAN_STY_PATH = Path(__file__).resolve().parent / "latex" / "evan.sty"
LOG_TAIL_MAX_CHARS = 12_000
# Failed runs can produce multi-MB logs; scan a bounded suffix for error markers.
LOG_READ_MAX_BYTES = 4 * 1024 * 1024

_MSG_LATEX_TIMEOUT = "LaTeX compilation timed out."
_MSG_LATEX_FAILED = "LaTeX compilation failed."
_MSG_TOOL_NOT_FOUND = "LaTeX tool not found in PATH: {binary}"


class SolutionPdfError(Exception):
    """Base class for solution PDF export failures."""


class SolutionPdfCompileError(SolutionPdfError):
    def __init__(self, message: str, log_tail: str = "") -> None:
        super().__init__(message)
        self.log_tail = log_tail


class SolutionPdfToolError(SolutionPdfError):
    pass


@dataclass(frozen=True)
class SolutionPdfCompileParams:
    media_root: Path
    problem_label: str
    timeout: int
    latex_binary: str
    problem_statement_latex: str = ""


# Vertical gap between exported blocks.
_SOLUTION_PDF_BLOCK_VSPACE = r"\addvspace{\baselineskip}"

_LATEX_ESCAPES = (
    ("\\", r"\textbackslash{}"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("$", r"\$"),
    ("&", r"\&"),
    ("#", r"\#"),
    ("%", r"\%"),
    ("_", r"\_"),
    ("^", r"\textasciicircum{}"),
    ("~", r"\textasciitilde{}"),
)


def latex_escape_plain_text(value: str) -> str:
    if not value:
        return ""
    out = value
    for a, b in _LATEX_ESCAPES:
        out = out.replace(a, b)
    return out


def _block_heading(block: ProblemSolutionBlock) -> str:
    type_label = (block.block_type.label if block.block_type else "").strip() or "Block"
    title = (block.title or "").strip()
    if title:
        return f"{type_label} — {title}"
    return type_label


def _block_slug(block: ProblemSolutionBlock) -> str:
    if not block.block_type_id or not block.block_type:
        return ""
    return (block.block_type.slug or "").strip()


def _is_plain_block(block: ProblemSolutionBlock) -> bool:
    return _block_slug(block) == "plain"


def _graphicspath_tex(media_root: Path) -> str:
    media = media_root.resolve().as_posix()
    if not media.endswith("/"):
        media += "/"
    return media.replace("#", "\\#").replace("%", "\\%")


def _solution_pdf_author_display(user) -> str:
    name = (getattr(user, "name", None) or "").strip()
    return name or "Unknown"


def _solution_pdf_subtitle(solution: ProblemSolution) -> str:
    title = (solution.title or "").strip()
    if not title or title == "Untitled solution":
        return ""
    return title


def _join_block_text(title: str, body: str) -> str:
    parts = [part for part in [(title or "").strip(), (body or "").strip()] if part]
    return "\n\n".join(parts)


def _render_theorem_like_block(env_name: str, *, title: str, body: str) -> list[str]:
    content = _join_block_text(title, body)
    if not content:
        return []
    return [rf"\begin{{{env_name}}}", content, rf"\end{{{env_name}}}", ""]


def _render_claim_block(*, title: str, body: str) -> list[str]:
    statement = (title or "").strip()
    proof_text = (body or "").strip()
    if statement and proof_text:
        return [
            r"\begin{claim}",
            statement,
            r"\end{claim}",
            r"\begin{proof}",
            proof_text,
            r"\end{proof}",
            "",
        ]
    if statement:
        return [r"\begin{claim}", statement, r"\end{claim}", ""]
    if proof_text:
        return [r"\begin{claim}", proof_text, r"\end{claim}", ""]
    return []


def _render_proof_block(*, title: str, body: str) -> list[str]:
    body_text = (body or "").strip()
    if not title.strip() and not body_text:
        return []
    if title.strip():
        return [rf"\begin{{proof}}[{title.strip()}]", body_text, r"\end{proof}", ""]
    return [r"\begin{proof}", body_text, r"\end{proof}", ""]


def _render_heading_block(command: str, *, title: str, fallback: str, body: str) -> list[str]:
    heading = (title or "").strip() or fallback
    if not heading and not (body or "").strip():
        return []
    lines = [rf"\{command}*{{{heading}}}"]
    if (body or "").strip():
        lines.extend([(body or "").strip(), ""])
    else:
        lines.append("")
    return lines


def _render_bold_leadin(label: str, *, title: str, body: str) -> list[str]:
    lead = ((title or "").strip() or label).rstrip(".")
    if not lead and not (body or "").strip():
        return []
    lines = [rf"\textbf{{{lead}.}}"]
    if (body or "").strip():
        lines.extend([(body or "").strip(), ""])
    else:
        lines.append("")
    return lines


def _render_block(block: ProblemSolutionBlock) -> list[str]:
    rendered: list[str]
    if _is_plain_block(block):
        rendered = [block.body_source or "", ""]
    else:
        slug = _block_slug(block)
        theorem_env = {
            "observation": "fact",
            "remark": "remark",
        }.get(slug)
        if theorem_env:
            rendered = _render_theorem_like_block(theorem_env, title=block.title or "", body=block.body_source or "")
        elif slug == "claim":
            rendered = _render_claim_block(title=block.title or "", body=block.body_source or "")
        elif slug == "proof":
            rendered = _render_proof_block(title=block.title or "", body=block.body_source or "")
        elif slug in {"section", "part"}:
            command = "section" if slug == "section" else "subsection"
            fallback = block.block_type.label if block.block_type else slug.title()
            rendered = _render_heading_block(
                command,
                title=block.title or "",
                fallback=fallback,
                body=block.body_source or "",
            )
        elif slug in {"case", "subcase", "idea", "computation", "conclusion"}:
            rendered = _render_bold_leadin(
                (block.block_type.label if block.block_type else slug.title()),
                title=block.title or "",
                body=block.body_source or "",
            )
        else:
            heading = latex_escape_plain_text(_block_heading(block))
            rendered = [rf"\paragraph{{{heading}}}", block.body_source or "", ""]

    return rendered


def build_solution_tex_source(
    *,
    solution: ProblemSolution,
    blocks: Sequence[ProblemSolutionBlock],
    media_root: Path,
    problem_label: str,
    problem_statement_latex: str = "",
) -> str:
    title = latex_escape_plain_text(problem_label)
    subtitle = latex_escape_plain_text(_solution_pdf_subtitle(solution))
    author = latex_escape_plain_text(_solution_pdf_author_display(solution.author))
    dt_ref = solution.published_at or solution.updated_at
    date_str = latex_escape_plain_text(
        timezone.localtime(dt_ref).strftime("%Y-%m-%d"),
    )
    gp = _graphicspath_tex(media_root)

    lines: list[str] = [
        r"\documentclass[11pt]{scrartcl}",
        r"\usepackage[sexy,noasy]{evan}",
        rf"\graphicspath{{{gp}}}",
        rf"\title{{{title}}}",
        rf"\author{{{author}}}",
        rf"\date{{{date_str}}}",
        r"\begin{document}",
        r"\maketitle",
    ]
    if subtitle:
        lines.insert(4, rf"\subtitle{{{subtitle}}}")
    stmt_body = (problem_statement_latex or "").strip()
    if stmt_body:
        lines.append(r"\begin{mdframed}[style=mdpurplebox,frametitle={Problem Statement}]")
        lines.append(stmt_body)
        lines.append(r"\end{mdframed}")
        lines.append("")
    for i, block in enumerate(blocks):
        if i:
            lines.append(r"\par")
            lines.append(_SOLUTION_PDF_BLOCK_VSPACE)
        lines.extend(_render_block(block))
    lines.append(r"\end{document}")
    return "\n".join(lines)


def _read_log_bytes(path: Path) -> str:
    if not path.is_file():
        return ""
    raw = path.read_bytes()
    if len(raw) > LOG_READ_MAX_BYTES:
        raw = raw[-LOG_READ_MAX_BYTES:]
    return raw.decode("utf-8", errors="replace")


def _latex_log_user_excerpt(log_text: str, *, max_chars: int) -> str:
    """Prefer the last TeX error region; a plain tail is often only preamble noise."""
    if not log_text:
        return ""
    if len(log_text) <= max_chars:
        return log_text
    markers = ("\n! ", "\n!", "Emergency stop", "Fatal error", "==> Fatal error")
    best = -1
    for m in markers:
        idx = log_text.rfind(m)
        best = max(best, idx)
    if best != -1:
        chunk = log_text[best:].lstrip("\n")
        if len(chunk) <= max_chars:
            return chunk
        return chunk[:max_chars]
    return log_text[-max_chars:]


def _merge_latex_fail_detail(*, log_text: str, stderr: str, max_chars: int) -> str:
    excerpt = _latex_log_user_excerpt(log_text, max_chars=max_chars)
    err = (stderr or "").strip()
    if not err or err in excerpt:
        return excerpt
    suffix = f"\n\n--- latexmk / driver stderr ---\n{err[-4000:]}"
    if len(excerpt) + len(suffix) <= max_chars:
        return excerpt + suffix
    room = max(0, max_chars - len(suffix))
    return excerpt[:room] + suffix


def compile_solution_tex_to_pdf(
    tex_source: str,
    *,
    timeout: int,
    latex_binary: str,
) -> bytes:
    if not EVAN_STY_PATH.is_file():
        msg = f"Missing vendored evan.sty at {EVAN_STY_PATH}"
        raise SolutionPdfError(msg)
    if shutil.which(latex_binary) is None:
        msg = _MSG_TOOL_NOT_FOUND.format(binary=repr(latex_binary))
        raise SolutionPdfToolError(msg)

    with tempfile.TemporaryDirectory(prefix="ap_solution_pdf_") as tmp:
        tmp_path = Path(tmp)
        shutil.copy2(EVAN_STY_PATH, tmp_path / "evan.sty")
        main_tex = tmp_path / "main.tex"
        main_tex.write_text(tex_source, encoding="utf-8")
        cmd = [
            latex_binary,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            str(main_tex.name),
        ]
        try:
            completed = subprocess.run(  # noqa: S603
                cmd,
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_raw = _read_log_bytes(tmp_path / "main.log")
            log_tail = _merge_latex_fail_detail(log_text=log_raw, stderr="", max_chars=LOG_TAIL_MAX_CHARS)
            raise SolutionPdfCompileError(_MSG_LATEX_TIMEOUT, log_tail=log_tail) from exc

        pdf_path = tmp_path / "main.pdf"
        if pdf_path.is_file() and completed.returncode == 0:
            return pdf_path.read_bytes()

        log_raw = _read_log_bytes(tmp_path / "main.log")
        logger.warning(
            "solution_pdf_compile_failed returncode=%s",
            completed.returncode,
        )
        combined = _merge_latex_fail_detail(
            log_text=log_raw,
            stderr=completed.stderr or "",
            max_chars=LOG_TAIL_MAX_CHARS,
        ) or (completed.stderr or "")[-2000:]
        raise SolutionPdfCompileError(_MSG_LATEX_FAILED, log_tail=combined)


def compile_solution_to_pdf(
    solution: ProblemSolution,
    blocks: Sequence[ProblemSolutionBlock],
    params: SolutionPdfCompileParams,
) -> bytes:
    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=params.media_root,
        problem_label=params.problem_label,
        problem_statement_latex=params.problem_statement_latex,
    )
    return compile_solution_tex_to_pdf(
        tex,
        timeout=params.timeout,
        latex_binary=params.latex_binary,
    )
