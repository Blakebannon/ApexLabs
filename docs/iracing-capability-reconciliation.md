# iRacing capability reconciliation

Reconciliation of the strict Research Recorder profile
(`apex-labs-research-recorder-profile/1.0.0`) against a sanitized live iRacing
variable inventory.

**Evidence**: `research/capability/iracing-variable-inventory.2026-08-21.json`,
331 variables, SHA-256 `81c5c88d46c112968e9de463c58c2a0820e62592bf43dde285f3f34b81c61f2f`,
`values_sampled: false`, `direct_identifiers_included: false`.

This document describes **capability only**. No telemetry values were sampled,
so nothing here is a finding about driving.

## Contract discipline

The recorder profile is **not** version-bumped by this pass. The export contract
already carries per-channel `availability`, `provenance`, `unit`,
`axis_and_sign`, and `missing_value`, and `recorder-metadata.json` accepts
additional declarations. Every promotion below fits those existing semantics, so
`apex-labs-research-recorder-profile/1.0.0` is retained.

Two things did change on the Labs side, both scoped to the research adapter:

- `apex-research-recorder` adapter version `1.0.0` to `1.1.0`, because the
  corrected source-channel attribution changes normalized record content.
- The tyre-pressure derivation string now states cold-garage semantics
  explicitly.

`NORMALIZATION_VERSION` is deliberately unchanged. Nothing in this pass alters
how any other adapter normalizes, and bumping it would have left five committed
synthetic artifacts silently claiming a version the code no longer produces.

## Channel reconciliation

| Channel | New classification | Supporting iRacing variables |
| --- | --- | --- |
| `timestamp` | directly available | `SessionTime` |
| `brake` | directly available | `Brake` |
| `throttle` | directly available | `Throttle` |
| `steering_angle` | directly available | `SteeringWheelAngle` |
| `speed` | directly available | `Speed` |
| `gear` | directly available | `Gear` |
| `rpm` | directly available | `RPM` |
| `longitudinal_acceleration` | directly available | **`LongAccel`** |
| `lateral_acceleration` | directly available | `LatAccel` |
| `yaw_rate` | directly available | `YawRate` |
| `wheel_state` | **unavailable** | none exist |
| `tire_state` | partial / semantically limited | carcass temps, wear, cold pressure, odometer, compound |
| `fuel` | directly available | `FuelLevel`, `FuelLevelPct` |
| `setup` | partial / semantically limited | cold pressures, `dcBrakeBias`, `dcABS`, `dcTractionControl`, `PitSv*` |
| `assists` | available — car dependent | `dcABS`, `dcTractionControl`, `BrakeABSactive`, `dcPitSpeedLimiterToggle`, `SteeringFFBEnabled` |
| `damage` | **unavailable** | none exist |
| `flags` | partial / semantically limited | `SessionFlags`, `SessionState`, `PaceMode`, `PitsOpen` |
| `weather` | directly available | `AirTemp`, `AirPressure`, `AirDensity`, `RelativeHumidity`, `Precipitation`, `FogLevel`, `WindVel`, `WindDir`, `Skies`, `WeatherDeclaredWet` |
| `traffic` | partial / semantically limited | `CarDistAhead`, `CarDistBehind`, `CarLeftRight` |
| `track_conditions` | partial / semantically limited | `TrackTempCrew`, `TrackWetness`, `PlayerTrackSurface`, `PlayerTrackSurfaceMaterial` |

The machine-readable form, with per-channel semantics, limitations, privacy
restrictions, and rehearsal/campaign requirements, is
`research/capability/iracing-capability-map.json`.

## Semantics the reconciliation refuses to blur

**A setting is not an intervention.** `dcABS` is the driver-adjustable in-car ABS
adjustment. `BrakeABSactive` is true while ABS is actually reducing brake force.
They answer different questions. Absence of `dcABS` activity is never proof that
a car has no ABS.

**Cold pressure is not live pressure.** `LFcoldPressure` and its siblings are
explicitly "as set in the garage". The inventory contains **no hot or running
tyre pressure variable at all**, so live inflation pressure is genuinely
unavailable and must never be inferred from the cold value.

**Suspension is not wheel state.** Shock deflection, shock velocity, brake-line
pressure, and tyre odometer are corner-located chassis and tyre measurements.
There is no per-wheel rotational speed or slip-ratio variable anywhere in the
331. `wheel_state` stays unavailable; suspension is retained as auxiliary
evidence under its own name.

**Repair timers are not a damage model.** `PitRepairLeft`, `PitOptRepairLeft`,
`FastRepairAvailable`, `FastRepairUsed`, and `PlayerCarTowTime` say that repair
time or a tow was required. They say nothing about what is damaged or how badly.
`damage` stays unavailable; repair evidence is retained separately for exclusion.

