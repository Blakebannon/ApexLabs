# Future Apex Sim Coach Research export handoff

`apex-research-session-export/1.0.0` is an implementation-neutral target
contract for a future Research build. The JSON Schema and a synthetic contract
example live under `contracts/`. Apex Labs does not implement production
capture, and the production repository is outside this project.

The future bundle must preserve or explicitly declare unavailable:

- stable anonymized session and participant-pseudonym identities, exact
  simulator/build, car, track, and layout identities;
- UTC session/lap timing and original or near-original timestamped samples;
- source clock, nominal/actual frequency, resolution, origin, ordering, reset,
  reconnect, pause, and rollover behavior;
- lap elapsed time and distance; brake, throttle, steering, speed, gear, RPM;
- longitudinal/lateral acceleration, yaw, wheels, tires, fuel, setup, assists,
  damage, flags, weather, traffic, and track conditions when the simulator makes
  them available;
- per-channel measured/derived/estimated/unavailable provenance, units,
  reference frames, axes/signs, missing values, quantization, sampling rates,
  and derivation algorithm identity;
- gaps, dropped/duplicated frames, buffering, recorder backpressure, incomplete
  writes, corruption/truncation detection, and a definitive completion marker;
- incidents, pit transitions, lap validity reasons, session state, replay/reset,
  and other boundary events;
- coaching cue authorization and delivery receipts, plus a coaching-disabled
  research mode;
- experimental block/condition markers and exact collection-protocol/schedule
  identity;
- configuration/setup hash, privacy classification, deterministic file
  inventory/hashes, configured storage location, and retention metadata.

The contract never assumes iRacing or another simulator supplies every channel.
Unavailable channels must be explicit; absence cannot be represented as zero.

## Production/Research build boundary

The production handoff requires one shared Apex Sim Coach codebase with an
isolated research-capture module and an explicit Research build capability.
Production builds must compile the capture module out or otherwise prove it
absent. Production must expose no public research UI and create no
high-resolution research files/directories.

Research capture must be explicitly activated with visible recording state,
record locally only, stream bounded chunks to disk, preflight disk capacity,
stop safely on low disk, support a configurable external output location, and
never upload automatically. The ordinary customer Session Analysis Bundle
remains a separate, supported product export.

Implementing this handoff requires production engineering and security/privacy
review. Schema conformance alone is not proof that capture is low-overhead,
private, complete, or scientifically suitable.
