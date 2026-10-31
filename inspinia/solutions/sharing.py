"""Public snapshots contain only content reviewed by their owner."""

import base64
import hashlib
import json
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse

from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.pdf_latex import solution_pdf_date_display

MAX_SHARED_BYTES = 1024 * 1024


def public_share_url(share):
    return settings.PUBLIC_SITE_ORIGIN.rstrip("/") + reverse("solutions:public_solution", args=[share.token])


def public_collection_url(collection):
    return settings.PUBLIC_SITE_ORIGIN.rstrip("/") + reverse("solutions:public_collection", args=[collection.token])


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
    if snapshot["author"]:
        details.append(f"By {snapshot['author']}")
    return " · ".join(part for part in details if part)[:200] + ". Read the full solution on AsterProof."


def public_preview_image():
    """Use the prebuilt website logo without rendering or exposing proof content."""
    return (settings.APPS_DIR / "static/images/asterproof-share-logo.jpg").read_bytes()
