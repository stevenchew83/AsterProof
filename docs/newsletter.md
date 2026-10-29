# Newsletter operations

Open **Administration → Newsletter** in the main backend, or visit
`/manage/newsletter/` after signing in. Access requires the existing app Admin
role or superuser status, including in DEBUG. Django staff status alone is
insufficient. Subscriber addresses and history are private and never cached.

## Subscribers

Use the Subscribers tab to search by email and filter awaiting confirmation,
subscribed and unsubscribed records. Each record shows consent dates, consent
version and related deliveries. **Unsubscribe this address** revokes consent and
invalidates outstanding confirmation links through the existing public opt-out
service. Administrators cannot manually add or confirm subscriptions. A new
signup must complete the public email confirmation flow.

## Draft, preview, test and send

1. Create a draft with a subject, short inbox preview and Markdown message.
   The existing email shell supplies the logo, typography and footer. Markdown
   is sanitized; scripts, external images and arbitrary CSS are stripped.
   Email clients do not run the website's MathJax, so use readable text for
   formulas or link to the full lecture.
2. Save to refresh the desktop/mobile preview. The preview is admin-only and
   sandboxed with a restrictive content security policy. Drafts use version
   checks to prevent one editor overwriting another editor's changes.
3. **Save & send test** saves the current draft and sends only to the signed-in
   administrator's address. Test messages are labelled and do not enroll or
   unsubscribe that address. Check the destination inbox; SMTP acceptance alone
   does not establish inbox delivery. Editing the message requires a new test.
4. **Review & send** shows the current confirmed audience and exact saved version.
   The latest test for this version must have succeeded, and explicit
   confirmation is required.
   Starting saves an audience snapshot and locks the message against editing.
   Copy a started campaign to a new draft to make changes.
5. Keep the sending page open. It sends one recipient per request with a short
   interval, and displays progress. **Pause** stops further dispatch; an email
   already in progress may finish. Closing the page stops further browser-driven
   requests. Open the campaign and use **Continue sending** to resume queued
   recipients. Without JavaScript, use **Send next recipient** on the campaign.

No background worker, recurring job or infrastructure change is required.
Sending is deliberately an interactive, resumable operation. There are no
scheduled campaigns or automatic lecture notifications.

## Consent, limits and delivery history

- Only confirmed subscribers with a recorded confirmation time enter a campaign.
  Consent is rechecked immediately before SMTP. Unsubscribed/deleted addresses
  and addresses that reconfirm after the audience snapshot are skipped. New
  subscribers do not join an already-started campaign.
- Each message has one recipient, a stable delivery Message-ID, and that
  subscriber's signed preference link in HTML, plain text and List-Unsubscribe.
  The preference page retains the CSRF-protected POST opt-out flow. It does not
  advertise RFC 8058 one-click POST support.
- Confirmation requests, campaign attempts and tests share
  `DJANGO_NEWSLETTER_DAILY_EMAIL_LIMIT` (default 100 per 24-hour counter window).
  Campaigns are also limited to 20 attempts per minute globally and tests to
  three per administrator per minute. Cache unavailability never bypasses limits.
  Reaching the allowance pauses a campaign; resume later. No counters are reset
  by the workspace. Account email is outside this newsletter budget.
- History records queued, in-progress, accepted, failed, skipped and needs-review
  outcomes. **Accepted** records the email server's acknowledgement. This feature
  has no provider delivery/bounce webhooks, open tracking or inbox guarantees.
  History retains each attempt's subject and draft version, even after a draft
  is edited. Started campaign content is immutable through the workspace.
- Delivery claims commit before contacting SMTP. Campaign row locks and partial
  unique constraints permit one in-progress attempt per campaign and one campaign
  delivery per address. No automatic request retry or recipient retry is used.
- A known SMTP rejection is Failed; an interrupted or uncertain SMTP handoff is
  Needs review. Either stops further sending until an administrator continues.
  Queued recipients can resume; attempted recipients are never silently replayed.
- If a process ends after claiming an attempt, the In progress record blocks
  further dispatch. After five minutes, **Mark interrupted delivery for review**
  marks it uncertain and pauses the campaign. Check receipt before deciding on
  any separately composed follow-up. It never requeues that recipient.
- SMTP runs outside database transactions and uses the configured email timeout.
  Dispatch code records generic outcomes without logging SMTP diagnostic text,
  message bodies, tokens or recipient addresses.

The additive `website.0002_newsletter_campaigns` migration creates campaign and
delivery tables and their indexes/constraints. It does not rewrite existing
subscriber or account data. Production activation must use the reviewed migration
release procedure; the earlier authority for `website.0001_initial` does not
implicitly permit this migration. This feature does not modify deployment
authority, secrets, provider configuration or existing production data.

## Local verification

Use `DJANGO_READ_DOT_ENV_FILE=False` with `config.settings.test` for the focused
website tests. Tests use in-memory mail. A browser preview must use a separate
local database and file/in-memory email backend. Implementing or previewing the
feature does not authorize sending a real campaign or deploying it.
