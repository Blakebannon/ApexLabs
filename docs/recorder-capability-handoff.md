# Apex Sim Coach Research Recorder — capability handoff

`RECORDER UPDATE REQUIRED — PRODUCT REVIEW`

A review artifact for a separate, owner-reviewed product checkpoint. Apex Labs
never opens, patches, configures, or deploys the Apex Sim Coach repository, and
no change below was made from Labs.

Evidence: `research/capability/iracing-variable-inventory.2026-08-21.json`,
331 variables, SHA-256 `81c5c88d46c112968e9de463c58c2a0820e62592bf43dde285f3f34b81c61f2f`.
Full reconciliation: [iracing-capability-reconciliation.md](iracing-capability-reconciliation.md).

---

## 1. Blocking defect — required before the 30-minute rehearsal

### `LonAccel` does not exist. The variable is `LongAccel`.

The live inventory contains `LongAccel` (`Float`, count 1, `m/s^2`,
"Longitudinal acceleration (including gravity)"). It contains **no** variable
named `LonAccel`.

Two product sites name the nonexistent variable:

| Site | Current | Required |
| --- | --- | --- |
| `src/ApexTrackCoach.IRacing/IRacingFrameReader.cs` | `LonAccel = GetFloat(data, "LonAccel", ref errors)` | read `"LongAccel"` |
| `src/ApexTrackCoach.Research/ResearchContract.cs` | `Has("LonAccel") ? Available("longitudinal_acceleration", …, "LonAccel") : Unavailable(…)` | gate and attribute on `"LongAccel"` |

**Why this is blocking.** `GetFloat` returns `null` without incrementing the
error count when a name is absent from `TelemetryDataProperties`. So the lookup
fails silently: `read_error_count` stays 0, `Has("LonAccel")` is false, and every
recording declares the **required** profile channel
`longitudinal_acceleration` as `unavailable` with the reason "LonAccel was
absent." The failure is invisible in the bundle — it looks like an honest
capability limit rather than a typo.

Braking and brake-release are the campaign's primary controlled blocks.
Deceleration evidence is not substitutable, and a 30-minute rehearsal that
silently records no longitudinal acceleration proves the wrong thing.

**Note the same silent-null behaviour affects `LFrideHeight`, `RFrideHeight`,
`LRrideHeight`, and `RRrideHeight`**, which are also absent from the inventory.
They are read into `RawTelemetryFrame` but are not part of the research sample
columns, so they are harmless today — but they are dead reads that will always
be null, and they should either be removed or corrected.

**Recommended hardening.** A name absent from the variable table is a
configuration error, not a missing value. Consider distinguishing "variable not
in table" from "variable present but unreadable" so a typo surfaces loudly.

---

## 2. Capture additions — required before the ~10-hour campaign, not the rehearsal

None of these block the rehearsal. Each is currently declared `unavailable`
honestly, which Labs accepts; they are required before the campaign because each
closes a real confound.

| Channel | iRacing variables | Type / count / unit | Representation | Privacy |
| --- | --- | --- | --- | --- |
| `weather` | `AirTemp`, `AirPressure`, `AirDensity`, `RelativeHumidity`, `Precipitation`, `FogLevel`, `WindVel`, `WindDir` | `Float` ×1 — `C`, `Pa`, `kg/m^3`, `%`, `%`, `%`, `m/s`, `rad` | measured scalars | none |
| `weather` | `Skies` | `Int` ×1 | category index (0 clear, 1 partly cloudy, 2 mostly cloudy, 3 overcast — from the SDK description) | none |
| `weather` | `WeatherDeclaredWet` | `Bool` ×1 | stewarding decision, not a measurement | none |
| `track_conditions` | `TrackTempCrew` | `Float` ×1 `C` | crew-measured track temperature — **not** per-point | none |
| `track_conditions` | `TrackWetness` | `Int` ×1 `irsdk_TrackWetness` | **average** surface wetness; needs enum dictionary | none |
| `track_conditions` | `PlayerTrackSurface`, `PlayerTrackSurfaceMaterial` | `Int` ×1 `irsdk_TrkLoc` / `irsdk_TrkSurf` | player-car location and surface material; needs enum dictionaries | player only |
| `flags` | `SessionFlags` | `BitField` ×1 `irsdk_Flags` | raw bitfield **plus dictionary** | player session only |
| `flags` | `SessionState`, `PaceMode` | `Int` ×1 `irsdk_SessionState` / `irsdk_PaceMode` | raw enum **plus dictionary** | none |
| `flags` | `PitsOpen` | `Bool` ×1 | documented as current-player scope | none |
| `traffic` | `CarDistAhead`, `CarDistBehind` | `Float` ×1 `m` | nearest-car distance only | no opponent identity |
| `traffic` | `CarLeftRight` | `Int` ×1 `irsdk_CarLeftRight` | alongside indicator; needs enum dictionary | no opponent identity |
| `assists` | `dcABS`, `dcTractionControl` | `Float` ×1 | driver-adjustable **settings** | none |
| `assists` | `BrakeABSactive` | `Bool` ×1 | actual ABS **intervention** | none |
| `assists` | `dcPitSpeedLimiterToggle`, `SteeringFFBEnabled` | `Bool` ×1 | limiter state; FFB is rig context, not vehicle | rig config |
| `tire_state` | `LFtempCL/CM/CR` and RF/LR/RR | `Float` ×1 `C` | across-tread carcass temperature (currently CM only) | none |
| `tire_state` | `LFwearL/M/R` and RF/LR/RR | `Float` ×1 `%` | percent tread **remaining** | none |
| `tire_state` | `LFodometer` and RF/LR/RR | `Float` ×1 `m` | distance since the tyre was fitted | none |
| `tire_state` | `PlayerTireCompound`, `TireSetsUsed`, `TireSetsAvailable` | `Int` ×1 | compound index and set usage | none |
| `setup` | `dcBrakeBias` | `Float` ×1 | driver-adjustable brake bias | none |
| `setup` | `PitSvLFP`, `PitSvRFP`, `PitSvLRP`, `PitSvRRP`, `PitSvTireCompound` | `Float`/`Int` ×1 `kPa` | pending pit-service selections | none |

