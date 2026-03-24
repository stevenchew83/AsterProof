# User detail TTFB investigation and fix — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure server-side time for authenticated HTML (starting with `/users/<pk>/`), identify the dominant bottleneck, and ship a targeted fix with before/after TTFB evidence, per [`docs/superpowers/specs/2026-03-25-user-detail-ttfb-investigation-design.md`](../specs/2026-03-25-user-detail-ttfb-investigation-design.md).

**Architecture:** Add **env-gated** request timing logs for a short production/staging window; compare loopback vs public URL and a second authenticated route; then implement **one primary fix** backed by findings (possibly session/middleware/DB introspection caching or session backend tuning).

**Tech Stack:** Django 5, Gunicorn (assumed), PostgreSQL, Redis (production cache), `uv run pytest`, `uv run ruff check`.

---

## File map

| File | Role |
|------|------|
| `config/settings/base.py` | Default `REQUEST_TIMING_LOG = False`; insert `RequestTimingMiddleware` as **first** in `MIDDLEWARE` |
| `config/settings/production.py` | Read `DJANGO_REQUEST_TIMING_LOG`, set flag |
| `config/middleware.py` | **Create:** `RequestTimingMiddleware` (timing + structured log) |
| `.env.sample` | Document `DJANGO_REQUEST_TIMING_LOG` |
| `config/tests/test_request_timing_middleware.py` | **Create:** tests for off-by-default and on behavior |
| `inspinia/users/monitoring.py` | **Phase B (conditional):** e.g. cache `_model_table_exists` result per process |
| AWS / RDS runbook | **Out-of-repo:** optional slow-query logging |

**Middleware placement:** In Django, **earlier** entries in `MIDDLEWARE` are **outer** wrappers. To include `TrackActiveSessionMiddleware`’s post-response `touch_tracked_session` work in the same interval, add `RequestTimingMiddleware` as the **first** entry in `MIDDLEWARE` (outermost), so `self.get_response(request)` spans the entire inner chain including session touch. `request.user` is available inside the timed section once `AuthenticationMiddleware` has run (still inside `get_response`).

---

### Task 1: Baseline capture (manual, no code)

**Files:** None (notes in ticket or paste into PR).

- [ ] **Step 1:** From your **laptop**, DevTools → Network → document row for `/users/1/` (or your user pk): **TTFB** and total time.

- [ ] **Step 2:** From the **EC2 host** (SSH), time loopback (adjust port/socket if needed):

```bash
curl -sS -o /dev/null -w 'loopback TTFB starttransfer=%{time_starttransfer}s total=%{time_total}s\n' \
  -H 'Cookie: sessionid=YOUR_SESSION_ID' \
  http://127.0.0.1:8000/users/1/
```

Expected: a number; compare to public URL with same cookie (or use logged-in browser export).

- [ ] **Step 3:** Repeat for a **second** authenticated URL (e.g. `/` per spec) and record both.

- [ ] **Step 4:** If loopback is fast but public is slow, suspect **proxy/security group**; if both slow, suspect **app/DB**.

---

### Task 2: Settings flag for request timing

**Files:**
- Modify: `config/settings/base.py`
- Modify: `config/settings/production.py`
- Modify: `.env.sample`

- [ ] **Step 1:** In `base.py`, add:

```python
REQUEST_TIMING_LOG = False
```

- [ ] **Step 2:** In `production.py` (after imports from base), add:

```python
REQUEST_TIMING_LOG = env.bool("DJANGO_REQUEST_TIMING_LOG", default=False)
```

- [ ] **Step 3:** In `.env.sample`, add a commented line:

```
# DJANGO_REQUEST_TIMING_LOG=True  # short-lived: log per-request duration
```

- [ ] **Step 4:** Commit

```bash
git add config/settings/base.py config/settings/production.py .env.sample
git commit -m "config: env flag for request timing logs"
```

---

### Task 3: `RequestTimingMiddleware`

**Files:**
- Create: `config/middleware.py`
- Modify: `config/settings/base.py` (append middleware string, **before** `TrackActiveSessionMiddleware`)

- [ ] **Step 1:** Create `config/middleware.py`:

