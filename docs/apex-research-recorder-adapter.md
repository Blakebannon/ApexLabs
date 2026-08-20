# Apex Research Recorder adapter

The dependency-free `apex-research-recorder/1.0.0` adapter consumes only a completed local
`apex-research-session-export/1.0.0` directory conforming to
`apex-labs-research-recorder-profile/1.0.0`.

```powershell
apex-labs apex-research inspect "D:\ApexResearch\sessions\<session-id>"
apex-labs apex-research validate "D:\ApexResearch\sessions\<session-id>" --collection-record "D:\ApexResearch\collection-record.json"
apex-labs apex-research ingest "D:\ApexResearch\sessions\<session-id>" --collection-record "D:\ApexResearch\collection-record.json" --protocol-snapshot "D:\ApexResearch\protocol-freeze.json" --output "D:\ApexResearch\normalized\<session-id>"
```

`inspect` and `validate` independently enforce the exact inventory, portable paths, completion
marker, manifest/file/configuration hashes, profile pins, CSV shape, finite/null semantics,
sequence/drop accounting, event ordering, coaching/condition evidence, and privacy declarations.
The collection record binds `source_bundle.sha256` to the exact recorder `manifest.json`
SHA-256; `COMPLETE` independently binds the same manifest. The collection record remains a
Labs-side operator artifact and is never fabricated by the product.

`ingest` streams RFC-4180 CSV; it does not load a session's samples into memory. Empty fields
become normalized values with `provenance: unavailable`, while measured zero remains zero.
Original row/file/hash provenance is retained. No interpolation or silent repair is performed.
Outputs are staged and atomically promoted, and identical logical inputs produce identical
normalized records and fingerprints.

Real ingestion requires a clean committed Labs code identity, a matching collection record,
and a reviewed protocol-freeze snapshot. `--integration-validation` permits a dirty-code
mechanics rehearsal only; that run is not scientific evidence. Synthetic fixtures do not need
a protocol snapshot. A protocol identity written by the recorder is an explicit operator input,
not proof that Labs reviewed or froze it.

The direction is strictly product bundle to Labs ingestion. This command has no product-repo
locator, writeback, PR, configuration, deployment, uploader, or finding-promotion capability.
