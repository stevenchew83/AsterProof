from __future__ import annotations

import html
import re

from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = INLINE_CODE_RE.sub(r"<code>\1</code>", escaped)
    escaped = BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return ITALIC_RE.sub(r"<em>\1</em>", escaped)


def render_markdown(value: str) -> SafeString:  # noqa: C901, PLR0915
    """Render a small, sanitized Markdown subset while leaving MathJax delimiters intact."""
    lines = (value or "").strip().splitlines()
    chunks: list[str] = []
    paragraph: list[str] = []
    in_list = False
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            chunks.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            chunks.append("</ul>")
            in_list = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                chunks.append(f"<pre><code>{html.escape(chr(10).join(code_lines), quote=True)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            close_list()
            chunks.append(f"<h5>{_inline_markdown(stripped[4:])}</h5>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            close_list()
            chunks.append(f"<h4>{_inline_markdown(stripped[3:])}</h4>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            close_list()
            chunks.append(f"<h3>{_inline_markdown(stripped[2:])}</h3>")
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            if not in_list:
                chunks.append("<ul>")
                in_list = True
            chunks.append(f"<li>{_inline_markdown(stripped[2:])}</li>")
            continue
        paragraph.append(stripped)

    if in_code:
        chunks.append(f"<pre><code>{html.escape(chr(10).join(code_lines), quote=True)}</code></pre>")
    flush_paragraph()
    close_list()
    return mark_safe("\n".join(chunks))  # noqa: S308
