"""Allowlisted paths for \\includegraphics{...} in solution block bodies."""

from __future__ import annotations

import re
import unicodedata

ALLOWED_PREFIX = "solution_body_images/"
# Filenames from upload_to: uuid4 hex + allowed image extension.
_CANONICAL_PATH = re.compile(
    r"^solution_body_images/[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)$",
    re.IGNORECASE,
)


def is_allowed_includegraphics_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    normalized = unicodedata.normalize("NFKC", path).strip().replace("\\", "/")
    normalized = normalized.lstrip("/")
    if ".." in normalized or "//" in normalized:
        return False
    if ":" in normalized:
        return False
    if "\x00" in normalized:
        return False
    if not normalized.startswith(ALLOWED_PREFIX):
        return False
    return bool(_CANONICAL_PATH.match(normalized))
