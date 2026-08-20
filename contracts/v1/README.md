# Version 1 JSON contracts

These Draft 2020-12 JSON Schemas describe the portable structure of Apex Labs v1 artifacts. They are intended for editors, CI conformance checks, and external consumers. The dependency-free Python runtime validators are authoritative. They additionally enforce semantic and cross-file rules that JSON Schema cannot establish, including safe local paths, self-hashes, frozen-protocol linkage, record relationships, and review gates.

Conformance tests run representative valid and invalid artifacts through both paths. Passing a published schema is necessary but not sufficient: callers must also use the runtime validator and any applicable cross-file verifier. Schema validity establishes structure, not reproducibility, adequate evidence, scientific validity, authorship, or product approval.

Contract IDs are stable within v1. A breaking semantic or structural change requires v2. Adding an adapter version, metric version, protocol version, or finding version does not itself change a contract major version.
