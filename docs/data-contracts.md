# Data and contract model

Runtime validation in `src/apex_labs/schemas/validation.py` is authoritative for this release. Contract examples and external JSON Schemas live under `contracts/v1/`. Canonical JSON uses UTF-8, sorted keys, compact separators, finite numbers only, and one trailing newline.

## Source dataset manifest

A dataset manifest records identity, synthetic/private classification, minimum privacy metadata, exact frozen-protocol/condition/block/schedule collection context, simulator, source format, adapter and mapping configuration, source files, roles, media types, and SHA-256 hashes. Contract paths use canonical relative POSIX syntax. Traversal, POSIX/Windows absolute paths, drives, UNC/device paths, ambiguous Windows names, and symlink/reparse escapes are rejected.

`dataset_id` is a declared human/machine identity. `source_fingerprint` binds canonical source-manifest content, sorted source byte hashes/roles/media types, adapter/configuration, simulator/classification, and normalization contract. The final `dataset_fingerprint` additionally binds the exact code/schema identity, preprocessing configuration/hash, frozen collection context, temporal/convention policies, deterministic normalized-record hash/counts, and integrity summary. It is calculated only after normalization. Enumeration order and absolute local roots are excluded; scientifically meaningful record order is preserved and hashed.

Adapter input is copied once while hashing, then the snapshot bytes—not a second read of a changing source—are parsed. Real datasets require a clean exact Git commit. Synthetic demonstrations may explicitly record `UNCOMMITTED`, but remain scientifically ineligible.

The fingerprint identifies normalized research input; it does not anonymize content and is not proof of consent.

## Qualified values

Normalized record fields have this logical form:

```json
{
  "value": 31.5,
  "unit": "m/s",
  "provenance": "measured",
  "source_channel": "speed_mps",
  "quality_flags": []
}
```

- `measured`: directly reported by the declared source; requires `source_channel`.
- `derived`: deterministically computed from other values; requires a derivation description.
- `estimated`: model- or assumption-based; requires an estimation description.
- `unavailable`: source/capability cannot provide a value; value must be null.

An absent field means the concept was not supplied/applicable on that record. It is distinct from an explicit unavailable value and from a measured numeric zero. JSON duplicate keys and non-finite numbers are refused.

Measured does not mean accurate. Quality flags, unit definitions, calibration metadata, and source limitations still matter.

## Normalized levels

All record types contain dataset/session/record IDs and source provenance.

- `session`: simulator, pseudonymous driver identity, car, track, layout, and session-level fields.
- `lap`: stable lap ID/number and lap-level fields.
- `segment`: corner, straight, or custom segment linked to a lap.
- `telemetry_sample`: sample index and timestamp plus available telemetry fields.
- `driver_input_event`: a versioned event type and timestamp plus event fields.

Record IDs, session IDs, lap IDs, and segment IDs are unique in their relevant namespace. The canonical stream uses contiguous `sequence_index` values with parents before children. Every lap belongs to its session; every segment/sample/event belongs to its declared lap and optional segment. The record stream may omit levels that cannot be produced honestly. For example, ingestion must not fabricate corners when no trusted segmentation exists. A later preprocessing stage can create derived segment/event records while naming its version and derivation.

The adapter declares source clock, normalized clock origin/reference, resolution, duplicate/reset policies, expected cadence/gap tolerance, lap-distance regression policy, and interpolation provenance. Normalized telemetry and input-event timestamps reference `normalized_monotonic_time`. Within-session regressions and duplicates are rejected or explicitly flagged according to policy. New sessions establish a new declared clock origin. Sample-index gaps, cadence gaps, allowed resets/duplicates, unavailable time, and allowed lap-distance regressions produce exclusion-capable quality flags; no meaningful defect is silently repaired. Lap distance may reset between laps, not silently within one lap.

Canonical v1 values use SI-oriented units and a right-handed vehicle frame (`x` forward, `y` left, `z` up), positive-left steering/lateral acceleration, positive-forward longitudinal acceleration, and counterclockwise-positive yaw viewed from above. Source-specific clock conversions, units, axes/signs, lap boundaries, resets, and corruption behavior remain adapter responsibilities; normalized parent, finite-value, canonical-unit, and ordering rules are universal.

## Normalized v1 concepts

The v1 vocabulary includes time, lap timing/validity/distance, position, speed, acceleration, yaw, steering, pedals, gear/RPM, per-wheel speeds, tire pressures/temperatures, ABS/TC, fuel, session/incident/off-track state, and air/track conditions. The manifest capability matrix enumerates every concept, including unavailable concepts. New concepts require review for definition, unit/reference-frame semantics, and compatibility.

## Optimal future Apex Sim Coach export

No current production export format is assumed. For high-fidelity research, a future versioned export should ideally provide:

- Stable export, dataset, session, driver-pseudonym, car, track, and layout identifiers.
- Export schema/version and simulator/build/plugin versions.
- Original channel names, units, coordinate/reference frames, sign conventions, sampling clocks/rates, timestamp origin, and resampling/dropout information.
- Monotonic sample time plus lap/session timing and distance/position where available.
- Raw driver inputs and vehicle motion channels before coaching transformations.
- Wheel/tire, driver-aid, fuel, damage, incident, off-track, reset, pit, flag, and traffic context where available.
- Weather, track state, setup identifier/hash, control calibration, hardware context, and changes during the session.
- Lap validity and the reason for invalidity.
- Production-derived corners/events only when their algorithm ID/version/configuration and source samples are included.
- File hashes, export timestamp, data classification, consent/authority, redaction state, and known data-quality issues.
- Explicit capability availability rather than zero-filled missing channels.

An export need not contain every channel. It must distinguish absent information from a real zero and preserve enough context to assess comparability.

## Experiment protocol

An experiment declares one research question and null, independent variable and levels, primary/secondary metrics, controls, comparability, exclusions, minimum samples, conditions, randomization/counterbalancing, methods, success/falsification criteria, safety, protocol version, time, and source commit.

`draft` protocols may mark sample and success rules `to_be_determined`. Any `preregistered`, `active`, `completed`, or `aborted` protocol must have those rules declared. Freezing creates a non-overwritable snapshot containing the entire canonical protocol, protocol/hash/code/commit/time identity, predetermined seed or schedule where applicable, and initial amendment history. Changes require a new protocol version or a separately hash-bound append-only amendment chain; the original snapshot is never rewritten. Collected datasets reference the exact freeze and schedule.

## Finding

A finding records the analyst claim, status and scope separately, effect/uncertainty when appropriate, complete counts, sample sufficiency, comparability, datasets/fingerprints/manifest/record hashes, frozen protocol, preprocessing/normalization, analysis version/config/seed/code identity, limitations, confounders, generalizability, falsification, implications, future validation, timestamp, and source commit.

The separate finding-validation artifact is authoritative for evidence/review binding. It distinguishes analyst claims from computed or unavailable evidence; evaluates structural, reproducibility, and scientific gates; and records scientific reviewers separately from product review. Cross-file verification binds it to the canonical finding hash and all exact evidence references. Unresolved gates remain inconclusive.

Synthetic findings cannot be validated or provisional and must say `do_not_implement`. Real findings cannot use `UNCOMMITTED`. Global consideration is allowed only for validated `algorithmic` or `population_supported` scope; this permits review, not automatic implementation.
