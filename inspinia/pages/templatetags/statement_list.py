from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def imo_slot_labels(value: object) -> str:
    """Turn comma-separated IMO slot indices into 'P2, P5' style labels."""
    if not value:
        return ""
    parts = [p.strip() for p in str(value).split(",")]
    return ", ".join(f"P{p}" for p in parts if p)


@register.simple_tag
def statement_topic_tag_links(links: list | None) -> str:
    """Render topic tag chips as comma-separated links (safe HTML)."""
    if not links:
        return mark_safe('<span class="text-muted fs-xs">—</span>')  # noqa: S308
    chunks: list[str] = []
    for item in links:
        label = escape(str(item.get("label") or ""))
        url = item.get("url") or ""
        if url:
            chunks.append(f'<a class="statement-inline-link" href="{escape(str(url))}">{label}</a>')
        elif label:
            chunks.append(f"<span>{label}</span>")
    if not chunks:
        return mark_safe('<span class="text-muted fs-xs">—</span>')  # noqa: S308
    return mark_safe(", ".join(chunks))  # noqa: S308


@register.filter
def ellipsize(value: object, max_len: int = 30) -> str:
    s = str(value or "").strip()
    if len(s) <= max_len:
        return s
    return f"{s[: max_len - 1]}…"
