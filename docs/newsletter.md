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
5. In background mode, the sending page reports progress while the worker sends.
   You can close it and return later. Pause stops further claims; a message
   already in progress may finish. Continue sending resumes only queued recipients.
   When background mode is not configured, the existing browser-driven sending
   flow remains available and its page must stay open.
6. **Schedule for later** freezes the tested draft until the selected Malaysia
   date/time. The worker checks due campaigns on its next minute tick and
   captures the then-confirmed, eligible audience. Cancellation returns the
   content to a draft and requires another test. Due campaigns with no eligible
   recipients complete without sending.

## Lecture automation

Open **Automation** and choose a saved draft whose current version has an accepted
admin test. Its subject, preview and text become the daily digest introduction;
new lecture links are appended automatically. Explicitly confirm automatic
emails and choose a local send time (default 09:00 Asia/Kuala_Lumpur).

Enabling records the current public lectures as an excluded baseline. Only new
publicly visible lectures observed afterward enter the queue, once per lecture.
A lecture, its concept and its area must all be published. The worker checks
visibility again before sending. Each digest contains up to 10 links within the
message length limit; overflow waits for the next digest. Without eligible
subscribers, pending lectures wait for a later digest.

Changing the approved draft/version or importing a failure for its test disables
lecture automation and pauses active lecture campaigns until the introduction
is tested and approved again. Disabling also excludes the pending backlog and
pauses active lecture campaigns. An attempt already in progress may finish.
Re-enabling does not resume old paused campaigns or announce material published
while disabled. Notification history links each included lecture to its campaign.

## Gmail bounce import

Gmail remains the sender for newsletter and account mail. No provider credentials,
mailbox access or external services are added. **Accepted** retains its SMTP
meaning; the separate delivery result starts as **Delivery unconfirmed**.

In **Bounce import**, upload the original Gmail delivery-failure notice as an
EML file (maximum 1 MB), review the matched recipient/campaign/action/status code,
confirm its source, then apply. Gmail documents [More → Download message](https://support.google.com/mail/answer/9261412).
Only structured [RFC 3464 delivery-status notifications](https://www.rfc-editor.org/rfc/rfc3464.html)
with original AsterProof Message-ID and a matching recipient are accepted.
Ordinary, ambiguous, unmatched and success messages are rejected. The signed
review expires after 15 minutes. No email body, attachment or diagnostic text is
retained or displayed; history stores the source digest, normalized result,
status code, operator and import time. Re-importing the same report is idempotent.

Failure and delay reports are shown separately from SMTP status. Delays and
policy/authentication failures do not establish an invalid address. Only specific
permanent address failures place a sending hold, preserving consent and history.
Existing queued deliveries recheck holds before sending. An administrator may
clear a hold from the subscriber detail after confirming and recording a reason;
that action never confirms or re-enrols a subscription. A later independent
address failure may create another hold. No application-level email retry is
added, and successful inbox delivery remains unknown with Gmail SMTP.

## Background worker and activation

`process_newsletters --max-messages=20 --seconds=50` processes one bounded batch
and can send real email. It requires `DJANGO_NEWSLETTER_BACKGROUND_ENABLED=True`.
A database lease excludes a second worker; claim records commit before SMTP.
Abandoned claims become Needs review after five minutes, pause their campaign,
and are never replayed. Minute/daily allowance pauses defer only queued work;
manual/review pauses require an administrator to continue. Worker heartbeat and
failure state are visible in Automation. The sending page only polls GET status
in background mode and never dispatches recipients itself.

The default is off until the schema and separately reviewed service are ready.
Render proposed units without installing them:

```sh
python -m scripts.deployment.newsletter_schedule --contract deployment/production-target.json
```

The once-minute timer runs a bounded oneshot as the existing app user against
`current` and the external environment. Requisite/After/PartOf bind it to the app:
it cannot start a stopped app during maintenance, and stopping/restarting the app
also stops/restarts an active worker. A service kill can leave an uncertain claim;
the lease/claim safeguards retain it for review. Validate units with Linux
`systemd-analyze verify` before installation and test stop/drain semantics before
production activation. This repository command only renders units; it cannot
install, enable, start or edit host configuration.

Production merge/deployment, the exact `website.0003_newsletter_automation`
runner allowance, worker-unit installation and enabling background mode require
their respective authorization. The previous completed website.0002 grant does
not cover another migration or service. Existing app/deploy identities, Gmail
credentials, subscriber consent and old history remain intact. No current
production environment, runner or service is changed by implementing this work.

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
  In background mode, the worker checks a minute limit after one minute and a
  daily-limit/unavailable allowance after one hour. Manual pauses remain paused.
  No counters are reset
  by the workspace. Account email is outside this newsletter budget.
- History records queued, in-progress, accepted, failed, skipped and needs-review
  outcomes. **Accepted** records the email server's acknowledgement. This feature
  has reviewed Gmail bounce import, with no provider webhooks, open tracking or inbox guarantees.
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

The original `website.0002_newsletter_campaigns` migration creates campaign and
delivery tables. `website.0003_newsletter_automation` adds scheduling fields,
the unconfirmed delivery-result default and queue/lecture/bounce/hold tables.
It preserves existing consent, campaign content and attempt status. Old SMTP
acceptance is never backfilled as successful delivery. Production activation
uses the reviewed migration release procedure with a new exact allowance.

## Local verification

Use `DJANGO_READ_DOT_ENV_FILE=False` with `config.settings.test` for the focused
website tests. Tests use in-memory mail. A browser preview must use a separate
local database and file/in-memory email backend. Implementing or previewing the
feature does not authorize sending a real campaign or deploying it.