**Recommended additional session context** (auxiliary, not a profile channel):
`PlayerCarInPitStall`, `PitstopActive`, `PlayerCarWeightPenalty` (`Float`, `kg`),
`PlayerCarTowTime`, `PitRepairLeft`, `PitOptRepairLeft`, `FastRepairUsed`. These
define lap validity and exclusion boundaries; a weight penalty in particular is a
step change in vehicle mass that would otherwise read as an unexplained
performance shift.

---

## 3. Channels that stay unavailable, now on evidence rather than pending

| Channel | Keep as | Why |
| --- | --- | --- |
| `wheel_state` | `unavailable` | The inventory contains **no** per-wheel rotational speed, angular velocity, or slip-ratio variable. Shock deflection/velocity, brake-line pressure, and odometer are corner-located chassis and tyre evidence and must not be relabelled as wheel state. |
| `damage` | `unavailable` | No vehicle damage-state variable exists. `PitRepairLeft`, `PitOptRepairLeft`, `FastRepairAvailable`, `FastRepairUsed`, `PlayerCarTowTime` are repair and tow timers. They indicate that repair was required, not what is damaged. |
| `setup` (as a *full* setup) | partial only | No suspension geometry, spring, damper, aerodynamic, differential, or gearing variable exists. Keep the full-setup declaration unavailable and put partial configuration in `configuration-setup.json`. |

Please update the `Unavailable(...)` reason strings: "Pending live
variable-table evidence" is no longer accurate. The evidence now exists and it
shows these are genuinely absent.

---

## 4. Two contract-level requests

### 4a. Export the authoritative SDK enum dictionaries

Every enumerated and bitfield channel must be exported **with its authoritative
value dictionary** in `recorder-metadata.json`, alongside the raw value. Affected:
`irsdk_Flags`, `irsdk_SessionState`, `irsdk_PaceMode`, `irsdk_TrackWetness`,
`irsdk_TrkLoc`, `irsdk_TrkSurf`, `irsdk_CarLeftRight`.

The inventory names these enumerations but carries no value-to-meaning table. The
recorder links the real SDK and knows them; Labs does not and will not guess.
Without the dictionary Labs must preserve raw bitfields verbatim and cannot
decode green, yellow, checkered, pacing, or wetness state.

Labs validates `recorder-metadata.json` on named keys and does not forbid
additional ones, so this needs **no contract-version change**.

### 4b. Declare the sample-column list in `recorder-metadata.json`

The recorder's `ResearchContract.SampleColumns` and the Labs `SAMPLE_HEADERS`
are matched by exact equality. They must change together, and nothing in the
pinned profile records the column list, so a one-sided change fails every bundle
with an opaque header mismatch.

Declaring the column list explicitly in `recorder-metadata.json` would let Labs
report a precise, actionable mismatch instead.

---

## 5. Sequencing

1. **Fix `LongAccel` first.** It needs no new columns on either side — the
   `longitudinal_acceleration_mps2` column already exists and is already declared
   in the profile. It is a self-contained product-only correction.
2. **Then run the 30-minute rehearsal.** Confirm longitudinal acceleration is
   populated, and confirm the unproven declarations the metadata cannot settle:
   steering sign convention, the 0-to-1 range of `Brake` and `Throttle` (the SDK
   unit token reads `%` while descriptions define a 0-to-1 fraction), and the
   behaviour of `CarDistAhead`/`CarDistBehind` in clear air.
3. **Then add capture columns**, product and Labs together in one coordinated
   change, before the ~10-hour campaign.

## 6. Not requested

360 Hz `_ST` sub-sample capture is **deferred**, not requested. Element ordering,
per-sub-sample timestamps, and behaviour across dropped ticks are unproven by
metadata, and Labs will not implement timing semantics it cannot evidence. If the
authoritative SDK header settles the array contract, this becomes a separate
reviewed decision.

## 7. Privacy constraints that remain in force

Never capture opponent identity, the `RadioTransmit*` participant variables,
complete 72-car `CarIdx*` telemetry, session identifiers resolvable to public
results, or raw participant identity. The recorder's existing pseudonym and
privacy rules remain authoritative and unchanged by this pass.
