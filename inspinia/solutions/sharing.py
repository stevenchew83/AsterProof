"""Public snapshots contain only content reviewed by their owner."""

import base64
import hashlib
import json
import re
from io import BytesIO
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.pdf_latex import solution_pdf_date_display

MAX_SHARED_BYTES = 1024 * 1024
PREVIEW_SIZE = (1200, 630)


def public_share_url(share):
    return settings.PUBLIC_SITE_ORIGIN.rstrip("/") + reverse("solutions:public_solution", args=[share.token])


def whatsapp_share_url(url):
    return "https://wa.me/?" + urlencode({"text": url})


def build_public_snapshot(solution, problem_data, coverage):
    author = (solution.author.name or "").strip()
    # A name is optional; never fall back to the account email on public pages.
    author = author if author and "@" not in author else "AsterProof learner"
    segments = []
    for segment in problem_data["statement_render_segments"]:
        if segment["kind"] == "text":
            segments.append({"kind": "text", "content": segment["content"]})
        elif segment.get("svg_markup"):
            # SVG is displayed as an image, never injected into the document.
            encoded = base64.b64encode(segment["svg_markup"].encode()).decode("ascii")
            segments.append({
                "kind": "image", "src": "data:image/svg+xml;base64," + encoded,
                "diagram_source": segment.get("code", ""),
            })
        else:
            segments.append({"kind": "diagram_source", "content": segment.get("code", "")})
    snapshot = {
        "version": 1,
        "title": solution.title.strip() or problem_data["problem_label"],
        "summary": solution.summary,
        "author": author if solution.pdf_show_author else "",
        "date": solution_pdf_date_display(solution) if solution.pdf_show_date else "",
        "show_footer": solution.pdf_show_footer,
        "problem": {
            "label": problem_data["problem_label"],
            "topic": display_topic_label(solution.problem.topic),
            "mohs": problem_data["problem_mohs"],
            "segments": segments,
            "areas": list(coverage["concept_areas"]),
            "concepts": [row["display"] for row in coverage["concept_coverage"]],
        },
        "blocks": [
            {
                "heading": block.title,
                "label": block.block_type.label if block.block_type else "",
                "format": block.body_format,
                "source": block.body_source,
            }
            for block in solution.blocks.select_related("block_type").order_by("position", "id")
        ],
    }
    if not snapshot["blocks"]:
        message = "Add and save at least one solution block before sharing."
        raise ValidationError(message)
    if len(json.dumps(snapshot, ensure_ascii=False).encode()) > MAX_SHARED_BYTES:
        message = "This solution is too large to share. Reduce its size and save before trying again."
        raise ValidationError(message)
    return snapshot


def snapshot_digest(snapshot):
    # SVG IDs/layout can differ between renderer processes; compare the source
    # instead, while binding all author, statement, option, and proof content.
    reviewed = {**snapshot, "problem": {**snapshot["problem"], "segments": [
        {key: value for key, value in segment.items() if key != "src"}
        for segment in snapshot["problem"]["segments"]
    ]}}
    return hashlib.sha256(json.dumps(reviewed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def public_description(snapshot):
    problem = snapshot["problem"]
    details = [problem["label"], problem["topic"]]
    if problem["mohs"] is not None:
        details.append(f"MOHS {problem['mohs']}")
    if snapshot["author"]:
        details.append(f"By {snapshot['author']}")
    return " · ".join(part for part in details if part)[:200] + ". Read the full solution on AsterProof."


def _image_lines(draw, text, font, *, width, max_lines):
    """Wrap by measured glyph widths, including titles without spaces."""
    text = re.sub(r"\s+", " ", text).strip()
    lines = []
    current = ""
    for char in text:
        if current and draw.textlength(current + char, font=font) > width:
            lines.append(current.rstrip())
            current = ""
            if len(lines) == max_lines:
                break
        current += char
    else:
        if current:
            lines.append(current)
        return lines
    # There is more title text than the card can display.
    last = lines[-1]
    while last and draw.textlength(last + "…", font=font) > width:
        last = last[:-1]
    lines[-1] = last.rstrip() + "…"
    return lines


def build_preview_image(snapshot):
    """Generate once on sharing; public requests never compile math or fetch URLs."""
    image = Image.new("RGB", PREVIEW_SIZE, "#f8f7f2")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=62)
    body_font = ImageFont.load_default(size=28)
    brand_font = ImageFont.load_default(size=32)
    draw.rectangle((0, 0, 16, 630), fill="#28766a")
    draw.text((72, 54), "AsterProof", fill="#28766a", font=brand_font)
    draw.text((72, 132), "A SHARED SOLUTION", fill="#55675f", font=body_font)
    for row, line in enumerate(_image_lines(draw, snapshot["title"], title_font, width=1056, max_lines=3)):
        draw.text((72, 195 + row * 78), line, fill="#233d34", font=title_font)
    details = snapshot["problem"]["topic"]
    if snapshot["problem"]["mohs"] is not None:
        details += f" · MOHS {snapshot['problem']['mohs']}"
    draw.line((72, 486, 1128, 486), fill="#ccd6ca", width=2)
    draw.text((72, 514), details[:65], fill="#28766a", font=body_font)
    draw.text((72, 561), "Read the problem. Follow the proof.  /  asterproof.com", fill="#55675f", font=body_font)
    output = BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()
