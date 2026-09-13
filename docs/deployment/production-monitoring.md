# Production release monitoring

Blocking verification covers activation and one short stabilization interval. Longer observations are assigned to a named operator and do not keep the GitHub workflow open.

## Baseline and blocking checks

Before activation, record current SHA/digest, schema fingerprint, process start/PID evidence, public and loopback health, representative static hashes, disk free space, database readiness, scheduler state/path, and a bounded recent error count. Degraded or unknown baseline is No-Go.

Immediately after activation and again after the workflow's stabilization interval, require:

- systemd service active with a fresh stable main PID/start time;
- every process in the service cgroup executing/working under `releases/<target-sha>` with no residual worker;
- current symlink, server registry, and cache-busted HTTPS `/healthz/` agreeing on SHA/digest;
- expected schema fingerprint and fresh `recorded_at` value;
- representative hashed CSS and JS returning 200 with the expected content type and artifact-matching SHA-256;
- bounded trusted database readiness and scheduler path resolving through `current`;
- no material increase from the pre-release application/proxy error baseline.

Do not use a cached browser page as release evidence. `/healthz/` is intentionally non-secret and `no-store`; it is not a database/Redis diagnostic endpoint.

## Assigned observations

Record one owner and due time for each checkpoint:

| Time | Required observations |
|---|---|
| +1 hour | SHA/digest drift, HTTP error count, latency, static failures, disk trend, database connectivity/fingerprint, scheduler path/run |
| +4 hours | Repeat +1h evidence and compare to the recorded pre-release baseline |
| +24 hours | Repeat all evidence, confirm next scheduled catalog task, close or escalate the release record |

Use existing monitoring and narrowly scoped manual/read-only evidence. This work does not create a monitoring platform. Store links or sanitized summaries in the release/incident record; do not paste raw environment values, credentials, query parameters, customer data, or unrestricted logs.

## Escalation

- SHA/digest/static disagreement: stop deployment and rollback automation; follow [rollback and recovery](rollback-and-recovery.md).
- Health or service failure with an eligible immediate previous release: use the protected rollback workflow.
- Database fingerprint drift, migration ambiguity, or a data/non-compatible release: set/retain `recovery_required`; do not code-switch automatically.
- Host marker, host key, gateway/helper/unit hash, or scheduler path drift: treat as an authority incident and follow [disaster recovery](disaster-recovery.md).
- Capacity below the target contract minimum: stop receipt/pruning and resolve capacity through a separately reviewed host operation.
