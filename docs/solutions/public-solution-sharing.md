# Public solution sharing

The editor's **Share** action opens owner-only settings for the last saved solution, with a detailed review available separately. **Create public link** makes that reviewed content readable without an account. It does not publish the workspace solution or record a completion.

The editor toolbar's **Share** button opens an anchored dialog on desktop and a bottom sheet below 768px. It loads current owner-only sharing settings, supports Copy link, WhatsApp, Update shared version, and Stop sharing without navigating away or submitting the editor form. Unsaved edits are flagged and excluded. Native dialog focus trapping, Escape, outside-click dismissal, focus return, and a full-page fallback are provided. The dialog is outside the editor form, so sharing does not mark work saved or change progress.

The existing owner route negotiates JSON through `Accept: application/json`; its HTML review remains available without JavaScript. Mutations retain CSRF, owner/approval checks, source timestamp, review digest, and share-revision validation. The client sends only these identifiers and the explicit action. It rereads state after a mutation or ambiguous failure, never automatically retries a mutation, and ignores stale asynchronous reads after closing or reopening the dialog.

`SolutionPublicShare` stores one active snapshot per solution, with an unpredictable UUID link, a separate revision UUID, and a prebuilt 1200 × 630 JPEG. The preview uses the existing website logo, centered on the site's dark background with room for thumbnail cropping. The snapshot includes the problem statement, MOHS, mapped areas/concepts, ordered solution blocks, summary, and saved display options. Author credit uses the profile name or a generic learner label; it never falls back to the account email. Diagrams are captured during snapshot creation as SVG images; anonymous readers do not invoke the diagram or PDF compilers.

Ordinary editor saves never update this row. **Update shared version** replaces the snapshot explicitly, preserving the page link and changing the image revision URL. The logo stays the same. Source timestamps, a digest of the reviewed content, and share revisions reject stale tabs, including a profile or catalogue change after the review was opened. **Stop sharing** clears the snapshot/image and disables both endpoints; creating a link again rotates its token. Deleting a solution cascades to its share.

Public page and image responses check active state on every request and use `private, no-store` plus `noindex, nofollow, noarchive`. Links are not placed in a public catalogue. These are public bearer links, not confidential invitations: anyone receiving one may forward it. Previously sent previews, downloaded content, and screenshots cannot be recalled.

The public page includes server-rendered Open Graph and large-image card metadata with absolute URLs based on `PUBLIC_SITE_ORIGIN`. The solution title and description remain specific to the shared snapshot. Active image endpoints serve the bundled logo JPEG, including for existing links that stored an older thumbnail; no proof update, data backfill, or per-request image generation is needed. Revoked links and obsolete revisions still return 404. **Share on WhatsApp** opens the user's composer; it does not send a message automatically. WhatsApp ultimately controls card presentation and may suppress previews through the sender's privacy settings.

Migration `solutions.0005_solutionpublicshare` adds one table. Existing drafts and published workspace solutions receive no share rows and remain under their existing access controls. The new public middleware exception is limited to `/solutions/shared/`.

## Admin oversight and readership

**Management → Administration → Public solutions** (`solutions:admin_public_shares`) is a read-only dashboard for app admins and superusers. Staff, trainers, moderators, and ordinary users cannot access it, including in DEBUG. Search the shared title/problem or account owner, filter active/stopped status and shared topic, and order by the last sharing change or views. Pagination keeps the filters. Active titles open the actual public snapshot; details show the account email, first-share date, source save time, and link. The listing extracts only snapshot metadata, without loading proof bodies, preview images, or private draft fields. Stopped rows show that content was removed, with no working public link or retained proof.

The same page reports active links, active sharing authors, stopped links, reader views over the last 30 local calendar days, a daily breakdown, first shares, and active shares by snapshot topic. All metrics follow the current filters. Topic filters only apply to active snapshots because stopped snapshots are cleared. A first share counts the solution once; updating or creating a replacement link does not create a new first-share event. These records are current sharing state, not a complete publication audit trail.

Migration `solutions.0006_solution_share_daily_views` adds a daily aggregate counter table with a unique `(share, day)` constraint. No existing proofs or account rows are changed and no historical readership is invented. Successful public-page GET requests increment an atomic counter. HEAD/image requests, prefetches, known bots/link-preview crawlers, authenticated owners, and admins are excluded. Other signed-in readers count without retaining their identity. The counter stores only share, date, and total; no visitor IDs, IP addresses, user agents, referrers, or tracking cookies. Bot filtering is best effort, repeat opens count, and traffic before deployment is unavailable. Analytics database errors do not break the proof page or log request details.

Production schema rehearsal and the separate bounded authority installation follow [the analytics schema release guide](../deployment/solution-analytics-schema.md).

Daily counts remain when a link is updated, stopped, or replaced, so views cover all shared versions of the same solution. Deleting the solution cascades to the sharing record and its counters. The dashboard has no moderation writes. A future report/review queue or admin takedown action should have separate authorization rules and an audit trail.

Relevant verification:

```sh
uv run pytest inspinia/solutions/test_public_sharing.py
uv run pytest inspinia/solutions/test_share_analytics.py
uv run pytest inspinia/solutions inspinia/website/tests inspinia/users/tests config/tests
uv run python manage.py check --settings=config.settings.test
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
npm run build
```

After deployment, verify the live link and JPEG anonymously, then paste a newly created link into WhatsApp's composer and inspect its preview without sending. Verify revocation on both endpoints. Cached cards already in messages may survive revocation.
