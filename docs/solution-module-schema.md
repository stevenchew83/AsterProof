# Solution Module Schema Plan

This document proposes the first database shape for a user-submitted solution module.

## Goals

- Let any authenticated user submit one full solution for a problem.
- Store a solution as an ordered list of blocks.
- Support LaTeX-heavy authoring, while still accepting imported plain-text or PDF-derived material.
- Reuse the existing archive anchor: solutions belong to `ProblemSolveRecord`.
- Keep the schema stable enough that we can add submission pages, rendering pages, moderation, and imports without a rewrite.

## Recommended app boundary

Create a new app such as `inspinia/solutions/` instead of growing `inspinia/pages/` further.

Reason:

- `pages` already owns archive, statements, analytics, imports, and explorer views.
- solutions will likely need their own forms, rendering helpers, moderation, attachments, and tests.
- a separate app keeps table ownership and future migrations cleaner.

## Core design choice

Do **not** turn every transition word into a first-class schema enum.

Words like `Hence`, `Now`, `Therefore`, `When`, and `Such that` are good **display titles**, but they are weak **data categories**.

Instead:

- keep a small structural block taxonomy
- give every block an optional free-form `title`
- render the title exactly as the author entered it

This gives you both:

- stable querying and filtering
- flexible writing style

## Proposed core tables

### 1. `ProblemSolution`

One user-owned solution for one problem.

Recommended fields:

- `id`
- `problem = ForeignKey(ProblemSolveRecord, on_delete=CASCADE, related_name="solutions")`
- `author = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name="problem_solutions")`
- `title = CharField(max_length=160, blank=True)`
- `status = CharField(...)`
  Suggested choices: `draft`, `submitted`, `published`, `archived`
- `summary = TextField(blank=True)`
  Short preview text for listings. Optional, but useful.
- `created_at`
- `updated_at`
- `submitted_at = DateTimeField(null=True, blank=True)`
- `published_at = DateTimeField(null=True, blank=True)`

Recommended constraints and indexes:

- unique constraint on `(problem, author)` for v1
- index on `(problem, status)`
- index on `(author, status)`

Why anchor to `ProblemSolveRecord`:

- it is already the canonical archive problem object
- it already links to user completion
- statement records already optionally point back to it

### 2. `SolutionBlockType`

Controlled vocabulary for the structural role of a block.

Recommended fields:

- `id`
- `slug = SlugField(unique=True)`
- `label = CharField(max_length=64)`
- `description = TextField(blank=True)`
- `sort_order = PositiveIntegerField(default=0)`
- `is_system = BooleanField(default=True)`
- `allows_children = BooleanField(default=False)`
- `created_at`
- `updated_at`

Why use a table instead of hard-coded choices:

- you can add or rename block types without a migration
- admins can extend the vocabulary later
- seeded rows still give us predictable defaults

### 3. `ProblemSolutionBlock`

One ordered block inside a solution.

Recommended fields:

- `id`
- `solution = ForeignKey(ProblemSolution, on_delete=CASCADE, related_name="blocks")`
- `parent_block = ForeignKey("self", null=True, blank=True, on_delete=CASCADE, related_name="children")`
- `block_type = ForeignKey(SolutionBlockType, null=True, blank=True, on_delete=SET_NULL)`
- `position = PositiveIntegerField()`
- `title = CharField(max_length=160, blank=True)`
  Display heading such as `Claim 1`, `Hence`, or `When n is even`
- `body_format = CharField(...)`
  Suggested choices: `latex`, `plain_text`
- `body_source = TextField()`
- `created_at`
- `updated_at`

Recommended constraints and indexes:

- unique constraint on `(solution, position)`
- index on `(solution, parent_block, position)`

Why `parent_block` now:

- it gives us Notion-like nesting later
- it supports structures like `Claim -> Proof -> Case 1 -> Case 2`
- if we do not need nesting in the first UI, we can still keep every block at the root

Why `body_format` now:

- pasted notepad text and imported PDF/OCR text are not always clean LaTeX
- we still want to render math for LaTeX-first content
- format-aware rendering is safer than pretending every block is valid LaTeX

### 4. `SolutionSourceArtifact`

Optional provenance table for imported raw material.

Recommended fields:

- `id`
- `solution = ForeignKey(ProblemSolution, on_delete=CASCADE, related_name="source_artifacts")`
- `uploaded_by = ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL)`
- `artifact_type = CharField(...)`
  Suggested choices: `pdf`, `text`, `tex`, `image`, `url`
- `file = FileField(blank=True)`
- `original_name = CharField(max_length=255, blank=True)`
- `mime_type = CharField(max_length=128, blank=True)`
- `source_text = TextField(blank=True)`
  Raw pasted text or extracted OCR text
- `created_at`

Why keep this separate:

- the author-facing solution should stay clean and block-based
- imported material may be messy, partial, or unreviewed
- we may want to re-parse a PDF or pasted text later without rewriting the authored blocks

## Suggested seeded block types

Start small.

Recommended seeded rows:

- `plain` -> Plain
- `section` -> Section
- `idea` -> Idea
- `claim` -> Claim
- `proof` -> Proof
- `case` -> Case
- `subcase` -> Subcase
- `part` -> Part
- `observation` -> Observation
- `computation` -> Computation
- `conclusion` -> Conclusion
- `remark` -> Remark

Use `title` for the exact visible label.

Examples:

- `block_type=claim`, `title="Claim 1"`
- `block_type=observation`, `title="Observe that"`
- `block_type=conclusion`, `title="Therefore"`
- `block_type=case`, `title="When n is even"`

This is better than creating block types named `therefore`, `hence`, `when`, `now`, and `then`.

## Rendering plan

For v1:

- store only the raw source text in `body_source`
- do not store rendered HTML in the database
- render solution blocks with the same frontend math stack already used for statements

Practical rule:

- `body_format=latex`: render as math-aware rich text
- `body_format=plain_text`: escape text, preserve line breaks, and still allow later import cleanup

## Deferred tables for v2

These are useful, but not required before the first submission pages.

### `ProblemSolutionRevision`

Immutable snapshot of a solution on save or publish.

Useful for:

- edit history
- moderation
- rollback
- future diff views

### `ProblemSolutionRevisionBlock`

Snapshot blocks belonging to a revision.

### `ProblemSolutionComment`

Inline or whole-solution feedback from reviewers.

### `ProblemSolutionReaction` or `ProblemSolutionVote`

Useful only after public browsing exists.

## Recommended v1 implementation order

1. Add the four core tables above.
2. Seed `SolutionBlockType`.
3. Build a simple author page:
   One solution per `(user, problem)`, status `draft/published`.
4. Reuse the existing math rendering stack for block previews.
5. Add attachment upload only after the manual block editor is stable.

## Important product decisions to confirm before coding

1. Should v1 enforce exactly one solution per user per problem?
   Recommendation: yes.

2. Should drafts be private by default?
   Recommendation: yes.

3. Should all published solutions be visible immediately, or require admin/trainer review?
   Recommendation: start with `draft -> published` only unless moderation is already needed.

4. Do we want PDF/text import in v1, or only manual block entry first?
   Recommendation: manual block entry first, attachments second.
