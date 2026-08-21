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

No inferential or racing-performance analysis is implemented in this milestone; analysis runs are descriptive summaries, never scientific evidence.

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
apex-labs repository-guard --root .
apex-labs verify-synthetic-demo --root .
apex-labs apex-session inspect "D:\external-data\session.zip"
apex-labs apex-session validate "D:\external-data\session.zip" --collection-record "D:\external-data\collection-record.json"
```

`ingest` and `export-product-findings` refuse to overwrite existing files. `inspect` verifies content hashes and normalized record counts; it is not merely a metadata viewer.

## Research lifecycle

1. Register source files in a dataset manifest and retain raw/private data outside Git.
2. Verify hashes and normalize through an explicit, versioned adapter.
3. Draft a falsifiable protocol with comparability, exclusion, sample, and success rules.
4. Freeze an immutable protocol snapshot and schedule before confirmatory collection; never rewrite it.
5. Run versioned code against fingerprinted data and preserve configuration and random seeds.
6. Attempt falsification, quantify effects and uncertainty, assess confounding and sample sufficiency.
7. Create an independent validation artifact. Unsupported or unresolved gates remain `inconclusive`.
8. Save the reviewed result as `validated`, `provisional`, `inconclusive`, or `rejected`.
9. Export selected findings and validation state as an evidence package.
10. Require human and production-engineering review in the separate Apex Sim Coach repository.

See [architecture](docs/architecture.md), [scientific method](docs/scientific-method.md), [data contracts](docs/data-contracts.md), [analysis runs](docs/analysis-runs.md), and [product handoff](docs/apex-sim-coach-handoff.md).

## Data policy

Real telemetry is not committed by default. Keep it in an approved external location and commit only reviewed, non-identifying manifests when appropriate. Tiny fixtures may be committed only when synthetic or explicitly sanitized and labeled. Never add credentials, production databases, customer data, or private keys.

Real participant ingestion requires pseudonymization, no direct identifiers, collection authority/consent metadata, retention policy, and a clean Apex Labs Git commit. Controlled experimental data additionally requires an exact frozen-protocol/condition/block/schedule link. Observational data must be labeled observational and cannot masquerade as preregistered. Run `apex-labs repository-guard` before review, while recognizing its heuristic limits.

## Status and scope are separate

A finding status describes evidential disposition. Its scope describes where evidence applies. A `driver_specific` result cannot become globally safe merely by being statistically strong. `population_supported` is reserved for validated population evidence; `population_hypothesis` is not a substitute. See [research/findings/README.md](research/findings/README.md).

## Readiness boundary

Compatibility with the existing customer-facing `apex-session-export/1.0.0` bundle has been validated against an external anonymized sample. That bundle contains distance-binned aggregates and is suitable for limited observational analysis, not high-fidelity time-domain research. Formal controlled collection remains blocked until the future Research-export contract, production capture implementation, privacy review, and frozen campaign protocol/schedule are reviewed. See the [customer-bundle adapter](docs/apex-session-export-adapter.md), [collection sidecar](docs/collection-record.md), [Research-export handoff](docs/apex-research-export-contract.md), and [remaining readiness checklist](docs/native-adapter-readiness.md).

Deterministic output is not scientific truth, schema validity is not adequate evidence, product annotations are not ground truth, and export verification is not authorship or production approval.
