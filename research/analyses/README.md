# Analysis definitions

Reviewed `apex-labs.analysis-definition/v1` documents. A definition declares
*what* deterministic descriptive computations run; it never binds a dataset.
`apex-labs analyze` binds a definition to one verified normalized dataset and
emits an `apex-labs.analysis-run/v1` artifact whose results are reproducible
with `apex-labs verify-analysis`.

Only `descriptive_observational` analyses exist in v1: inventories,
availability/provenance counts, robust value summaries, and per-lap event
yield. No computation here tests a hypothesis, produces an interval, or
assigns confidence. An analysis run is computed descriptive evidence for a
finding's validation artifact; it is never itself a finding, a status, or a
scientific claim. See [docs/analysis-runs.md](../../docs/analysis-runs.md).
