# Problem-library Area and Coverage

The authenticated problem library displays a single line per problem, with Area and Coverage replacing the original Topic tags column. Coverage lists supported canonical concepts; it is not a percentage or a completion score.

`statement_concept_coverage.py` resolves the effective stored source tags through the subject catalogs and alias policy. It batches source reads and does not rebuild progress facts or rewrite persistent tags. Statement tags take precedence over linked-problem tags. Suppressed tags and inactive statements do not produce canonical coverage. Same-source context is required for overloaded labels.

Area shows one value plus an additional-value count. Coverage shows two concepts plus a count. A keyboard-accessible dialog reveals every area and concept, unresolved captions grouped with their roles, and the original source captions. Separate identities with identical names are qualified by subject until a reviewed merge occurs.

Library search resolves canonical names and areas before the latest-100 limit. The loaded-row filter includes concepts hidden behind the additional-value count. Existing source-caption search remains available. Copy loaded rows includes complete Area, Coverage, mapping status, review labels and original tags for every loaded row, independently of the client-side filter; values preserve one TSV line per problem.

The existing Inspinia shell remains. Long labels truncate, metadata stays inline, and small screens scroll the table horizontally. Regression coverage is in `test_statement_concept_coverage.py` and the statement-list tests.
