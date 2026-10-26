# Number Theory concept implementation

The finalized catalog is packaged in
`inspinia/pages/data/number_theory_concepts_v1.json`. It contains 236 Number Theory
identities, 32 shared identities, and 852 exact role/caption associations. Its
source hash identifies the reviewed reference catalog. The application reads this
packaged data without depending on files under `artifacts/`.

## Application behavior

The Benchmark Map provides the Number Theory concept catalog, shared tools, and
the original role profiles. The concept catalog includes definitions without a
benchmark, displayed as unrated. Search includes the reviewed exact aliases.
Role, target, and detailed assessment values remain available in the profile
details and the original-profile view.

Number Theory runtime IDs use `nt-`, such as `nt-crt` and `nt-additive-functions`.
This preserves Algebra IDs and prevents an additive arithmetic function from
being confused with Cauchy's additive equation. The 17 retired Number Theory
variant IDs redirect to their surviving identities in benchmark deep links and
practice filters. The 32 shared definitions retain their separate catalog scope.

Aliases are exact, case-insensitive full-caption matches within a role and
subject. Punctuation and domain restrictions are retained. Curriculum captions
and reviewed canonical names are supported as legacy technique captions;
original benchmark captions are associated only with their original roles.
Compound labels and alternative meanings from the nine review decisions do not
become single-identity aliases. In particular, `number of prime factors` does
not select either omega function automatically. The finite-logarithm association
is limited to the reviewed Number Theory source context.

Combined learning gaps count the union of statement IDs across accepted role
members. Completion retains the existing statement-before-linked-problem
precedence. Subject selection includes secondary subject associations. Exact
practice filters select the same role/name union in the same subject population.
Role-specific gap tabs and benchmark import/export keys remain available.

## Assessment preservation

The implementation performs no benchmark or benchmark-alias database writes,
creates no replacement assessments, and changes no stored tags or problem UUIDs.
Existing and newly imported role facts resolve through the same runtime registry.
The existing import preview and write classification paths remain identical.

All 307 captured Number Theory profiles retain their IDs, roles, and rating
fields. The 266 profiles attached to accepted identities remain independently
visible; the other 41 broad, compound, or underspecified profiles remain in the
original-profile view. Four source profiles are also used by existing Algebra
definitions; subject-specific catalog views reference the same database rows.
The unfiltered map preserves their established Algebra ownership.

A concept receives an existing reference assessment only when its captured
rating vectors agree. Concepts with differing profiles keep each original
assessment and have no combined rating or automatic priority. If live vectors
diverge or a selected reference is absent, the combined score fails closed;
another role is never silently substituted. Existing Algebra reference decisions
are preserved.

The progress-cache version incorporates both packaged catalog hashes, so a
catalog or alias change invalidates the affected cached projections.

## Verification

Regression coverage lives in `inspinia/pages/test_number_theory_concepts.py`.
It covers catalog sizes, exact aliases and exclusions, cross-subject ownership,
retired IDs, all-profile preservation, rating drift, missing references,
statement unions, secondary associations, authentication, and import parity.
It also verifies that catalog and profile GETs leave every database value
unchanged and that the existing Algebra catalog retains its references.

Use the normal test settings with local SQLite and dotenv loading disabled:

```sh
DJANGO_READ_DOT_ENV_FILE=false uv run --no-sync pytest \
  inspinia/pages/test_number_theory_concepts.py \
  inspinia/pages/test_technique_concepts.py \
  inspinia/pages/test_algebra_vocabulary.py -q
```

This is a local application implementation. It does not deploy the application
or apply production data changes.
