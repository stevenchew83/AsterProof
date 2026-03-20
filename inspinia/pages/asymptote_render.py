from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ASY_BLOCK_RE = re.compile(r"\[asy\](?P<code>.*?)\[/asy\]", flags=re.DOTALL | re.IGNORECASE)
SVG_TAG_RE = re.compile(r"(<svg\b[\s\S]*?</svg>)", flags=re.IGNORECASE)
ASY_REMOTE_BASE_URL = "https://asymptote.ualberta.ca"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
UNSAFE_SVG_TAGS = {
    f"{{{SVG_NAMESPACE}}}foreignObject",
    f"{{{SVG_NAMESPACE}}}script",
    "foreignObject",
    "script",
}
UNSAFE_ATTR_PREFIXES = ("on",)
UNSAFE_ATTR_VALUES = ("javascript:",)

ET.register_namespace("", SVG_NAMESPACE)
ET.register_namespace("xlink", XLINK_NAMESPACE)


@dataclass(frozen=True)
class AsymptoteRenderResult:
    svg_markup: str
    error: str = ""
    backend: str = ""


def has_asymptote_blocks(statement_latex: str) -> bool:
    return bool(ASY_BLOCK_RE.search(statement_latex or ""))


def build_statement_render_segments(statement_latex: str) -> list[dict]:
    statement_text = statement_latex or ""
    segments: list[dict] = []
    cursor = 0

    for match in ASY_BLOCK_RE.finditer(statement_text):
        prefix = statement_text[cursor : match.start()]
        if prefix:
            segments.append({"kind": "text", "content": prefix})

        asy_code = match.group("code").strip()
        render_result = render_asymptote_svg(asy_code) if asy_code else AsymptoteRenderResult(
            svg_markup="",
            error="Empty Asymptote block.",
        )
        segments.append(
            {
                "backend_label": (
                    "Rendered locally"
                    if render_result.backend == "local"
                    else "Rendered via Asymptote Web Application"
                    if render_result.backend == "remote"
                    else ""
                ),
                "code": asy_code,
                "error": render_result.error,
                "kind": "asymptote",
                "svg_markup": render_result.svg_markup,
            },
        )
        cursor = match.end()

    suffix = statement_text[cursor:]
    if suffix or not segments:
        segments.append({"kind": "text", "content": suffix})

    return segments


@lru_cache(maxsize=128)
def render_asymptote_svg(asy_code: str) -> AsymptoteRenderResult:
    code = (asy_code or "").strip()
    if not code:
        return AsymptoteRenderResult(svg_markup="", error="Empty Asymptote block.")

    asy_executable = shutil.which("asy")
    if asy_executable:
        local_result = _render_asymptote_svg_local(code, asy_executable)
        if local_result.svg_markup:
            return local_result

    return _render_asymptote_svg_remote(code)


