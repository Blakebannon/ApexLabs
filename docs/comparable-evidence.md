# Comparable evidence, segments, and units

A comparable evidence set is the object that decides *what may be compared with
what*. It is built before any statistic is computed, from a declaration written
before the values were inspected, and it records every stage at which evidence
left the funnel.

An evidence set is not a result and not a finding. Its own contract calls it
`comparable_evidence_not_scientific_evidence`.

```powershell
apex-labs evidence build research/evidence-sets/synthetic-paired-corner-speed.json `
  --segment research/segments/synthetic-corner-a.json `
  --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json `
  --metric research/metrics/segment-minimum-speed.json `
  --dataset .apex-labs/block-01 --dataset .apex-labs/block-02 `
  --built-at 2026-08-20T00:00:00Z --output .apex-labs/evidence
apex-labs evidence verify research/evidence-sets/synthetic-paired-corner-speed.json `
  --segment ... --protocol-freeze ... --metric ... --dataset ... .apex-labs/evidence
```

## What an evidence set binds

Every built set carries, and re-verifies before computing anything:

- Each contributing dataset's id, fingerprint, normalized-manifest hash, records
  hash, and synthetic classification.
- The participant pseudonym, simulator, car, track, and layout read from the
  session record.
- The frozen protocol: freeze id and hash, protocol id, version and hash,
  randomization strategy, derived collection classification, and whether its
  minimum-sample requirements are declared.
- The collection condition and block, and the arm the protocol assigns to that
  condition.
- The coaching state the definition declares for that arm.
- Configuration/setup identity and product-build identity from exact,
  fingerprint-bound `configuration-setup.json` and `product-build.json` source
  declarations, or an explicit record that the identity is unavailable.
- The complete segment definition and its hash.
- The metric definition, its hash, its unit, and its directionality.
- Inclusion rules, exclusion rules, confounds, covariates, and the pairing key.
- The experimental unit, the resampling unit, and the level at which the
  compared factor varies.
- The holdout policy and the units it reserves.
- Apex Labs code and schema identity, and a self-hash over the whole artifact.

## Comparability is declared, never inferred

The definition must place **every** guarded comparability field into exactly one
of two lists: `must_match`, or `permitted_variation` with a justification and a
retention (`covariate` or `limitation`). The guarded fields are participant,
simulator, car, track, layout, protocol version, condition semantics, coaching
state, configuration identity, segment definition, metric definition,
normalization contract, and product build. Leaving one undeclared is refused.

If a `must_match` field actually varies across the contributing datasets, the
build is **refused outright** rather than downgraded — that evidence may not be
combined at all. If a `must_match` field is unavailable in the corpus, the build
records a comparability violation and the status becomes `limited`: an absent
field cannot be verified as matching. If only one arm is represented, the status
is `inadequate` and the interpretation ceiling collapses to descriptive.

For the initial scientific corpus, `configuration_identity` and `product_build`
are always `must_match`. A known mismatch is a hard refusal. Missing identity is
never treated as a match or as unrestricted permitted variation: it remains a
documented violation and limitation and prevents a causal-candidate ceiling.

A future protocol may study setup or build variation only through a structured
`identity_variation_plans` entry frozen with the protocol. That entry must name
the varying factor, rationale, assignment or balancing, analysis handling,
confounding implications, and a reduced interpretation ceiling. The evidence
definition must bind the exact plan id. A free-text justification by itself is
rejected, and every protected variation remains a recorded limitation.

## Segments

A segment is a geometric region on a specific layout, not a label.

- `applies_to` lists exactly the simulator/track/layout combinations the segment
  covers, each with a `geometry_fingerprint` and a stated geometry source.
  Evidence from an uncovered layout is refused.
- All contributing datasets must resolve to a **single** geometry fingerprint.
  Two regions that share an ordinal name such as "Turn 4" on different layout
  geometry are refused even when the protocol explicitly permitted layout to
  vary. That refusal is exercised by a checked-in campaign.
- `corner_identity` may only be claimed by a segment whose `identity_source` is a
  verified catalog or verified corner identity, and it must bind that catalog and
  its hash. A protocol distance or lap-fraction range must not claim a corner
  number: corner ordinals are never invented.
