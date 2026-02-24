import re

from django.utils.html import escape
from django.utils.safestring import mark_safe


def render_markdown_with_math(content: str):  # noqa: ANN201
    escaped = escape(content or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = escaped.replace("\n", "<br>")
    return mark_safe(escaped)  # noqa: S308
