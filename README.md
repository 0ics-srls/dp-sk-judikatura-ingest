# dp-sk-judikatura-ingest

Proc-protocol class (Python 3.12) of the `sk-judikatura` package: loads `<item>.plan.json` (written by `dp-sk-judikatura-convert`) into the dataset schema
`ds_sk_judikatura`, one transaction per item.

- `rozhodnutia` upserted on `(fonte, source_id)`; `ingested_at` moves only when something changed.
- `passages` from the segmenter/chunker (`[<court> <cislo>[ <ecli>]]` prefix); an embedding is kept while `text_contextual` is unchanged, set NULL otherwise.
- `skipped` and `coverage` upserted on their natural keys; a decision that is ingested later clears its `skipped` row.
- `dryRun` rolls every item back (the package Manifest does not pass the Source `dryRun` to this step: that flag is the embedding dry run).

Tests: `.venv/Scripts/python -m pytest -m "not integration" tests` (unit), `-m integration` (Testcontainers `pgvector/pgvector:pg17`, needs Docker).
`docker build -f Dockerfile.test .` is the ProcMon gate: 49 passed, 1 skipped (sibling schema comparison), integration tests collect but are deselected.
Image size 379 MB, build 17 s (warm cache). `tests/test_collectable.py` guards the phase 78/79 defect (module-level `parents[n]`).

`plan.schema.json` is a byte-identical copy of the one in `dp-sk-judikatura-convert` (a test compares them when both repos are next to each other).
