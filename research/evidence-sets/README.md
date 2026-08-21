# Evidence-set definitions

Each `apex-labs.evidence-set-definition/v1` document declares, before any value
is inspected, which evidence may be combined and how: the frozen protocol, the
segment and its hash, every guarded comparability field as either must-match or
explicitly justified permitted variation, the experimental and resampling units,
the compared factor and its arms, the unit metric and its extractor, the
aggregation and its dispersion measure, the pairing rule, the inclusion and
exclusion rules, the confounds, and the holdout policy.

Setup/configuration identity and product-build identity are protected controls:
the initial corpus requires both to match exactly. Missing identity is a
limitation, not a match. A future exception requires a structured variation plan
in the frozen protocol; a general justification string cannot waive the guard.

A definition binds no dataset. `apex-labs evidence build` binds one definition to
a set of verified normalized datasets and emits an `apex-labs.evidence-set/v1`
artifact that is reproducible with `apex-labs evidence verify`.

An evidence set is comparable evidence, never scientific evidence. See
[docs/comparable-evidence.md](../../docs/comparable-evidence.md).
