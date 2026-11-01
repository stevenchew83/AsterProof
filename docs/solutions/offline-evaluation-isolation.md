# Offline evaluation isolation

The evaluation workspace must not contact a model provider. Application feature
flags and a fake provider boundary are necessary, but are not proof of network
isolation. `scripts/offline_evaluation.py` adds a disposable local Docker execution
boundary. A successful run establishes engineering test evidence only; its report
origin is `deterministic_fixture`, never verified model evidence.

## Prepare dependencies before isolation

Prepare a reviewed dependency image using the repository's pinned
`requirements/local.txt`, Python 3.12.4 and `/usr/local/bin/python`. Install packages
during preparation, before running the isolated gate. The supplied
`scripts/offline/Dockerfile` uses the Python version tag during preparation;
execution is bound to its resulting immutable local image ID. Record that image
ID, the requirements digest and complete installed package list in the build
evidence. Do not copy application source, `.env` files,
credentials, private data, host sockets or a developer home directory into it.
Set this image label:

```dockerfile
LABEL io.asterproof.offline-dependencies="true"
```

The supplied Dockerfile already sets this label, installs only the requirements,
and writes the installed package list to `/dependency-freeze.txt`. Its entire
build context must be the `requirements/` directory, not the checkout. Prepare a
local image with:

```sh
offline_build_dir="$(mktemp -d)"
docker build --file scripts/offline/Dockerfile --iidfile "$offline_build_dir/image.iid" requirements
offline_image_id="$(cat "$offline_build_dir/image.iid")"
docker pull postgres:17.9-bookworm@sha256:47f917f7409eacd22fc5dfb1dee634e1b55cf0c01d1a7eb701be2227a03e0641
python -m scripts.offline_evaluation --image "$offline_image_id"
python -m scripts.offline_evaluation --image "$offline_image_id" --postgres
```

The runner accepts only an already-local immutable image ID of the form
`sha256:<64 lowercase hexadecimal digits>`. It does not accept a mutable tag or
pull an image. `docker image inspect` must resolve that exact ID and label. Image
environment variables are restricted to Python/base-image runtime metadata; an
image with embedded provider or application environment configuration is rejected.
This check does not inspect image layers for secrets: the image producer must
review the dependency build. Never use a production application image.

The PostgreSQL mode additionally needs this exact image already prepared locally:

```text
postgres:17.9-bookworm@sha256:47f917f7409eacd22fc5dfb1dee634e1b55cf0c01d1a7eb701be2227a03e0641
```

Dependency preparation can use package registries; executing either gate below
does not install packages, pull images or call provider APIs. Dependency preparation
does not authorize paid services or new infrastructure.

## Execute the gates

Run from the repository after preparing and recording the dependency image ID:

```sh
python -m scripts.offline_evaluation --image sha256:REPLACE_WITH_PREPARED_IMAGE_ID
python -m scripts.offline_evaluation --image sha256:REPLACE_WITH_PREPARED_IMAGE_ID --postgres
```

The placeholder must be replaced with the actual 64-character image digest.
Additional or narrower explicit modules can be selected with repeated
`--test-target inspinia/solutions/test_example.py` arguments. Only solution tests
and scripts test modules are accepted. A specific test can be selected with
`module.py::test_name`. PostgreSQL mode always includes the reservation,
worker-claim, duplicate-hint, freeze/withdrawal, aggregate-delivery and
capability-revocation race tests; skipped or missing required races fail that gate.

The default suite covers the existing offline scorer and review protections. CI
explicitly selects the contract, assistance, execution, governance, scoring, workspace,
concurrency and security suites as well as harness tests. Future evaluation
suites must be supplied explicitly or added to those selected targets; the
default is not a claim that every future workspace subsystem has been exercised.
Runtime CI changes build the dependency-only image, run both isolation modes,
and retain the image ID, installed package list and test logs as engineering
artifacts. This does not dispatch a deployment or a provider experiment.

