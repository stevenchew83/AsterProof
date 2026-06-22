# Technique Gap Benchmarking

The technique gap dashboard supports a manual ChatGPT import/export loop for curriculum benchmark metadata. The app does not call an AI model. ChatGPT only classifies stable topic metadata; AsterProof computes live ranks from current completion data.

## Workflow

1. Open `Dashboard -> Techniques -> Gaps`.
2. Click `Benchmark gaps`.
3. Review the Benchmark Coverage Dashboard counts across all actionable gap kinds.
4. Click `Create next batch`, or use the Batch Export Wizard to choose scope, kind, size, and sort.
5. Copy `Step 1: Copy this prompt to ChatGPT`.
6. Paste ChatGPT's benchmark response into `Step 2: Paste ChatGPT benchmark JSON`.
7. Click `Preview`.
8. Review new, changed, invalid, and missing rows.
9. Click `Apply validated rows`.
10. Repeat with the next batch until the missing count is cleared.

The importer accepts schema version `technique-gap-benchmark-v1` only. Future versions are rejected until the importer is explicitly updated.

Imports validate against the frozen `TechniqueBenchmarkExportBatch` row keys, not the current filter state. This keeps a response valid even if an admin changes filters after copying the prompt.

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

The paste parser accepts strict JSON, fenced JSON, JSONL, markdown tables, and ChatGPT prose containing JSON. If an admin accidentally pastes the source export payload instead of ChatGPT's benchmark response, the importer shows a specific warning and refuses to preview it as benchmark metadata.

Limits:

- pasted response max: 2 MB
- rows per import max: 250
- rationale, pitfalls, recommended sequence max: 500 characters each
