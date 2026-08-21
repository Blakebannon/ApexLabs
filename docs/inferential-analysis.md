# Preregistered inferential analysis

`apex-labs.analysis-definition/v1` is untouched by this milestone. It remains
`descriptive_observational` only, and its runtime validator still refuses any
inferential classification. Inference is a **separately named contract**,
`apex-labs.inferential-analysis-definition/v1`, so that a descriptive definition
can never be quietly promoted into evidence for a hypothesis test.

```powershell
apex-labs infer run research/analyses/synthetic-paired-corner-speed-confirmatory.json `
  --evidence .apex-labs/evidence `
  --protocol-freeze research/campaigns/frozen/synthetic-inference-controlled.freeze.json `
  --run-id demo-run --created-at 2026-08-20T00:00:00Z --output .apex-labs/run
apex-labs infer verify .apex-labs/run --evidence .apex-labs/evidence --protocol-freeze ...
```

## What an inferential definition must declare

Scientific question; hypothesis and null hypothesis; confirmatory or exploratory
classification; the frozen protocol; the evidence-set definition and its hash;
the evidence scope (`primary` or `holdout`); primary and secondary metrics;
experimental and resampling units; paired or unpaired grouping with a
justification when unpaired; every comparison with its role, method,
directionality, effect-size definition, practical threshold, and optional
subgroup; the multiple-comparison family, correction, alpha, and fixed
membership; the uncertainty method, coverage level, draw count, seed, resampling
unit, and interval semantics; missing-data and outlier policies; the sufficiency
and stopping rule with its source; the replication policy; the causal
interpretation ceiling; the falsification tests; and the limitations.

## Statistical methods

Everything is standard library. The methods are deliberately modest: a robust
paired estimate with transparent uncertainty is preferable to a fragile model
fitted to evidence that cannot support it.

### Paired comparison

Per-pair raw differences are computed as intervention minus baseline and
preserved in full in the artifact. The effect size is the declared
`median_paired_difference` or `mean_paired_difference`; the other is reported
beside it as a secondary estimate so a divergence between them is visible.

Statistical evidence is the **exact two-sided paired sign test**. Zero
differences are ties: they are excluded from the test rather than counted as
support for either direction, and a set with no informative pair yields no
p-value rather than a placeholder. The p-value is the exact binomial tail under a
fair-coin null. It is the probability of evidence at least this lopsided if the
null were true. It is never the probability that a hypothesis is true, and it says
nothing about how large the difference is.

Results are never converted into true or false on the strength of a p-value.
Direction, practical magnitude, interval, sensitivity, sufficiency, and human
review are all reported separately and all matter.

### Unpaired comparison

Implemented, but only for a design that declares itself unpaired and says **why**
pairing would fabricate a correspondence that does not exist. The result carries
that justification, the arm sizes, and an explicit note that group imbalance and
every unmeasured confound recorded beside it apply in full.

### Trend

Theil–Sen slope: the median of pairwise slopes, computed over the paired
differences against pair order. It is available only for paired designs. The
result states plainly that order is an ordering, not a cause: a non-zero slope is
an order effect to be explained, never evidence that coaching caused it.

### Consistency

The ratio of intervention MAD to baseline MAD, reported together with both MADs
and both interquartile ranges. A ratio below one means the intervention arm
varied less. The result says explicitly that less variation is not automatically
better: it can equally reflect a narrower sample or a driver who stopped
exploring. A zero baseline dispersion yields no ratio rather than an infinity.

### Bootstrap and interval semantics

The only uncertainty method is
`deterministic_cluster_percentile_bootstrap`, and it has a fixed seed, a declared
draw count, and a declared minimum cluster count.

- **Clusters are the declared resampling unit.** Whole clusters are resampled
  with replacement and their observations travel together, because nested
  observations are not independent evidence about a factor that varies only
  between clusters. Raw frames are never resampled.
- **Draws are machine independent.** Indices come from a SHA-256 counter stream
  keyed by the seed and the comparison, with rejection sampling to remove modulo
  bias. No platform or version dependent PRNG is involved.
- **Draws are order independent.** Clusters are canonicalized within and across
  themselves before resampling, so neither record order nor cluster assembly
  order can move an interval.
- **Interval convention.** With `B` draws sorted ascending and
  `alpha = 1 - coverage`, the bounds are `s[floor(alpha / 2 * B)]` and
  `s[ceil((1 - alpha / 2) * B) - 1]`. The indices are computed in IEEE double
  arithmetic, so a coverage level whose complement is not exactly representable
  can land one index from the textbook round number. That is identical on every
  machine, which is the property an interval needs.
- **Meaningless sample sizes are refused.** Below the declared minimum cluster
  count, or when fewer than half the draws produce a defined statistic, no
  interval is published and the reason is recorded in `unusable_reason`.

An interval describes the sampling variability of this estimator on this evidence
under resampling of whole clusters. It is not a probability that the true effect
lies inside it, and it does not account for confounding, selection, or any
unmeasured limitation recorded beside it.

## Small-sample discipline

Every run reports available and required units, pairs, resampling clusters, and
participants; unpaired unit counts; condition balance; replication count; holdout
availability; total attrition; whether the uncertainty estimate is usable;
whether the result is descriptive only; whether confirmatory interpretation is
permitted; and an explicit list of unmet requirements.

No universal thresholds are invented. Requirements come from one of:

- `frozen_protocol` — the analysis cites the protocol's minimum-sample
  requirement strings verbatim, and the run checks that each cited string
  actually appears in the frozen protocol.
- `documented_pilot` — the analysis binds a pilot document id, hash, and
  completion time.
- `not_declared` — no numeric threshold may be stated at all, and confirmatory
  classification is refused.

When requirements are not satisfied, the run is preserved with
`analysis_state: inconclusive` rather than refused, so the same underpowered
attempt is not repeated blindly. An inconclusive run is descriptive only, permits
no confirmatory interpretation, and says so in its limitations.

## Multiple-comparison protection

Every comparison belongs to one declared family. Membership is fixed in the
definition and must name exactly the declared comparisons; the run must produce
exactly one result per declared comparison in declaration order. Comparisons can
be neither added nor removed after results are known.

- A small preregistered confirmatory family uses **Holm–Bonferroni** familywise
  control. False-discovery-rate control is refused for it.
- A broad exploratory family uses **Benjamini–Hochberg** false-discovery-rate
  control. Familywise control is refused for it.
- `none` is permitted only for a single-member family.
- The family size is the **declared membership**, not the subset that happened to
  produce a p-value, so a comparison that fails to compute cannot weaken the
  correction applied to the others.
- Raw and adjusted values are both retained. An adjusted value may never be
  smaller than its raw value, and rejection requires an adjusted value at or
  below the preregistered alpha.
- The practical threshold is preregistered separately from the statistical
  evidence and is never derived from it.
- A confirmatory primary comparison is evaluated over the whole preregistered
  evidence set, never a subgroup. Subgroup comparisons are exploratory, are
  labelled as one of several searched slices in their own notes, and require
  independent replication.

Adjusted p-values are not the probability that a hypothesis is true. Crossing a
threshold is not a discovery.

## Sensitivity and falsification

Every declared falsification test runs against every computed comparison and is
reported beside the primary estimate, never in place of it. A fragile direction
is a reason for doubt, not a reason to re-estimate.

| Test | What it asks |
| --- | --- |
| `leave_one_unit_out` | Does the direction survive removing each pair in turn? |
| `leave_one_cluster_out` | Does it survive removing each block in turn? |
| `outlier_dependence` | Does the direction and practical magnitude survive removing the pair furthest from the median? |
| `order_effect_early_versus_late` | Do both halves of the ordered pairs carry the direction? |
| `isolation_by_cluster` | Is the direction isolated to one block? |
| `direction_sign_stability` | Does a majority of pairs share the direction? |

A check that is not defined for the available evidence returns
`not_computable` with its reason, rather than a manufactured verdict.

## Confounds

Every run enumerates the confounds the evidence set declared as controlled,
measured as covariates, and unavailable. The synthetic known-answer corpus binds
fixed, explicitly demo-only setup and build declaration files. Real normalized
datasets may bind an exact setup/build declaration when the source inventory
contains it; otherwise that identity stays unavailable and reduces
comparability. Fuel state, tyre state and history, traffic, and ambient and track
conditions remain unavailable in normalized v1.

## Interpretation ceilings

The maximum permissible interpretation, weakest first:

| Ceiling | Meaning |
| --- | --- |
| `descriptive` | The result describes this evidence and nothing else. |
| `associational` | Two things moved together in this evidence. |
| `intervention_associated` | A change followed a delivered intervention. |
| `causal_candidate` | A design that could support a causal reading, still requiring scientific review and replication. |

The **structural ceiling** is derived from the frozen protocol, never from how
the result turned out:

- Comparability `inadequate` → `descriptive`.
- Missing required setup or build identity → no stronger than
  `intervention_associated`.
- Preregistered setup/build variation → no stronger than the reduced ceiling
  frozen in its structured variation plan.
- No declared intervention condition → `associational`.
- Intervention conditions, plus a randomized or counterbalanced assignment, plus
  predeclared success criteria → `causal_candidate`.
- Intervention conditions otherwise → `intervention_associated`.

The definition declares a requested ceiling. Requesting more than the structural
ceiling permits is **refused before anything is computed**. The effective ceiling
is the weakest of the requested and structural ceilings, and collapses to
`descriptive` whenever the result is descriptive only. `causal` with no
qualification is not an available state.

## Replication and holdouts

A frozen protocol may reserve blocks or sessions. The primary analysis reads only
non-reserved evidence and the evidence set records
`primary_scope_excludes_holdout`. Reserved evidence may be read only by an
analysis whose `evidence_scope` is `holdout` and whose replication policy states
`this_run_is_the_replication`; every definition must also declare
`holdout_inspected: false`, so no definition can claim it already looked.

Replication scopes are explicit: same block, same session, different session,
same car/track, different track, different car, different participant. Only
different session, track, car, or participant count as genuinely independent
repetitions. Repeated frames or repeated samples from one opportunity are never
replication, and neither is a second look at the same block.

## Verification

`infer verify` re-runs the whole analysis from the bound evidence and compares
the result section by section, rather than re-hashing the stored answer. Runs are
byte deterministic, output is staged and atomically promoted, existing output is
never overwritten, and a refused run leaves nothing behind.

Synthetic evidence is permanently ineligible for scientific promotion, whatever
its statistics look like.