The runner copies Git-visible regular source files into a temporary read-only
snapshot. It excludes environment files, private configuration directories,
database files, private-key file types and symlinks. It mounts that snapshot only,
not the checkout, `.git`, developer home, credentials, Docker socket or host media.
Locally modified and untracked nonignored source is included so the gate tests the
current implementation. Review source before treating any test artifact as
reproducible release evidence, and bind release evidence to its immutable revision.

The test container has a read-only root, no capabilities, no privilege escalation,
bounded memory/CPU/processes, an unprivileged UID and disposable scratch/tmp mounts.
It receives a fixed environment, with AI disabled and execution mode `offline`.
The host Docker process receives no inherited remote endpoint or credential
environment; its config directory is empty and temporary. Only the existing
default local daemon is used. No context switch or remote Docker endpoint is
supported.

The default mode uses `--network=none` and a SQLite database inside `/scratch`.
PostgreSQL mode creates a new `--internal` network and verifies Docker reports it
as internal, attaches only the disposable database and runner, publishes no host
ports, and uses PostgreSQL storage in a disposable tmpfs. Trust authentication is
confined to that disposable local network and is never a production setting.

Before importing Django or collecting tests, the bootstrap:

- Validates both offline gate variables and disabled provider settings.
- Rejects inherited database or provider/cloud credential environment variables.
- Requires explicit scratch media and configures only the disposable database.
- Probes direct outbound TCP connections to two public addresses; success fails
  the gate before tests start. These are TCP probes, not HTTP or provider requests.
- Checks PostgreSQL reports version 17.9 before concurrency evidence is accepted.
- Marks collected tests `offline_evaluation`; direct plugin loading cannot stand
  in for the bootstrap.

Docker's network boundary is the isolation control; failed TCP probes alone are
not sufficient evidence of isolation. No model output is obtained in either mode.
The test process cleans up only generated container/network names from its own
invocation. Cleanup failures identify those names and fail rather than silently
claiming a clean run.

## Verification limits

`scripts/tests/test_offline_evaluation.py` tests safe command construction,
environment rejection, source filtering, failed probes, required concurrency
results and cleanup using controlled subprocess doubles. It can run without
Docker or Django initialization:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -o addopts= scripts/tests/test_offline_evaluation.py
```

Those tests do not prove actual container isolation. If the Docker CLI, local
daemon, prepared image or pinned PostgreSQL image is unavailable, record the
container gate as **not verified**. Do not substitute an unrestricted local run
or mark engineering readiness passed. The development environment used to create
this harness had no Docker CLI, so actual container acceptance remains outstanding.

Successful isolation testing neither activates AI review nor authorizes spending,
provider experiments, deployment or use of real learner data.

## Separate exact schema rehearsal

`scripts/deployment/evaluation_schema.py` binds the exact bytes of migration
`0010_offline_evaluation_contract` and its 19 `CreateModel` operations. This is a
local/CI rehearsal contract, not a production migration allowance. The completed
document-editor allowance and production dispatch guards remain separate.

Run its local smoke with:

```sh
python -m scripts.deployment.evaluation_schema --sqlite --output /private/tmp/evaluation-schema-smoke.json
```

This command creates its own fresh temporary SQLite database, migrates through
the document schema, seeds synthetic legacy solutions, blocks, a saved document
revision/current pointer, public shares, view counters, collections and a legacy
trigger, then applies only the frozen evaluation migration. It checks preservation
of old rows, columns, constraints, foreign keys, triggers and sequences; exactly
one migration recorder row is appended and all new evidence tables remain empty.
The synthetic policy remains disabled and unfunded. The temporary database is
removed after the bounded JSON report is written.

SQLite reports `local_sqlite_smoke_passed` and explicitly records
`authoritative_postgresql_rehearsal=false`. Authoritative schema rehearsal is a
separate CI execution against the exact fresh PostgreSQL 17.9 rehearsal target.
It refuses another target, version, nonempty database or changed migration bytes.
The rehearsal does not claim an old-code compatibility smoke was run and does not
establish engineering readiness or deployment authorization by itself. The CI
selector routes the new migration to this new module without widening the old
document-editor allowance.
