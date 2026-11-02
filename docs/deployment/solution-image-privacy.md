# Managed solution image privacy

The compatibility application release routes managed images through the
authenticated solution/editor readers or the active public-share snapshot reader.
Stored image paths, existing snapshots, share tokens, collections, and files are
preserved. PDF generation continues reading its already-authorized local files.

The application change alone does not protect a reverse proxy's static media alias.
The reviewed fragment is `deployment/solution-image-privacy.nginx.conf`. Installing
it and reloading the media-serving proxy requires separate action-specific
authorization; the application deployment cannot install this rule itself.

## Deployment order

1. Verify the target account, host, application, MEDIA_URL, persistent media alias,
   included proxy configuration, and exact image-aware compatibility release.
2. Deploy the compatibility application through the established protected release
   workflow. Validate owner image preview, member image access, existing public
   copies, and a mixed-author public collection using synthetic fixtures outside
   production. Retain this artifact as the minimum image-aware recovery baseline.
3. Under the separately authorized configuration procedure, insert the reviewed
   fragment into only the verified application's server block. Preserve all other
   media and static routes. If MEDIA_URL differs from `/media/`, prepare and review
   the corresponding exact fragment rather than applying this one blindly.
4. Validate the complete effective proxy configuration before its normal reload.
   Record the exact configuration diff, syntax-validation result, authorization,
   operation identity, and reload outcome. Reconcile an ambiguous outcome before
   another dispatch; do not automatically retry or reopen direct media access.
5. Verify raw managed image paths return 404, including encoded slash/dot path
   variants, while authenticated image routes and active author-shared copies
   remain readable. Public revocation and obsolete sharing revisions must deny
   image access. Confirm other application media and static assets are unchanged.

The `^~` location prevents regular-expression image handlers from overriding this
prefix. NGINX normalizes URI escapes and dot segments before location matching.
There must be no alternate hostname, storage URL, or proxy alias that serves the
same managed files outside these controls. Verify all effective serving routes
before claiming image privacy is live.

## Recovery and acceptance

Keep the deny rule during application recovery, and use only an image-aware
compatibility artifact. Do not move/delete images, rewrite public snapshots, or
reverse database migrations. A prior artifact that requires raw media paths is
not a safe recovery target after cutover. Changing the proxy rule again requires
its own explicit authorization.

Production acceptance is bounded and read-only: confirm release identity and
compiled assets, authorized page/image access, denied raw media access, preserved
public sharing, and immediate plus short stabilization logs. Create no production
proof, vote, comment, review, or sharing record merely to test privacy. No delayed
monitoring is scheduled.

Focused tests live in `inspinia/solutions/test_image_access.py`; regression coverage
also includes public sharing, personal/curated collections, the editor, document
preview, and public-preview JavaScript.
