# Admin AI solution review

This guide describes the review workflow in the current source. Check the active
release and feature settings before using it in production.

Under **Administration → AI review settings**, save an OpenAI project API key,
select the models available on solution entries, set the thinking level and
output token limit, and edit the review prompt. The key is encrypted at rest
and is never returned to the browser. Saving settings does not contact OpenAI.
An empty key field keeps the current key; **Remove the saved key** removes it.
Replacing or removing the key invalidates queued work for that key.

## Queue a review

The admin actions require an active app admin or superuser. The worker also
checks that the requester can still access the app and that their role, key,
and review target are current before sending a request.

- On a submitted or member-published solution, open **AI review** on the
  solution detail page to select one or more configured models and queue drafts.
- In **User Solution Records** (`/dashboard/user-solutions/`), the row's
  **AI review** action queues one request using the first enabled model in the
  app's model order. It is available for a reviewable saved proof with no review
  for its current version, when generation is enabled. The button submits
  immediately. The server checks the saved input and prevents duplicate queue
  entries for the same current target. The row polls for status.

Every request requires the problem label, active linked statement, and complete
saved proof text. Both author and admin requests also send images uploaded to
that solution and referenced in the proof. Each review supports up to four static
PNG, JPEG, GIF, or WebP images, each at most 3 MiB and 16 megapixels. The worker
sends PNGs scaled to fit within 1536 by 1536 pixels. A missing or invalid
embedded image stops the review before it reaches OpenAI. External image
references and diagram code remain part of the text. Requests queued before the
image disclosure remain text-only.

Queueing itself saves work for the worker. Each model dispatched to OpenAI is a
paid request, and the token cap covers reasoning and output. Use a dedicated
OpenAI project to track spend and queue requests only within authorized spending.

## Inspect and publish a review

**Administration → AI review queue** shows active jobs and up to 200 past
requests per history page, with date filters and local search. The solution
detail page shows partial feedback while the worker streams. The fixed rubric
requires an integer score from 0 to 7 and feedback supporting that score.
Admin drafts are private to admins. The inventory row shows status and score.
Open the solution detail page to read the draft feedback.

When the inventory row has a completed current draft and no review in progress
or published for that version, **Publish AI review** publishes the draft shown
by that row immediately. The solution detail page and queue also support
publication. Only one review can be published per saved version. A changed
proof or active statement makes the old result an earlier version. Generate
a review for the new version before publishing.

Publication makes the score and written feedback available to the solver and
admins through the signed-in reader. It queues a notification when eligible.
The email contains the score and a link to the signed-in entry. Publication
does not make a provider request or change trainer assessments, verification,
or completion records.

Use **Take down** in the queue to remove a published review from the solver's
view and keep it in admin history. The action records the admin and time and
cancels an email that is still queued. An email already sending or sent may
still reach the solver with the score. Its review link stops showing the
feedback while the review is taken down. An outdated publish or takedown action
must be refreshed after the publication changes. An admin can republish a
completed review if it still matches the current proof and statement. The queue
requires migration
`solutions.0016_admin_review_takedown`, which adds nullable take-down metadata.
The protected release admits only the frozen migration, its actor foreign key
and index, and the PostgreSQL 17.9 preservation proof. Install the reviewed
allowance using the [production bootstrap](../deployment/production-bootstrap.md)
before dispatching the protected schema release.

When `SELF_SOLUTION_REVIEW_ENABLED=True`, approved accounts can also request a
review of their own submitted or member-published proof. Authors choose one
configured model per request and can have one active request across their account.
Each account can generate two successful reviews per problem across revisions.
A successful author request uses one of the 50 account credits shared with
AI hints. Failed attempts leave those allowances available.
The author can see partial feedback while their request runs. Once the worker
validates the final score and feedback, it shares the review privately and queues
the same email link automatically. Earlier completed drafts are not republished.

The author request flow requires `solutions.0015_self_solution_review_usage`.
It adds one usage table and retains the account and per-problem allowances when
a solution is deleted. Apply the migration through the protected release
procedure before turning on author requests. The author switch defaults to off
and requires the existing `ADMIN_SOLUTION_REVIEW_ENABLED` setting and worker.

The frozen allowance checks the quota migration file, the prior migration tree,
and the PostgreSQL 17.9 catalog delta. The rehearsal proves that the existing
app can still read its reviews and settings and that the new table starts
empty. Install the reviewed allowance through the separately authorized
[bootstrap procedure](../deployment/production-bootstrap.md). The protected
release applies the migration with author requests disabled. Verify the live
schema and worker before enabling author requests.

## Runtime setup

1. Apply migration `solutions.0014_admin_solution_review` through the environment's
   normal migration process. It creates two tables and does not backfill records.
2. Provision a dedicated Fernet key in the protected runtime environment as
   `ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY`. Use `Fernet.generate_key()` from the
   existing `cryptography` dependency and store the result directly through the
   environment's secret provisioning process. Keep this key stable across web and
   worker processes. If it is lost, save a new OpenAI key after provisioning the
   new encryption key.
3. Render and validate the [worker unit](../../deployment/systemd/asterproof-admin-solution-reviews.service.in)
   and [timer](../../deployment/systemd/asterproof-admin-solution-reviews.timer.in)
   with the verified [production target](../../deployment/production-target.json).
   Substitute the application service, application user, managed `current`
   path, and protected environment file using the local renderer:

   ```bash
   python -m scripts.deployment.newsletter_schedule --admin-solution-reviews \
     --contract deployment/production-target.json
   ```

   Install the rendered units through the approved host procedure after the
   matching application release is active and the previous worker is idle.
   Check that the host has headroom for the worker's process pool and memory
   limit. The timer checks for new work every five seconds while the worker is
   idle. Once running, the worker refills up to five review slots in queue
   order as each job finishes. One separate slot sends notification emails.
   Each job has a five-minute deadline. On shutdown, the supervisor stops
   claiming new work and lets claimed reviews and notifications finish.
   Systemd gives the worker up to 330 seconds to exit before restarting it.
   Queued jobs remain available to the new worker. Uncertain outcomes are
   recorded and require reconciliation before another attempt. Author review
   allowances still apply when requests are queued.

   For the first rollout of graceful shutdown, pause the review timer and let
   the old worker exit before activating the updated code. Install and reload
   the updated worker unit through the approved host procedure before resuming
   the timer. Both the application code and the unit are required.
   Before using it for a maintenance deployment, also install the matching
   trusted deployment helper through the approved bootstrap procedure. Its
   ordered stop deadline allows the review worker to drain before the app stops.
4. Set `ADMIN_SOLUTION_REVIEW_ENABLED=True` to allow generation. Disabling this
   setting pauses OpenAI requests; previously published reviews and their email
   notifications still work. This setting is independent of student coaching,
   statement AI review, and offline evaluation.

The protected production release uses the exact two-table
`backward-compatible-schema` allowance in
[admin_solution_review_schema.py](../../scripts/deployment/admin_solution_review_schema.py).
CI must reproduce its catalog delta on PostgreSQL 17.9 and confirm the active
reader still works. Install the allowance separately through the reviewed
[bootstrap procedure](../deployment/production-bootstrap.md). Keep generation
disabled through schema activation. Start the scheduled worker, verify it is
idle with an empty queue, and then enable generation and enter the OpenAI key.

For acceptance on entry #56, first open the page as an administrator and check
the AI review panel, the linked statement, and the saved proof. Once a project
key and paid verification are in scope, select one model and confirm that a
private draft streams and finishes with a score out of 7. Publication would
notify the solver and requires a separate decision. Local tests use a mocked
OpenAI transport and Django's in-memory mail backend.
