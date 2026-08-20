# Datasets

This directory is policy and manifest space, not a raw-data store.

Real telemetry belongs in an approved external or ignored local location. `raw/`, `private/`, `incoming/`, and `local/` are ignored, along with common large telemetry/database formats. Commit a manifest only after confirming that paths, labels, pseudonyms, metadata, and free text contain no sensitive information. A checksum is not anonymization.

Before ingesting real participant data, the manifest must declare participant classification, pseudonymized driver IDs, the pseudonymization method, absence of direct identifiers, consent or other collection authority, retention policy, and exact frozen protocol/condition/block/schedule. Pseudonymization must occur before data enters this repository. The repository guard supplements `.gitignore` by inspecting Git-visible content, but its secret/privacy detection is heuristic and never a proof that data is safe.

Tiny data may be committed under `tests/fixtures` only when it is fabricated or explicitly sanitized, clearly labeled, and needed for a test. The current demo is wholly synthetic.

Never commit credentials, customer data, production databases, private keys, or telemetry whose collection/consent authority is unclear.
