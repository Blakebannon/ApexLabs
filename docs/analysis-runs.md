# Descriptive analysis runs

`apex-labs analyze` executes a declared `apex-labs.analysis-definition/v1`
against one verified normalized dataset and emits a single
`apex-labs.analysis-run/v1` artifact. It is the only implemented analysis
surface, and it is descriptive only: record inventory, per-concept
availability and provenance counts, robust numeric summaries
(count/min/max/mean/median/quartiles/median-absolute-deviation), and per-lap
event yield. No hypothesis test, interval, confidence, or model exists in this
milestone; those require a preregistered protocol and a dedicated reviewed
method, per [architecture](architecture.md) and
[scientific method](scientific-method.md).

```powershell
apex-labs analyze research/analyses/synthetic-demo-descriptive.json `
  --dataset .apex-labs/demo-normalized `
  --run-id synthetic-demo-descriptive-run-001 `
  --created-at 2026-08-20T00:00:00Z `
  --metric research/metrics/demo-record-count.json `
  --output .apex-labs/demo-analysis
apex-labs verify-analysis .apex-labs/demo-analysis --dataset .apex-labs/demo-normalized
apex-labs validate analysis-definition research/analyses/synthetic-demo-descriptive.json
apex-labs validate analysis-run .apex-labs/demo-analysis/analysis-run.json
```

## Guarantees

- The dataset is fully re-verified before any computation: manifest contract,
  records hash, dataset fingerprint basis, per-record validation, integrity
  summary, and record counts. Analysis of tampered or inconsistent normalized
  output is refused.
- Real (non-synthetic) datasets require a clean committed Labs code identity;
  synthetic mechanics may run uncommitted.
- The run artifact binds the complete embedded definition and its canonical
  hash, the dataset reference (id, fingerprint, manifest and records hashes,
  synthetic flag), each bound metric definition's content hash, the Labs code
  identity, and a self-hash (`run_sha256`) over the whole artifact.
- Given identical definition, dataset bytes, and code, output bytes are
  identical across directories and platforms. Statistics are computed over
  sorted values, so enumeration order cannot change a result. Unavailable
  values are excluded and counted as attrition; they are never coerced to zero
  or repaired.
- Output is staged and atomically promoted under an exclusive lock, and the
  command refuses to overwrite an existing output directory.

`verify-analysis` re-verifies the dataset, recomputes every result from the
embedded definition, and compares against the artifact. It also reports
whether the current code identity matches the recording identity.

## What a run is not

A run artifact is computed descriptive evidence that a finding's validation
artifact may cite. It is not a finding, a status, a scope, a review, or
scientific truth. Reproducibility proves that the same code produces the same
summary from the same bytes; it does not prove the summary answers any
preregistered question, that samples are sufficient or comparable, or that any
racing interpretation is warranted.
