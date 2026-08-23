# Collection-record sidecar

`apex-labs.collection-record/v1` supplies research and privacy context that the
customer bundle does not contain. It accompanies an external bundle without
modifying the ZIP. The exact source-bundle SHA-256 binds the two artifacts.

Required metadata includes a dataset identity; pseudonymous participant ID and
optional external identity-map reference; collection authority; privacy and
retention declarations; confirmed simulator/car/track/layout identity; session
condition; coaching state; deviations and operator notes; and source hash. A
real record must declare pseudonymization and no direct identifiers. The
identity map remains external and must never contain the real identity in this
repository.

An `observational` record must have no frozen-protocol claim, experimental
blocks, conditions, or lap assignments. This is the correct classification for
a session collected without a preregistered assignment. An `experimental`
record must bind the exact protocol freeze and schedule hashes, schedule
assignment, declared blocks/conditions, and unique lap-to-block assignments.
Assignments must resolve to both a declared block and a lap in the bundle.

The sidecar does not itself prove consent, correct operator entry, or protocol
adherence. It makes those claims explicit and integrity-bound so they can be
reviewed. Formal controlled collection still requires independent review of the
frozen campaign protocol and generated schedule.

## Sessions collected before a protocol existed

An observational collection record describes a session with no preregistered assignment, and it
is correct for exactly that. On its own it does not admit a real session to normalization: real
ingestion still requires a reviewed protocol freeze. A session that was driven before any freeze
existed is admitted instead by a separate `apex-labs.exploratory-intake/v1` artifact, which binds
this record by identity and SHA-256 and permanently limits the resulting dataset to descriptive
analysis and hypothesis generation. See `docs/apex-research-recorder-adapter.md`. Editing this
record after the intake was reviewed invalidates the intake, which is the intended behaviour.
