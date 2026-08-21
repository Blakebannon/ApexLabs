# Apex Labs

Apex Labs is the reproducible performance-science and telemetry-research environment for Apex Sim Coach. It ingests declared datasets, normalizes simulator channels into stable concepts, preserves provenance, validates research protocols and findings, and creates review-gated product handoffs.

It is not the Apex Sim Coach application, a live coach, a notebook dumping ground, or an automatic production-update system. It does not turn plausible correlations into racing truths. Apex Labs never writes to the separate production repository.

## Foundation and native customer-bundle capabilities

- Versioned contracts for datasets, normalized records, experiments, findings, metrics, algorithm recommendations, and product exports.
- Manifest-driven generic CSV ingestion plus a strict native adapter for exactly `apex-session-export/1.0.0`.
- Content-bound dataset fingerprints covering source bytes, canonical manifest, complete adapter/preprocessing configuration, code and schema identity, normalized record bytes, and integrity summary.
- Session, lap, segment, timestamped telemetry-sample, distance-bin aggregate, and driver-input-event record types.
- Explicit canonical units/conventions; measured, derived, estimated, and unavailable provenance; parent/order/time policies; and non-repairing quality flags.
- Immutable protocol freezes, hash-bound randomization/schedules, and append-only amendments.
- Independent finding-validation artifacts separating analyst claims, computed evidence, structural/reproducibility gates, scientific review, and product review.
- Deterministic atomic product exports carrying findings and validation artifacts.
- A Git-visible repository guard for raw data, privacy, credential, binary, and fixture-policy risks. It is heuristic and does not replace human review or a dedicated secret scanner.
- Declared, deterministic, descriptive-only analysis runs (record inventory, channel availability/provenance, robust value summaries, per-lap event yield) whose artifacts bind dataset fingerprint, definition, metric, and code identity and are independently reproducible.
- A synthetic mechanics demonstration that produces no racing conclusion.

## Comparable evidence, inference, and the finding lifecycle

- Versioned segment definitions with explicit layout applicability, geometry fingerprints, boundary inclusivity, wraparound behaviour, and reproducible phases. Corner ordinals are never invented, and two regions sharing a name on different layout geometry are refused.
- Declared comparable evidence sets that bind datasets, protocol, segment, metric, conditions, arms, units, pairing, confounds, and holdouts, and that refuse to combine evidence across incompatible drivers, simulators, cars, tracks, layouts, protocol versions, conditions, coaching states, setup/configuration identities, product builds, segment or metric definitions, or normalization contracts. Missing setup/build identity is not a match; future variation requires a structured frozen-protocol plan.
- Enforced experimental and resampling units: telemetry frames and single events are never independent experimental units, and an interval must resample at or above the level at which the compared factor varies.
- A continuous attrition funnel over records, units, and pairs that distinguishes preregistered exclusion, unavailable evidence, structural invalidity, accepted limitations, and post-hoc exclusion, and never discards evidence silently.
- A separately named `apex-labs.inferential-analysis-definition/v1` contract for preregistered inference. `apex-labs.analysis-definition/v1` is unchanged and remains descriptive-observational only.
- A small standard-library statistical foundation: robust paired and unpaired differences, an exact paired sign test, a Theil-Sen ordered trend, a dispersion-ratio consistency comparison, and a deterministic, order-independent, machine-independent cluster percentile bootstrap with a fixed seed and stated interval semantics.
- Preregistered multiple-comparison families with Holm-Bonferroni familywise control for confirmatory work and Benjamini-Hochberg false-discovery control for exploratory search. Membership is fixed before results are known, and raw and adjusted evidence are both retained.
- Small-sample discipline that classifies sufficiency against preregistered or documented-pilot requirements and produces a preserved INCONCLUSIVE run rather than inventing a threshold or discarding the attempt.
- Deterministic sensitivity and falsification checks reported beside the primary estimate, never in place of it.
- Interpretation ceilings (`descriptive`, `associational`, `intervention_associated`, `causal_candidate`) derived from the frozen protocol, with a stronger requested interpretation refused before anything is computed.
- An append-only, hash-chained hypothesis lifecycle whose current state is recomputed by replay, with promotion gated on a completed independently verified run and a recorded reviewer disposition.
- Deterministic finding review packages with a machine-readable dossier and a plain human report that states weak evidence rather than burying it, and a conservative production recommendation that can never change Apex Sim Coach. Synthetic derivations are restricted to `none` or `do_not_implement` and cannot enter product review.
- Thirteen fabricated known-answer campaigns covering clear improvement, honest nulls, outlier-driven effects, unbalanced pairs, unmet sample requirements, observational association, delivered-versus-undelivered cues, exploratory false-positive pressure, a failed holdout replication, segment mismatch, the same corner ordinal on incompatible layouts, measured zeros beside unavailable values, and a counterbalanced causal candidate.

