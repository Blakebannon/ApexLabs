"""Ordered scientific vocabulary shared by contracts, evidence, and inference.

This module has no Apex Labs imports so that every layer can depend on it.
The orderings are contract semantics, not presentation preferences: a unit
level and an interpretation ceiling are both comparable quantities, and the
guards in this package are written as comparisons against them.
"""

from __future__ import annotations

# Observation hierarchy, from the most deeply nested measurement upward. A
# thousand telemetry frames from one braking event are one opportunity, not a
# thousand independent observations.
UNIT_LEVELS: tuple[str, ...] = (
    "telemetry_frame",
    "event",
    "segment_opportunity",
    "lap",
    "stint",
    "block",
    "session",
    "participant",
)
UNIT_LEVEL_SET = set(UNIT_LEVELS)
UNIT_LEVEL_RANK = {level: index for index, level in enumerate(UNIT_LEVELS)}

# Levels that may never serve as the experimental unit of an inferential
# comparison. Nested frames and single events inside one opportunity are
# pseudoreplication whenever the question concerns laps, blocks, or sessions.
FORBIDDEN_EXPERIMENTAL_UNITS = frozenset({"telemetry_frame", "event"})

# Maximum permissible interpretation, weakest first.
INTERPRETATION_CEILINGS: tuple[str, ...] = (
    "descriptive",
    "associational",
    "intervention_associated",
    "causal_candidate",
)
CEILING_SET = set(INTERPRETATION_CEILINGS)
CEILING_RANK = {ceiling: index for index, ceiling in enumerate(INTERPRETATION_CEILINGS)}

COMPARABILITY_FIELDS = frozenset(
    {
        "participant",
        "simulator",
        "car",
        "track",
        "layout",
        "protocol_version",
        "condition_semantics",
        "coaching_state",
        "configuration_identity",
        "segment_definition",
        "metric_definition",
        "normalization_contract",
        "product_build",
    }
)

# Comparability fields that must be declared in every evidence-set definition,
# whether as must-match or as explicitly justified permitted variation. A
# protocol may permit variation, but never silently.
GUARDED_COMPARABILITY_FIELDS = COMPARABILITY_FIELDS

# Setup/configuration and product-build identity are protected scientific
# controls.  They default to must-match and may only vary through a structured
# plan preserved in the frozen protocol; a free-text evidence-set justification
# is never sufficient to waive either control.
PROTECTED_IDENTITY_FIELDS = frozenset({"configuration_identity", "product_build"})

EXCLUSION_STAGES: tuple[str, ...] = (
    "source_records",
    "outside_segment",
    "missing_required_channel",
    "invalid_lap",
    "incident_affected",
    "pit_replay_discontinuity",
    "protocol_mismatch",
    "condition_mismatch",
    "insufficient_coverage",
    "duplicate_evidence",
    "out_of_order_or_corrupt",
    "confound_based",
    "holdout_reserved",
)
EXCLUSION_STAGE_SET = set(EXCLUSION_STAGES)

ATTRITION_DISPOSITIONS = frozenset(
    {
        "counted",
        "excluded_by_preregistered_rule",
        "unavailable",
        "structurally_invalid",
        "accepted_with_limitations",
        "post_hoc_exclusion",
    }
)

REPLICATION_SCOPES = frozenset(
    {
        "not_applicable",
        "same_block",
        "same_session",
        "different_session",
        "same_car_track",
        "different_track",
        "different_car",
        "different_participant",
    }
)

# Replication scopes that are genuinely independent repetitions. Repeated
# frames or repeated samples from one opportunity are never replication, and
# neither is a second look at the same block.
INDEPENDENT_REPLICATION_SCOPES = frozenset(
    {
        "different_session",
        "different_track",
        "different_car",
        "different_participant",
    }
)

HYPOTHESIS_STATES: tuple[str, ...] = (
    "generated",
    "analysis_ready",
    "tested",
    "replication_required",
    "supported_provisionally",
    "rejected",
    "inconclusive",
)
HYPOTHESIS_STATE_SET = set(HYPOTHESIS_STATES)

# Permitted lifecycle edges. States are never skipped, and a rejected
# hypothesis is terminal within one hypothesis version.
HYPOTHESIS_TRANSITIONS: dict[str, frozenset[str]] = {
    "generated": frozenset({"analysis_ready"}),
    "analysis_ready": frozenset({"tested"}),
    "tested": frozenset(
        {"supported_provisionally", "rejected", "inconclusive", "replication_required"}
    ),
    "replication_required": frozenset({"tested"}),
    "supported_provisionally": frozenset({"replication_required", "rejected", "inconclusive"}),
    "inconclusive": frozenset({"analysis_ready"}),
    "rejected": frozenset(),
}

# States that may only be entered from a completed, verified analysis run.
EVIDENCE_BEARING_STATES = frozenset(
    {"tested", "supported_provisionally", "rejected", "inconclusive", "replication_required"}
)

PRODUCT_RECOMMENDATION_STATES = frozenset(
    {"none", "investigate", "replication_required", "engineering_review_candidate", "do_not_implement"}
)

# Synthetic mechanics can never recommend production work.
SYNTHETIC_PRODUCT_RECOMMENDATIONS = frozenset({"none", "do_not_implement"})


def at_or_above(level: str, floor: str) -> bool:
    """True when `level` sits at or above `floor` in the observation hierarchy."""
    return UNIT_LEVEL_RANK[level] >= UNIT_LEVEL_RANK[floor]


def ceiling_at_or_below(ceiling: str, limit: str) -> bool:
    """True when `ceiling` claims no more than `limit` permits."""
    return CEILING_RANK[ceiling] <= CEILING_RANK[limit]


def weakest_ceiling(*ceilings: str) -> str:
    """The most conservative of several interpretation ceilings."""
    return min(ceilings, key=lambda item: CEILING_RANK[item])
