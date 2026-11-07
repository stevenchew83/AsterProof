# Admin AI solution review

Under **Administration → AI review settings**, save an OpenAI project API key,
select the models available on solution entries, set the thinking level and
request limits, and edit the review prompt. The key is encrypted at rest and is
never returned to the browser. Saving settings does not contact OpenAI.
An empty key field keeps the current key; **Remove the saved key** removes it.
Replacing or removing the key invalidates queued work for that key.

On a submitted or member-published solution, use **AI review** to choose models
and generate drafts. Every request includes the problem label, active linked
statement and complete saved proof text. All three are required. Uploaded images
are not sent. Each selected model uses one paid request. The rolling 24-hour
request limit counts queued attempts, including failures, and the token cap
covers reasoning and output. Use a dedicated OpenAI project to track spend.

The fixed rubric requires an integer score from 0 to 7 and feedback supporting
that score. Admins see feedback stream into the review panel as OpenAI writes it. Partial
feedback is private to admins and cannot be published. Admins can compare
completed drafts and publish one for each saved version.
Only the solver and admins can read a published review; an email links to the
signed-in entry. Publishing does not change trainer assessments, verification,
or completion records. If a proof or statement changes, regenerate before
publishing. Already-published feedback remains marked as an earlier version.

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

   Install the units through the approved host procedure after schema activation. The timer starts the worker
   once per minute after the previous invocation ends. Each invocation handles
   at most one OpenAI request or one email, with a five-minute deadline.
   Notifications get priority. An uncertain outcome is recorded and requires
   reconciliation before another attempt.
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
