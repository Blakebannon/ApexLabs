# Apex Labs contributor instructions

These instructions apply to this repository tree.

- Work only inside this Apex Labs repository. Never inspect or modify the separate Apex Sim Coach production repository as part of Apex Labs work.
- Apex Labs produces evidence packages; it never automatically promotes changes into production.
- Do not treat an LLM explanation, a chart, a correlation, or synthetic data as scientific evidence.
- Preserve measurement provenance as measured, derived, estimated, or unavailable.
- Preregister confirmatory protocols. Declare comparability, exclusions, sample requirements, analysis, success criteria, and falsification criteria before execution.
- Keep rejected and inconclusive findings. Never recategorize weak evidence to make a result more attractive.
- Never generalize driver-, car-, track-, corner-, simulator-, or session-specific evidence without new supporting evidence and a new finding.
- Record dataset fingerprints, source hashes, preprocessing and normalization versions, analysis code version/configuration, protocol version, source commit, and random seed where applicable.
- Keep raw/private telemetry and all secrets out of Git. Synthetic fixtures must say synthetic and demo-only in their manifests and findings.
- Prefer the simplest statistical method that reliably answers the preregistered question. State interval meaning; never invent an uncalibrated confidence score.
- Do not claim causality from uncontrolled observational data.
- Run the full test suite after changing contracts, ingestion, provenance, or exports.
