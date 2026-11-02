"""One safe Markdown/LaTeX boundary for drafts, review and published notes."""

import html
import re
import unicodedata
import uuid
from contextlib import suppress
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import SubElement

import bleach
import markdown
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from markdown.extensions import Extension
from markdown.inlinepatterns import IMAGE_LINK_RE
from markdown.inlinepatterns import ImageInlineProcessor

from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import require_draft_owner
from inspinia.training.markdown import ALLOWED_MARKDOWN_ATTRIBUTES
from inspinia.training.markdown import ALLOWED_MARKDOWN_PROTOCOLS
from inspinia.training.markdown import ALLOWED_MARKDOWN_TAGS
from inspinia.users.roles import user_can_access_app_features

SOURCE_LIMIT = 64_000
UNSAFE_TEX = re.compile(
    r"\\(?:href|url|class|cssId|style|html[A-Za-z]*|require|autoload|input|include|includegraphics|"
    r"def|gdef|edef|xdef|let|futurelet|csname|catcode|newcommand|renewcommand|providecommand|"
    r"newenvironment|renewenvironment|unicode)\b",
    re.IGNORECASE,
)
MATH = re.compile(r"(?<!\\)(\$\$[\s\S]*?\$\$|\$[^\n$]+?\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\))")
MANAGED = re.compile(r"asset:([0-9a-fA-F-]{36})\Z")


def validate_learning_source(source):
    if not isinstance(source, str) or len(source) > SOURCE_LIMIT or "\x00" in source:
        msg = "Keep learning source within 64,000 text characters without null characters."
        raise ValidationError(msg)
    if UNSAFE_TEX.search(unicodedata.normalize("NFKC", source)):
        msg = (
            "Use mathematical LaTeX only; HTML, URL, styling, macro definitions and loading commands are unavailable."
        )
        raise ValidationError(msg)
    return source


class _ManagedImageProcessor(ImageInlineProcessor):
    def __init__(self, pattern, md, assets):
        super().__init__(pattern, md)
        self.assets = assets

    def handleMatch(self, match, data):  # noqa: N802 - Markdown extension API.
        element, start, end = super().handleMatch(match, data)
        if element is None:
            return element, start, end
        token = MANAGED.fullmatch(element.get("src", ""))
        key = None
        if token:
            with suppress(ValueError):
                key = str(uuid.UUID(token[1]))
        asset = self.assets.get(key) if key else None
        if not asset:
            warning = Element("span")
            warning.text = "[Image unavailable: use an authorised managed image.]"
            return warning, start, end
        url = asset.get("url", "")
        if (
            not isinstance(url, str)
            or not url.startswith("/library/")
            or "//" in url
            or any(character in url for character in "\\\r\n\x00")
        ):
            warning = Element("span")
            warning.text = "[Image unavailable.]"
            return warning, start, end
        wrapper = Element("span", {"class": "learning-managed-image"})
        image = SubElement(
            wrapper,
            "img",
            {
                "src": url,
                "alt": asset.get("alt", ""),
                "loading": "lazy",
                "decoding": "async",
            },
        )
        del image  # The ElementTree owns the child.
        details = [value for value in (asset.get("caption", ""), asset.get("credit", "")) if value]
        if details:
            caption = SubElement(wrapper, "span", {"class": "learning-image-caption"})
            caption.text = " · ".join(details)
        return wrapper, start, end


class _ManagedImages(Extension):
    def __init__(self, assets):
        super().__init__()
        self.assets = assets

    def extendMarkdown(self, md):  # noqa: N802 - Markdown extension API.
        # Let Markdown escape authored tags as text while retaining its own
        # structural syntax such as blockquotes. No author HTML enters the stash.
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        # Only explicit managed-image tokens enter image generation. Reference
        # images otherwise use Markdown's separate, uncontrolled URL processor.
        md.inlinePatterns.deregister("image_reference")
        md.inlinePatterns.register(_ManagedImageProcessor(IMAGE_LINK_RE, md, self.assets), "image_link", 150)


def render_learning_markdown(source, *, assets=None):
    """Assets is a server-authorised mapping; no URL is ever taken from user source."""
    try:
        validate_learning_source(source)
    except ValidationError as exc:
        return mark_safe(  # noqa: S308 - Every interpolated value is escaped text.
            '<p class="learning-render-warning">'
            + html.escape(" ".join(exc.messages))
            + '</p><pre class="tex2jax_ignore">'
            + html.escape(str(source)[:SOURCE_LIMIT])
            + "</pre>",
        )
    assets = assets or {}
    math = {}
    prefix = "LEARNINGMATH" + uuid.uuid4().hex.upper()

    def preserve(match):
        key = prefix + str(len(math)) + "END"
        math[key] = html.escape(match[0], quote=False)
        return key

    protected = MATH.sub(preserve, source)
    # Controlled images are constructed by the extension; raw author HTML is
    # disabled there. Both are included in the same final scrub.
    raw = markdown.markdown(
        protected,
        extensions=["extra", "sane_lists", _ManagedImages(assets)],
        output_format="html",
    )
    for key, value in math.items():
        raw = raw.replace(key, value)
    urls = {asset.get("url") for asset in assets.values() if isinstance(asset, dict)}

    def allowed_attribute(tag, name, value):
        if tag == "img":
            return (name == "src" and value in urls and value.startswith("/library/")) or name in {
                "alt",
                "loading",
                "decoding",
            }
        if tag == "span" and name == "class":
            return value in {"learning-managed-image", "learning-image-caption"}
        return name in ALLOWED_MARKDOWN_ATTRIBUTES.get(tag, [])

    cleaned = bleach.clean(
        raw,
        tags=ALLOWED_MARKDOWN_TAGS | {"img", "span"},
        attributes=allowed_attribute,
        protocols=ALLOWED_MARKDOWN_PROTOCOLS,
        strip=True,
    )
    return mark_safe(cleaned)  # noqa: S308 - Single final allowlist scrub, including generated images.


def render_draft(draft, user):
    from inspinia.learning.assets import asset_mapping

    require_draft_owner(draft, user)
    return render_learning_markdown(draft.body_source, assets=asset_mapping(user=user, draft=draft))


def render_revision(revision, user, *, public=False):
    from inspinia.learning.assets import asset_mapping
    from inspinia.learning.models import ContentPublication
    from inspinia.learning.models import ContributionProposal

    publication = ContentPublication.objects.filter(revision=revision)
    public_current = publication.filter(public_visible=True).exists()
    if public:
        allowed = public_current
    else:
        approved = bool(getattr(user, "is_active", False) and user_can_access_app_features(user))
        allowed = public_current or (
            approved
            and (
                revision.author_id == user.pk
                or publication.filter(training_visible=True).exists()
                or ContributionProposal.objects.filter(revision=revision, author_id=user.pk).exists()
                or (is_publisher(user) and ContributionProposal.objects.filter(revision=revision).exists())
            )
        )
    if not allowed:
        msg = "This revision is not available in this reading context."
        raise PermissionDenied(msg)
    # The page already provides the document title. Preserve all other authored headings.
    source = revision.body_source
    heading, separator, remainder = source.partition("\n")
    if heading.rstrip("\r") == f"# {revision.title}":
        source = remainder if separator else ""
    return render_learning_markdown(source, assets=asset_mapping(user=user, revision=revision))