- `identity_confidence` is `verified`, `declared`, or `approximate`. An
  approximate mapping must record that limitation, and a bound catalog identity
  may not be approximate.
- The region declares `start`, `end`, `wraparound`, an optional lap length, and
  explicit `start_inclusive`/`end_inclusive` boundaries, which must agree with
  the declared `boundary_sample_resolution`. A wrapping region (start above end)
  holds everything from the start bound to the end of the lap and everything from
  the beginning of the lap to the end bound, and requires a declared lap length.
- A phase (`braking`, `turn_in`, `apex_region`, `exit`) may narrow the region
  only through the one supported reproducible method,
  `apex-labs.threshold-phase/1.0.0`, which declares a normalized concept, a
  comparison, and a threshold. No undocumented heuristic is accepted.
- `coverage_requirements` declare the required normalized concepts, the minimum
  records per unit, the minimum concept-coverage ratio, and the minimum number of
  comparable units.

## Experimental units and pseudoreplication

The observation hierarchy, from most nested upward, is `telemetry_frame`,
`event`, `segment_opportunity`, `lap`, `stint`, `block`, `session`,
`participant`.

Three rules are enforced by contract, before any data is read:

1. **Frames and single events are never experimental units.** A thousand
   telemetry frames from one braking event are one opportunity, not a thousand
   observations.
2. **The resampling unit sits at or above the experimental unit.**
3. **The resampling unit sits at or above the level at which the compared factor
   varies.** If the condition changes between blocks, laps nested inside a block
   are not independent evidence about it, so an interval must resample blocks.

This milestone can construct `segment_opportunity`, `lap`, `block`, and `session`
units from normalized v1 records. `stint` and `participant` are refused with a
clear message rather than approximated.

When repeated observations are summarized into a unit, the unit preserves the
records considered, the records used, the records missing, the within-unit
dispersion, the aggregation method, its provenance, and its covariates. A
summarizing aggregation that declares no dispersion measure is refused.

For a paired design the independent replicate is the **block pair**, not either
side's block: a pair spans both arms, so assigning it to one arm's block would
overstate the number of independent replicates.

## Attrition

Evidence is never silently discarded. The ledger is a continuous funnel at each
level — records, then units, then pairs — where every stage considers exactly
what the previous stage left, and `considered - excluded = remaining` always.

Record-level stages: records streamed, protocol mismatch, out-of-order or
corrupt, record type not read, outside segment, invalid lap, missing required
channel, incident affected, pit/replay/discontinuity. Unit-level stages: units
formed, insufficient coverage, duplicate evidence, confound based, holdout
reserved. Pair-level stages: pairable units, unpaired units.

Each entry records a disposition:

| Disposition | Meaning |
| --- | --- |
| `counted` | The stage established a denominator; nothing was removed. |
| `excluded_by_preregistered_rule` | A rule the definition declared before construction removed it. |
| `unavailable` | The evidence was absent, not adverse. A measured zero is never read as unavailable, and an unavailable value is never read as zero. |
| `structurally_invalid` | The record could not be trusted at all. |
| `accepted_with_limitations` | Nothing was removed, but something must be stated. |
| `post_hoc_exclusion` | A rule that was **not** preregistered removed evidence. |

If evidence is removed at a stage that no declared rule permits, the build is
refused. If any stage records a post-hoc exclusion, the artifact sets
`post_hoc_exclusions_present`, and a confirmatory analysis over that evidence is
denied confirmatory interpretation.

Units reserved for replication are **flagged, not dropped**: they stay in the
artifact, are enumerated in `holdout.reserved_unit_ids`, and are withheld from
the primary analysis scope.

## Determinism and verification

Units are serialized in lexicographic `unit_id` order, pairs in `pair_id` order.
Given the same definition, segment, metric, protocol, and dataset bytes, the
output bytes are identical regardless of the order the datasets were supplied in.

`evidence verify` rebuilds the whole set from its declared inputs and compares it
section by section, rather than re-hashing the stored answer. Tampering with the
artifact, a dataset, the segment, the metric, or the protocol is detected.

Output is staged and atomically promoted under an exclusive lock. The command
refuses to overwrite an existing directory, and a refused build leaves nothing
behind.

Real datasets require a clean committed Apex Labs code identity. Synthetic
mechanics may run uncommitted, and synthetic and real evidence may never be
combined in one set.