```python
from __future__ import annotations

import logging
import time
from typing import Callable

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse

logger = logging.getLogger(__name__)


class RequestTimingMiddleware:
    """Log request duration when settings.REQUEST_TIMING_LOG is True."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "REQUEST_TIMING_LOG", False):
            return self.get_response(request)

        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000
        user_id = getattr(getattr(request, "user", None), "pk", None)
        logger.info(
            "request_timing path=%s method=%s status=%s duration_ms=%.2f user_id=%s",
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            getattr(response, "status_code", 0),
            duration_ms,
            user_id,
        )
        return response
```

- [ ] **Step 2:** In `base.py` `MIDDLEWARE`, insert as the **first** element (index 0):

```python
"config.middleware.RequestTimingMiddleware",
```

- [ ] **Step 2b:** In `production.py`, change WhiteNoise insertion from `insert(1, …)` to **`insert(2, …)`** so the stack stays `RequestTiming → Security → WhiteNoise → …` (see file map note).

- [ ] **Step 3:** Commit

```bash
git add config/middleware.py config/settings/base.py
git commit -m "feat: optional request timing middleware"
```

---

### Task 4: Tests for timing middleware

**Files:**
- Create: `config/tests/test_request_timing_middleware.py`

- [ ] **Step 1:** Add tests:

```python
import logging

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory

from config.middleware import RequestTimingMiddleware


def test_request_timing_middleware_noop_when_disabled(settings, rf: RequestFactory):
    settings.REQUEST_TIMING_LOG = False

    def get_response(request):
        return HttpResponse("ok")

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/users/1/")
    response = mw(request)
    assert response.status_code == 200
    assert response.content == b"ok"


def test_request_timing_middleware_logs_when_enabled(settings, rf: RequestFactory, caplog):
    settings.REQUEST_TIMING_LOG = True
    caplog.set_level(logging.INFO)

    def get_response(request):
        return HttpResponse("ok")

    mw = RequestTimingMiddleware(get_response)
    request = rf.get("/test-path/")
    response = mw(request)
    assert response.status_code == 200
    assert any("request_timing" in r.message for r in caplog.records)
    assert any("/test-path/" in r.message for r in caplog.records)
```

- [ ] **Step 2:** Run

```bash
uv run pytest config/tests/test_request_timing_middleware.py -v
```

Expected: **2 passed**

- [ ] **Step 3:** Run

```bash
uv run ruff check config
```

Expected: **All checks passed**

- [ ] **Step 4:** Commit

```bash
git add config/tests/test_request_timing_middleware.py
git commit -m "test: request timing middleware"
```

---

### Task 5: Staging/production smoke (manual)

- [ ] **Step 1:** Deploy build with flag **off**; confirm no behavior change.

- [ ] **Step 2:** Set `DJANGO_REQUEST_TIMING_LOG=True`, restart app, hit `/users/<pk>/` a few times.

- [ ] **Step 3:** Collect log lines; identify p50/p95 duration; correlate with slow query logs if enabled.

- [ ] **Step 4:** Turn flag **off** after collection.

---

### Task 6: Phase B — Primary fix (branch on evidence)

**Files:** TBD. Examples tied to earlier hypotheses:

| If evidence shows… | Likely touch |
|--------------------|--------------|
| High time + `UserSession` / introspection | `inspinia/users/monitoring.py` — cache `_model_table_exists` (module-level bool set once True) |
| Session table hammering | `SESSION_ENGINE` → `cached_db` or cache backend using existing Redis |
| Single slow SQL | Migration/index or query change in the offending view |

- [ ] **Step 1:** Write a one-paragraph **finding → fix** note in the PR description.

- [ ] **Step 2:** Implement the **smallest** change that addresses the finding.

- [ ] **Step 3:** Add or extend tests for that change (e.g. monitoring behavior, session config sanity).

- [ ] **Step 4:** `uv run pytest` (relevant modules) and `uv run ruff check`.

- [ ] **Step 5:** Commit with a message that references the measured bottleneck.

---

### Task 7: Verification

- [ ] **Step 1:** Repeat Task 1 DevTools TTFB measurement; record **before/after**.

- [ ] **Step 2:** Confirm timing middleware is **disabled** in production default config.

- [ ] **Step 3 (spec Phase C):** If Task 6 introduced a concrete regression risk, add the **smallest** automated guard (test or assertion) documented in the PR; otherwise skip with a one-line rationale.

---

## Execution order

Tasks **1** and **5** (manual) can overlap with **2–4**. **6** only after **5**. **7** last.

---

## Out of scope

See spec: front-end LCP focus, wholesale session monitor rewrite.
