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
 frozen protocol/schedule + segment + metric definitions
                  |
        comparable evidence set (units, pairs, attrition)
                  |
 preregistered inferential analysis definition + run
                  |
    append-only hypothesis lifecycle transitions
                  |
 finding + independent validation artifact
                  |
      deterministic finding review package
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
- `analysis`: declared, deterministic computations over verified inputs. `descriptive` covers inventories, availability, robust summaries, and event yield; `statistics` holds the robust, order-independent, machine-independent kernels; `inferential` runs preregistered comparisons over one comparable evidence set.
- `evidence`: segment identity and membership, the comparability guard, and deterministic comparable-evidence-set construction with full attrition accounting.
- `hypotheses`: the append-only, hash-chained hypothesis lifecycle whose current state is recomputed by replay.
- `campaigns`: fabricated known-answer campaigns that drive the real path end to end and compare the outcome with expectations written by hand.
- `exports`: locked, failure-atomic deterministic package generation and internal-consistency verification.
- `repository_guard`: heuristic Git-visible privacy/raw-data/secret boundary used locally and in CI.
- `cli`: thin orchestration; it contains no scientific logic.

The `analysis` package is standard library only. Beyond the descriptive computations it now implements a deliberately small inferential foundation: paired and unpaired robust differences, a Theil-Sen ordered trend, a dispersion-ratio consistency comparison, an exact paired sign test, a deterministic cluster percentile bootstrap, and Holm-Bonferroni and Benjamini-Hochberg corrections. No regression, hierarchical model, or machine learning exists, because no real corpus supports one and no preregistered question needs one. Adding a sophisticated model without both is how fragile results get manufactured. See [inferential analysis](inferential-analysis.md).

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

## Scientific layering

Four artifacts sit between a normalized dataset and a human decision, and none
implies the next:

1. A **comparable evidence set** decides what may be compared with what, at which
   experimental and resampling unit, under which preregistered exclusion rules,
   and reports every stage at which evidence left the funnel.
2. An **inferential analysis run** answers exactly the preregistered question over
   exactly that evidence, and reports its estimate, interval, raw and adjusted
   statistical evidence, sensitivity results, sufficiency, and interpretation
   ceiling.
3. A **hypothesis lifecycle** preserves how a proposal moved from generated to a
   disposition, append-only and hash-chained, with every promotion gated on a
   completed independently verified run and a recorded reviewer disposition.
4. A **finding review package** assembles the whole dossier for human scientific
   review and states its production recommendation conservatively.

There is still deliberately no code path from any of them into production source
code or configuration.