A descriptive summary is not inferential evidence. An inferential result is not a finding. A finding is not validated. A validated finding is not a product change. Statistical evidence is not the probability that a hypothesis is true. Synthetic evidence proves mechanics only.

## Quick start

Python 3.11 or newer is required. The runtime has no third-party dependencies.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
apex-labs --help
python -m unittest discover -s tests -v
```

Without installing, set `PYTHONPATH=src` and run `python -m apex_labs`.

## Core workflows

```powershell
apex-labs inspect tests/fixtures/synthetic_demo/dataset.manifest.json
apex-labs ingest tests/fixtures/synthetic_demo/dataset.manifest.json --output .apex-labs/demo-normalized
apex-labs inspect .apex-labs/demo-normalized/manifest.json
apex-labs analyze research/analyses/synthetic-demo-descriptive.json --dataset .apex-labs/demo-normalized --run-id demo-run-001 --created-at 2026-08-20T00:00:00Z --output .apex-labs/demo-analysis
apex-labs verify-analysis .apex-labs/demo-analysis --dataset .apex-labs/demo-normalized
apex-labs experiment validate protocols/first-controlled-campaign.json
apex-labs experiment verify-freeze tests/fixtures/synthetic_demo/protocol.freeze.json
apex-labs findings validate research/findings
apex-labs findings verify research/findings/inconclusive/synthetic-mechanics-demo.json research/validations/synthetic-mechanics-demo-validation.json
apex-labs export-product-findings product-exports/synthetic-demo-export-definition.json --output product-exports/generated/demo --root .
apex-labs verify-export product-exports/generated/demo
apex-labs evidence build research/evidence-sets/synthetic-paired-corner-speed.json --segment research/segments/synthetic-corner-a.json --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json --metric research/metrics/segment-minimum-speed.json --dataset .apex-labs/block-01 --dataset .apex-labs/block-02 --built-at 2026-08-20T00:00:00Z --output .apex-labs/evidence
apex-labs evidence verify research/evidence-sets/synthetic-paired-corner-speed.json --segment research/segments/synthetic-corner-a.json --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json --metric research/metrics/segment-minimum-speed.json --dataset .apex-labs/block-01 --dataset .apex-labs/block-02 .apex-labs/evidence
apex-labs infer run research/analyses/synthetic-paired-corner-speed-confirmatory.json --evidence .apex-labs/evidence --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json --run-id demo-run --created-at 2026-08-20T00:00:00Z --output .apex-labs/run
apex-labs infer verify .apex-labs/run --evidence .apex-labs/evidence --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json
apex-labs hypothesis register hypothesis.json --registry .apex-labs/hypotheses --recorded-at 2026-08-20T00:00:00Z
apex-labs hypothesis verify --registry .apex-labs/hypotheses
apex-labs review-package verify .apex-labs/package --evidence .apex-labs/evidence --run .apex-labs/run
apex-labs campaign verify-all --root .
apex-labs campaign regenerate-references --root . --output .apex-labs/regenerated-references
apex-labs repository-guard --root .
apex-labs verify-synthetic-demo --root .
apex-labs verify-science-demo --root .
apex-labs apex-session inspect "D:\external-data\session.zip"
apex-labs apex-session validate "D:\external-data\session.zip" --collection-record "D:\external-data\collection-record.json"
```

`ingest` and `export-product-findings` refuse to overwrite existing files. `inspect` verifies content hashes and normalized record counts; it is not merely a metadata viewer.

## Research lifecycle

1. Register source files in a dataset manifest and retain raw/private data outside Git.
2. Verify hashes and normalize through an explicit, versioned adapter.
3. Draft a falsifiable protocol with comparability, exclusion, sample, and success rules.
4. Freeze an immutable protocol snapshot and schedule before confirmatory collection; never rewrite it.
5. Declare a segment and an evidence-set definition before looking at any value, then build a comparable evidence set with full attrition accounting.
6. Preregister an inferential analysis, run it once against fingerprinted evidence, and preserve its configuration and random seed.
7. Attempt falsification, quantify the effect and its uncertainty, correct the declared comparison family, and classify sample sufficiency.
8. Record the hypothesis lifecycle transition. Promotion requires a completed, independently verified run and a reviewer disposition.
9. Create an independent validation artifact. Unsupported or unresolved gates remain `inconclusive`.
10. Save the reviewed result as `validated`, `provisional`, `inconclusive`, or `rejected`.
11. Assemble a finding review package for human scientific review, and export selected findings and validation state as an evidence package.
12. Require human and production-engineering review in the separate Apex Sim Coach repository.

See [architecture](docs/architecture.md), [scientific method](docs/scientific-method.md), [data contracts](docs/data-contracts.md), [analysis runs](docs/analysis-runs.md), [comparable evidence](docs/comparable-evidence.md), [inferential analysis](docs/inferential-analysis.md), [hypothesis and finding lifecycle](docs/hypothesis-and-finding-lifecycle.md), [L6 readiness](docs/l6-readiness.md), and [product handoff](docs/apex-sim-coach-handoff.md).

## Data policy

Real telemetry is not committed by default. Keep it in an approved external location and commit only reviewed, non-identifying manifests when appropriate. Tiny fixtures may be committed only when synthetic or explicitly sanitized and labeled. Never add credentials, production databases, customer data, or private keys.

Real participant ingestion requires pseudonymization, no direct identifiers, collection authority/consent metadata, retention policy, and a clean Apex Labs Git commit. Controlled experimental data additionally requires an exact frozen-protocol/condition/block/schedule link. Observational data must be labeled observational and cannot masquerade as preregistered. Run `apex-labs repository-guard` before review, while recognizing its heuristic limits.

## Status and scope are separate

A finding status describes evidential disposition. Its scope describes where evidence applies. A `driver_specific` result cannot become globally safe merely by being statistically strong. `population_supported` is reserved for validated population evidence; `population_hypothesis` is not a substitute. See [research/findings/README.md](research/findings/README.md).

## Readiness boundary

Compatibility with the existing customer-facing `apex-session-export/1.0.0` bundle has been validated against an external anonymized sample. That bundle contains distance-binned aggregates and is suitable for limited observational analysis, not high-fidelity time-domain research. Formal controlled collection remains blocked until the future Research-export contract, production capture implementation, privacy review, and frozen campaign protocol/schedule are reviewed. See the [customer-bundle adapter](docs/apex-session-export-adapter.md), [collection sidecar](docs/collection-record.md), [Research-export handoff](docs/apex-research-export-contract.md), and [remaining readiness checklist](docs/native-adapter-readiness.md).

Deterministic output is not scientific truth, schema validity is not adequate evidence, product annotations are not ground truth, and export verification is not authorship or production approval.

Campaign and rehearsal readiness is deliberately not built yet. What remains before a real collection campaign is listed in [L6 readiness](docs/l6-readiness.md).
