# ruff: noqa: EM101, EM102, PLR2004, S603, S607, TRY003
"""Prepare a reviewable image-only source snapshot; never commit or deploy it."""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

BASELINE_SHA = "fd2bb2bc737004652d4e72d4b44f1b80170cc67d"
COPY_PATHS = (
    "config/urls.py",
    "deployment/solution-image-privacy.nginx.conf",
    "docs/deployment/solution-image-privacy.md",
    "inspinia/solutions/forum_access.py",
    "inspinia/solutions/image_access.py",
    "inspinia/solutions/image_urls.py",
    "inspinia/solutions/public_views.py",
    "inspinia/solutions/collection_views.py",
    "inspinia/solutions/admin_collections.py",
    "inspinia/static/js/solution-document-preview-entry.js",
    "inspinia/static/js/solution-document-preview.bundle.js",
    "inspinia/static/js/solution-document-preview.bundle.js.map",
    "inspinia/static/js/solution-latex-hybrid.js",
    "inspinia/templates/solutions/partials/shared-solution-content.html",
    "inspinia/templates/solutions/problem-solution-editor.html",
    "inspinia/templates/solutions/admin-collection-edit.html",
    "inspinia/templates/solutions/collection-edit.html",
    "inspinia/templates/website/shared_collection.html",
    "scripts/tests/solution_document_preview.test.cjs",
    "scripts/deployment/solution_document_compat.py",
    "scripts/deployment/solution_image_compat.py",
    "scripts/deployment/release_manifest.py",
    "scripts/deployment/build_release.py",
)


def _replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError("Image compatibility extraction no longer matches its frozen baseline")
    return source.replace(before, after, 1)


def _views(source):
    source = _replace_once(
        source,
        "from inspinia.solutions.forms import ProblemSolutionForm\n",
        "from inspinia.solutions.forms import ProblemSolutionForm\n"
        "from inspinia.solutions.image_access import editor_image_base_url\n"
        "from inspinia.solutions.image_access import internal_image_base_url\n",
    )
    source = _replace_once(
        source,
        '                "id": solution.id,\n',
        '                "id": solution.id,\n'
        '                "image_base_url": internal_image_base_url(solution.pk),\n',
    )
    if source.count('"solution_media_base_url": _solution_media_base_url(request)') != 2:
        raise ValueError("Unexpected image editor consumers in the baseline")
    source = source.replace(
        '"solution_media_base_url": _solution_media_base_url(request)',
        '"solution_media_base_url": editor_image_base_url(problem.problem_uuid)',
    )
    source = _replace_once(
        source,
        '"solution_media_url": settings.MEDIA_URL,',
        '"solution_media_url": internal_image_base_url(solution.pk),',
    )
    return _replace_once(
        source,
        '"url": _absolute_media_file_url(request, row.file.url),',
        '"url": request.build_absolute_uri(internal_image_base_url(solution.pk) + canonical_path),',
    )


def _urls(source):
    source = _replace_once(
        source,
        "from .evaluation_consent_views import solution_reuse_consent_withdraw_view\n",
        "from .evaluation_consent_views import solution_reuse_consent_withdraw_view\n"
        "from .image_urls import urlpatterns as image_patterns\n",
    )
    return _replace_once(source, "urlpatterns = [\n", "urlpatterns = [\n    *image_patterns,\n")


def _list(source):
    source = _replace_once(
        source,
        '<article id="solution-{{ my_solution_row.id }}"',
        '<article data-solution-image-base-url="{{ my_solution_row.image_base_url }}" '
        'id="solution-{{ my_solution_row.id }}"',
    )
    source = _replace_once(
        source,
        "<article {% if row.id != my_solution_row.id %}",
        '<article data-solution-image-base-url="{{ row.image_base_url }}" {% if row.id != my_solution_row.id %}',
    )
    return _replace_once(
        source,
        'mediaUrlPrefix: "{{ MEDIA_URL|escapejs }}",',
        'mediaUrlPrefix: "{{ solution_media_base_url|escapejs }}",',
    )


