"""Sanitisation is exercised after Markdown/math placeholders and image generation."""

import uuid
from html.parser import HTMLParser

import pytest
from django.core.exceptions import ValidationError

from inspinia.learning.rendering import render_learning_markdown
from inspinia.learning.rendering import validate_learning_source


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_markdown_and_latex_keep_headings_tables_and_math_source():
    source = "## Assumptions\n\nFor $a_1,a_2 \\geq 0$,\n\n\\[\\frac{a_1+a_2}{2} \\geq \\sqrt{a_1a_2}.\\]"
    rendered = render_learning_markdown(source)
    assert "<h2>Assumptions</h2>" in rendered
    assert r"\frac{a_1+a_2}{2}" in rendered
    assert "<em>" not in rendered


def test_markdown_blockquotes_and_code_remain_available_without_authored_html():
    rendered = render_learning_markdown("> **Recognition cue:** balance the degrees.\n\n`<img src=x>`")
    assert "<blockquote>" in rendered
    assert "<strong>Recognition cue:</strong>" in rendered
    assert "<code>&lt;img src=x&gt;</code>" in rendered


@pytest.mark.parametrize("source", [
    '<script>alert(1)</script><img src=x onerror="alert(1)">',
    "[Unsafe](javascript:alert(1)) ![remote](https://example.com/tracker.png)",
    "![remote](data:image/svg+xml;base64,aaaa)",
])
def test_raw_html_and_unmanaged_images_cannot_create_executable_elements(source):
    elements = Elements(render_learning_markdown(source)).elements
    assert not any(tag in {"script", "iframe", "svg", "img"} for tag, _ in elements)
    assert not any(value.get("href", "").startswith("javascript:") for _, value in elements)
    assert not any(key.startswith("on") for _, values in elements for key in values)


def test_managed_image_uses_authorised_description_and_caption_inside_final_scrub():
    key = str(uuid.uuid4())
    url = f"/library/assets/{key}/"
    rendered = render_learning_markdown(f"![](asset:{key})", assets={key: {
        "url": url, "alt": 'Triangle " onerror="alert(1)',
        "caption": "<script>bad</script>", "credit": "Original contributor",
    }})
    elements = Elements(rendered).elements
    image = next(values for tag, values in elements if tag == "img")
    assert image["src"] == url
    assert image["alt"] == 'Triangle " onerror="alert(1)'
    assert "onerror" not in image
    assert not any(tag == "script" for tag, _ in elements)
    assert "Original contributor" in rendered


def test_guessed_or_external_mapping_does_not_load_an_image():
    key = str(uuid.uuid4())
    assert not any(tag == "img" for tag, _ in Elements(render_learning_markdown(f"![](asset:{key})")).elements)
    rendered = render_learning_markdown(f"![](asset:{key})", assets={key: {"url": "https://bad.example/image.png"}})
    assert not any(tag == "img" for tag, _ in Elements(rendered).elements)


def test_reference_images_cannot_bypass_managed_token_processor():
    key = str(uuid.uuid4())
    url = f"/library/assets/{key}/"
    source = f"![Uncontrolled description][diagram]\n\n[diagram]: {url}"
    rendered = render_learning_markdown(source, assets={key: {"url": url, "alt": "Approved description"}})
    assert not any(tag == "img" for tag, _ in Elements(rendered).elements)


@pytest.mark.parametrize("command", [r"\href{javascript:alert(1)}{x}", r"\require{html}",
    r"\class{bad}{x}", r"\newcommand{\x}{a}", r"\csname href\endcsname"])
def test_unsafe_tex_is_rejected_and_preview_preserves_inert_source(command):
    with pytest.raises(ValidationError):
        validate_learning_source(f"${command}$")
    rendered = render_learning_markdown(f"${command}$")
    assert any(tag == "pre" and values.get("class") == "tex2jax_ignore" for tag, values in Elements(rendered).elements)
    assert not any(tag == "a" for tag, _ in Elements(rendered).elements)
