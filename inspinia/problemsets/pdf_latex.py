from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone

from inspinia.solutions.pdf_latex import compile_solution_tex_to_pdf
from inspinia.solutions.pdf_latex import latex_escape_plain_text

if TYPE_CHECKING:
    from inspinia.problemsets.models import ProblemList


@dataclass(frozen=True)
class ProblemListPdfCompileParams:
    timeout: int
    latex_binary: str


def compile_problem_list_to_pdf(
    problem_list: ProblemList,
    item_rows: list[dict],
    params: ProblemListPdfCompileParams,
) -> bytes:
    tex_source = build_problem_list_tex_source(problem_list, item_rows)
    return compile_solution_tex_to_pdf(
        tex_source,
        timeout=params.timeout,
        latex_binary=params.latex_binary,
    )


def build_problem_list_tex_source(problem_list: ProblemList, item_rows: list[dict]) -> str:
    title = latex_escape_plain_text(problem_list.title)
    author = latex_escape_plain_text(_problem_list_pdf_author(problem_list))
    dt_ref = problem_list.published_at or problem_list.updated_at
    date_str = latex_escape_plain_text(timezone.localtime(dt_ref).strftime("%Y-%m-%d"))

    lines: list[str] = [
        r"\documentclass[11pt]{scrartcl}",
        r"\usepackage[sexy,noasy]{evan}",
        rf"\title{{{title}}}",
        rf"\author{{{author}}}",
        rf"\date{{{date_str}}}",
        r"\begin{document}",
        r"\maketitle",
    ]

    description = (problem_list.description or "").strip()
    if description:
        lines.extend(["", latex_escape_plain_text(description), ""])

    if not item_rows:
        lines.extend(["", r"\textit{This public list does not have visible active problems yet.}"])

    for row in item_rows:
        heading = latex_escape_plain_text(f"Problem {row['position']}. {row['display_label']}")
        lines.extend(["", rf"\section*{{{heading}}}"])

        metadata = _problem_metadata_parts(problem_list, row)
        if metadata:
            lines.append(rf"\textit{{{latex_escape_plain_text(' | '.join(metadata))}}}")
            lines.append("")

        topic_tags = row.get("topic_tags") or []
        if topic_tags and not problem_list.hide_subtopics:
            tags = latex_escape_plain_text(", ".join(topic_tags))
            lines.extend([rf"\textbf{{Tags:}} {tags}", ""])

        problem_notes = row.get("problem_notes") or []
        for note in problem_notes:
            label = latex_escape_plain_text(note["label"])
            value = latex_escape_plain_text(note["value"])
            lines.append(rf"\textbf{{{label}:}} {value}")
        if problem_notes:
            lines.append("")

        statement = row.get("statement")
        statement_latex = ((statement.statement_latex if statement is not None else "") or "").strip()
        if statement_latex:
            lines.append(r"\begin{mdframed}[style=mdpurplebox,frametitle={Statement}]")
            lines.append(statement_latex)
            lines.append(r"\end{mdframed}")
        else:
            lines.append(r"\textit{No linked statement is available for this problem yet.}")

    lines.append(r"\end{document}")
    return "\n".join(lines)


def _problem_list_pdf_author(problem_list: ProblemList) -> str:
    user = problem_list.author
    name = (getattr(user, "name", "") or "").strip()
    label = name or user.email
    return f"Curated by {label}"


def _problem_metadata_parts(problem_list: ProblemList, row: dict) -> list[str]:
    parts: list[str] = []
    if row.get("show_source_context"):
        parts.append(row["problem_label"])
    if not problem_list.hide_topic:
        parts.append(row["topic_label"])
    if not problem_list.hide_mohs:
        mohs = row.get("mohs")
        parts.append(f"MOHS {mohs if mohs not in (None, '') else '-'}")
    return parts
