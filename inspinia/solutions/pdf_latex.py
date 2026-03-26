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


def _is_plain_block(block: ProblemSolutionBlock) -> bool:
    return bool(block.block_type_id and block.block_type and block.block_type.slug == "plain")


def _graphicspath_tex(media_root: Path) -> str:
    media = media_root.resolve().as_posix()
    if not media.endswith("/"):
        media += "/"
    return media.replace("#", "\\#").replace("%", "\\%")


def _solution_pdf_author_display(user) -> str:
    name = (getattr(user, "name", None) or "").strip()
    return name or "Unknown"


def build_solution_tex_source(
    *,
    solution: ProblemSolution,
    blocks: Sequence[ProblemSolutionBlock],
    media_root: Path,
    problem_label: str,
    problem_statement_latex: str = "",
) -> str:
    title = latex_escape_plain_text(
        f"{problem_label} — {(solution.title or '').strip() or 'Untitled solution'}",
    )
    author = latex_escape_plain_text(_solution_pdf_author_display(solution.author))
    dt_ref = solution.published_at or solution.updated_at
    date_str = latex_escape_plain_text(
        timezone.localtime(dt_ref).strftime("%Y-%m-%d"),
    )
    gp = _graphicspath_tex(media_root)

    lines: list[str] = [
        r"\documentclass{scrartcl}",
        r"\usepackage[noasy]{evan}",
        rf"\graphicspath{{{gp}}}",
        rf"\title{{{title}}}",
        rf"\author{{{author}}}",
        rf"\date{{{date_str}}}",
        r"\begin{document}",
        r"\maketitle",
    ]
    stmt_body = (problem_statement_latex or "").strip()
    if stmt_body:
        lines.append(r"\section*{Problem}")
        lines.append(stmt_body)
        lines.append("")
    for block in blocks:
        if _is_plain_block(block):
            lines.append(block.body_source or "")
            lines.append("")
            continue
        heading = latex_escape_plain_text(_block_heading(block))
        lines.append(rf"\paragraph{{{heading}}}")
        lines.append(block.body_source or "")
        lines.append("")
    lines.append(r"\end{document}")
    return "\n".join(lines)


def _read_log_tail(path: Path) -> str:
    if not path.is_file():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > LOG_TAIL_MAX_CHARS:
        return data[-LOG_TAIL_MAX_CHARS:]
    return data


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
            log_tail = _read_log_tail(tmp_path / "main.log")
            raise SolutionPdfCompileError(_MSG_LATEX_TIMEOUT, log_tail=log_tail) from exc

        pdf_path = tmp_path / "main.pdf"
        if pdf_path.is_file() and completed.returncode == 0:
            return pdf_path.read_bytes()

        log_tail = _read_log_tail(tmp_path / "main.log")
        stderr_tail = (completed.stderr or "")[-2000:]
        logger.warning(
            "solution_pdf_compile_failed returncode=%s",
            completed.returncode,
        )
        combined = log_tail or stderr_tail
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
