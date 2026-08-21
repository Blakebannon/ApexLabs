# Research records

This directory holds reviewable research artifacts: segment definitions,
evidence-set definitions, metric definitions, descriptive and inferential
analysis definitions, synthetic known-answer campaigns and their frozen
protocols, findings, and finding-validation artifacts. It does not hold raw
telemetry, generated evidence sets, analysis runs, hypothesis registries, or
notebook-only state; those are produced into a local workspace and are never
tracked.

The synthetic campaigns bind demo-only setup and build declaration hashes so
the protected `must_match` controls are exercised. These declarations and all
derived artifacts remain synthetic mechanics, never scientific or product
evidence.

Every finding remains immutable by version. Corrections create a new version and
preserve the old artifact. Findings are organized by current status; moving
status requires a new reviewed finding version, not rewriting history without
explanation. Hypothesis lifecycle history is append-only and hash-chained, and
its current state is recomputed by replay rather than read from a stored summary.
