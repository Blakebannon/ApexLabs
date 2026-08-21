# Segment definitions

A segment is a geometric region on a specific layout, not a label. Each
`apex-labs.segment-definition/v1` document declares the simulator, track, and
layout combinations it covers, a geometry fingerprint and geometry source for
each, the along-lap region with explicit boundary inclusivity and wraparound
behaviour, an optional reproducible phase, and the channel and unit coverage a
comparable unit must meet.

Corner ordinals are never invented. Only a segment whose identity source is a
verified catalog or verified corner identity may claim a corner reference, and it
must bind that catalog and its hash. A protocol distance or lap-fraction range
records that limitation instead.

Evidence spanning two different geometry fingerprints is refused, even when both
regions share a name such as "Turn 4" and the protocol explicitly permitted
layout to vary. See [docs/comparable-evidence.md](../../docs/comparable-evidence.md).

The definitions here are fabricated demonstration geometry. There is no real
track behind any of them.
