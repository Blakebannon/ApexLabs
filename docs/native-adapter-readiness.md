# Native Apex Research-export readiness

The existing customer Session Analysis Bundle is supported at exactly
`apex-session-export/1.0.0` and has been validated against one external
anonymized sample. It contains distance-binned aggregates, not the timestamped
raw or near-raw samples needed for the proposed controlled campaign. Native
The M54R recorder profile now has deterministic synthetic end-to-end evidence:
an actual C# recorder bundle passes the dependency-free Labs runtime validator
and streams through the `apex-research-recorder/1.0.0` adapter into normalized
records. Real-session fitness remains unverified.

## Required input package

1. A tiny sanitized or synthetic, versioned sample produced by the actual
   Research export path, its SHA-256, and expected record counts.
2. The export contract/version and compatibility policy, including strict
   refusal of unsupported older/newer versions.
3. Every channel name, type, semantic definition, availability, source unit,
   canonical conversion, coordinate frame, sign, structural range, and
   measured/derived/estimated/unavailable provenance.
4. Nominal and variable sampling rates, per-channel rates, ordering, buffering,
   dropped/duplicated samples, resampling, interpolation, quantization, clock
   resolution, and recorder backpressure.
5. Clock source/origin/epoch, monotonicity, precision, rollover, pause, reset,
   reconnect, and the relationships among simulator/session/lap/wall clocks.
6. Missing conventions for absent columns, null/blank/sentinel/NaN, true zero,
   disabled channels, and partial records.
7. Session, stint, lap, sector, pit, reset, replay, reconnect, and file-rotation
   boundaries and invalidation reasons.
8. Exact simulator/build, car, track/layout, participant pseudonym, session, and
   export identifiers and their stability/privacy classifications.
9. Incident, off-track, traffic, flags, assists, damage, fuel, tires, environment,
   calibration, hardware, setup, and change events where available.
10. Privacy review, pseudonymization/key custody, collection authority/consent,
    retention/deletion, and permitted research uses.
11. Container/file hashes, exporter build identity, configuration, completeness
    markers, and product-derived algorithm versions/configuration.
12. Minimum/typical/maximum file sizes, rates, durations, and record counts.
13. Truncation, interrupted writes, invalid hashes, duplicates, unexpected
    fields, encodings, compression failure, and completion detection.
14. One small conformance fixture with expected normalized records and explicit
    unavailable capabilities, containing no racing conclusion.

## Adapter acceptance checks

- Hash and parse the same immutable snapshot bytes.
- Validate path, privacy, protocol, version, unit, clock, boundary, and identity
  declarations before producing a final artifact.
- Convert only declared channels and retain source provenance/unknown channels.
- Enforce parent, order, finite-value, gap/reset/distance, and interpolation
  rules without silent repair.
- Reproduce identical normalized bytes and fingerprints across independent
  directories and supported platforms.
- Keep real/private inputs outside Git and review expected storage requirements.

## Campaign gate

Formal controlled collection remains blocked until the live variable inventory,
30-minute overhead/storage rehearsal, privacy key custody, and campaign protocol—including
conditions, privacy handling, frozen schedule, comparability, exclusions, sample
design, success/falsification rules, and safe collection procedure—are reviewed.
Passing the deterministic M54R checks confirms adapter mechanics, not that the first campaign
is scientifically ready. The customer bundle may be ingested as an explicitly
observational session; that does not satisfy the controlled-campaign gate.
