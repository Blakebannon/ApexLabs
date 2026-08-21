# Synthetic Research Recorder conformance fixture

`bundle/` holds a complete `apex-research-session-export/1.0.0` bundle produced by the actual
**Apex Sim Coach Research Recorder** (`ApexTrackCoach.ResearchRecorder synthetic`), not by a
Labs re-implementation of it. That is the point: these bytes are what the product emits, so a
one-sided sample-column, metadata or file-inventory change fails a Labs test rather than a live
rehearsal.

## Classification

**Synthetic and demo-only.** Every value is fabricated. The participant pseudonym is explicitly
`synthetic-participant`, the privacy classification is `synthetic`, timestamps are fixed, and
there is no real driver, session, car, track or simulator data of any kind. It is scientifically
inconclusive by construction and must never support a racing or coaching conclusion.

The recorder writes it deterministically, so regenerating it byte-for-byte requires only the
same product revision and the same `--source-revision` argument.

## What it exercises

Two samples, deliberately different:

- **Row 0** leaves every optional channel empty, proving a missing value stays `unavailable`
  and is never silently converted to zero.
- **Row 1** populates the synchronized shape, including a genuine measured zero for brake and
  for precipitation, which must survive normalization as zero rather than as missing.

It carries the corrected `LongAccel` mapping, the expanded tire state, weather, track
conditions, flags, privacy-minimal traffic, car-dependent assists, partial configuration, and
the enum-dictionary declarations. No `CarIdx*` opponent array, no `RadioTransmit*` participant
variable, and no 360 Hz `_ST` channel appears anywhere in it.

`collection-record.json` is the Labs-side operator artifact binding this exact bundle manifest.