def _worker(source):
    source = _replace_once(
        source,
        "from scripts.deployment.solution_document_compat import verified_reader_release\n",
        "from scripts.deployment.solution_document_compat import verified_reader_release\n"
        "from scripts.deployment.solution_image_compat import reader_required as image_reader_required\n"
        "from scripts.deployment.solution_image_compat import verified_reader_release as verified_image_reader\n",
    )
    document_guard = (
        "    def ensure_document_reader(self, contract: TargetContract, release: Path, "
        "*, required: bool = False) -> None:\n"
    )
    source = _replace_once(
        source, document_guard, document_guard + "        self.ensure_image_reader(contract, release)\n",
    )
    return _replace_once(
        source,
        "    def learning_reader_required(self, contract: TargetContract) -> bool:\n",
        "    def ensure_image_reader(self, contract: TargetContract, release: Path) -> None:\n"
        "        try:\n"
        "            required = image_reader_required(contract.registry_dir)\n"
        "        except (OSError, ValueError) as exc:\n"
        '            raise OperationError("image_reader_floor_unavailable") from exc\n'
        "        if required and not verified_image_reader(release):\n"
        '            raise OperationError("image_reader_required")\n\n'
        "    def learning_reader_required(self, contract: TargetContract) -> bool:\n",
    )


def _compatibility_tests(source):
    tree = ast.parse(source)
    spans = []
    for node in tree.body:
        forum_import = isinstance(node, ast.ImportFrom) and (
            node.module == "inspinia.solutions.forum_models"
            or (node.module == "inspinia.solutions" and any(item.name == "forum" for item in node.names))
        )
        forum_test = isinstance(node, ast.FunctionDef) and any(
            (isinstance(item, ast.Name) and item.id in {"forum", "SolutionForumTarget"})
            or (isinstance(item, ast.Attribute) and item.attr == "check_solution_forum_schema")
            for item in ast.walk(node)
        )
        if forum_import or forum_test:
            start = min([node.lineno, *(item.lineno for item in getattr(node, "decorator_list", []))])
            spans.append((start, node.end_lineno))
    lines = source.splitlines(keepends=True)
    for start, end in reversed(spans):
        del lines[start - 1:end]
    return "".join(lines).rstrip() + "\n"


def prepare(root: Path, output: Path):
    root = root.resolve(strict=True)
    if output.exists():
        raise ValueError("Compatibility output must not already exist")
    archive = subprocess.run(
        ["git", "archive", "--format=tar", BASELINE_SHA], cwd=root, check=True, capture_output=True,
    ).stdout
    output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(output, filter="data")
    changes = {}
    for relative in COPY_PATHS:
        current = root / relative
        if current.is_symlink() or not current.is_file():
            raise ValueError(f"Compatibility source must be a regular file: {relative}")
        changes[relative] = current.read_text()
    for relative, transform in (
        ("inspinia/solutions/views.py", _views),
        ("inspinia/solutions/urls.py", _urls),
        ("inspinia/templates/solutions/problem-solution-list.html", _list),
        ("scripts/deployment/operation_worker.py", _worker),
    ):
        changes[relative] = transform((output / relative).read_text())
    changes["inspinia/solutions/test_image_compatibility.py"] = _compatibility_tests(
        (root / "inspinia/solutions/test_image_access.py").read_text(),
    )
    changes["scripts/deployment/tests/test_solution_image_compat.py"] = _compatibility_tests(
        (root / "scripts/deployment/tests/test_solution_image_compat.py").read_text(),
    ).replace("compat.READER_SOURCES", "compat.COMPATIBILITY_SOURCES")
    changes["scripts/deployment/tests/test_solution_document_schema.py"] = (
        (output / "scripts/deployment/tests/test_solution_document_schema.py").read_text()
        .replace("compat.READER_SOURCES", "compat.IMAGE_COMPATIBILITY_SOURCES")
    )
    if (output / "inspinia/solutions/migrations/0013_solution_forum.py").exists():
        raise ValueError("Compatibility baseline unexpectedly contains the forum migration")
    patches = []
    for relative, body in sorted(changes.items()):
        destination = output / relative
        previous = destination.read_text() if destination.exists() else None
        patches.extend(
            difflib.unified_diff(
                (previous or "").splitlines(keepends=True),
                body.splitlines(keepends=True),
                fromfile="a/" + relative if previous is not None else "/dev/null",
                tofile="b/" + relative,
            ),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body)
    patch = output.parent / (output.name + ".patch")
    patch.write_text("".join(patches))
    manifest = {
        "format_version": 1,
        "baseline_sha": BASELINE_SHA,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "files": [
            {"path": relative, "sha256": hashlib.sha256(body.encode()).hexdigest()}
            for relative, body in sorted(changes.items())
        ],
        "production_artifact": False,
        "authorization": "Reviewable local preparation only; no commit, release SHA, deployment or proxy change",
    }
    (output.parent / (output.name + "-manifest.json")).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output), sort_keys=True, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
