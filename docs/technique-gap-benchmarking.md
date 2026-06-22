# Technique Gap Benchmarking

The technique gap dashboard supports a manual ChatGPT import/export loop for curriculum benchmark metadata. The app does not call an AI model. ChatGPT only classifies stable topic metadata; AsterProof computes live ranks from current completion data.

## Workflow

1. Open `Dashboard -> Techniques -> Gaps`.
2. Filter the gap table to the rows you want to benchmark.
3. Click `Benchmark gaps`.
4. Copy the generated prompt into ChatGPT.
5. Paste ChatGPT's JSON response back into AsterProof.
6. Click `Preview`.
7. Review invalid rows and changed rows.
8. Click `Apply valid rows`.

The importer accepts schema version `technique-gap-benchmark-v1` only. Future versions are rejected until the importer is explicitly updated.

## What ChatGPT Populates

ChatGPT returns static benchmark metadata:

- syllabus core
- contest frequency
- transfer value
- prerequisite value
- difficulty components
- typical MOHS band
- parent family
- training type
- target level
- rationale, pitfalls, and recommended sequence

## What AsterProof Computes

AsterProof computes dynamic scores from current database rows:

- gap pressure
- priority score
- efficiency score
- deep-work score
- priority rank
- final training action

Ranks are computed after filtering and before DataTables pagination, so rank values cover the full matching result set rather than only the current page.

## Safety

Imports are previewed before apply. Apply writes valid rows transactionally and stores old/new snapshots in the import batch. Admins can restore previous values from an applied batch; newly created benchmarks from that batch are deleted during restore.

Limits:

- pasted response max: 2 MB
- rows per import max: 300
- rationale, pitfalls, recommended sequence max: 500 characters each
