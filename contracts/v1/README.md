# Version 1 JSON contracts

These Draft 2020-12 JSON Schemas describe the portable structure of Apex Labs v1 artifacts. They are intended for editors, CI conformance checks, and external consumers. The dependency-free Python runtime validators under `src/apex_labs/schemas/` are authoritative. They additionally enforce semantic and cross-file rules that JSON Schema cannot establish, including safe local paths, self-hashes, frozen-protocol linkage, record relationships, and review gates.

Conformance tests run representative valid and invalid artifacts through both paths. Passing a published schema is necessary but not sufficient: callers must also use the runtime validator and any applicable cross-file verifier. Schema validity establishes structure, not reproducibility, adequate evidence, scientific validity, authorship, or product approval.

Contract IDs are stable within v1. A breaking semantic or structural change requires v2. Adding an adapter version, metric version, protocol version, or finding version does not itself change a contract major version.

Native contracts cover the supported customer `apex-session-export/1.0.0`
manifest, the Apex Labs collection-record sidecar, the permanently
non-scientific product-annotation wrapper, and the proposed future
`apex-research-session-export/1.0.0` handoff. The additive
`apex-research-recorder-profile-v1.json` pins the exact M54R recorder channel,
file, null, coaching-evidence, configuration-hash, and completion conventions.
It tightens conformance without invalidating historical base-v1 manifests.

`exploratory-intake` is the one way a REAL session collected before any protocol
freeze reaches normalization. It is deliberately a separate contract rather than a
relaxation of `protocol-freeze`: every field that would describe a prospective plan
is pinned to the value that denies one, the only reviewer disposition is
`approved_exploratory_only`, and it must bind the exact bundle manifest and
collection-record hashes it admits. A dataset admitted this way carries a
`scientific_eligibility` block with `stratum: exploratory_pilot` that is an
ingredient of the dataset fingerprint, so descriptive analysis and hypothesis
generation are permitted while confirmatory claims, causal claims, primary effect
estimates and primary-corpus pooling are permanently refused. The primary gate is
unchanged: without a reviewed freeze or a valid intake, real ingestion still fails.

Scientific contracts added for comparable evidence and inference are
`segment-definition`, `evidence-set-definition`, `evidence-set`,
`inferential-analysis-definition`, `inferential-analysis-run`, `hypothesis`,
`hypothesis-transition`, and `finding-review-package`. Inference is a separately
named contract rather than a second version of `analysis-definition`, which
remains descriptive-observational only, so that a descriptive definition can
never be quietly promoted into evidence for a hypothesis test and every existing
v1 descriptive artifact stays valid unchanged.

Setup/configuration and product-build identities are protected comparability
fields. The initial corpus requires them to match. The experiment contract's
optional structured `identity_variation_plans` is the only way a future frozen
protocol can authorize either field to vary; evidence definitions must bind the
plan id and cannot use free text as a waiver. Synthetic conditions in the
finding, validation, review-package, and product-export schemas prohibit product
review and every recommendation state except `none` or `do_not_implement` as
applicable. Runtime cross-file gates preserve that restriction transitively.

`iracing-variable-inventory` describes a sanitized simulator variable table:
name, SDK type, array count, unit token, and description, with `values_sampled`
and `direct_identifiers_included` both required to be false. It is simulator
capability metadata and never telemetry. A snapshot proves what one build
exposed in one session, so it is dated and hash-bound rather than treated as
standing simulator truth, and it supports no scientific finding because no
values were sampled. A unit token beginning `irsdk_` identifies an enumeration
whose value dictionary the inventory does **not** carry, which is why Labs
preserves such values verbatim instead of decoding them.
