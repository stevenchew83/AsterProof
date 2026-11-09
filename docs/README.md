# AsterProof documentation

Use the [repository README](../README.md) to set up a checkout. Start with the
guide for your task below. A feature guide describes behavior in the source
unless it cites a dated release or activation record. Deployment contracts
describe release requirements. Check dated records for what was actually
verified, deployed, or enabled.

## Development and agent instructions

- [Repository setup and checks](../README.md#python-environment) covers local
  development. Use the [dashboard style guide](inspinia-dashboard-style.md) for
  dashboard and admin UI.
- Follow the [root AGENTS.md](../AGENTS.md) and the scoped AGENTS files along the
  path you are editing. This index is navigation. The existing AGENTS hierarchy
  defines contributor instructions.

## Production deployment and recovery

- Start with the [production release runbook](deployment/production-release.md).
  Use the [monitoring checklist](deployment/production-monitoring.md) for
  preflight, postflight, and stabilization.
- For target setup, use [production bootstrap](deployment/production-bootstrap.md)
  and [GitHub administration](deployment/github-administration.md). For an
  interrupted release, use [rollback and recovery](deployment/rollback-and-recovery.md).
  [Disaster recovery](deployment/disaster-recovery.md) covers break glass.
- Use the subsystem's exact schema or maintenance contract where applicable.
  The [catalogue backup and maintenance procedure](deployment/catalogue-backup-and-maintenance.md)
  covers encrypted backup and isolated restore.

## Catalogue and concept assignments

- Start with [catalogue and derived progress](catalogue-and-progress-implementation.md).
  See [Area and Coverage](problem-library-concept-coverage.md) for what the
  problem library displays and exports.
- Use the [alias policy](concept-alias-policy.md) to interpret names and the
  [assignment contract](problem-concept-assignments.md) for evidence, provenance,
  and approval. The [bulk review workflow](bulk-concept-review-workflow.md)
  covers exports and revalidation.
- Use the [catalogue maintenance contract](deployment/catalogue-backup-and-maintenance.md)
  for recovery requirements. The
  [27 October readiness record](deployment/catalogue-release-readiness-2026-10-27.md)
  captures the earlier release checkpoint.

## Mathematics Training 2.0

- Start at `/learning/` with an approved account when the module is enabled.
  Explore the catalogue and published pathways. Draft notes, reviewed content,
  and curated pathways have separate workflows and permissions. The legacy
  points roadmap is at `/training/legacy/`.
- Use the [shared learning release and recovery guide](deployment/learning-pilot.md)
  for the reader floor, contribution and publication gates, and the dated
  production release. The [public library guide](public-website.md#publishing-the-library)
  covers what readers can see.
- See the [adopted content architecture](brainstorms/2026-11-01-training-lecture-library-requirements.md),
  [local implementation evidence](validation/training-2-implementation.md),
  and [PostgreSQL rehearsal record](validation/training-2-postgresql17-verification.md)
  for design and verification history.

## Solution authoring and sharing

- Start with the [continuous editor guide](solutions/continuous-solution-editor.md)
  for saved LaTeX, immutable revisions, and legacy blocks. See the
  [first solution guide](solutions/getting-started.md) for starter problems
  and the [sharing guide](solutions/public-solution-sharing.md) for public snapshots.
- Use the [editor schema contract](deployment/solution-document-editor.md) and
  [multiple-solutions contract](deployment/multiple-solutions-release.md) for
  reader and migration constraints.
- The [member solution forum](solution-forum.md) and its
  [release contract](deployment/solution-forum-release.md) cover member
  publication, discussion, assessments, and verification. For PDF troubleshooting,
  see the [pasted-image export incident](solutions/integration-issues/solution-pdf-export-missing-body-images-2026-03-29.md).

## Community Proof Library

- Start with the [Phase 1 guide](community-proof-library.md) for visibility,
  private attempts, and reviewed publication. The
  [adopted roadmap](plans/2026-11-01-community-proof-library-requirements.md)
  covers later phases.
- Use the [Phase 1 release contract](deployment/community-proof-library-release.md)
  for the migration and recovery procedure. See
  [similarity-index maintenance](community-problems.md#library-similarity-index)
  for the refresh command and index behavior.

## Rankings administration

- Start with the [Rankings Admin Guide](rankings-admin-guide.md) for imports,
  ranking recalculation, and student profiles. Use
  [achievement paste imports](ranking-achievement-paste.md) to record supplied
  evidence and [ranking analysis](ranking-analysis.md) for reviewed corrections.
- See the [ranking analysis release](deployment/ranking-analysis-release.md)
  and [student profile release](deployment/ranking-profile-release.md) for
  schema boundaries and verification.

## AI solution review

- Start with the [admin and author review guide](solutions/admin-ai-review.md)
  for permissions, queueing, publication, takedowns, and worker setup. Its
  runtime section links the frozen schema allowance and worker configuration.
- [Study Help](study-help.md) has separate qualification and activation gates.
  The [offline evaluation architecture](solutions/ai-solution-checking-architecture.md)
  and its [release record](deployment/offline-evaluation-release.md) cover the
  independent evaluation workspace.

## Public website and learning library

- Start with the [public website guide](public-website.md) for routes, the
  library, assets, and publishing. Use [newsletter operations](newsletter.md)
  for subscriber consent, campaigns, and worker behavior.
- The [newsletter schema contract](deployment/newsletter-schema.md) separates
  installing the schema from enabling campaign sending.

## Historical decisions and evidence

- Read [design discussions](brainstorms/) and [implementation plans](plans/)
  for original decisions and staged work. The [older designs and plans](superpowers/)
  preserve earlier decisions and implementation details.
- See [performance investigations](performance/),
  [solution incidents](solutions/integration-issues/), and
  [validation records](validation/) for dated measurements and test evidence.
  Use the primary guide and the matching release record before applying an
  old procedure.
