# Public solution sharing

The editor's **Share** action opens owner-only settings for the last saved solution, with a detailed review available separately. **Create public link** makes that reviewed content readable without an account. It does not publish the workspace solution or record a completion.

The editor toolbar's **Share** button opens an anchored dialog on desktop and a bottom sheet below 768px. It loads current owner-only sharing settings, supports Copy link, WhatsApp, Update shared version, and Stop sharing without navigating away or submitting the editor form. Unsaved edits are flagged and excluded. Native dialog focus trapping, Escape, outside-click dismissal, focus return, and a full-page fallback are provided. The dialog is outside the editor form, so sharing does not mark work saved or change progress.

The existing owner route negotiates JSON through `Accept: application/json`; its HTML review remains available without JavaScript. Mutations retain CSRF, owner/approval checks, source timestamp, review digest, and share-revision validation. The client sends only these identifiers and the explicit action. It rereads state after a mutation or ambiguous failure, never automatically retries a mutation, and ignores stale asynchronous reads after closing or reopening the dialog.

`SolutionPublicShare` stores one active snapshot per solution, with an unpredictable UUID link, a separate revision UUID, and a prebuilt 1200 × 630 JPEG. The snapshot includes the problem statement, MOHS, mapped areas/concepts, ordered solution blocks, summary, and saved display options. Author credit uses the profile name or a generic learner label; it never falls back to the account email. Diagrams are captured during snapshot creation as SVG images; anonymous readers do not invoke the diagram or PDF compilers.

Ordinary editor saves never update this row. **Update shared version** replaces the snapshot and image explicitly, preserving the page link and changing the image revision URL. Source timestamps, a digest of the reviewed content, and share revisions reject stale tabs, including a profile or catalogue change after the review was opened. **Stop sharing** clears the snapshot/image and disables both endpoints; creating a link again rotates its token. Deleting a solution cascades to its share.

Public page and image responses check active state on every request and use `private, no-store` plus `noindex, nofollow, noarchive`. Links are not placed in a public catalogue. These are public bearer links, not confidential invitations: anyone receiving one may forward it. Previously sent previews, downloaded content, and screenshots cannot be recalled.

The public page includes server-rendered Open Graph and large-image card metadata with absolute URLs based on `PUBLIC_SITE_ORIGIN`. Its image is generated when the author shares or updates, never per crawler request. **Share on WhatsApp** opens the user's composer; it does not send a message automatically. WhatsApp ultimately controls card presentation and may suppress previews through the sender's privacy settings.

Migration `solutions.0005_solutionpublicshare` adds one table. Existing drafts and published workspace solutions receive no share rows and remain under their existing access controls. The new public middleware exception is limited to `/solutions/shared/`.

Relevant verification:

```sh
uv run pytest inspinia/solutions/test_public_sharing.py
uv run pytest inspinia/solutions inspinia/website/tests inspinia/users/tests config/tests
uv run python manage.py check --settings=config.settings.test
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
npm run build
```

After deployment, verify the live link and JPEG anonymously, then paste a newly created link into WhatsApp's composer and inspect its preview without sending. Verify revocation on both endpoints. Cached cards already in messages may survive revocation.
