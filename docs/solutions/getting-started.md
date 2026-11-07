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

The checklist has two steps: selecting a problem and saving at least one block.
Saving completes getting started. Public sharing is a separate optional action
and does not affect the completion count. Once saved, the panel names the selected
solution, condenses completed steps, and offers review/sharing alongside continued
editing. Its heading and instructions reflect unfinished, saved and shared work.
The editor rejects empty or whitespace-only proof blocks. Empty records created by image uploads do
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
