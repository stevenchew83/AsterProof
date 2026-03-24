# AWS static single-origin `/static/` implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure production AWS serves all Django `{% static %}` assets from a single coherent `/static/` tree (built via `npm run build` + `collectstatic`), with S3 used only for media — matching [`docs/superpowers/specs/2026-03-24-aws-static-single-origin-design.md`](../specs/2026-03-24-aws-static-single-origin-design.md).

**Architecture:** Keep current `config/settings/production.py` model (WhiteNoise + filesystem `staticfiles` storage). Fix **process and infrastructure** so deploys always include fresh `STATIC_ROOT` output and nothing in front of the app serves a stale S3 “static” mirror for the same URLs. Document the pipeline in-repo; add a regression test on `STORAGES`; add `scripts/build_and_collectstatic.sh` for repeatable CI/container builds.

**Tech Stack:** Django 5, WhiteNoise, `django-storages` (S3 for `default` only), npm/gulp frontend build, `uv` for Python commands (per repo norms).

---

## File map

| File | Role |
|------|------|
| `README.md` | Document production static pipeline and AWS verification checklist |
| `scripts/build_and_collectstatic.sh` | **Create:** run `npm run build` + `collectstatic` with settings that need no production secrets |
| `config/tests/test_production_settings.py` | **Modify:** assert `staticfiles` stays on filesystem and `default` stays on S3 |
| `config/AGENTS.md` | **Modify:** one short bullet pointing deployers to README static section |
| AWS / reverse-proxy config | **Out-of-repo:** engineer records actual `/static/` routing (nginx/ALB vs WhiteNoise-only) and removes conflicting S3 static if any |

---

### Task 1: Confirm root cause (manual, before code changes)

**Files:** None (browser + infra console).

- [ ] **Step 1:** Open the **same authenticated page** on localhost and on AWS (e.g. main dashboard after login).

- [ ] **Step 2:** In DevTools **Network**, filter by `JS` and `CSS`. For each environment, confirm requests for:
  - `/static/js/vendors.min.js`
  - `/static/js/app.js`
  - `/static/css/app.min.css`
  Record status code, **full URL** (same host vs S3/CloudFront), and **Content-Type**.

- [ ] **Step 3:** If any core asset is **404**, **301/302 to another host**, or **HTML error body**, note it — that is the primary fix target (routing, missing `collectstatic` in artifact, or wrong `STATIC_ROOT` on the server).

- [ ] **Step 4:** In AWS (or your host), identify **how `/static/` is served** today: only the app (WhiteNoise), nginx/ALB `alias` to disk, S3/CloudFront, or mixed. Write one sentence in your notes for Task 5.

**Expected:** You can state whether the bug is “missing files,” “wrong host,” or “stale cache,” and which component serves `/static/`.

---

### Task 2: Regression test — production `STORAGES` layout

**Files:**
- Modify: `config/tests/test_production_settings.py`
- Test: `config/tests/test_production_settings.py` (same file)

- [ ] **Step 1: Add the test**

Append:

```python
def test_production_settings_staticfiles_on_filesystem_default_on_s3(monkeypatch):
    production = _load_production_settings(monkeypatch)

    assert production.STORAGES["staticfiles"]["BACKEND"] == (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    assert production.STORAGES["default"]["BACKEND"] == (
        "storages.backends.s3.S3Storage"
    )
    assert production.STORAGES["default"]["OPTIONS"]["location"] == "media"
```

- [ ] **Step 2: Run test**

Run: `uv run pytest config/tests/test_production_settings.py::test_production_settings_staticfiles_on_filesystem_default_on_s3 -v`

Expected: **PASS**

- [ ] **Step 3: Commit**

```bash
git add config/tests/test_production_settings.py
git commit -m "test: lock production staticfiles to filesystem storage"
```

---

### Task 3: Create `scripts/build_and_collectstatic.sh`

**Files:**
- Create: `scripts/build_and_collectstatic.sh`

- [ ] **Step 1: Add executable script**

Create `scripts/build_and_collectstatic.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

npm install
npm run build

# Use test settings so collectstatic does not require production AWS/DB env.
# Output matches STATICFILES_DIRS → STATIC_ROOT the same as local/production for static files.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
uv run python manage.py collectstatic --noinput

echo "collectstatic complete. Files are under STATIC_ROOT (repo root staticfiles/)."
```

Run: `chmod +x scripts/build_and_collectstatic.sh`

Commit the executable bit so clones work without `chmod`:

```bash
git update-index --chmod=+x scripts/build_and_collectstatic.sh
```

