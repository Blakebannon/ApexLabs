# Architecture

## Boundaries

Apex Labs owns research ingestion, normalization, reproducibility metadata, protocol/finding records, and evidence exports. Apex Sim Coach owns live coaching and all production decisions. The only planned bridge is a versioned, read-only product export reviewed by humans and production engineering.

```text
declared source files + dataset manifest
                  |
          versioned adapter
                  |
 content-bound normalized manifest + JSONL
                  |
 frozen protocol/schedule + analysis code
                  |
 finding + independent validation artifact
                  |
 deterministic product export package
                  |
     explicit external review gate
```

There is deliberately no code path from an Apex Labs finding into production source code or configuration.

## Package responsibilities

- `ingestion`: source-adapter registry and the initial manifest-driven CSV adapter.
- `normalization`: simulator-independent concepts, canonical units/conventions, record types, and cross-record integrity.
- `schemas`: contract identifiers and strict runtime validation.
- `provenance`: source snapshots, path-independent code/schema identity, source fingerprints, and normalized content fingerprints.
- `experiments`: immutable protocol freeze/verification and append-only amendment artifacts.
- `findings`: cross-file binding between analyst findings and evidence/review validation artifacts.
- `exports`: locked, failure-atomic deterministic package generation and internal-consistency verification.
- `repository_guard`: heuristic Git-visible privacy/raw-data/secret boundary used locally and in CI.
- `cli`: thin orchestration; it contains no scientific logic.

Statistics and racing-analysis packages do not exist yet because Milestone 0 has no real analysis to implement. They should be added only with a concrete preregistered method, tests, and dependency justification.

## Storage model

The source dataset manifest is small JSON. Large telemetry remains in external/local storage and is addressed through relative paths and SHA-256 hashes. Ingestion emits:

```text
normalized-dataset/
    manifest.json
    records.jsonl
```

JSONL allows streaming and partitioning later without changing the record contract. A future columnar backend may store identical logical records in Parquet or Arrow, but it must preserve the v1 meanings and provenance. The normalized manifest inventories every v1 concept as measured, derived, estimated, or unavailable.

## Adapter boundary

An adapter translates an explicitly declared source format to normalized records. It must:

1. Validate its versioned configuration.
2. Copy each source once while hashing, then parse exactly those snapshot bytes.
3. Preserve source file, hash, channel, and row/record references.
4. Attach units and provenance to values.
5. Report source channels it did not normalize.
6. Declare source clock, normalized monotonic clock, resolution, reset/duplicate/gap policies, interpolation, canonical units, and coordinate/sign conversion.
7. Refuse malformed or ambiguous input and preserve detectable defects as quality flags when policy allows them.

The generic `tabular-csv` adapter has no iRacing or Apex Sim Coach names embedded
in it. Its manifest supplies the mapping. The native customer-bundle adapter
targets exactly the reviewed `apex-session-export/1.0.0` contract and represents
its telemetry as distance aggregates, not raw samples. High-resolution Research
export compatibility remains unimplemented until production engineering supplies
an actual reviewed sample/specification for that separate contract.

## Versioning

Contract identifiers use `apex-labs.<contract>/v1`. Semantic versions identify adapter, normalization, preprocessing, metric, algorithm, experiment, finding, and package releases. Breaking meaning changes require a new contract major version and compatibility tests. Unknown versions are rejected rather than coerced.

A semantic version is not code identity. Normalized provenance also records the exact package-content hash, individual schema hashes, Git commit/state, complete configuration hash, and output-content hash. Real research refuses dirty or uncommitted code even when the declared version appears unchanged.
