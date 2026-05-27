from __future__ import annotations

import bleach
import markdown as markdown_lib
from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

ALLOWED_MARKDOWN_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_MARKDOWN_ATTRIBUTES = {
    "a": ["href", "rel", "target", "title"],
    "td": ["align"],
    "th": ["align"],
}
ALLOWED_MARKDOWN_PROTOCOLS = {"http", "https", "mailto"}
MATH_DELIMITER_PLACEHOLDERS = {
    r"\[": "ASTERPROOF_MATH_DISPLAY_OPEN",
    r"\]": "ASTERPROOF_MATH_DISPLAY_CLOSE",
    r"\(": "ASTERPROOF_MATH_INLINE_OPEN",
    r"\)": "ASTERPROOF_MATH_INLINE_CLOSE",
}


def render_markdown(value: str) -> SafeString:
    """Render trainer-authored Markdown while stripping unsafe HTML."""
    source = _protect_math_delimiters(value or "")
    raw_html = markdown_lib.markdown(
        source,
        extensions=["extra", "sane_lists"],
        output_format="html",
    )
    cleaned = bleach.clean(
        raw_html,
        tags=ALLOWED_MARKDOWN_TAGS,
        attributes=ALLOWED_MARKDOWN_ATTRIBUTES,
        protocols=ALLOWED_MARKDOWN_PROTOCOLS,
        strip=True,
    )
    linked = bleach.linkify(cleaned, callbacks=[_external_link_attrs])
    linked = _restore_math_delimiters(linked)
    return mark_safe(linked)  # noqa: S308


def _protect_math_delimiters(value: str) -> str:
    for delimiter, placeholder in MATH_DELIMITER_PLACEHOLDERS.items():
        value = value.replace(delimiter, placeholder)
    return value


def _restore_math_delimiters(value: str) -> str:
    for delimiter, placeholder in MATH_DELIMITER_PLACEHOLDERS.items():
        value = value.replace(placeholder, delimiter)
    return value


def _external_link_attrs(attrs, new=False):  # noqa: FBT002
    href_key = (None, "href")
    href = attrs.get(href_key, "")
    if href.startswith(("http://", "https://")):
        attrs[(None, "rel")] = "noopener noreferrer"
        attrs[(None, "target")] = "_blank"
    return attrs
