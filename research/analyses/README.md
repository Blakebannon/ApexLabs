# Analysis definitions

This directory holds two deliberately separate contracts.

`apex-labs.analysis-definition/v1` documents remain **descriptive-observational
only**: inventories, availability and provenance counts, robust value summaries,
and per-lap event yield. No computation there tests a hypothesis, produces an
interval, or assigns confidence. `apex-labs analyze` binds one to a verified
normalized dataset and emits an `apex-labs.analysis-run/v1` artifact reproducible
with `apex-labs verify-analysis`. See
[docs/analysis-runs.md](../../docs/analysis-runs.md).

`apex-labs.inferential-analysis-definition/v1` documents are preregistered
inferential analyses over one comparable evidence set. They declare the question,
hypothesis and null, confirmatory or exploratory classification, the frozen
protocol, the evidence-set binding, the comparisons and their fixed family, the
practical thresholds, the uncertainty method and seed, the sufficiency and
stopping rule, the replication policy, the interpretation ceiling, and the
falsification tests. `apex-labs infer run` binds one to a built evidence set and
emits an `apex-labs.inferential-analysis-run/v1` artifact reproducible with
`apex-labs infer verify`. See
[docs/inferential-analysis.md](../../docs/inferential-analysis.md).

Neither contract can be used as the other. A descriptive definition is refused by
the inferential validator, and the descriptive validator still refuses any
inferential classification. A descriptive summary is not inferential evidence, an
inferential result is not a finding, and a finding is not validated.
