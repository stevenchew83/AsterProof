# First solution guide

New accounts land on **My solutions** after password sign-in, email-code sign-in,
or signup. A staged Solution Writer draft takes priority and resumes through the
existing problem picker, including after account approval. Approval and MFA gates
are unchanged.

Migration `users.0009_user_solution_guide_status` gives existing accounts the
`not_enrolled` state, preserving their **My activity** destination. Newly created
accounts default to `active`. **Skip for now** changes only the current user's
guide preference to `dismissed`; **Show getting-started guide** reopens it. Both
actions use authenticated, CSRF-protected POST requests and persist across sessions
and devices. Accounts enrolled in the guide continue landing on My solutions even
after dismissing it. Existing users can opt in by showing the guide there.

The checklist derives progress from the current user's saved solutions: a selected
problem, at least one saved block, and an active public link. The editor rejects
empty or whitespace-only proof blocks. Empty records created by image uploads do
not count as saved proofs, and the list never loads proof bodies. The
next action prefers an already shared solution, then the latest solution containing
saved content, then an unfinished record. A pending Writer handoff remains the
primary action so existing writing is preserved.

The editor provides a contextual prompt before saving and after saving or sharing.
Public links are created only through the existing sharing review, with its saved
snapshot and explicit consent. Guide actions never publish a solution, create a
link, mark a problem solved, or send a message. Stopping sharing is reflected when
the checklist is next loaded. Copying a link is available on the sharing page and
is not treated as proof of delivery.
