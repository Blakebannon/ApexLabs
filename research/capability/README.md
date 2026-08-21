# Simulator capability evidence

This directory holds **point-in-time simulator capability snapshots** and the
capability map Apex Labs derives from them.

## What is here

| File | Role |
| --- | --- |
| `iracing-variable-inventory.2026-08-21.json` | Sanitized live iRacing variable table, 331 variables, acquired 2026-08-21 |
| `iracing-capability-map.json` | Generated reconciliation of that snapshot against the Research Recorder profile |

## What a snapshot is, and is not

A snapshot records **variable name, SDK type, array count, unit token, and
description**. It contains no telemetry values and no participant identifiers,
and it is captured with `values_sampled: false` and
`direct_identifiers_included: false`. Apex Labs refuses an inventory that
declares otherwise rather than filtering it, because filtering would hide the
breach.

A snapshot proves **capability**, not behaviour:

- It proves what one iRacing build exposed in one session. It is **not eternal
  iRacing truth**. A simulator update can add, remove, or redefine variables,
  which is why the snapshot is dated and hash-bound rather than treated as a
  standing fact.
- It supports **no scientific finding whatsoever**. No driving values were
  sampled, so nothing here can say anything about weather affecting a driver,
  tyre wear affecting a lap, ABS affecting braking, or traffic costing time.
- It names `irsdk_*` enumerations but **does not carry their value
  dictionaries**. Labs therefore cannot decode a flag bitfield, a session state,
  a wetness level, or an alongside indicator from a snapshot alone. The recorder
  links the real SDK and must export the authoritative dictionary alongside raw
  values.

## Why the raw inventory is committed

It is 39 KB of metadata with no values and no identifiers, and the capability
map's every claim is checked against these exact bytes. Storing only a hash
would make the map unreproducible: a reviewer could confirm the hash matched
some file they did not have, but could not re-derive the reconciliation. The
snapshot is small enough, and sensitive enough to nothing, that reproducibility
wins.

Superseding evidence is added as a **new dated snapshot**, never by editing an
existing one. An old snapshot stays as the record of what was known when a
decision was made.

## Regenerating the capability map

```powershell
apex-labs capability inspect   research/capability/iracing-variable-inventory.2026-08-21.json
apex-labs capability map       research/capability/iracing-variable-inventory.2026-08-21.json
apex-labs capability readiness research/capability/iracing-variable-inventory.2026-08-21.json
```

`iracing-capability-map.json` is generated, canonical JSON. A test regenerates it
from the committed snapshot and compares bytes, so it cannot silently drift from
the evidence it claims to summarize.

Every variable named in the map is re-checked against the snapshot's name, SDK
type, array count, and unit. A claim the evidence does not support is a hard
refusal, not a warning. That guard is what caught Labs and the product recorder
both naming `LonAccel`, a variable iRacing does not expose; the real one is
`LongAccel`.
