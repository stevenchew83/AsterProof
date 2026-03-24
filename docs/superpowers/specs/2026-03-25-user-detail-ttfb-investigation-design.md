# User detail page high TTFB: investigation and fix

## Goal

Reduce **server-side latency** (high **Time To First Byte** on the HTML document) for authenticated requests, using `/users/<pk>/` (`UserDetailView`) as the initial example. The view and template are lightweight; the work is to **measure** where time is spent, then **fix** the dominant cause(s) without redesigning the product.

## Context

- **Route:** `users:detail` → `UserDetailView` (`inspinia/users/views.py`, `inspinia/users/urls.py`).
- **Template:** `user_detail.html` — simple `object` fields, no heavy in-template queries observed.
- **Observation:** In the browser, slowness presents as **high document TTFB** (option A), so the bottleneck is not primarily static subresources.
- **Hypotheses (to validate, not assume):** per-request middleware (`TrackActiveSessionMiddleware` → `touch_tracked_session` → `ensure_tracked_session`, `UserSession` I/O, `_model_table_exists`), Django session backend I/O, database round-trip latency, or duplicate user queries vs `request.user`.

## Decision (approved)

**Investigate first, then fix.**

1. **Phase A — Instrument (short-lived)**  
   - Compare timing from **app host to loopback** vs **public URL** to detect proxy/network vs app work.  
   - Add **temporary** server-side visibility: e.g. timing middleware (path, duration, optional query count behind an env flag) **and/or** PostgreSQL slow-query logging / `pg_stat_statements` for a bounded window.  
   - Record baseline for `/users/<pk>/` and at least one **lighter** authenticated route for contrast.

2. **Phase B — Fix**  
   - Apply changes **only** supported by Phase A evidence.  
   - Candidate directions (examples, not commitments): reduce per-request `_model_table_exists` cost if significant; tune `UserSession` touch/create path; session engine / caching if session DB dominates; `select_related` only if extra queries are proven; connection pooling / same-region DB if network/DB latency dominates.

3. **Phase C — Verify**  
   - Re-check **document TTFB** in DevTools before/after.  
   - Keep or add a **minimal** automated guard if a specific regression risk is identified (e.g. session middleware behavior).

## Out of scope

- Front-end LCP, image optimization, or CDN changes as the primary lever.  
- Rewriting session monitoring or audit semantics unless measurement shows they are the bottleneck and a smaller change is insufficient.

## Success criteria

- Document TTFB for `/users/<pk>/` (and similarly affected pages) is **measurably improved** on production or staging, with **before/after numbers** recorded.  
- The chosen fix is **traceable to measured evidence** (logs, query analysis, or timing breakdown).  
- Instrumentation that was only for diagnosis is **removed or gated** so it does not run unbounded in production unless explicitly desired.

## Notes for implementation planning

- Prefer **env-flagged** or **short-deploy** instrumentation over permanent verbose logging on every request.  
- If using query logging in Django, ensure it is **never** enabled with real user PII in untrusted environments without care.  
- Coordinate **RDS** logging changes with whoever owns the AWS account.
