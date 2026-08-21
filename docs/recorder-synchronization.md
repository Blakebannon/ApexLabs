# Research Recorder synchronization

The coordinated checkpoint that brought the Apex Sim Coach Research Recorder and Apex Labs to
the same sample shape, ahead of the first 30-minute rehearsal.

The sequence was deliberately tightened: rather than fixing only the rehearsal blocker and
expanding capture afterwards, the whole campaign shape landed first, so the rehearsal exercises
exactly the recorder we intend to freeze for the ~10-hour campaign and does not need repeating.

**The recorder profile version is unchanged**: `apex-labs-research-recorder-profile/1.0.0`.
Nothing here needed an incompatible contract change.

## Three defects, all of which would have broken the rehearsal

### 1. `LonAccel` does not exist; the variable is `LongAccel`

Found by the capability reconciliation. `GetFloat` returns `null` without incrementing the read
error count when a name is absent from the SDK variable table, so the lookup failed **silently**:
`read_error_count` stayed 0 and the required `longitudinal_acceleration` channel was declared
`unavailable` in every recording, indistinguishable from an honest capability limit.

Braking is the campaign's primary controlled block, so a rehearsal without deceleration evidence
would have proved the wrong thing.

### 2. Timestamps the consumer could not parse

Pre-existing, dating from the original recorder commit and independent of any change here. The
recorder writes .NET round-trip timestamps with 100-nanosecond precision — seven fractional
digits, which is valid ISO 8601. Python's `datetime.fromisoformat` accepts at most six, so Labs
rejected **every** recorder bundle at the very first manifest field.

Fixed on the Labs side, which is where the limitation actually was: excess fractional digits are
truncated for parsing only. The declared text is never rewritten, so an artifact keeps the
recorder's exact bytes.

### 3. Text concepts carrying integers

Also pre-existing, and latent only because no fixture had ever populated the fields. `session_state`
and `incident_state` are text concepts, but the adapter emitted integers, which normalized-record
validation rejects. Every real session has a non-null session state, so **every real ingest would
have failed**.

Both now carry the raw simulator value as its decimal string, with a quality flag recording that
the enumeration has not been decoded.

## Sample shape

`samples.csv` went from 32 to 82 columns. `ResearchContract.SampleColumns` and the Labs
`SAMPLE_HEADERS` are matched by exact equality, and neither list is recorded in the pinned
profile, so they must change together or every bundle fails its header check.

Added: across-tread tyre carcass temperature and tread wear, tyre odometer and compound;
start/finish-line weather; crew-measured track temperature, wetness and surface material; session
flag, state and pacing; privacy-minimal traffic proximity; assist settings and ABS intervention;
and driver-adjustable brake bias.

Renamed for honesty: `tire_temp_lf_c` became `tire_temp_lf_middle_c` now that all three tread
positions are captured, and `tire_pressure_lf_kpa` became `tire_cold_pressure_lf_kpa` because the
value is garage-set cold pressure and iRacing exposes no hot or running pressure at all.

At 60 Hz this writes about 21.9 KiB/s, roughly 77 MiB per hour: near 38 MiB for the rehearsal and
about 0.75 GiB across the whole campaign, comfortably inside the unchanged 2 GiB preflight and
1 GiB low-disk floor.

## What Labs normalizes, and what it deliberately does not

Four concepts became fillable without inventing anything, because each already existed in the
normalized vocabulary and now has an honest source:

| Concept | Source | Provenance |
| --- | --- | --- |
| `air_temperature` | `AirTemp` | measured |
| `track_temperature` | `TrackTempCrew` | measured |
| `abs_active` | `BrakeABSactive` | measured |
| `off_track_state` | `PlayerTrackSurface` via the declared `irsdk_TrkLoc` dictionary | derived |

