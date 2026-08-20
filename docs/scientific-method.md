# Scientific method and analysis conduct

## Aim at falsification

Start with a question that could produce `rejected` or `inconclusive`, not a story to confirm. Write the null hypothesis, comparable unit, exclusions, primary outcome, minimum-sample method, analysis, and success/falsification rules before confirmatory analysis. Preserve failed and negative work so attractive unsupported ideas are not repeatedly rediscovered.

## Four separate validity layers

- Structural validity means an artifact satisfies its contract and cross-reference rules.
- Reproducibility means exact input, protocol, code/schema identity, configuration, randomness, and output hashes are bound and can be rerun.
- Scientific validity requires adequate computed evidence, uncertainty, comparability, falsification, bounded scope, and explicit scientific review.
- Product approval is a later human and production-engineering decision outside Apex Labs.

None implies the next. Deterministic output does not make a finding true. Schema validity does not establish adequate evidence. Export verification establishes package integrity and internal consistency, not authorship, scientific correctness, or product approval.

## Evidence vocabulary

- `validated`: the predeclared criteria were met, samples were sufficient, comparability was adequate, and falsification attempts did not overturn the bounded conclusion.
- `provisional`: useful evidence exists but replication, holdout validation, scope expansion, or another declared requirement remains.
- `inconclusive`: available evidence cannot reliably distinguish the hypothesis from alternatives. This is a successful research outcome.
- `rejected`: evidence contradicts the hypothesis or it failed its declared falsification criterion. This is also a successful outcome.

Status never widens scope. Scope answers where evidence currently applies: `driver_specific`, `car_specific`, `track_specific`, `corner_archetype_specific`, `simulator_specific`, `session_specific`, `algorithmic`, `population_hypothesis`, or `population_supported`.

## Comparability before comparison

Define the observational/experimental unit before selecting rows. Telemetry samples within one lap are not independent drivers or laps. Corner comparisons may require compatible approach speed, vehicle state, corner geometry, traffic, tires, fuel, setup, weather, and validity. Report how many units were eligible, excluded, and retained, with reasons.

Do not condition on variables affected by the intervention without explaining the bias risk. Do not select a driver's best laps after seeing the outcome unless that selection was preregistered or clearly labeled exploratory.

## Statistical principles

- Begin with plots and robust descriptive summaries, but keep exploratory results exploratory.
- Prefer within-driver paired designs when conditions are repeated by the same driver.
- Report effect size and uncertainty, not only a p-value.
- State whether an interval is a confidence, credible, bootstrap, prediction, or other interval and define its interpretation.
- Account for dependence across samples, corners, laps, sessions, drivers, cars, and tracks.
- Use robust/outlier-resistant methods when justified and report sensitivity to reasonable alternatives.
- Use regression or hierarchical/mixed models only when structure and data support them.
- Hold out data or collect a confirmation wave for hypotheses selected after exploration.
- Declare multiple-hypothesis handling for families of metrics or hypotheses.
- Never label an arbitrary model score as confidence.
- Never claim causality from an uncontrolled observational association.

The simplest method that reliably answers the question is preferred.

## Generalization ladder

A single driver's pattern starts as driver-specific even if repeated across many laps. Evidence may separately suggest car, track, corner-archetype, simulator, or session limitations. Population claims require a design and sampling frame that support population inference; several samples from one person are not a population.

Algorithmic findings are about measurement or analysis behavior—for example, a demonstrated comparability failure—not a loophole for universal driving advice. They still require validation and bounded caveats.

## Status is not self-certifying

The finding file contains the analyst's proposed status and narrative. A separate validation artifact binds exact datasets/fingerprints/manifests/records, frozen protocol, processing and analysis configuration, code identity, computed counts/exclusions/effect/uncertainty/comparability/falsification evidence, scope assessment, gate evaluations, and reviewer state. A hand-entered “sufficient” or “adequate” value cannot alone produce validation. Unimplemented or unsupported gates are recorded as `unresolved`, which requires an `inconclusive` finding.

`population_supported` additionally requires a passed preregistered population-validation design. Apex Labs defines no universal numeric population threshold in this milestone.

## Contributor or AI analysis checklist

1. Verify repository and data authority; never copy private/raw telemetry into Git.
2. Inspect and hash source data; freeze the adapter and normalized manifest.
3. Identify measured, derived, estimated, and unavailable inputs.
4. Create/version the protocol; distinguish exploratory work from preregistered work.
5. Define units, sample hierarchy, comparability, exclusions, and missing-data handling.
6. Establish sample requirements using a documented method, not a convenient round number.
7. Implement analysis as versioned, tested code—not notebook-only state.
8. Record all configuration and randomness; use deterministic seeds where randomness exists.
9. Run planned falsification, sensitivity, multiplicity, and holdout checks.
10. Write the narrowest supported status and scope. List limitations and plausible confounders.
11. Reproduce from clean inputs and verify the finding contract.
12. Export only deliberately selected findings and retain the human review gate.

LLMs may propose questions, code, critiques, or explanations. Deterministic/statistical results and their provenance determine evidence status. Any LLM-generated narrative must remain consistent with the machine-readable result.

Synthetic fixtures and their “findings” are mechanics tests only. They are permanently ineligible for scientific or product approval and are not racing research.