**Partial configuration is not a garage setup.** Brake bias, assist settings, and
cold pressures are meaningful configuration signals, but no suspension geometry,
spring, damper, aerodynamic, differential, or gearing variable exists. Full setup
remains unavailable and partial configuration belongs in
`configuration-setup.json`.

**Track location is not weather, and neither is a condition score.**
`TrackTempCrew` is temperature *measured by the crew around the track*, not the
surface temperature at an arbitrary point. `TrackWetness` is the *average*
surface wetness and cannot represent a locally wet corner or a drying line.
`PlayerTrackSurface` and `PlayerTrackSurfaceMaterial` describe where the car is
and what it is on. These stay distinct.

**Weather is a start/finish-line point measurement.** Every atmospheric variable
is explicitly measured at the start/finish line. It is not a track-wide field and
must not be presented as the condition at a specific corner.

**`TrackTemp` is deprecated.** The inventory documents it as deprecated and set
to `TrackTempCrew`. Labs reads `TrackTempCrew`.

## Enumerations are named but not decoded

The inventory proves `SessionFlags` is an `irsdk_Flags` bitfield and that
`SessionState`, `PaceMode`, `TrackWetness`, `PlayerTrackSurface`,
`PlayerTrackSurfaceMaterial`, and `CarLeftRight` are `irsdk_*` enumerations. It
carries **no value dictionary** for any of them.

Labs therefore cannot decode green, yellow, checkered, pacing, wetness level, or
alongside state from this evidence alone, and will not guess. Raw values are
preserved verbatim; the recorder, which links the real SDK, must export the
authoritative dictionary in `recorder-metadata.json` alongside them.

## Traffic: the privacy-minimal representation

The initial corpus captures exactly three scalars: `CarDistAhead`,
`CarDistBehind`, and `CarLeftRight`. Together they distinguish clear air, a close
car ahead, a close car behind, and an alongside or overlapping car, which is what
separates a compromised lap from a clean one.

The 27 `CarIdx*` arrays covering up to 72 cars are **excluded**: unnecessary
volume, opponent-provenance complexity, analytical complexity, and no
first-campaign question that requires them. Opponent identity, the
`RadioTransmit*` participant variables, and session identifiers that could
resolve to public results are never captured. A protocol that genuinely needs
richer opponent context later is a separately reviewed expansion.

## 360 Hz sub-sample channels: deferred

Eighteen `_ST` channels exist, each a six-element `Float` array described as "at
360 Hz". Six samples per 60 Hz update is arithmetically consistent, and
`LongAccel_ST`, `LatAccel_ST`, and `YawRate_ST` would genuinely sharpen braking,
turn-in, and rotation analysis.

**Recommendation: defer until timing semantics are proven.**

What the metadata does **not** establish:

- element ordering — whether index 0 is the oldest or newest sub-sample;
- per-sub-sample timestamps — no offsets are carried, and inventing evenly
  spaced ones would be fabricated provenance;
- the relationship to the update tick — whether the six precede, straddle, or
  follow it;
- behaviour across dropped, repeated, or stale ticks;
- behaviour across session transitions, resets, and reconnects.

A sub-sample whose position in time is unproven cannot carry temporal meaning.
Capturing these with fabricated timing would produce a corpus that looks
higher-resolution while being unusable for exactly the transient analysis that
motivates it. Labs also has no sub-sample nesting in its normalized record model
today, so support would need new record structure rather than new columns.

Resolve by reading the authoritative SDK header for the sub-sample array
contract, confirming ordering against live values once the corrected recorder
runs, and only then choosing between an optional secondary evidence stream and
main-contract capture. The first campaign proceeds at 60 Hz.

## Confounds now measurable

Newly measurable: weather, track wetness, track temperature, traffic, tyre
compound, tyre wear, tyre age and distance, assists (setting and intervention
separately), and weight penalty. Improved: tyre temperature (across-tread rather
than middle only), pit state, session and flag state, track-surface location.

Still not measurable: live tyre pressure, vehicle damage state, and full garage
setup. Each is genuinely absent from the simulator's variable table, not merely
uncaptured.

A measurable confound does not become a primary metric. Most of these will be
reported and used for exclusion, not analysed.

## Sequencing constraint

The recorder's sample-column list and the Labs sample header are matched
**exactly** on both sides. Any new sample column must land in the product
recorder and in Labs together. A one-sided change makes every bundle fail its
header check, so Labs deliberately does **not** add columns ahead of the product.
