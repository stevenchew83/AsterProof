# First solution guide

New accounts land on **My solutions** after password sign-in, email-code sign-in,
or signup. A staged Solution Writer draft takes priority and resumes through the
existing problem picker, including after account approval. Approval and MFA gates
are unchanged.

Migration `users.0009_user_solution_guide_status` gives existing accounts the
`not_enrolled` state, preserving their **My activity** destination. Newly created
accounts default to `active`. A persistent database default of `not_enrolled`
keeps account creation compatible with the previous application revision.
Production schema controls follow [the frozen release procedure](../deployment/onboarding-schema.md).
**Skip for now** changes only the current user's
guide preference to `dismissed`; **Show getting-started guide** reopens it. Both
actions use authenticated, CSRF-protected POST requests and persist across sessions
and devices. Accounts enrolled in the guide continue landing on My solutions even
after dismissing it. Existing users can opt in by showing the guide there.

The guide offers **Try a starter problem**, **I already have a proof**, and
**See a worked example**. The starter prefers the active, linked IMO 1959 P1
statement and otherwise picks an active, linked statement, ranking by lowest
available MOHS rating. If no linked statement is available, the proof picker
and worked example remain available.

Opening a problem alone does not save a draft. For learners with the guide
active, the first proof is saved privately before it can be published. The
editor opens the statement and offers **Save private draft** as the primary
action. Saving non-blank writing completes the guide and makes publication and
sharing available as separate actions. The guide prioritizes the latest private
draft with saved writing over published and shared work. Empty upload records do
not count as saved writing. A pending Writer handoff still takes priority.

The editor provides a contextual prompt before saving and after saving or sharing.
Public links are created only through the existing sharing review, with its saved
snapshot and explicit consent. Guide actions never publish a solution, create a
link, mark a problem solved, or send a message. Stopping sharing is reflected when
the checklist is next loaded. Copying a link is available on the sharing page and
is not treated as proof of delivery.
