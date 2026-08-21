# Synthetic known-answer campaigns

Each `*.campaign.json` fabricates a tiny corpus whose correct interpretation is
obvious by hand, then drives the real ingestion, evidence, and inference path
over it and compares the outcome with expectations written before the pipeline
ran. The fabricated numbers are visible in the specification so a reviewer can
confirm the expected answer without running anything.

The campaigns cover a clear paired improvement, an honest null, an effect carried
entirely by one extreme unit, unbalanced arms, an unmet preregistered sample
requirement, an observational comparison that refuses a causal reading, an
explicitly unpaired delivered-cue contrast, a searched subgroup family containing
exactly the false-positive pressure searching creates, a reserved holdout that
fails to replicate, a segment that does not cover the layout, the same corner
ordinal on incompatible layouts, a measured zero beside an unavailable value, and
a counterbalanced design that reaches the causal-candidate ceiling.

```powershell
apex-labs campaign list --root .
apex-labs campaign verify research/campaigns/clear-paired-improvement.campaign.json --root .
apex-labs campaign verify-all --root .
apex-labs verify-science-demo --root .
```

After an engine commit is clean, regenerate the hash-bound reference layer into
a fresh review directory (never directly over the repository):

```powershell
apex-labs campaign regenerate-references --root . --output .apex-labs/regenerated-references
```

The command refuses dirty or uncommitted code identity and refuses to overwrite
its output. It emits exactly the derived protocol freezes plus the evidence and
analysis definitions whose exact bindings change. Review that artifact-only tree
before promoting those generated files into a separate reference commit.

`frozen/` holds the immutable protocol snapshots the campaigns bind. Generated
telemetry, manifests, evidence sets, and runs live only in a throwaway workspace
and are never tracked.

Every campaign is `synthetic_demo_only_not_racing_research`, is permanently
ineligible for scientific promotion, and preregisters the product state `none`
as part of its known answer. The generated source inventories contain fixed,
demo-only setup and build declarations so the `must_match` identity guards are
exercised rather than bypassed. They demonstrate that the machinery behaves as
designed. They demonstrate nothing whatsoever about driving.
