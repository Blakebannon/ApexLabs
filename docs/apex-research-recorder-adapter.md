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

## Exploratory pilot intake

A real session that was already driven before any protocol existed has exactly one other way
in: `--exploratory-intake`, carrying an `apex-labs.exploratory-intake/v1` artifact. It is
deliberately NOT a protocol freeze and cannot become one. Every field that would describe a
prospective plan is pinned to the value that denies one — no protocol, no randomization,
observational classification — and the only reviewer disposition the contract offers is
`approved_exploratory_only`.

The intake is worthless unless it is welded to the exact bytes it approves, so ingestion
re-checks the session id, the completed manifest SHA-256, and the collection record's identity
and SHA-256 against the files actually being ingested. Editing the collection record after
review invalidates the intake. The two doors are mutually exclusive: supplying a protocol
snapshot and an intake together is refused as a contradiction rather than silently preferring
one, because a session cannot both have been governed by a prospective plan and have predated
one.

What it buys is narrow. The normalized dataset carries a `scientific_eligibility` block with
`stratum: exploratory_pilot`, permitting descriptive analysis and hypothesis generation and
permanently forbidding confirmatory claims, causal claims, primary effect estimates, and
pooling into the frozen primary corpus. That block is an ingredient of the dataset fingerprint,
so it cannot be edited into something wider without invalidating the dataset, and the validator
refuses an exploratory dataset that claims a frozen protocol — a later protocol snapshot can
never retroactively upgrade retrospectively admitted evidence. Comparable-evidence construction
refuses the stratum by name.

This path adds no bypass of the primary gate. A real bundle presented with neither a protocol
snapshot nor a valid intake fails exactly as it did before, including under
`--integration-validation`, which only ever relaxed the clean-tree requirement.

```powershell
apex-labs validate exploratory-intake "D:\ApexResearch\exploratory-intake.json"
apex-labs apex-research ingest "D:\ApexResearch\sessions\<session-id>" `
  --collection-record "D:\ApexResearch\collection-record.json" `
  --exploratory-intake "D:\ApexResearch\exploratory-intake.json" `
  --output "D:\ApexResearch
ormalized\<session-id>"
```

Pilot sessions may be compared with other pilot sessions. They remain a distinct exploratory
stratum and never merge into the primary corpus.

The direction is strictly product bundle to Labs ingestion. This command has no product-repo
locator, writeback, PR, configuration, deployment, uploader, or finding-promotion capability.

Source-channel attribution is checked against a committed simulator capability
snapshot, so the adapter cannot name a variable the simulator does not expose.
That guard corrected `longitudinal_acceleration`, previously attributed to
`LonAccel`; the iRacing variable is `LongAccel`. Because that attribution is part
of normalized record content, the adapter version moved to `1.1.0`, and then to
`1.2.0` when the synchronized 82-column sample shape landed.

Tyre pressure is derived from `LFcoldPressure` and its siblings, which are
garage-set cold pressures. The derivation says so explicitly: iRacing exposes no
hot or running tyre pressure, so live inflation pressure is unavailable and is
never inferred from the cold value.

See [iracing-capability-reconciliation.md](iracing-capability-reconciliation.md).

`SAMPLE_HEADERS` is matched by exact equality against the recorder's
`ResearchContract.SampleColumns`, and the pinned profile records neither list, so the two must
change together. `tests/fixtures/research_recorder_v1` holds a bundle emitted by the real
recorder, and the cross-repository tests drive those exact bytes through validation, collection
binding and ingestion, so a one-sided change fails a test rather than a live rehearsal.

Columns without an existing normalized concept are validated and retained in the manifest's
`unknown_source_channels` rather than being promoted. Promoting traffic, flag, tyre-wear or
assist-setting evidence to normalized concepts is a deliberate later concept review, not a side
effect of capture.
