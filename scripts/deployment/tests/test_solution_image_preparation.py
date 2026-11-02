# ruff: noqa: S607, SLF001
"""The compatibility extraction has no dependency on forum tables or reader routes."""

import subprocess
from pathlib import Path

from scripts.deployment import prepare_solution_image_compat as preparation

ROOT = Path(__file__).resolve().parents[3]


def baseline(relative):
    return subprocess.run(  # noqa: S603 - fixed git read of the reviewed immutable baseline
        ["git", "show", f"{preparation.BASELINE_SHA}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_image_only_views_keep_old_links_and_do_not_query_forum_tables():
    source = preparation._views(baseline("inspinia/solutions/views.py"))
    assert '"solution_media_base_url": editor_image_base_url(problem.problem_uuid)' in source
    assert '"image_base_url": internal_image_base_url(solution.pk)' in source
    assert '"solution_media_url": internal_image_base_url(solution.pk)' in source
    assert '"url": request.build_absolute_uri(internal_image_base_url(solution.pk) + canonical_path)' in source
    assert "?{urlencode({'solution': solution.id})}#solution-" in source
    assert 'Count("upvotes"' not in source
    assert "forum_models" not in source
    assert '"solutions:solution_detail"' not in source


def test_image_only_urls_and_templates_preserve_nonforum_navigation():
    urls = preparation._urls(baseline("inspinia/solutions/urls.py"))
    assert "*image_patterns" in urls
    assert "forum_patterns" not in urls
    template = preparation._list(baseline("inspinia/templates/solutions/problem-solution-list.html"))
    assert 'data-solution-image-base-url="{{ row.image_base_url }}"' in template
    assert 'data-solution-image-base-url="{{ my_solution_row.image_base_url }}"' in template
    assert "Top voted" not in template


def test_compatibility_image_tests_do_not_import_or_create_forum_targets():
    source = preparation._compatibility_tests((ROOT / "inspinia/solutions/test_image_access.py").read_text())
    assert "SolutionForumTarget" not in source
    assert "from inspinia.solutions import forum" not in source
    assert "test_public_image_is_bound_to_shared_snapshot_not_current_private_content" in source
    assert "test_private_image_requires_authentication" in source


def test_compatibility_copy_manifest_excludes_forum_migration_and_runtime():
    assert "inspinia/solutions/image_access.py" in preparation.COPY_PATHS
    assert "inspinia/solutions/public_views.py" in preparation.COPY_PATHS
    assert not any(
        "migrations/" in path or path.endswith(("forum.py", "forum_views.py", "forum_models.py"))
        for path in preparation.COPY_PATHS
    )