def _render_asymptote_svg_local(asy_code: str, asy_executable: str) -> AsymptoteRenderResult:
    with tempfile.TemporaryDirectory(prefix="asterproof-asy-") as tmp_dir:
        source_path = Path(tmp_dir) / "diagram.asy"
        output_path = Path(tmp_dir) / "diagram.svg"
        source_path.write_text(asy_code, encoding="utf-8")

        try:
            completed = subprocess.run(  # noqa: S603
                [asy_executable, "-f", "svg", "-o", str(output_path), str(source_path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
            )
        except OSError as exc:
            return AsymptoteRenderResult(svg_markup="", error=str(exc))
        except subprocess.TimeoutExpired:
            return AsymptoteRenderResult(svg_markup="", error="Local Asymptote render timed out.")

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "").strip() or "Local Asymptote render failed."
            return AsymptoteRenderResult(svg_markup="", error=error_text)

        if not output_path.exists():
            return AsymptoteRenderResult(svg_markup="", error="Local Asymptote render did not produce SVG output.")

        return AsymptoteRenderResult(
            svg_markup=_extract_svg_markup(output_path.read_bytes()),
            backend="local",
        )


def _render_asymptote_svg_remote(asy_code: str) -> AsymptoteRenderResult:
    try:
        connect_response = _post_remote_json(
            "/",
            {"reqType": "usrConnect"},
            content_type="application/json; charset=utf-8",
        )
        user_id = connect_response.get("usrID")
        if not user_id:
            return AsymptoteRenderResult(svg_markup="", error="Remote Asymptote service did not return a session id.")

        payload = {
            "reqType": "download",
            "id": user_id,
            "workspaceId": 1,
            "workspaceName": "asterproof",
            "codeOption": "false",
            "outputOption": "true",
            "codeText": asy_code,
            "requestedOutformat": "svg",
            "isUpdated": "false",
        }
        render_response = _post_remote_json(
            "/",
            payload,
            content_type="application/x-www-form-urlencoded",
            encode_form=True,
        )
        if render_response.get("responseType") != "ASY_OUTPUT_CREATED":
            error_text = (
                render_response.get("stderr")
                or render_response.get("errorText")
                or render_response.get("stdout")
                or "Remote Asymptote render failed."
            )
            return AsymptoteRenderResult(svg_markup="", error=str(error_text))

        svg_bytes = _post_remote_bytes(
            "/clients",
            payload,
            content_type="application/x-www-form-urlencoded",
            encode_form=True,
        )
        return AsymptoteRenderResult(
            svg_markup=_extract_svg_markup(svg_bytes),
            backend="remote",
        )
    except (TimeoutError, urllib.error.URLError, ValueError) as exc:
        return AsymptoteRenderResult(svg_markup="", error=str(exc))


def _post_remote_json(
    path: str,
    payload: dict,
    *,
    content_type: str,
    encode_form: bool = False,
) -> dict:
    raw_response = _post_remote_bytes(
        path,
        payload,
        content_type=content_type,
        encode_form=encode_form,
    )
    return json.loads(raw_response.decode("utf-8"))


def _post_remote_bytes(
    path: str,
    payload: dict,
    *,
    content_type: str,
    encode_form: bool = False,
) -> bytes:
    body = (
        urllib.parse.urlencode(payload).encode("utf-8")
        if encode_form
        else json.dumps(payload).encode("utf-8")
    )
    request = urllib.request.Request(  # noqa: S310
        ASY_REMOTE_BASE_URL + path,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def _extract_svg_markup(svg_bytes: bytes) -> str:
    decoded = svg_bytes.decode("utf-8", errors="replace")
    match = SVG_TAG_RE.search(decoded)
    if match is None:
        msg = "Asymptote output did not contain an SVG tag."
        raise ValueError(msg)
    return _sanitize_svg_markup(match.group(1))


def _sanitize_svg_markup(svg_markup: str) -> str:
    try:
        root = ET.fromstring(svg_markup)  # noqa: S314
    except ET.ParseError:
        return svg_markup

    _remove_unsafe_svg_children(root)
    _remove_unsafe_svg_attributes(root)

    return ET.tostring(root, encoding="unicode")


def _remove_unsafe_svg_children(root: ET.Element) -> None:
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag in UNSAFE_SVG_TAGS:
                parent.remove(child)


def _remove_unsafe_svg_attributes(root: ET.Element) -> None:
    for element in root.iter():
        unsafe_attributes = [
            attr_name
            for attr_name, attr_value in element.attrib.items()
            if _is_unsafe_svg_attribute(attr_name, attr_value)
        ]
        for attr_name in unsafe_attributes:
            element.attrib.pop(attr_name, None)


def _is_unsafe_svg_attribute(attr_name: str, attr_value: str) -> bool:
    normalized_name = attr_name.lower()
    normalized_value = attr_value.strip().lower()

    if normalized_name.startswith(UNSAFE_ATTR_PREFIXES):
        return True
    if any(marker in normalized_value for marker in UNSAFE_ATTR_VALUES):
        return True
    return normalized_name in {"href", f"{{{XLINK_NAMESPACE}}}href"} and normalized_value.startswith(
        "data:",
    )
