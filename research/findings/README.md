# Finding classification

Directories correspond to the four evidence statuses: `validated`, `provisional`, `inconclusive`, and `rejected`. Negative and ambiguous results are retained as first-class outputs.

Status and evidence scope are independent. Driver/car/track/corner/simulator/session findings are never globally safe. `population_hypothesis` is not validated population evidence. Only validated `algorithmic` or `population_supported` findings can set `safe_for_global_consideration` to true, and that flag only opens production review.

The included synthetic finding lives under `inconclusive` and is explicitly `do_not_implement`. It demonstrates serialization and review behavior, not research.
