# Future Apex Sim Coach Research export handoff

`apex-research-session-export/1.0.0` is the implementation-neutral base contract.
The JSON Schema and a synthetic contract example live under `contracts/`. The
stricter additive `apex-labs-research-recorder-profile/1.0.0` describes the Apex
Sim Coach M54R recorder inventory and CSV/completion semantics. Apex Labs does
not implement product capture, and the production repository is outside this
project.

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

The original v1 runtime validator accidentally omitted prose-required `traffic`
from its exact 19-channel set. Compatibility is preserved: the base v1 validator
continues to accept those historical 19-channel manifests and now accepts an
optional explicit `traffic` declaration. The recorder profile requires the exact
20-channel set, including `traffic`; unknown extras still fail. No previously
valid v1 bundle changes meaning, so no v2 contract is required.

For the recorder profile, `collection.configuration_setup_hash` is SHA-256 of
the exact inventoried `configuration-setup.json` bytes. That file distinguishes
an unavailable simulator setup from the known recorder configuration; the hash
does not imply that setup itself was available.

The generic base schema permits false coaching capability declarations. The
recorder profile is deliberately stricter: authorization/delivery evidence and
experimental condition markers must be declared, and the event stream must
contain either a coached evidence summary or an explicit coaching-disabled
control. Authorization never implies delivery.

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

The Labs `apex-research` command independently verifies `COMPLETE`, manifest and
file hashes, portable paths, unavailable/null semantics, evidence markers, and
collection-record identity before streaming CSV into normalized records. This
still does not prove that capture is low-overhead, private, complete, or
scientifically suitable in a real session.
