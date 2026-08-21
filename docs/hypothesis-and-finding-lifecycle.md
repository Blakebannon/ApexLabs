# Hypothesis lifecycle, findings, and the review package

Five things are separate, and none implies the next:

1. A **descriptive summary** is not inferential evidence.
2. An **inferential result** is not a finding.
3. A **finding** is not validated.
4. A **validated finding** is not a product change.
5. **Statistical evidence** is not the probability that a hypothesis is true.

Synthetic evidence proves mechanics only, at every one of those stages.

## Hypothesis lifecycle

```text
generated -> analysis_ready -> tested -> supported_provisionally
                                      -> replication_required -> tested
                                      -> inconclusive -> analysis_ready
                                      -> rejected (terminal)
supported_provisionally -> replication_required | rejected | inconclusive
```

States are never skipped. `rejected` is terminal within one hypothesis version.
A lifecycle is never restarted in place; a genuinely new attempt needs a new
hypothesis version.

```powershell
apex-labs hypothesis register hypothesis.json --registry .apex-labs/hypotheses --recorded-at 2026-08-20T00:00:00Z
apex-labs hypothesis transition my-hypothesis --registry .apex-labs/hypotheses `
  --to-state analysis_ready --rationale "Frozen before the run." --recorded-at ... `
  --evidence .apex-labs/evidence --analysis-definition research/analyses/....json
apex-labs hypothesis transition my-hypothesis --registry .apex-labs/hypotheses `
  --to-state tested --rationale "Ran once and recomputed." --recorded-at ... `
  --evidence .apex-labs/evidence --run .apex-labs/run --protocol-freeze ... --reviewer-state pending
apex-labs hypothesis state my-hypothesis --registry .apex-labs/hypotheses
apex-labs hypothesis verify --registry .apex-labs/hypotheses
```

### Where a hypothesis came from

Generation is recorded as `deterministic_algorithm`, `human`, or `llm`, together
with the actor and the detail. Every hypothesis must carry `is_evidence: false`,
and a hypothesis that claims otherwise is refused.

The source confers no authority. An LLM-generated hypothesis enters at
`generated` exactly like any other and still needs a frozen plan, a completed
independently verified run, and a reviewer disposition before it can reach an
evidence-bearing state. An LLM saying a result is meaningful is not evidence.

### Append-only history

Each transition is a separate file under
`<registry>/<hypothesis-id>/transitions/NNNN-<from>-to-<to>.json`, hash-chained
to its predecessor and bound to the hypothesis content hash. The current state is
**recomputed by replaying the chain**, not read from a stored summary. Replay
re-verifies contiguous sequence indices, the chain of predecessor hashes, each
transition's self-hash, that every transition targets this hypothesis, that the
hypothesis text has not been rewritten underneath its history, and that every
edge is permitted. Editing, removing, or reordering a transition is detected.
Writing over an existing transition file is refused.

### Promotion gates

| To state | Requires |
| --- | --- |
| `analysis_ready` | Frozen protocol, evidence set, and frozen analysis definition. No run may be bound yet. |
| `tested`, `replication_required`, `supported_provisionally`, `rejected`, `inconclusive` | All of the above **plus** a bound analysis run marked independently verified, an interpretation ceiling, the multiple-comparison family, falsification results, a replication policy, and a recorded reviewer disposition that is not `unreviewed`. |
| `supported_provisionally` | Additionally an **approved** scientific review and a computed (not inconclusive) result. |

## Finding lifecycle

The existing statuses are reused unchanged: `provisional`, `validated`,
`inconclusive`, `rejected`, together with the existing independent
`apex-labs.finding-validation/v1` artifact that separates the analyst's claim
from computed evidence, structural and reproducibility gates, and reviewer state.
No competing finding system was introduced, and no extra status was added:
`exploratory` and `replication_required` are already expressible through the
hypothesis state and the replication policy, both of which the review package
carries.

A finding binds hypothesis identity and version, the frozen protocol, the
evidence set, the analysis definition and run, dataset fingerprints, metric
definitions and hashes, effect magnitude, uncertainty, sample sufficiency,
multiple-comparison treatment, confounds, sensitivity results, the interpretation
ceiling, replication status, analysis and Labs code identity, scientific review,
and product-review state.

A finding is **not** validated because an adjusted threshold was crossed, because
an effect is non-zero, because a language model called it meaningful, because one
fastest lap supports it, because one session supports it, or because the
product's existing detector reported it. Validation requires passed
reproducibility and scientific gates, an approved scientific review, a computed
and independently recomputed run, and a tested hypothesis. Synthetic evidence can
never reach `validated`, and the contract refuses it.

## Review package

```powershell
apex-labs review-package build finding.json validation.json `
  --evidence .apex-labs/evidence --run .apex-labs/run `
  --registry .apex-labs/hypotheses --hypothesis my-hypothesis `
  --metric research/metrics/segment-minimum-speed.json `
  --package-id my-package --created-at 2026-08-20T00:00:00Z `
  --recomputed-and-verified --output .apex-labs/package
apex-labs review-package verify .apex-labs/package --evidence .apex-labs/evidence --run .apex-labs/run
```

The package emits a deterministic `review-package.json` and a human-readable
`review-report.md` whose content hash is bound into the package. It refuses to be
built unless the hypothesis head transition is actually bound to this run: it
never invents that link.

The report states the effect, status, question, evidence inventory, attrition,
practical threshold, uncertainty with its semantics, raw and adjusted statistical
evidence, sample sufficiency and any unmet requirement, controlled/measured/
unavailable confounds, every sensitivity outcome, replication state, the
interpretation ceiling, the limitations, the review gates, and the production
recommendation. Weak evidence is stated, not buried in prose.

`review-package verify` re-renders the report from the package, run, and evidence
and compares it byte for byte, so an edited report or an edited package is
detected.

## Production boundary

Apex Labs never edits Apex Sim Coach, changes a coaching policy, threshold, or
configuration, opens a production pull request, commits to the production
repository, deploys, or publishes. The package is evidence for human
consideration only, and every package records
`automatic_production_change: false`.

Product recommendation states, derived from the evidence rather than written by
hand:

| State | When |
| --- | --- |
| `do_not_implement` | Synthetic evidence. Always, regardless of statistics. |
| `replication_required` | A computed result whose frozen protocol still requires independent replication. |
| `investigate` | A provisional finding over a provisionally supported hypothesis. |
| `engineering_review_candidate` | A validated finding with passed reproducibility and scientific gates, an approved review, and no outstanding replication requirement. |
| `none` | Everything else, including honest nulls. |

Synthetic evidence may only ever be `none` or `do_not_implement`. Published
schemas and runtime validators refuse any stronger state on a synthetic finding,
validation artifact, review package, or product-export summary. Synthetic
classification is preserved in evidence/run bindings and cross-checked when a
hypothesis transition or review package is assembled. An algorithm that
transitively references a synthetic finding must remain `not_recommended` and
globally unsafe. Synthetic evidence cannot enter product review, become product
approved, carry an implementation recommendation, or support a real performance
claim.
