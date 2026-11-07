# Admin AI solution review

Under **Administration → AI review settings**, save an OpenAI project API key,
select the models available on solution entries, set the thinking level and
request limits, and edit the review prompt. The key is encrypted at rest and is
never returned to the browser. Saving settings does not contact OpenAI.
An empty key field keeps the current key; **Remove the saved key** removes it.
Replacing or removing the key invalidates queued work for that key.

On a submitted or member-published solution, use **AI review** to choose models
and generate drafts. Every request includes the problem label, active linked
statement and complete saved proof text. All three are required. Both author
and admin requests also send images uploaded to that solution and referenced in
the saved proof. Each review supports up to four static PNG, JPEG, GIF, or WebP
images, each at most 3 MiB and 16 megapixels. The worker sends PNGs scaled to
fit within 1536 by 1536 pixels. A missing or invalid embedded image stops the
review before it reaches OpenAI. External image references and diagram code
remain part of the text. Requests queued before the image disclosure remain
text-only.

Each selected model uses one paid request. The rolling 24-hour request limit
counts queued attempts, including failures, and the token cap covers reasoning
and output. Use a dedicated OpenAI project to track spend.
**Administration → AI review queue** shows waiting and running model requests.
On the solution page, a spinner indicates a request is waiting for the worker.

The fixed rubric requires an integer score from 0 to 7 and feedback supporting
that score. The worker reads OpenAI's stream and the review panel polls for
status and partial feedback. Admin-generated drafts are private to admins until
they choose a completed draft to publish. Only one review can be published per
saved version, and partial feedback is never published as the result.
Only the solver and admins can read a published review; an email links to the
signed-in entry. Publishing does not change trainer assessments, verification,
or completion records. If a proof or statement changes, regenerate before
publishing. Already-published feedback remains marked as an earlier version.

When `SELF_SOLUTION_REVIEW_ENABLED=True`, approved accounts can also request a
review of their own submitted or member-published proof. Authors choose one
configured model per request and can have one active request across their account.
Each account can generate two successful reviews per problem across revisions
and 50 successful reviews overall. Failed attempts leave those allowances
available. All requests share the existing rolling 24-hour site cap.
The author can see partial feedback while their request runs. Once the worker
validates the final score and feedback, it shares the review privately and queues
the same email link automatically. Earlier completed drafts are not republished.

The author request flow requires `solutions.0015_self_solution_review_usage`.
It adds one usage table and retains the account and site quotas when a solution
is deleted. Apply the migration through the protected release procedure before
turning on author requests. The author switch defaults to off and requires the
existing `ADMIN_SOLUTION_REVIEW_ENABLED` setting and worker.

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
   Each job has a five-minute deadline. Uncertain outcomes are recorded and
   require reconciliation before another attempt. The site and author review
   quotas still apply when requests are queued.
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
