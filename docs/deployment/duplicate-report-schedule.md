# Independent duplicate-report maintenance and request timing

The frequent `recompute_technique_progress_catalog` command publishes technique
facts and concept summaries. It does not import or run duplicate analysis. The
legacy `--catalog-only` option remains accepted for existing callers.

`refresh_statement_duplicate_report` is a separate command. Its existing disk
index, lock, time budget, source-change guard and atomic cache publication remain
in use. It reads statement data and writes only disposable report cache/scratch;
it does not modify completions, catalogue memberships or personal progress.

The independent timer runs at **02:00 Asia/Kuala_Lumpur**, using the existing
application account, environment and managed `current` release. It never catches
up a missed night during daytime. The job has low CPU/I/O weight, a 160 MiB memory
high watermark, 192 MiB maximum and a 25-minute service timeout. A failed or
interrupted run leaves the previous complete cache publication available.
Completed reports are marked stale after 26 hours; cache retention is 72 hours
(71 hours for the manifest), allowing the previous report to survive two missed
nights when the cache backend retains its keys. Forced eviction or cache loss
still produces the existing unavailable/pending state; requests never rebuild.

The service requires the app to be active without starting it, and is ordered
after it. Explicitly stopping the app stops duplicate analysis first, including
during maintenance. Starting/restarting an app with an inactive duplicate job
does not launch analysis. The native CI test exercises these dependencies using
synthetic units on an ephemeral runner. Before a deployment gate, check that the
nightly job is inactive; if it is running, wait for its bounded run to finish.

## Schedule installation

Application release deployment does not replace host unit configuration. After
the exact application release is deployed and verified, the separately authorized
schedule installation uses `scripts/deployment/duplicate_schedule.py` from that
reviewed immutable revision. Feed its exact bytes to the existing bounded root
channel as a standalone script. Do not execute a release package module as root.

Pass `--release-sha <exact-active-sha>` for preparation, then add `--install` to
apply. Preparation validates the target, active release and app, rejects existing
different units, and runs `systemd-analyze verify`. Installation creates only
`asterproof-duplicate-report.service` and `.timer`, reloads systemd and enables the
timer. It does not start duplicate analysis, restart the app or change the existing
catalogue timer, deployment authority, IAM, credentials or network configuration.
Before enabling it, a one-time bounded process under the same app account runs
`--retain-current`, verifying and renewing the old cache chunks/manifest so its
previous three-hour TTL does not leave a gap before the first nightly run. This
does not query statement sources, recompute analysis or change generated-at time.
The script returns SHA-256 hashes of both installed unit definitions. Record
these hashes, next activation time and the active release in private release
evidence. Reconcile any interrupted operation by reading those definitions and
unit states before deciding whether another invocation is covered.

## Request/SQL timing

Production enables the existing `RequestTimingMiddleware` by default;
`DJANGO_REQUEST_TIMING_LOG=False` remains an opt-out. Static/media/health requests
are excluded. Dynamic responses include a generated `X-Request-ID` and aggregate
`Server-Timing` metrics. Existing Server-Timing values are preserved.

The existing console journal receives one line per request with request ID,
resolved route name, method/status, request duration, SQL execution count/time
and streaming flag. No user identity, raw path, query string, SQL text, parameters
or exception detail is recorded. Caller-provided request IDs are not trusted.

SQL collection uses temporary thread-local Django execute wrappers across all
configured aliases, with constant-size counters. It does not enable DEBUG or
retain query lists. Failed executions count and wrappers are removed on errors.
Time covers synchronous request handling and template rendering; SQL time covers
execute/executemany calls. Connection setup, commits and Python result processing
are not separately attributed. Streaming bodies run later and are excluded.
Browser first-byte time also includes network/proxy/worker waiting, so compare it
with the application timing rather than interpreting their difference as CPU.

This release has no schema migrations or changes to canonical problem identities,
completion records or progress calculations. Verify live catalogue/progress
timings and journal correlation after activation, then verify the next nightly
run at its scheduled time.
