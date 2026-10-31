# Public solution sharing

The editor's **Share** action opens owner-only settings for the last saved solution, with a detailed review available separately. **Create public link** makes that reviewed content readable without an account. It does not publish the workspace solution or record a completion.

The editor toolbar's **Share** button opens an anchored dialog on desktop and a bottom sheet below 768px. It loads current owner-only sharing settings, supports Copy link, WhatsApp, Update shared version, and Stop sharing without navigating away or submitting the editor form. Unsaved edits are flagged and excluded. Native dialog focus trapping, Escape, outside-click dismissal, focus return, and a full-page fallback are provided. The dialog is outside the editor form, so sharing does not mark work saved or change progress.

The existing owner route negotiates JSON through `Accept: application/json`; its HTML review remains available without JavaScript. Mutations retain CSRF, owner/approval checks, source timestamp, review digest, and share-revision validation. The client sends only these identifiers and the explicit action. It rereads state after a mutation or ambiguous failure, never automatically retries a mutation, and ignores stale asynchronous reads after closing or reopening the dialog.

`SolutionPublicShare` stores one active snapshot per solution, with an unpredictable UUID link, a separate revision UUID, and a prebuilt 1200 × 630 JPEG. The preview uses the existing website logo, centered on the site's dark background with room for thumbnail cropping. The snapshot includes the problem statement, MOHS, mapped areas/concepts, ordered solution blocks, summary, and saved display options. Author credit uses the profile name or a generic learner label; it never falls back to the account email. Diagrams are captured during snapshot creation as SVG images; anonymous readers do not invoke the diagram or PDF compilers.

Ordinary editor saves never update this row. **Update shared version** replaces the snapshot explicitly, preserving the page link and changing the image revision URL. The logo stays the same. Source timestamps, a digest of the reviewed content, and share revisions reject stale tabs, including a profile or catalogue change after the review was opened. **Stop sharing** clears the snapshot/image and disables both endpoints; creating a link again rotates its token. Deleting a solution cascades to its share.

Public page and image responses check active state on every request and use `private, no-store` plus `noindex, nofollow, noarchive`. Links are not placed in a public catalogue. These are public bearer links, not confidential invitations: anyone receiving one may forward it. Previously sent previews, downloaded content, and screenshots cannot be recalled.

The public page includes server-rendered Open Graph and large-image card metadata with absolute URLs based on `PUBLIC_SITE_ORIGIN`. The solution title and description remain specific to the shared snapshot. Active image endpoints serve the bundled logo JPEG, including for existing links that stored an older thumbnail; no proof update, data backfill, or per-request image generation is needed. Revoked links and obsolete revisions still return 404. **Share on WhatsApp** opens the user's composer; it does not send a message automatically. WhatsApp ultimately controls card presentation and may suppress previews through the sender's privacy settings.

Migration `solutions.0005_solutionpublicshare` adds one table. Existing drafts and published workspace solutions receive no share rows and remain under their existing access controls. The new public middleware exception is limited to `/solutions/shared/`.

## Solution collections

On **My solutions**, select solutions in reading order and choose **Share selected solutions**. Number badges and an ordered tray show the click sequence, including while filtering the list. The collection builder supports a title, an optional introduction, adding/removing solutions, and accessible up/down reordering. The editor's sharing options also offer **Add to a collection**; a selection can be appended to an existing owner-only collection editor without duplicating entries.

**Review before sharing** previews every included copy. Active public snapshots are reused, even when the private editor has newer saves. Solutions without an active public copy are previewed from their saved content and become shared only when the owner confirms the collection. The one-hour signed review binds the owner, collection revision, title, introduction, selection order, shared revisions and snapshot digests. Publishing locks the selected solution rows in primary-key order, using the same lock as individual sharing actions. A changed or invalid selection fails before any sharing writes. Collections allow 1–20 solutions and at most 5 MiB of reviewed snapshot data.

The guest URL under `/solutions/shared/collections/` renders all available public snapshots on one page, with a sticky desktop contents menu, a collapsible phone menu, and native anchors. Each entry has an independent UUID anchor that survives reordering. **Copy solution link** copies a deep link into the collection. Proofs, statements, bylines and display options continue to come from the existing shared snapshot; account emails, private editor changes and completion data are excluded. Responses retain the existing no-store/noindex policy and anonymous math safety configuration. Aggregate analytics continue to count individual solution-page opens; collection pages do not invent individual page opens.

Updating a solution's public copy updates collections containing that copy. Stopping its sharing immediately excludes it from every collection. An entry is also bound to the solution's sharing token: stopping and later sharing the solution again does not reactivate old collection entries. An owner can explicitly review and update a collection to include it again. Removing an entry does not revoke its individual solution link. Stopping a collection revokes only the collection URL; sharing the collection again rotates that URL. Deleting a solution cascades its collection entries.

Migration `solutions.0007_solutioncollection_solutioncollectionentry` adds only the collection and ordered-entry tables, with owner/share foreign keys and unique public tokens/anchors. It does not share or rewrite existing solutions. Its frozen allowance, PostgreSQL rehearsal and release procedure are documented in [the collection schema release guide](../deployment/solution-collections-schema.md); the existing sharing/analytics allowances do not admit it.

## Admin-curated collections

Administrators can mix different authors' existing public copies. Open **Management → Administration → Public solutions**, select active rows in reading order, and choose **Create curated collection** or **Add to existing collection**. The tray supports up/down reordering, removal, and explicit clearing. Selection follows filters and pagination; transient tab storage retains only ordered share IDs and sharing-generation references, scoped to the current user and picker flow. If storage is unavailable, page links retain the selection and the screen explains the browser Back limitation.

**Management → Administration → Curated collections** lists the shared workspace, including active/stopped status and available/total entries. Every current app administrator or superuser can manage it. Curated collections are site-owned and survive the creator's account deletion or demotion. Personal collections retain their owner-only controls, including for administrators.

The builder accepts a title and introduction, supports an inline public-copy picker, and requires a full review before publication. Browsing the picker preserves the unsaved draft without publishing anything. Only active public copies are eligible: curation never reads a private draft to construct a proof, updates a source share, or reactivates one. The signed one-hour review binds the acting administrator, collection revision, metadata, order, source generations, revisions, and snapshot digests. Publication locks the collection and source solution rows, reloads share state after locking, and rejects changes atomically. Another administrator's conflicting edit requires loading the latest collection and reviewing again.

Builder history/reload restoration stores only ordered references, separately from the inventory basket. It rehydrates public labels through an admin-only, read-only metadata endpoint; titles, introductions, proofs, and account details are never put in tab storage. A fresh inventory handoff starts from its newly submitted selection. Browsing and history restoration cannot submit a publication action.

Guest contents, proofs, and credits use the authors' saved public snapshots. Hidden attribution remains hidden. Different authors' proofs of one problem can appear together with distinct anchors. Reordering retains anchors; replacing an unavailable sharing generation requires explicit removal/reselection and creates a new anchor. Author revocation hides affected entries immediately, and stopping/re-sharing a source never revives an old generation automatically. Deleting a source removes only its entries. An active collection with no available sources has a neutral empty state. Collection stopping/re-sharing affects only its own link.

Migration `solutions.0008_solutioncollection_kind_and_nullable_owner` adds a persistent personal/curated kind, permits site-owned collections with no owner, and enforces the corresponding ownership constraint. Existing collections remain personal with their owners, ordering, anchors, and public tokens preserved. See [the curated collection schema guide](../deployment/curated-collections-schema.md) for the separate exact allowance, preservation proof, and older-code recovery limitations.

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
