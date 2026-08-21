# What remains for L6 campaign readiness

This milestone built the scientific engine and proved it against fabricated
corpora with known answers. It deliberately did **not** build campaign or
rehearsal readiness. The following are the gaps a real campaign would hit, listed
so that none of them is discovered halfway through a collection session.

## Protocol requirements are still free text

`apex-labs.experiment/v1` records `minimum_sample_requirements.requirements` as
prose. An inferential definition states machine-readable minimums and must cite
the protocol's requirement strings verbatim, and the run checks that each cited
string really appears in the frozen protocol — but nothing checks that the number
in the definition matches the number in the sentence. A reviewer must still read
both. Making protocol requirements machine-readable is an L6 contract change.

## No pilot has estimated event yield, variance, or attrition

Every sample requirement exercised here is a fabricated software threshold, not a
power calculation. Before any confirmatory real analysis, a documented pilot must
estimate per-segment event yield, within-driver and between-block variance,
dependence structure, and realistic attrition, and that document must be bound
through `sufficiency_rule.pilot_reference`.

## Fields the corpus cannot fully supply

Normalized v1 carries no record-level representation of fuel state, tyre state
or temperature history, traffic, or ambient and track conditions. Exact setup
and product-build identity can be bound only when the source inventory includes
the dedicated declaration file; absence is recorded as unavailable and is never
a match. The current Apex research export supplies an exact setup declaration
but still needs richer product-build telemetry. A real campaign must collect the
remaining identities and conditions or accept them as explicit limitations and
a lower interpretation ceiling.

## Segment identity is declared, not verified

The checked-in segments are fabricated distance ranges with declared geometry
fingerprints. A real campaign needs a verified track/layout catalog with real
geometry provenance before any segment may claim `verified_track_catalog` or a
corner ordinal. Until then, real work must use distance or lap-fraction ranges
and record that limitation.

## Units the evidence layer cannot yet build

`stint` and `participant` experimental units are refused rather than
approximated, because normalized v1 records carry no stint boundary and a
participant-level unit needs a sampling frame that does not exist. Multi-driver
population work needs both, plus a population-validation design.

## Collection-time enforcement

Blocks, conditions, and their arm assignment are declared in the evidence-set
definition and read from each dataset's collection context. Nothing yet enforces
at collection time that the realized session matched the frozen schedule, that
block boundaries were respected, or that a deviation was recorded. Campaign
rehearsal is where that gap gets closed.

## Multi-dataset provenance

Each contributing block is presently its own normalized dataset. That is correct
and auditable, but it means a real session becomes several datasets whose
collection records must agree. L6 should decide whether a session-level ingest
that emits block-partitioned datasets is worth the contract change.

## Methods deliberately not implemented

No regression, no hierarchical or mixed model, no Bayesian estimation, and no
machine learning. Those become defensible only when a real corpus is large enough
to support them and a concrete preregistered question needs them. Adding one
without both is how fragile results get manufactured.

## Review capacity

Every gate that ends in "human scientific review" currently ends in a state, not
a person. L6 needs named reviewers, a review rota, and a written standard for
what an approving review actually checked.
