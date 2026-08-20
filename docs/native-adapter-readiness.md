# Native Apex telemetry adapter readiness

Native Apex Sim Coach compatibility is unverified. Generic CSV ingestion does not establish it. Do not implement or claim a native adapter until a reviewed sample and specification are deliberately supplied to Apex Labs.

## Required input package

1. A tiny sanitized or synthetic, versioned sample export produced by the actual export path, plus its SHA-256 hash and expected parsed record counts.
2. The export contract/version and compatibility policy, including how unsupported older/newer versions must fail.
3. Every channel name, type, semantic definition, availability rule, source unit, canonical-unit conversion, coordinate frame, sign convention, valid range if structural, and provenance (`measured`, production-derived with algorithm identity, estimated, or unavailable).
4. Sampling behavior: nominal and variable rates, per-channel rates, ordering, buffering, dropped/duplicated samples, resampling, interpolation, quantization, and clock resolution.
5. Clock behavior: timestamp type/source/origin/epoch, monotonicity, precision, rollover, pause/reset/reconnect/session-reset behavior, and relationship among simulator, session, lap, wall, and export clocks.
6. Missing-value conventions: absent columns, null/blank/sentinel/NaN behavior, zero semantics, disabled channels, and partial-record behavior.
7. Session, stint, lap, sector, corner/segment, pit, reset, replay, reconnect, and file-rotation boundaries, including identifiers and invalidation reasons.
8. Simulator, simulator/build, car/model/class/setup, track/layout/configuration, driver pseudonym, session, and export identifiers; state which are stable, local, or personally identifying.
9. Incident, off-track, traffic, flag, aid, damage, fuel, tire, environment, calibration, hardware, and setup context where available, including change events.
10. Privacy classification and field-level review: direct identifiers, pseudonymization method and key custody, collection authority/consent, retention/deletion policy, and permitted research uses.
11. Provenance: original file/container hashes, exporter version/commit/build identity, configuration, source file ordering, completeness markers, and production-derived algorithm versions/configuration.
12. Expected minimum/typical/maximum files, record counts, duration, and byte sizes so streaming, limits, and repository boundaries can be tested without committing real telemetry.
13. Corruption behavior: truncation, incomplete final writes, invalid checksums, duplicate blocks, unexpected fields, unsupported encodings, compression/container failure, and how a complete export is distinguished from an interrupted one.
14. At least one expected-output conformance fixture showing normalized sessions/laps/samples and deliberately unavailable capabilities, with no racing conclusion.

## Adapter acceptance checks

- Hash and parse the same immutable snapshot bytes; reject source changes and truncation.
- Validate all path, privacy, protocol-link, version, unit, clock, boundary, and identifier declarations before emitting a final artifact.
- Convert only declared channels to canonical concepts/units/conventions; retain unknown source channels in provenance.
- Enforce parent/order/finite-value rules and apply documented timestamp, gap, reset, lap-distance, and interpolation policies without silent repair.
- Produce identical normalized bytes/fingerprints in independent directories for identical source bytes, configuration, code/schema content, and platform semantics.
- Add Linux and Windows conformance cases if the export is expected to move between them.
- Review expected file sizes against local storage and guard limits; raw/private files remain outside Git.

## Campaign gate

Real collection remains blocked until both the native export contract/sample and the campaign protocol—including conditions, privacy handling, frozen schedule, comparability, exclusions, sample design, success/falsification rules, and safe collection procedure—are reviewed. Passing this checklist confirms adapter mechanics, not that the first real campaign is scientifically ready.
