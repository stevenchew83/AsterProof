# Inspinia Production Vendor Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure production ships `inspinia/static/js/vendors.min.js` so the Inspinia shell loads its shared frontend dependencies from `/static/` and authenticated dashboards regain sidenav/DataTables behavior.

**Architecture:** Add a small regression test that fails when the repo is missing the built vendor bundle, then unignore and regenerate that bundle with the existing Gulp pipeline. Keep Django static settings, template load order, and page code unchanged because the confirmed root cause is the missing built asset, not the runtime wiring.

**Tech Stack:** Django 5.1 staticfiles, pytest, Gulp 4, npm, jQuery, Bootstrap bundle, Lucide, SimpleBar, Git

---

## File Map

- Modify: `/Users/stevenchew/Dev/AsterProof/.gitignore`
  - Allow exactly one generated JS bundle to be tracked: `inspinia/static/js/vendors.min.js`
- Create: `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py`
  - Regression tests for required built static assets that must exist in the repo
- Create/generated: `/Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js`
  - Concatenated vendor bundle produced by `npm run build`
- Reference only: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/base.html`
  - Already loads `{% static 'js/vendors.min.js' %}`; do not modify it in this fix
- Reference only: `/Users/stevenchew/Dev/AsterProof/plugins.config.js`
  - Defines the vendor JS inputs (`jquery`, `bootstrap.bundle`, `lucide`, `simplebar`)
- Reference only: `/Users/stevenchew/Dev/AsterProof/gulpfile.js`
  - Already writes `vendors.min.js` into `inspinia/static/js/`

## Preflight

- Work in a dedicated git worktree before executing the plan.
- Start from `/Users/stevenchew/Dev/AsterProof`.
- If `node_modules/` is missing, run `npm ci` before the build task so the
  build stays aligned with the committed lockfile.
- Do **not** change Django settings, template load order, or DataTables page code in this plan. Those are outside the approved scope.

### Task 1: Add a regression test for the required vendor bundle

**Files:**
- Create: `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py`

- [ ] **Step 1: Write the failing regression test**

Create `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py` with:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORS_BUNDLE = REPO_ROOT / "inspinia" / "static" / "js" / "vendors.min.js"


def _read_vendor_bundle() -> str:
    assert VENDORS_BUNDLE.is_file(), (
        "Expected built vendor bundle at "
        f"{VENDORS_BUNDLE}. Run `npm run build` and commit the generated file."
    )
    return VENDORS_BUNDLE.read_text(encoding="utf-8")


def test_inspinia_vendor_bundle_exists():
    assert VENDORS_BUNDLE.is_file(), (
        "Expected built vendor bundle at "
        f"{VENDORS_BUNDLE}. Run `npm run build` and commit the generated file."
    )


def test_inspinia_vendor_bundle_contains_expected_vendor_markers():
    bundle_lower = _read_vendor_bundle().lower()

    for marker in ("jquery", "bootstrap", "lucide", "simplebar"):
        assert marker in bundle_lower
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py -q
```

Expected: FAIL because `/Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js` does not exist yet.

- [ ] **Step 3: Commit the failing-test-only checkpoint if your workflow requires it**

If you prefer strict TDD checkpoints in your worktree, create a local checkpoint commit after the failing test and before the build output exists. If you do this, keep it local and squash or drop it before the final shared fix commit so the final history stays unambiguous.

### Task 2: Unignore and generate the tracked vendor bundle

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/.gitignore`
- Create/generated: `/Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js`
- Test: `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py`

- [ ] **Step 1: Add the targeted `.gitignore` exception**

In `/Users/stevenchew/Dev/AsterProof/.gitignore`, update the minified-JS block so it reads:

```gitignore
vendors.js
*.min.js
*.min.js.map
!inspinia/static/js/vendors.min.js
!inspinia/static/plugins/**/*.min.js
!inspinia/static/plugins/**/*.min.css
```

Do not relax the ignore rules more broadly than this single generated bundle.

- [ ] **Step 2: Rebuild frontend assets with the existing pipeline**

If `node_modules/` is missing, run:

```bash
npm ci
```

Then run:

```bash
npm run build
```

Expected:
- Gulp finishes successfully
- `/Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js` is created
- existing CSS/plugin outputs remain in their current locations

- [ ] **Step 3: Verify the build output path matches the template contract**

Confirm these read-only facts before making any further changes:

- `/Users/stevenchew/Dev/AsterProof/inspinia/templates/base.html` already loads `{% static 'js/vendors.min.js' %}`
- `/Users/stevenchew/Dev/AsterProof/gulpfile.js` already writes `vendors.min.js` into `inspinia/static/js/`
- `/Users/stevenchew/Dev/AsterProof/plugins.config.js` already defines the intended vendor inputs

No edits are needed in any of those files if the build output lands in the expected path.

- [ ] **Step 4: Re-run the focused test to verify it passes**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify git no longer ignores the generated bundle**

Run:

```bash
git check-ignore /Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js
```

Expected:
- no output
- exit status `1` because the file is no longer ignored

- [ ] **Step 6: Verify the generated bundle contains the expected vendor families**

Run:

```bash
rg -i "jquery|bootstrap|lucide|simplebar" /Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js
```

Expected: matches from the generated bundle confirming the vendor signatures are present.

### Task 3: Run final local verification and prepare rollout

**Files:**
- Modify: none
- Test: `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py`

- [ ] **Step 1: Run the Django system check**

Run:

```bash
uv run python manage.py check
```

Expected: Django reports no issues.

- [ ] **Step 2: Confirm the working tree only contains the intended fix**

Run:

```bash
git status --short
```

Expected: only the planned fix files appear before commit:
- `/Users/stevenchew/Dev/AsterProof/.gitignore`
- `/Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py`
- `/Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js`

If anything outside those files appears, stop and investigate before committing.

- [ ] **Step 3: Commit the shipped-bundle fix after validation passes**

Run:

```bash
git add /Users/stevenchew/Dev/AsterProof/.gitignore /Users/stevenchew/Dev/AsterProof/config/tests/test_static_assets.py /Users/stevenchew/Dev/AsterProof/inspinia/static/js/vendors.min.js
git commit -m "fix(static): ship Inspinia vendor bundle"
```

Expected: commit contains only the ignore-rule update, the new regression test, and the generated vendor bundle.

- [ ] **Step 4: Confirm the worktree is clean after the commit**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 5: Record the production verification commands for rollout**

After deployment, run:

```bash
curl -I "http://18.142.249.181/static/js/vendors.min.js"
```

Expected: `HTTP/1.1 200 OK` (or equivalent `200` response through the production proxy).

- [ ] **Step 6: Verify the reported production page in a browser session**

After deployment, sign in and verify the page below:

```text
http://18.142.249.181/dashboard/problem-statements/
```

Expected:
- sidenav toggle works
- the page no longer fails because `vendors.min.js` is missing
- representative DataTables pages initialize normally in production

## Rollout Notes

- This change intentionally does **not** modify `config/settings/production.py`, WhiteNoise, `STATIC_URL`, or template load order.
- The normal production deploy should still include `collectstatic` and the usual app restart/redeploy so the tracked bundle is copied into the served static tree.
- If production still shows JavaScript errors after `/static/js/vendors.min.js` returns `200`, stop and open a new bug/spec with fresh runtime evidence instead of expanding this fix ad hoc.