Everything else — traffic distances, flag and pacing state, tyre wear and odometer, assist
settings, brake bias, the remaining weather fields — is validated, carried, and declared in the
normalized manifest's `unknown_source_channels`. It is **retained, not promoted**. Promoting it
needs new normalized concepts, which is a deliberate concept and normalization-version review,
not a side effect of capturing more columns.

Two concepts that might look fillable are deliberately left unavailable:

- **`traction_control_active`** — `dcTractionControl` is a driver *setting*. iRacing exposes no
  traction-control *intervention* variable, and mapping a setting to an `_active` concept is
  exactly the conflation the reconciliation forbids.
- **`track_wetness`** — the normalized concept is a ratio; `TrackWetness` is an undecodable
  `irsdk_TrackWetness` enumeration. Coercing an enum into a ratio would fabricate a scale.

`NORMALIZATION_VERSION` is unchanged for the same reason: the concept set did not change. The
`apex-research-recorder` adapter moved `1.1.0` → `1.2.0`, which is the correctly scoped knob,
since it is recorded in every normalized record's provenance.

## Enumerations: identity always, meaning only when it exists

`recorder-metadata.json` now declares `enum_dictionaries` for every enumerated sample column,
each carrying the enumeration identity, its kind, its dictionary provenance, and
`unknown_value_behavior: preserve_raw_value`.

The honest outcome is that **only one of seven enumerations has a real dictionary**. Apex Sim
Coach does not vendor the iRacing SDK enum definitions; its shared-memory layer is hand-rolled.

- `track_surface` (`irsdk_TrkLoc`) — `product_declared`. This is Apex Sim Coach's own
  interpretation, already load-bearing in production lap and corner analysis.
- `skies_index` — `sdk_variable_description`, taken from the SDK's own description text.
- `irsdk_Flags`, `irsdk_SessionState`, `irsdk_PaceMode`, `irsdk_TrackWetness`, `irsdk_TrkSurf`,
  `irsdk_CarLeftRight` — **`unavailable`**. Raw values are preserved verbatim and carry no
  declared meaning.

So green, yellow, checkered, pacing and wetness state still cannot be decoded. Nothing is lost —
the raw values are captured — but decoding waits on vendoring the authoritative definitions,
which is a separate reviewed decision. Labs refuses a dictionary that claims provenance without
a value table, names an unknown column, or declares any unknown-value behaviour other than
preserving the raw value.

## Deliberately not done

- **360 Hz `_ST` channels** stay deferred. The metadata proves no element ordering, no
  per-element timestamp, no relationship to the SDK tick, and no dropped-tick behaviour. The
  decision is recorded in the bundle under `deferred_capabilities`, and a test asserts no `_ST`
  column reached the sample shape.
- **`CarIdx*` opponent arrays and `RadioTransmit*`** are never captured.
- **Raw driver inputs** (`BrakeRaw`, `ThrottleRaw`, `ClutchRaw`) do not replace the processed
  `Brake` and `Throttle` channels.
- **`wheel_state` and `damage`** stay unavailable, now on evidence rather than pending an
  inventory. Their reason strings were updated to say so.

## Cross-repository proof

`tests/fixtures/research_recorder_v1` holds a bundle emitted by the **real** recorder, not a Labs
re-implementation. It is wholly synthetic and deterministic. The conformance tests drive those
exact bytes through Labs validation, collection binding and ingestion, and cover a one-sided
column change, a declared-unavailable channel carrying a value, a truncated payload, a
mis-bound collection record, an unknown enumeration value, and a missing optional value that
must stay unavailable rather than becoming zero.

## What only a live session can settle

The inventory proves capability, not runtime behaviour. The rehearsal is the first chance to
confirm the steering sign convention and range; that `Brake` and `Throttle` really are 0-to-1
fractions despite the SDK's percent unit token; clear-air behaviour of `CarDistAhead` and
`CarDistBehind` and the observed value set of `CarLeftRight`; stable weather and track values
with correct nullable behaviour; and plausible, car-dependent tyre temperature, wear and
odometer values.

None of these may be inferred from metadata, and none is a scientific finding.