- [ ] **Step 2: Dry run locally**

Run: `./scripts/build_and_collectstatic.sh`

Expected: Gulp build succeeds; `collectstatic` copies files into `staticfiles/` (directory remains gitignored).

- [ ] **Step 3: Commit** (include executable bit in Git’s index)

```bash
git add scripts/build_and_collectstatic.sh
git update-index --chmod=+x scripts/build_and_collectstatic.sh
git commit -m "chore: script for npm build + collectstatic (test settings)"
```

---

### Task 4: Document production static pipeline in `README.md`

**Files:**
- Modify: `README.md` (after the existing **Frontend assets** section, ~line 101)

- [ ] **Step 1: Insert section**

Add a new subsection **Production static files (AWS)** after the Frontend assets block:

```markdown
## Production static files (AWS)

All dashboard JS/CSS and vendored `plugins/` under `inspinia/static/` must be **built and collected** into `STATIC_ROOT` (`staticfiles/` at the repo root) before or during deploy. **S3 is for user media only** (`STORAGES.default`); do not serve `/static/` from a stale bucket prefix alongside the app.

**Build + collect (recommended):**

```bash
./scripts/build_and_collectstatic.sh
```

Or manually: `npm install && npm run build`, then `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py collectstatic --noinput`.

**Deploy artifact:** The running app (or reverse proxy) must serve `/static/` from that collected tree — e.g. WhiteNoise (enabled in production settings) and/or nginx/ALB `alias` to `STATIC_ROOT`. Avoid mixing another origin for the same `/static/...` paths.

**Verify after deploy:** On production, open DevTools → Network and confirm `vendors.min.js`, `app.js`, and `app.min.css` return **200** from your **app hostname** with correct content types. Compare with localhost on the same page.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: production static build and AWS verification"
```

---

### Task 5: Point `config/AGENTS.md` at deploy docs

**Files:**
- Modify: `config/AGENTS.md`

- [ ] **Step 1:** Under **Change discipline** or **Validation**, add one bullet:

`When changing static, media, or middleware that affects `/static/`, see **Production static files (AWS)** in the root README and keep S3 on `default` (media) only unless deliberately redesigning storage.`

- [ ] **Step 2: Commit**

```bash
git add config/AGENTS.md
git commit -m "docs: link config agents to production static README"
```

---

### Task 6: Align AWS infrastructure (manual)

**Files:** Terraform, CDK, Elastic Beanstalk extensions, nginx conf, etc. (wherever your team keeps them — not necessarily in this repo).

- [ ] **Step 1:** Ensure the deploy pipeline runs **Task 3’s script** (or equivalent `npm run build` + `collectstatic`) so the runtime filesystem contains an up-to-date `staticfiles/` directory.

- [ ] **Step 2:** If a bucket or CloudFront distribution was serving **app** static for `/static/`, **remove or disable** that path so only the app (or a single nginx alias to `STATIC_ROOT`) answers `/static/*`.

- [ ] **Step 3:** If nginx terminates `/static/` **before** the request hits Django, confirm `alias` points at the **same** `STATIC_ROOT` produced by the deploy, not an old S3 sync.

- [ ] **Step 4:** Record in your team runbook (wiki, infra repo, or `docs/` if you keep ops notes there) one line: “Static: WhiteNoise only” vs “nginx `alias` + WhiteNoise fallback” — so future changes do not introduce a second source.

**Expected:** One serving path for `/static/`, matching the built artifact version.

---

### Task 7: Final verification

- [ ] **Step 1:** Run `uv run pytest config/tests/test_production_settings.py -v`

Expected: **All PASS**

- [ ] **Step 2:** Run `uv run ruff check config`

Expected: **Clean**

- [ ] **Step 3:** Repeat Task 1 Network checks on AWS. Shell (sidebar/topbar) and one DataTables page + one ApexCharts page should match localhost behavior.

- [ ] **Step 4:** If MathJax pages still fail but `/static/` is healthy, stop — treat as CDN/CSP follow-up (out of spec scope).

---

## Execution order summary

1. Task 1 (manual diagnosis) — can run in parallel with Task 2.  
2. Task 2 → Task 3 → Task 4 → Task 5 (repo changes, sequential commits as you prefer).  
3. Task 6 (infra) depends on Task 1 clarity.  
4. Task 7 last.

---

## Out of scope (per spec)

- Moving staticfiles to S3/CloudFront as primary storage.  
- Self-hosting MathJax.  
- Changing Django views/templates except where required for unrelated bugs discovered during verification.
