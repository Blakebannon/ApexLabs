# Apex Sim Coach handoff

## Boundary

A product export is a review artifact, not an integration mechanism. Apex Labs never opens, patches, configures, or deploys the Apex Sim Coach production repository. A human and a production engineer or production-focused AI must decide whether a finding is relevant, safe, implementable, and testable.

The future telemetry-capture handoff is separately specified in
[apex-research-export-contract.md](apex-research-export-contract.md). The normal
customer Session Analysis Bundle remains separate. Neither contract authorizes
Apex Labs to change production.

`apex-labs apex-research inspect|validate|ingest` is a local, one-way ingestion
surface for completed recorder directories. It never locates or writes the Apex
Sim Coach repository. Collection records and protocol snapshots remain Labs-side
operator inputs; findings still require human and production-engineering review.

## Package contract

`apex-labs export-product-findings` consumes a versioned export definition and creates:

```text
<export-id>/
    manifest.json
    README.md
    findings/
        <finding-id>-v<version>.json
    validations/
        <validation-id>-v<version>.json
    metrics/
        <metric-id>-v<version>.json
    algorithms/
        <algorithm-id>-v<version>.json
    provenance/
        summary.json
```

Empty metric or algorithm collections are allowed. Arbitrary notebook state, raw telemetry, executable production patches, and secrets are forbidden.

The provenance summary collects each finding's dataset fingerprints, protocol reference, preprocessing/normalization version and configuration, analysis version/configuration/random seed, validation-artifact reference, scientific review state, and product review state. The manifest identifies the Apex Labs package version and source commit, creation time supplied by the definition, every finding's status/scope/evidence class/global-safety flag/product action/caveats, its validation payload/hash, and every payload path/hash/media type/role. It always declares `human_and_production_engineering_review_required`.

Generation canonicalizes JSON and semantically unordered inventories. Given identical input bytes and definition, output bytes are identical across working directories, locale, timezone, and enumeration order. A local exclusive lock prevents concurrent writers, output is staged and verified before one atomic promotion, and the command refuses overwrite. `apex-labs verify-export` rejects missing, extra, corrupted, metadata-inconsistent, or cross-reference-inconsistent payloads.

Verification proves package hashes and internal contract consistency only. It does not prove who authored or reviewed an artifact, that computed evidence is scientifically correct, or that production has approved anything. Those require independent identity/review processes and deliberate production engineering.

## Production review questions

1. Do all hashes and finding-to-validation references verify, and do finding source commits match the export?
2. Is the finding validated, provisional, inconclusive, or rejected?
3. What is its evidence scope, and is global consideration explicitly false?
4. Were samples sufficient and comparisons adequate by a documented method?
5. What uncertainty, limitations, confounders, and falsification attempts remain?
6. Is the recommendation personalized, research-only, do-not-implement, or merely safe to consider?
7. Does a metric or algorithm specification state inputs, units, assumptions, and required validation?
8. What production implementation, regression, simulation, offline, and live validation tests are needed?

`safe_for_global_consideration: true` means only that a validated algorithmic or population-supported result may enter global product design review. It never means auto-approve, auto-merge, or universally true.

## Version and commit rule

Real findings require a real Apex Labs Git commit. Before the initial baseline exists, a synthetic demonstration may use `UNCOMMITTED`; validation permits that sentinel only for synthetic evidence. Checked-in references should bind the clean foundation revision once it exists. A reviewed production export should normally be generated from a clean, identified revision.
