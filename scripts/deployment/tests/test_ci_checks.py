from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.ci_checks import changed_paths
from scripts.ci_checks import select_checks

ROOT = Path(__file__).resolve().parents[3]


def test_documentation_changes_need_no_runtime_or_build():
    checks = select_checks(["README.md", "docs/deployment/production-release.md", "inspinia/pages/AGENTS.md"])
    assert checks == {"runtime": False, "workflows": False, "static": False, "locks": False, "tests": []}


@pytest.mark.parametrize("path", ["inspinia/rankings/views.py", "inspinia/templates/rankings/table.html"])
def test_app_changes_keep_permissions_and_settings_tests_without_other_app_suites(path):
    checks = select_checks([path])
    assert checks["tests"] == ["config/tests", "inspinia/rankings", "inspinia/users/tests"]
    assert checks["runtime"]
    assert not checks["static"]
    assert not checks["locks"]


def test_shared_problem_changes_cover_solution_and_problem_list_consumers():
    checks = select_checks(["inspinia/pages/models.py"])
    assert {"inspinia/pages", "inspinia/solutions", "inspinia/problemsets"} <= set(checks["tests"])


@pytest.mark.parametrize("path", ["inspinia/users/roles.py", "config/urls.py", "inspinia/templates/base.html"])
def test_shared_auth_routing_and_shell_changes_cover_all_apps(path):
    checks = select_checks([path])
    assert {
        "inspinia/pages", "inspinia/training", "inspinia/solutions", "inspinia/rankings", "inspinia/website",
    } <= set(checks["tests"])


def test_public_website_changes_run_their_own_tests():
    checks = select_checks(["inspinia/website/newsletter.py"])
    assert "inspinia/website" in checks["tests"]


def test_workflow_changes_run_deployment_contracts_and_actionlint():
    checks = select_checks([".github/workflows/ci.yml"])
    assert checks["workflows"]
    assert "scripts" in checks["tests"]
    assert "inspinia/pages" not in checks["tests"]


@pytest.mark.parametrize(
    "path", ["inspinia/static/scss/app.scss", "package-lock.json", "scripts/build_and_collectstatic.sh"],
)
def test_asset_changes_build_static_files(path):
    checks = select_checks([path])
    assert checks["static"]
    assert checks["runtime"]


def test_dependency_changes_keep_broad_tests_build_and_lock_validation():
    checks = select_checks(["requirements/production.lock"])
    assert checks["locks"]
    assert checks["static"]
    assert {"inspinia/pages", "inspinia/solutions", "scripts"} <= set(checks["tests"])


def test_unknown_paths_and_executable_docs_fail_toward_broad_checks():
    for path in ("new_shared_module.py", "docs/example.py", "inspinia/templates/help.md"):
        checks = select_checks([path])
        assert checks["runtime"]
        assert "inspinia/pages" in checks["tests"]


def test_mixed_docs_and_code_do_not_skip_tests():
    checks = select_checks(["docs/guide.md", "inspinia/training/services.py"])
    assert "inspinia/training" in checks["tests"]


def test_changed_paths_include_both_sides_of_rename_and_preserve_newlines(tmp_path):
    def git(*args):
        return subprocess.run(  # noqa: S603
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True,  # noqa: S607
        ).stdout.strip()

    git("init")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "Tests")
    (tmp_path / "runtime.py").write_text("# code\n")
    git("add", ".")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "runtime.py").rename(tmp_path / "README.md")
    (tmp_path / "new\nmodule.py").write_text("# code\n")
    git("add", ".")
    git("commit", "-m", "rename and add")
    assert set(changed_paths(base, root=tmp_path)) == {"runtime.py", "README.md", "new\nmodule.py"}


def test_invalid_base_does_not_silently_skip_checks():
    with pytest.raises(ValueError, match="exact PR base SHA"):
        changed_paths("--invalid")


def test_pr_ci_keeps_required_check_without_a_duplicate_main_run():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    # PyYAML's YAML 1.1 loader treats the Actions `on` key as True.
    assert set(workflow[True]) == {"pull_request", "workflow_dispatch"}
    assert workflow[True]["pull_request"] is None
    manual_input = workflow[True]["workflow_dispatch"]["inputs"]["baseline_sha"]
    assert manual_input["required"] is True
    assert manual_input["type"] == "string"
    assert set(workflow["jobs"]) == {"verify"}
    assert "if" not in workflow["jobs"]["verify"]
    assert "paths-ignore" not in workflow[True]
    assert workflow["permissions"] == {"contents": "read"}
    for name in ("Select checks and validate whitespace", "Rehearse the exact additive schema"):
        step = next(step for step in workflow["jobs"]["verify"]["steps"] if step["name"] == name)
        assert step["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha || inputs.baseline_sha }}"


@pytest.mark.parametrize("name", ["production-deploy.yml", "production-rollback.yml"])
def test_production_workflows_remain_manual(name):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    assert set(workflow[True]) == {"workflow_dispatch"}


def test_full_suite_and_verified_artifact_stay_in_manual_release():
    workflow = (ROOT / ".github/workflows/production-deploy.yml").read_text()
    assert workflow.count(".release-quality/bin/python -m pytest") == 1
    assert workflow.index(".release-quality/bin/python -m pytest") < workflow.index("Build immutable release")
    assert "artifact-ids: ${{ needs.build.outputs.artifact_id }}" in workflow
    assert "environment:\n      name: production" in workflow
