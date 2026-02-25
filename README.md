# AsterProof

AsterProof is a Django-based web application that uses the Inspinia UI templates and a Node/Gulp asset pipeline for frontend static assets.

## Project structure

- `manage.py`: Django management entrypoint (`config.settings.local` by default).
- `config/`: Django project configuration (`urls.py`, `wsgi.py`, and environment-specific settings).
- `inspinia/`: Main Django app package (users/pages apps, templates, static files).
- `requirements/`: Python dependency sets for base, local, and production environments.
- `locale/`: Translation sources and locale artifacts.
- `gulpfile.js`, `package.json`: Frontend build pipeline and scripts.

## Data model overview

The core schema is organized by domain app, with `catalog.Problem` as the main entity referenced across learning, contests, community, and moderation flows.

### Catalog (`inspinia/catalog/models.py`)

- `Contest`: source contest metadata (`short_code`, `contest_type`, `year`, visibility).
- `Tag`: reusable taxonomy with category (`topic`, `technique`, `theme`).
- `Problem`: canonical problem record with:
  - source fields (`contest`, `label`, `title`, `statement`);
  - editorial fields (`editorial_difficulty`, `editorial_quality`, `status`);
  - curation metadata (`topic`, `mohs`, `confidence`, `imo_slot_guess`, `topic_tags`, `rationale`, `pitfalls`);
  - deduplication (`canonical_problem` self-reference).
- `ProblemTag`: explicit through model for many-to-many `Problem` ↔ `Tag` links (unique per pair).
- `ProblemReference`: external links/resources per problem.
- `RelatedProblem`: typed problem-to-problem links (`similar`, `generalisation`, `uses_lemma`).

Key constraints:

- `Problem` is unique by `(contest, label)`.
- `ProblemTag` unique by `(problem, tag)`.
- `RelatedProblem` unique by `(source_problem, target_problem, relation_type)`.

### Progress and personal study state

- `progress` app:
  - `ProblemProgress`: per-user state (`unattempted/attempted/solved/revisiting`) with confidence and first solve timestamp.
  - `ProblemFavourite`, `ProblemDifficultyVote`, `ProblemQualityVote`: one record per `(user, problem)`.
- `notes` app:
  - `PrivateNote`: per-user per-problem note (unique `(user, problem)`).
- `organization` app:
  - `ProblemList` and ordered `ProblemListItem` for personal/public lists.
  - `ActivityEvent` for user event timeline with JSON metadata.

### Community and UGC

- `PublicSolution`: user-authored solution content attached to a problem.
- `SolutionVote`: unique vote per `(solution, user)`.
- `Comment`: threaded comments (self-parent), attachable to problem or solution.
- `CommentReaction`: unique per `(comment, user, emoji)`.
- `ContentReport`: lightweight report record for comments/solutions.
- `TrustedSuggestion`: trusted-user curation proposals (tag/duplicate/difficulty/quality).

### Contests and ratings

- `ContestEvent`: runnable contest instance (kind, visibility, schedule, rated flag).
- `ContestRegistration`: unique participation registration per `(user, contest)`.
- `ContestProblem`: ordered contest composition of catalog problems.
- `Submission`: contest submissions with marking status, score, grader info.
- `ScoreEntry`: per-contest final score/rank/delta (unique `(contest, user)`).
- `RatingSnapshot` and `RatingDelta`: rating history and contest deltas.

### Backoffice moderation, ingestion, and platform config

- Moderation:
  - `Report`, `ModerationLog`, `ContentRevision` using generic foreign keys for cross-model moderation targets.
- Ingestion:
  - `ProblemRequest` and `ProblemSubmission` queues with review status and reviewer decisions.
- Platform singleton configs:
  - `AbusePolicy`, `FeatureFlagConfig`, `PrivacyDefaultsConfig`, `BrandingConfig`, `RatingConfig`.
- Rating operations:
  - `RatingRun` and `RatingRunEntry` for auditable apply/rollback cycles.

### Feedback workflow

- `FeedbackItem`: user-submitted feature/bug/problem requests with workflow status.
- `FeedbackStatusEvent`: immutable status-transition history per feedback item.

## Prerequisites

- Python 3.12+
- Node.js + npm

## Local setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements/local.txt
   ```

3. Install Node dependencies:

   ```bash
   npm install
   ```

4. Run database migrations:

   ```bash
   python manage.py migrate
   ```

5. Start Django development server:

   ```bash
   python manage.py runserver
   ```

## Frontend workflow

- Start development asset build/watch:

  ```bash
  npm run dev
  ```

- Build production assets:

  ```bash
  npm run build
  ```

- Build RTL assets:

  ```bash
  npm run rtl
  npm run rtl-build
  ```

## Tests and code quality

- Run test suite:

  ```bash
  pytest
  ```

- Lint Python code:

  ```bash
  ruff check .
  ```

- Optional static checks configured in this repo:

  ```bash
  mypy inspinia
  djlint inspinia/templates --check
  ```

## Part B migration rollout

Part B introduces migration history for previously unmigrated apps. For environments that already have legacy tables, use `--fake-initial` so Django records initial migrations without recreating tables:

```bash
python manage.py migrate users --fake-initial
python manage.py migrate catalog --fake-initial
python manage.py migrate progress --fake-initial
python manage.py migrate notes --fake-initial
python manage.py migrate community --fake-initial
python manage.py migrate organization --fake-initial
python manage.py migrate feedback --fake-initial
python manage.py migrate contests --fake-initial
python manage.py migrate backoffice --fake-initial
```

Or run the helper command:

```bash
python manage.py migrate_part_b
```

## Internationalization

Translation workflow details are documented in `locale/README.md`.
