"""Runtime validation for segment definitions and comparable evidence sets.

Comparability is an explicit, declared property. Nothing here infers that two
records may be compared because they happen to be convenient, share an ordinal
corner label, or come from the same folder.
"""

from __future__ import annotations

from typing import Any

from apex_labs.normalization.concepts import NORMALIZED_CONCEPTS
from apex_labs.schemas import versions
from apex_labs.schemas.research_validation import _code_identity
from apex_labs.schemas.science_vocabulary import (
    ATTRITION_DISPOSITIONS,
    CEILING_SET,
    COMPARABILITY_FIELDS,
    EXCLUSION_STAGE_SET,
    FORBIDDEN_EXPERIMENTAL_UNITS,
    GUARDED_COMPARABILITY_FIELDS,
    PROTECTED_IDENTITY_FIELDS,
    REPLICATION_SCOPES,
    UNIT_LEVEL_SET,
    at_or_above,
)
from apex_labs.schemas.validation import (
    _boolean,
    _enum,
    _fail,
    _id,
    _integer,
    _keys,
    _list,
    _number,
    _object,
    _sha,
    _string,
    _strings,
    _timestamp,
    _version,
)

IDENTITY_SOURCES = {
    "verified_track_catalog",
    "verified_corner_identity",
    "protocol_distance_range",
    "protocol_lap_fraction_range",
    "deterministic_phase",
}
IDENTITY_CONFIDENCE = {"verified", "declared", "approximate"}
PHASE_IDS = {"braking", "turn_in", "apex_region", "exit"}
BOUNDARY_RESOLUTIONS = {"half_open_start_inclusive", "closed_both_ends", "half_open_end_inclusive"}
OVERLAP_POLICIES = {"disjoint_within_definition", "overlap_permitted_declared"}
ARMS = {"baseline", "intervention"}
COACHING_STATES = {"enabled", "disabled", "mixed", "unknown"}
DIRECTIONALITIES = {"higher_is_better", "lower_is_better", "target_range", "descriptive_only"}
AGGREGATION_METHODS = {"median", "arithmetic_mean", "single_record"}
PAIR_KEY_FIELDS = {
    "participant", "simulator", "car", "track", "layout", "session_id", "block_id", "order_index",
}
EXTRACTOR_RECORD_TYPES = {
    "record_field": {"lap"},
    "segment_aggregate": {"telemetry_sample", "distance_bin"},
    "segment_threshold_distance": {"telemetry_sample", "distance_bin"},
}
HOLDOUT_POLICIES = {"none", "reserved_blocks", "reserved_sessions"}
COMPARABILITY_STATUSES = {"adequate", "limited", "inadequate"}


def _unit_level(value: Any, path: str) -> str:
    return _enum(value, UNIT_LEVEL_SET, path)


def _unique_ids(values: Any, path: str) -> list[str]:
    items = _list(values, path, nonempty=True)
    seen: set[str] = set()
    for index, item in enumerate(items):
        identifier = _id(item, f"{path}[{index}]")
        if identifier in seen:
            _fail(f"{path}[{index}]", "must be unique")
        seen.add(identifier)
    return items


def validate_segment_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.SEGMENT_DEFINITION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "segment_definition_id", "version", "title", "identity_source",
            "identity_confidence", "corner_identity", "applies_to", "region", "phase",
            "coverage_requirements", "overlap_policy", "boundary_sample_resolution", "limitations",
        },
    )
    _id(obj["segment_definition_id"], "$.segment_definition_id")
    _string(obj["version"], "$.version")
    _string(obj["title"], "$.title")
    identity_source = _enum(obj["identity_source"], IDENTITY_SOURCES, "$.identity_source")
    confidence = _enum(obj["identity_confidence"], IDENTITY_CONFIDENCE, "$.identity_confidence")
    corner = obj["corner_identity"]
    if corner is not None:
        _keys(
            _object(corner, "$.corner_identity"),
            "$.corner_identity",
            required={"catalog_id", "catalog_version", "corner_reference", "catalog_sha256"},
        )
        _id(corner["catalog_id"], "$.corner_identity.catalog_id")
        _string(corner["catalog_version"], "$.corner_identity.catalog_version")
        _string(corner["corner_reference"], "$.corner_identity.corner_reference")
        _sha(corner["catalog_sha256"], "$.corner_identity.catalog_sha256")
    if identity_source in {"verified_track_catalog", "verified_corner_identity"} and corner is None:
        _fail("$.corner_identity", "verified corner identity requires a bound catalog reference")
    if identity_source in {"protocol_distance_range", "protocol_lap_fraction_range"} and corner is not None:
        _fail(
            "$.corner_identity",
            "a protocol distance/fraction segment must not claim catalog corner identity; corner numbers are never invented",
        )
    if corner is not None and confidence == "approximate":
        _fail("$.identity_confidence", "a bound catalog corner identity cannot be approximate")

    applies_to = _list(obj["applies_to"], "$.applies_to", nonempty=True)
    seen_targets: set[tuple[str, str, str]] = set()
    for index, target in enumerate(applies_to):
        path = f"$.applies_to[{index}]"
        item = _object(target, path)
        _keys(
            item,
            path,
            required={"simulator", "track", "layout", "geometry_fingerprint", "geometry_source"},
        )
        key = (
            _string(item["simulator"], f"{path}.simulator"),
            _string(item["track"], f"{path}.track"),
            _string(item["layout"], f"{path}.layout"),
        )
        if key in seen_targets:
            _fail(path, "duplicate simulator/track/layout applicability entry")
        seen_targets.add(key)
        _sha(item["geometry_fingerprint"], f"{path}.geometry_fingerprint")
        _string(item["geometry_source"], f"{path}.geometry_source")

    region = _object(obj["region"], "$.region")
    _keys(region, "$.region", required={"kind", "start", "end", "wraparound", "lap_length_m", "boundary"})
    kind = _enum(region["kind"], {"distance_range", "lap_fraction_range"}, "$.region.kind")
    start = _number(region["start"], "$.region.start")
    end = _number(region["end"], "$.region.end")
    if start < 0 or end < 0:
        _fail("$.region", "start and end must be non-negative")
    wraparound = _boolean(region["wraparound"], "$.region.wraparound")
    boundary = _object(region["boundary"], "$.region.boundary")
    _keys(boundary, "$.region.boundary", required={"start_inclusive", "end_inclusive"})
    _boolean(boundary["start_inclusive"], "$.region.boundary.start_inclusive")
    _boolean(boundary["end_inclusive"], "$.region.boundary.end_inclusive")
    if kind == "lap_fraction_range":
        if start > 1 or end > 1:
            _fail("$.region", "lap-fraction bounds must lie within [0, 1]")
        if region["lap_length_m"] is not None:
            _fail("$.region.lap_length_m", "must be null for a lap-fraction region")
    else:
        if region["lap_length_m"] is not None:
            if _number(region["lap_length_m"], "$.region.lap_length_m") <= 0:
                _fail("$.region.lap_length_m", "must be positive")
        elif wraparound:
            _fail("$.region.lap_length_m", "a wrapping distance region requires a declared lap length")
    if wraparound:
        if start <= end:
            _fail("$.region", "a wrapping region requires start greater than end")
    elif start >= end:
        _fail("$.region", "a non-wrapping region requires start strictly below end")
    if kind == "distance_range" and region["lap_length_m"] is not None:
        lap_length = region["lap_length_m"]
        if start >= lap_length or end > lap_length:
            _fail("$.region", "region bounds must lie within the declared lap length")

    phase = obj["phase"]
    if phase is not None:
        phase_obj = _object(phase, "$.phase")
        _keys(
            phase_obj,
            "$.phase",
            required={"phase_id", "method_id", "definition", "deterministic", "concept", "comparison", "threshold"},
        )
        _enum(phase_obj["phase_id"], PHASE_IDS, "$.phase.phase_id")
        if phase_obj["method_id"] != versions.PHASE_METHOD_ID:
            _fail("$.phase.method_id", f"must be the one supported reproducible phase method {versions.PHASE_METHOD_ID!r}")
        _string(phase_obj["definition"], "$.phase.definition")
        if phase_obj["deterministic"] is not True:
            _fail("$.phase.deterministic", "a phase may only be used when its method is reproducible")
        if _string(phase_obj["concept"], "$.phase.concept") not in NORMALIZED_CONCEPTS:
            _fail("$.phase.concept", "must be a normalized v1 concept")
        _enum(phase_obj["comparison"], {"at_or_above", "below"}, "$.phase.comparison")
        _number(phase_obj["threshold"], "$.phase.threshold")
    elif identity_source == "deterministic_phase":
        _fail("$.phase", "a deterministic-phase segment requires a declared reproducible phase method")

    coverage = _object(obj["coverage_requirements"], "$.coverage_requirements")
    _keys(
        coverage,
        "$.coverage_requirements",
        required={
            "required_concepts", "minimum_records_per_unit",
            "minimum_concept_coverage_ratio", "minimum_comparable_units",
        },
    )
    concepts = _strings(coverage["required_concepts"], "$.coverage_requirements.required_concepts", nonempty=True)
    for index, concept in enumerate(concepts):
        if concept not in NORMALIZED_CONCEPTS:
            _fail(
                f"$.coverage_requirements.required_concepts[{index}]",
                "must be a normalized v1 concept; simulator channels are never invented here",
            )
    if len(set(concepts)) != len(concepts):
        _fail("$.coverage_requirements.required_concepts", "must not repeat a concept")
    _integer(coverage["minimum_records_per_unit"], "$.coverage_requirements.minimum_records_per_unit", minimum=1)
    ratio = _number(coverage["minimum_concept_coverage_ratio"], "$.coverage_requirements.minimum_concept_coverage_ratio")
    if not 0 <= ratio <= 1:
        _fail("$.coverage_requirements.minimum_concept_coverage_ratio", "must lie within [0, 1]")
    _integer(coverage["minimum_comparable_units"], "$.coverage_requirements.minimum_comparable_units", minimum=1)
    _enum(obj["overlap_policy"], OVERLAP_POLICIES, "$.overlap_policy")
    _enum(obj["boundary_sample_resolution"], BOUNDARY_RESOLUTIONS, "$.boundary_sample_resolution")
    resolution = obj["boundary_sample_resolution"]
    expected = {
        "half_open_start_inclusive": (True, False),
        "closed_both_ends": (True, True),
        "half_open_end_inclusive": (False, True),
    }[resolution]
    if (boundary["start_inclusive"], boundary["end_inclusive"]) != expected:
        _fail(
            "$.boundary_sample_resolution",
            f"must agree with the declared boundary inclusivity {expected}",
        )
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    if confidence == "approximate" and not obj["limitations"]:
        _fail("$.limitations", "an approximate segment mapping must record its limitation")
    return obj


def _extractor(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    kind = _enum(
        obj.get("kind"),
        {"record_field", "segment_aggregate", "segment_threshold_distance"},
        f"{path}.kind",
    )
    required = {"kind", "record_type", "concept"}
    if kind == "segment_aggregate":
        required.add("method")
    elif kind == "segment_threshold_distance":
        required.update({"threshold", "direction"})
    _keys(obj, path, required=required)
    _enum(obj["record_type"], EXTRACTOR_RECORD_TYPES[kind], f"{path}.record_type")
    concept = _string(obj["concept"], f"{path}.concept")
    if concept not in NORMALIZED_CONCEPTS:
        _fail(f"{path}.concept", "must be a normalized v1 concept")
    if kind == "segment_aggregate":
        _enum(obj["method"], {"minimum", "maximum", "arithmetic_mean", "median"}, f"{path}.method")
    if kind == "segment_threshold_distance":
        _number(obj["threshold"], f"{path}.threshold")
        _enum(obj["direction"], {"first_at_or_above", "last_at_or_above"}, f"{path}.direction")
    return obj


def _rule(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(obj, path, required={"rule_id", "stage", "preregistered", "description"})
    _id(obj["rule_id"], f"{path}.rule_id")
    _enum(obj["stage"], EXCLUSION_STAGE_SET, f"{path}.stage")
    _boolean(obj["preregistered"], f"{path}.preregistered")
    _string(obj["description"], f"{path}.description")
    return obj


def validate_evidence_set_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.EVIDENCE_SET_DEFINITION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "evidence_set_id", "version", "title", "purpose", "synthetic",
            "protocol", "segment", "comparability", "experimental_unit", "resampling_unit",
            "factor", "unit_metric", "aggregation", "pairing", "inclusion_rules",
            "exclusion_rules", "confounds", "holdout", "limitations",
        },
    )
    _id(obj["evidence_set_id"], "$.evidence_set_id")
    _string(obj["version"], "$.version")
    _string(obj["title"], "$.title")
    _string(obj["purpose"], "$.purpose")
    _boolean(obj["synthetic"], "$.synthetic")

    protocol = _object(obj["protocol"], "$.protocol")
    _keys(protocol, "$.protocol", required={"freeze_id", "freeze_sha256", "experiment_id", "experiment_version"})
    _id(protocol["freeze_id"], "$.protocol.freeze_id")
    _sha(protocol["freeze_sha256"], "$.protocol.freeze_sha256")
    _id(protocol["experiment_id"], "$.protocol.experiment_id")
    _string(protocol["experiment_version"], "$.protocol.experiment_version")

    segment = _object(obj["segment"], "$.segment")
    _keys(segment, "$.segment", required={"segment_definition_id", "version", "sha256"})
    _id(segment["segment_definition_id"], "$.segment.segment_definition_id")
    _string(segment["version"], "$.segment.version")
    _sha(segment["sha256"], "$.segment.sha256")

    comparability = _object(obj["comparability"], "$.comparability")
    _keys(comparability, "$.comparability", required={"must_match", "permitted_variation"})
    must_match = _list(comparability["must_match"], "$.comparability.must_match", nonempty=True)
    matched: set[str] = set()
    for index, field in enumerate(must_match):
        name = _enum(field, COMPARABILITY_FIELDS, f"$.comparability.must_match[{index}]")
        if name in matched:
            _fail(f"$.comparability.must_match[{index}]", "must not repeat a comparability field")
        matched.add(name)
    permitted = _list(comparability["permitted_variation"], "$.comparability.permitted_variation")
    varied: set[str] = set()
    for index, item in enumerate(permitted):
        path = f"$.comparability.permitted_variation[{index}]"
        entry = _object(item, path)
        _keys(
            entry,
            path,
            required={"field", "justification", "retained_as"},
            optional={"protocol_variation_plan_id"},
        )
        name = _enum(entry["field"], COMPARABILITY_FIELDS, f"{path}.field")
        if name in matched:
            _fail(path, "a field cannot be both must-match and permitted variation")
        if name in varied:
            _fail(path, "must not repeat a comparability field")
        varied.add(name)
        _string(entry["justification"], f"{path}.justification")
        _enum(entry["retained_as"], {"covariate", "limitation"}, f"{path}.retained_as")
        if name in PROTECTED_IDENTITY_FIELDS:
            if "protocol_variation_plan_id" not in entry:
                _fail(
                    path,
                    "protected setup/build variation requires a structured frozen-protocol plan reference",
                )
            _id(entry["protocol_variation_plan_id"], f"{path}.protocol_variation_plan_id")
        elif "protocol_variation_plan_id" in entry:
            _fail(
                f"{path}.protocol_variation_plan_id",
                "is only valid for configuration_identity or product_build",
            )
    undeclared = GUARDED_COMPARABILITY_FIELDS - matched - varied
    if undeclared:
        _fail(
            "$.comparability",
            f"every guarded comparability field must be declared as must-match or explicitly permitted variation; missing={sorted(undeclared)}",
        )

    experimental_unit = _unit_level(obj["experimental_unit"], "$.experimental_unit")
    resampling_unit = _unit_level(obj["resampling_unit"], "$.resampling_unit")
    if experimental_unit in FORBIDDEN_EXPERIMENTAL_UNITS:
        _fail(
            "$.experimental_unit",
            "telemetry frames and single events inside one opportunity are never independent experimental units",
        )
    if not at_or_above(resampling_unit, experimental_unit):
        _fail("$.resampling_unit", "must sit at or above the experimental unit")

    factor = _object(obj["factor"], "$.factor")
    _keys(factor, "$.factor", required={"factor_id", "varies_at", "arms"})
    _id(factor["factor_id"], "$.factor.factor_id")
    varies_at = _unit_level(factor["varies_at"], "$.factor.varies_at")
    if not at_or_above(resampling_unit, varies_at):
        _fail(
            "$.resampling_unit",
            "must sit at or above the level at which the compared factor varies; nested observations are not independent evidence about it",
        )
    arms = _list(factor["arms"], "$.factor.arms", nonempty=True)
    if len(arms) != 2:
        _fail("$.factor.arms", "exactly one baseline and one intervention arm are required")
    seen_arms: set[str] = set()
    seen_conditions: set[str] = set()
    for index, item in enumerate(arms):
        path = f"$.factor.arms[{index}]"
        arm = _object(item, path)
        _keys(arm, path, required={"arm", "condition_ids", "coaching_state", "protocol_condition"})
        name = _enum(arm["arm"], ARMS, f"{path}.arm")
        if name in seen_arms:
            _fail(path, "each arm may appear once")
        seen_arms.add(name)
        for condition in _unique_ids(arm["condition_ids"], f"{path}.condition_ids"):
            if condition in seen_conditions:
                _fail(f"{path}.condition_ids", "a condition may belong to only one arm")
            seen_conditions.add(condition)
        _enum(arm["coaching_state"], COACHING_STATES, f"{path}.coaching_state")
        _string(arm["protocol_condition"], f"{path}.protocol_condition")
    if seen_arms != ARMS:
        _fail("$.factor.arms", "exactly one baseline and one intervention arm are required")

    metric = _object(obj["unit_metric"], "$.unit_metric")
    _keys(
        metric,
        "$.unit_metric",
        required={"metric_id", "version", "sha256", "directionality", "unit", "extractor"},
    )
    _id(metric["metric_id"], "$.unit_metric.metric_id")
    _string(metric["version"], "$.unit_metric.version")
    _sha(metric["sha256"], "$.unit_metric.sha256")
    _enum(metric["directionality"], DIRECTIONALITIES, "$.unit_metric.directionality")
    _string(metric["unit"], "$.unit_metric.unit")
    extractor = _extractor(metric["extractor"], "$.unit_metric.extractor")

    aggregation = _object(obj["aggregation"], "$.aggregation")
    _keys(aggregation, "$.aggregation", required={"method", "minimum_source_records", "dispersion"})
    method = _enum(aggregation["method"], AGGREGATION_METHODS, "$.aggregation.method")
    minimum_records = _integer(
        aggregation["minimum_source_records"], "$.aggregation.minimum_source_records", minimum=1
    )
    dispersion = _enum(
        aggregation["dispersion"],
        {"median_absolute_deviation", "not_applicable"},
        "$.aggregation.dispersion",
    )
    if method == "single_record":
        if minimum_records != 1:
            _fail("$.aggregation.minimum_source_records", "single-record aggregation summarizes exactly one record")
        if dispersion != "not_applicable":
            _fail("$.aggregation.dispersion", "single-record aggregation has no within-unit dispersion")
    elif dispersion == "not_applicable":
        _fail(
            "$.aggregation.dispersion",
            "summarizing repeated observations must preserve within-unit variability",
        )
    if extractor["kind"] == "record_field" and method != "single_record":
        _fail("$.aggregation.method", "a single record field is summarized as single_record")
    if extractor["kind"] != "record_field" and method == "single_record":
        _fail("$.aggregation.method", "aggregating records within a segment requires a summary method")

    pairing = _object(obj["pairing"], "$.pairing")
    _keys(pairing, "$.pairing", required={"kind", "key", "unpaired_justification"})
    pairing_kind = _enum(pairing["kind"], {"paired", "unpaired"}, "$.pairing.kind")
    key = _list(pairing["key"], "$.pairing.key", nonempty=True)
    seen_key: set[str] = set()
    for index, field in enumerate(key):
        name = _enum(field, PAIR_KEY_FIELDS, f"$.pairing.key[{index}]")
        if name in seen_key:
            _fail(f"$.pairing.key[{index}]", "must not repeat a pairing field")
        seen_key.add(name)
    if pairing_kind == "unpaired":
        _string(pairing["unpaired_justification"], "$.pairing.unpaired_justification")
    elif pairing["unpaired_justification"] is not None:
        _fail("$.pairing.unpaired_justification", "must be null for a paired design")

    for name in ("inclusion_rules", "exclusion_rules"):
        rules = _list(obj[name], f"$.{name}", nonempty=True)
        seen_rule_ids: set[str] = set()
        for index, item in enumerate(rules):
            rule = _rule(item, f"$.{name}[{index}]")
            if rule["rule_id"] in seen_rule_ids:
                _fail(f"$.{name}[{index}].rule_id", "must be unique within the definition")
            seen_rule_ids.add(rule["rule_id"])

    confounds = _object(obj["confounds"], "$.confounds")
    _keys(confounds, "$.confounds", required={"controlled", "measured_covariates", "unavailable"})
    for name in ("controlled", "measured_covariates", "unavailable"):
        _strings(confounds[name], f"$.confounds.{name}")

    holdout = _object(obj["holdout"], "$.holdout")
    _keys(holdout, "$.holdout", required={"policy", "reserved", "replication_scope"})
    policy = _enum(holdout["policy"], HOLDOUT_POLICIES, "$.holdout.policy")
    reserved = _list(holdout["reserved"], "$.holdout.reserved")
    seen_reserved: set[str] = set()
    for index, item in enumerate(reserved):
        identifier = _id(item, f"$.holdout.reserved[{index}]")
        if identifier in seen_reserved:
            _fail(f"$.holdout.reserved[{index}]", "must be unique")
        seen_reserved.add(identifier)
    _enum(holdout["replication_scope"], REPLICATION_SCOPES, "$.holdout.replication_scope")
    if policy == "none" and reserved:
        _fail("$.holdout.reserved", "must be empty when no holdout is reserved")
    if policy != "none" and not reserved:
        _fail("$.holdout.reserved", "a reserved holdout policy requires reserved identifiers")
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj


def _attrition_entry(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={"level", "stage", "rule_id", "disposition", "considered", "excluded", "remaining", "detail"},
    )
    _enum(obj["level"], {"record", "unit", "pair"}, f"{path}.level")
    _string(obj["stage"], f"{path}.stage")
    if obj["rule_id"] is not None:
        _id(obj["rule_id"], f"{path}.rule_id")
    _enum(obj["disposition"], ATTRITION_DISPOSITIONS, f"{path}.disposition")
    considered = _integer(obj["considered"], f"{path}.considered", minimum=0)
    excluded = _integer(obj["excluded"], f"{path}.excluded", minimum=0)
    remaining = _integer(obj["remaining"], f"{path}.remaining", minimum=0)
    if excluded > considered:
        _fail(path, "cannot exclude more evidence than was considered")
    if considered - excluded != remaining:
        _fail(path, "considered minus excluded must equal remaining; evidence is never silently discarded")
    _string(obj["detail"], f"{path}.detail", nonempty=False)
    return obj


def _evidence_unit(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={
            "unit_id", "unit_level", "dataset_id", "session_id", "block_id", "condition_id",
            "arm", "pair_key", "order_index", "value", "unit_of_measure", "aggregation_method",
            "source_records_considered", "source_records_used", "source_records_missing",
            "within_unit_dispersion", "provenance", "covariates", "holdout",
        },
    )
    _id(obj["unit_id"], f"{path}.unit_id")
    _unit_level(obj["unit_level"], f"{path}.unit_level")
    for name in ("dataset_id", "session_id", "block_id", "condition_id"):
        _id(obj[name], f"{path}.{name}")
    _enum(obj["arm"], ARMS, f"{path}.arm")
    _string(obj["pair_key"], f"{path}.pair_key")
    _integer(obj["order_index"], f"{path}.order_index", minimum=0)
    _number(obj["value"], f"{path}.value")
    _string(obj["unit_of_measure"], f"{path}.unit_of_measure")
    _enum(obj["aggregation_method"], AGGREGATION_METHODS, f"{path}.aggregation_method")
    considered = _integer(obj["source_records_considered"], f"{path}.source_records_considered", minimum=0)
    used = _integer(obj["source_records_used"], f"{path}.source_records_used", minimum=1)
    missing = _integer(obj["source_records_missing"], f"{path}.source_records_missing", minimum=0)
    if used + missing != considered:
        _fail(path, "used and missing source records must account for every record considered")
    if obj["within_unit_dispersion"] is not None:
        if _number(obj["within_unit_dispersion"], f"{path}.within_unit_dispersion") < 0:
            _fail(f"{path}.within_unit_dispersion", "must be non-negative")
    elif obj["aggregation_method"] != "single_record":
        _fail(
            f"{path}.within_unit_dispersion",
            "summarized units must preserve within-unit variability",
        )
    _enum(obj["provenance"], {"measured", "derived", "estimated"}, f"{path}.provenance")
    covariates = _object(obj["covariates"], f"{path}.covariates")
    for name, item in covariates.items():
        _string(name, f"{path}.covariates key")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            _fail(f"{path}.covariates.{name}", "must be a scalar or null")
    _boolean(obj["holdout"], f"{path}.holdout")
    return obj


def validate_evidence_set(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.EVIDENCE_SET)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "evidence_set_id", "version", "built_at", "synthetic",
            "classification", "method_id", "evidence_set_sha256", "definition", "definition_sha256",
            "segment_definition", "segment_definition_sha256", "protocol", "datasets",
            "comparability", "units_declaration", "attrition", "post_hoc_exclusions_present",
            "counts", "units", "pairs", "unpaired_unit_ids", "holdout", "confounds",
            "structural_interpretation_ceiling", "code_identity", "integrity", "limitations",
        },
    )
    _id(obj["evidence_set_id"], "$.evidence_set_id")
    _string(obj["version"], "$.version")
    _timestamp(obj["built_at"], "$.built_at")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if obj["classification"] != "comparable_evidence_not_scientific_evidence":
        _fail("$.classification", "an evidence set is comparable evidence, never scientific evidence")
    if obj["method_id"] != versions.EVIDENCE_METHOD_ID:
        _fail("$.method_id", f"must be {versions.EVIDENCE_METHOD_ID!r}")
    _sha(obj["evidence_set_sha256"], "$.evidence_set_sha256")
    definition = validate_evidence_set_definition(obj["definition"])
    _sha(obj["definition_sha256"], "$.definition_sha256")
    segment = validate_segment_definition(obj["segment_definition"])
    _sha(obj["segment_definition_sha256"], "$.segment_definition_sha256")
    if obj["segment_definition_sha256"] != definition["segment"]["sha256"]:
        _fail("$.segment_definition_sha256", "must equal the segment hash bound by the definition")
    if (
        segment["segment_definition_id"] != definition["segment"]["segment_definition_id"]
        or segment["version"] != definition["segment"]["version"]
    ):
        _fail("$.segment_definition", "identity must match the definition binding")
    if obj["evidence_set_id"] != definition["evidence_set_id"] or obj["version"] != definition["version"]:
        _fail("$", "evidence-set identity must match its definition")
    if synthetic != definition["synthetic"]:
        _fail("$.synthetic", "must agree with the definition synthetic classification")

    protocol = _object(obj["protocol"], "$.protocol")
    _keys(
        protocol,
        "$.protocol",
        required={
            "freeze_id", "freeze_sha256", "protocol_id", "protocol_version", "protocol_sha256",
            "randomization_strategy", "collection_classification", "minimum_sample_requirements_state",
        },
    )
    _id(protocol["freeze_id"], "$.protocol.freeze_id")
    for name in ("freeze_sha256", "protocol_sha256"):
        _sha(protocol[name], f"$.protocol.{name}")
    _id(protocol["protocol_id"], "$.protocol.protocol_id")
    _string(protocol["protocol_version"], "$.protocol.protocol_version")
    _enum(
        protocol["randomization_strategy"],
        {"randomized", "counterbalanced", "fixed", "not_applicable"},
        "$.protocol.randomization_strategy",
    )
    _enum(
        protocol["collection_classification"],
        {"observational", "experimental"},
        "$.protocol.collection_classification",
    )
    _enum(
        protocol["minimum_sample_requirements_state"],
        {"to_be_determined", "declared"},
        "$.protocol.minimum_sample_requirements_state",
    )
    if protocol["freeze_id"] != definition["protocol"]["freeze_id"] or protocol["freeze_sha256"] != definition["protocol"]["freeze_sha256"]:
        _fail("$.protocol", "must match the frozen protocol bound by the definition")

    datasets = _list(obj["datasets"], "$.datasets", nonempty=True)
    seen_datasets: set[str] = set()
    condition_to_arm = {
        condition: arm["arm"]
        for arm in definition["factor"]["arms"]
        for condition in arm["condition_ids"]
    }
    for index, item in enumerate(datasets):
        path = f"$.datasets[{index}]"
        dataset = _object(item, path)
        _keys(
            dataset,
            path,
            required={
                "dataset_id", "fingerprint", "normalized_manifest_sha256", "records_sha256",
                "synthetic", "session_id", "participant", "simulator", "car", "track", "layout",
                "condition_id", "block_id", "arm", "coaching_state", "configuration_identity",
                "product_build", "normalization_contract", "records_considered",
            },
        )
        dataset_id = _id(dataset["dataset_id"], f"{path}.dataset_id")
        if dataset_id in seen_datasets:
            _fail(path, "a dataset may contribute to an evidence set only once")
        seen_datasets.add(dataset_id)
        for name in ("fingerprint", "normalized_manifest_sha256", "records_sha256"):
            _sha(dataset[name], f"{path}.{name}")
        if _boolean(dataset["synthetic"], f"{path}.synthetic") != synthetic:
            _fail(f"{path}.synthetic", "synthetic and real evidence may never be combined")
        _id(dataset["session_id"], f"{path}.session_id")
        for name in ("participant", "simulator", "car", "track", "layout", "normalization_contract"):
            _string(dataset[name], f"{path}.{name}")
        condition_id = _id(dataset["condition_id"], f"{path}.condition_id")
        _id(dataset["block_id"], f"{path}.block_id")
        arm = _enum(dataset["arm"], ARMS, f"{path}.arm")
        if condition_to_arm.get(condition_id) != arm:
            _fail(f"{path}.arm", "must match the arm the definition assigns to this condition")
        _enum(dataset["coaching_state"], COACHING_STATES, f"{path}.coaching_state")
        for name in ("configuration_identity", "product_build"):
            if dataset[name] is not None:
                _string(dataset[name], f"{path}.{name}")
        _integer(dataset["records_considered"], f"{path}.records_considered", minimum=0)

    comparability = _object(obj["comparability"], "$.comparability")
    _keys(
        comparability,
        "$.comparability",
        required={
            "status", "must_match_fields", "observed_values", "permitted_variation",
            "violations", "limitations", "identity_limitations", "covariate_fields",
        },
    )
    status = _enum(comparability["status"], COMPARABILITY_STATUSES, "$.comparability.status")
    _strings(comparability["must_match_fields"], "$.comparability.must_match_fields")
    observed = _object(comparability["observed_values"], "$.comparability.observed_values")
    for name, values in observed.items():
        _string(name, "$.comparability.observed_values key")
        _strings(values, f"$.comparability.observed_values.{name}")
    _list(comparability["permitted_variation"], "$.comparability.permitted_variation")
    violations = _strings(comparability["violations"], "$.comparability.violations")
    limitations = _strings(comparability["limitations"], "$.comparability.limitations")
    identity_limitations = _strings(
        comparability["identity_limitations"], "$.comparability.identity_limitations"
    )
    _strings(comparability["covariate_fields"], "$.comparability.covariate_fields")
    if any(item not in limitations for item in identity_limitations):
        _fail("$.comparability.identity_limitations", "must be a subset of comparability limitations")
    if violations and status == "adequate":
        _fail("$.comparability.status", "recorded comparability violations cannot be adequate")
    if status == "inadequate" and not violations:
        _fail("$.comparability.violations", "an inadequate assessment must record what failed")

    expected_must_match = sorted(definition["comparability"]["must_match"])
    if comparability["must_match_fields"] != expected_must_match:
        _fail("$.comparability.must_match_fields", "must exactly repeat the definition's must-match fields")
    expected_permitted = sorted(
        definition["comparability"]["permitted_variation"], key=lambda item: item["field"]
    )
    if comparability["permitted_variation"] != expected_permitted:
        _fail("$.comparability.permitted_variation", "must exactly repeat the definition's permitted variation")
    expected_covariates = sorted(
        item["field"] for item in expected_permitted if item["retained_as"] == "covariate"
    )
    if comparability["covariate_fields"] != expected_covariates:
        _fail("$.comparability.covariate_fields", "must exactly reflect declared covariates")

    expected_observed: dict[str, list[str]] = {}
    for field in sorted(GUARDED_COMPARABILITY_FIELDS):
        if field == "protocol_version":
            values = [protocol["protocol_version"]]
        elif field == "segment_definition":
            values = [f"{segment['segment_definition_id']}@{segment['version']}"]
        elif field == "metric_definition":
            metric = definition["unit_metric"]
            values = [f"{metric['metric_id']}@{metric['version']}"]
        else:
            dataset_field = {
                "condition_semantics": "condition_id",
            }.get(field, field)
            values = [
                "<unavailable>" if dataset[dataset_field] is None else str(dataset[dataset_field])
                for dataset in datasets
            ]
        expected_observed[field] = sorted(set(values))
    if observed != expected_observed:
        _fail("$.comparability.observed_values", "must be recomputed exactly from the bound datasets and definitions")

    must_match_missing = False
    protected_identity_issue = bool(
        PROTECTED_IDENTITY_FIELDS
        & {item["field"] for item in expected_permitted}
    )
    for field in expected_must_match:
        values = expected_observed[field]
        real = [item for item in values if item != "<unavailable>"]
        if len(real) > 1:
            _fail(
                "$.comparability.observed_values",
                f"must-match field {field!r} has incompatible values {real}",
            )
        if "<unavailable>" in values:
            must_match_missing = True
            if field in PROTECTED_IDENTITY_FIELDS:
                protected_identity_issue = True

    expected_factor_variation = {"condition_semantics"}
    if len({arm["coaching_state"] for arm in definition["factor"]["arms"]}) > 1:
        expected_factor_variation.add("coaching_state")
    nuisance_limitation = False
    for entry in expected_permitted:
        values = expected_observed[entry["field"]]
        real = [item for item in values if item != "<unavailable>"]
        if (
            entry["field"] in PROTECTED_IDENTITY_FIELDS
            or "<unavailable>" in values
            or (len(real) > 1 and entry["field"] not in expected_factor_variation)
        ):
            nuisance_limitation = True
    arms_present = {dataset["arm"] for dataset in datasets}
    expected_status = (
        "inadequate"
        if len(arms_present) < 2
        else "limited"
        if must_match_missing or nuisance_limitation
        else "adequate"
    )
    if status != expected_status:
        _fail("$.comparability.status", f"must be {expected_status!r} for the observed comparison")
    if must_match_missing and not violations:
        _fail("$.comparability.violations", "unavailable must-match identity must be recorded as a violation")
    if nuisance_limitation and not limitations:
        _fail("$.comparability.limitations", "permitted nuisance variation must be recorded as a limitation")
    if bool(identity_limitations) != protected_identity_issue:
        _fail(
            "$.comparability.identity_limitations",
            "must explicitly record every protected setup/build comparability limitation",
        )

    declaration = _object(obj["units_declaration"], "$.units_declaration")
    _keys(
        declaration,
        "$.units_declaration",
        required={"experimental_unit", "resampling_unit", "factor_varies_at", "pseudoreplication_guard"},
    )
    experimental_unit = _unit_level(declaration["experimental_unit"], "$.units_declaration.experimental_unit")
    resampling_unit = _unit_level(declaration["resampling_unit"], "$.units_declaration.resampling_unit")
    factor_varies_at = _unit_level(declaration["factor_varies_at"], "$.units_declaration.factor_varies_at")
    if declaration["pseudoreplication_guard"] != "resampling_unit_at_or_above_factor_variation_level":
        _fail("$.units_declaration.pseudoreplication_guard", "unsupported guard declaration")
    if experimental_unit != definition["experimental_unit"] or resampling_unit != definition["resampling_unit"]:
        _fail("$.units_declaration", "must repeat the declared experimental and resampling units")
    if factor_varies_at != definition["factor"]["varies_at"]:
        _fail("$.units_declaration.factor_varies_at", "must repeat the declared factor variation level")
    if experimental_unit in FORBIDDEN_EXPERIMENTAL_UNITS:
        _fail("$.units_declaration.experimental_unit", "nested frames and events are never independent evidence")
    if not at_or_above(resampling_unit, factor_varies_at):
        _fail("$.units_declaration.resampling_unit", "must sit at or above the factor variation level")

    attrition = _list(obj["attrition"], "$.attrition", nonempty=True)
    previous_remaining: dict[str, int] = {}
    seen_levels: list[str] = []
    post_hoc = False
    for index, item in enumerate(attrition):
        entry = _attrition_entry(item, f"$.attrition[{index}]")
        level = entry["level"]
        if level not in previous_remaining:
            if level in seen_levels:
                _fail(f"$.attrition[{index}].level", "each funnel level must be reported contiguously")
            seen_levels.append(level)
        elif entry["considered"] != previous_remaining[level]:
            _fail(
                f"$.attrition[{index}].considered",
                "each stage must consider exactly what the previous stage at its level left",
            )
        previous_remaining[level] = entry["remaining"]
        if entry["disposition"] == "post_hoc_exclusion":
            post_hoc = True
    if seen_levels != [level for level in ("record", "unit", "pair") if level in previous_remaining]:
        _fail("$.attrition", "funnel levels must be reported from records through units to pairs")
    if _boolean(obj["post_hoc_exclusions_present"], "$.post_hoc_exclusions_present") != post_hoc:
        _fail("$.post_hoc_exclusions_present", "must reflect whether any stage recorded a post-hoc exclusion")

    counts = _object(obj["counts"], "$.counts")
    _keys(
        counts,
        "$.counts",
        required={
            "source_records", "included_units", "baseline_units", "intervention_units", "pairs",
            "unpaired_units", "holdout_units", "participants", "sessions", "blocks",
            "resampling_clusters",
        },
    )
    for name in counts:
        _integer(counts[name], f"$.counts.{name}", minimum=0)

    units = _list(obj["units"], "$.units")
    seen_units: set[str] = set()
    ordered_ids: list[str] = []
    baseline = intervention = holdout_units = 0
    for index, item in enumerate(units):
        unit = _evidence_unit(item, f"$.units[{index}]")
        if unit["unit_id"] in seen_units:
            _fail(f"$.units[{index}].unit_id", "must be unique")
        seen_units.add(unit["unit_id"])
        ordered_ids.append(unit["unit_id"])
        if unit["unit_level"] != experimental_unit:
            _fail(f"$.units[{index}].unit_level", "every unit must sit at the declared experimental unit")
        if unit["dataset_id"] not in seen_datasets:
            _fail(f"$.units[{index}].dataset_id", "must reference a bound dataset")
        if unit["arm"] == "baseline":
            baseline += 1
        else:
            intervention += 1
        if unit["holdout"]:
            holdout_units += 1
    if ordered_ids != sorted(ordered_ids):
        _fail("$.units", "units must be serialized in lexicographic unit_id order")
    if counts["included_units"] != len(units):
        _fail("$.counts.included_units", "must equal the number of preserved units")
    if counts["baseline_units"] != baseline or counts["intervention_units"] != intervention:
        _fail("$.counts", "arm counts must match the preserved units")
    if counts["holdout_units"] != holdout_units:
        _fail("$.counts.holdout_units", "must match the units reserved for replication")

    pairs = _list(obj["pairs"], "$.pairs")
    seen_pairs: set[str] = set()
    paired_units: set[str] = set()
    ordered_pair_ids: list[str] = []
    for index, item in enumerate(pairs):
        path = f"$.pairs[{index}]"
        pair = _object(item, path)
        _keys(
            pair,
            path,
            required={"pair_id", "pair_key", "cluster_id", "baseline_unit_id", "intervention_unit_id", "holdout"},
        )
        pair_id = _id(pair["pair_id"], f"{path}.pair_id")
        if pair_id in seen_pairs:
            _fail(path, "pair identity must be unique")
        seen_pairs.add(pair_id)
        ordered_pair_ids.append(pair_id)
        _string(pair["pair_key"], f"{path}.pair_key")
        _string(pair["cluster_id"], f"{path}.cluster_id")
        for name in ("baseline_unit_id", "intervention_unit_id"):
            unit_id = _id(pair[name], f"{path}.{name}")
            if unit_id not in seen_units:
                _fail(f"{path}.{name}", "must reference a preserved unit")
            if unit_id in paired_units:
                _fail(f"{path}.{name}", "a unit may belong to at most one pair")
            paired_units.add(unit_id)
        _boolean(pair["holdout"], f"{path}.holdout")
    if ordered_pair_ids != sorted(ordered_pair_ids):
        _fail("$.pairs", "pairs must be serialized in lexicographic pair_id order")
    if counts["pairs"] != len(pairs):
        _fail("$.counts.pairs", "must equal the number of formed pairs")
    if definition["pairing"]["kind"] == "unpaired" and pairs:
        _fail("$.pairs", "an unpaired design forms no pairs")

    unpaired = _list(obj["unpaired_unit_ids"], "$.unpaired_unit_ids")
    seen_unpaired: set[str] = set()
    for index, item in enumerate(unpaired):
        unit_id = _id(item, f"$.unpaired_unit_ids[{index}]")
        if unit_id not in seen_units:
            _fail(f"$.unpaired_unit_ids[{index}]", "must reference a preserved unit")
        if unit_id in paired_units:
            _fail(f"$.unpaired_unit_ids[{index}]", "a paired unit is not unpaired")
        if unit_id in seen_unpaired:
            _fail(f"$.unpaired_unit_ids[{index}]", "must be unique")
        seen_unpaired.add(unit_id)
    if list(unpaired) != sorted(unpaired):
        _fail("$.unpaired_unit_ids", "must be serialized in lexicographic order")
    if counts["unpaired_units"] != len(unpaired):
        _fail("$.counts.unpaired_units", "must equal the number of unpaired units")
    if len(paired_units) + len(seen_unpaired) != len(seen_units):
        _fail("$", "every preserved unit must be either paired or explicitly unpaired")

    holdout = _object(obj["holdout"], "$.holdout")
    _keys(
        holdout,
        "$.holdout",
        required={"policy", "reserved", "replication_scope", "reserved_unit_ids", "primary_scope_excludes_holdout"},
    )
    _enum(holdout["policy"], HOLDOUT_POLICIES, "$.holdout.policy")
    _list(holdout["reserved"], "$.holdout.reserved")
    _string(holdout["replication_scope"], "$.holdout.replication_scope")
    reserved_units = _list(holdout["reserved_unit_ids"], "$.holdout.reserved_unit_ids")
    for index, item in enumerate(reserved_units):
        unit_id = _id(item, f"$.holdout.reserved_unit_ids[{index}]")
        if unit_id not in seen_units:
            _fail(f"$.holdout.reserved_unit_ids[{index}]", "must reference a preserved unit")
    if holdout["primary_scope_excludes_holdout"] is not True:
        _fail(
            "$.holdout.primary_scope_excludes_holdout",
            "the primary analysis must never inspect reserved replication evidence",
        )
    if holdout["policy"] != definition["holdout"]["policy"]:
        _fail("$.holdout.policy", "must repeat the declared holdout policy")
    if len(reserved_units) != holdout_units:
        _fail("$.holdout.reserved_unit_ids", "must enumerate exactly the units flagged as holdout")

    confounds = _object(obj["confounds"], "$.confounds")
    _keys(confounds, "$.confounds", required={"controlled", "measured_covariates", "unavailable"})
    for name in ("controlled", "measured_covariates", "unavailable"):
        _strings(confounds[name], f"$.confounds.{name}")

    structural_ceiling = _enum(
        obj["structural_interpretation_ceiling"],
        CEILING_SET,
        "$.structural_interpretation_ceiling",
    )
    if protected_identity_issue and structural_ceiling == "causal_candidate":
        _fail(
            "$.structural_interpretation_ceiling",
            "unavailable or deliberately varied setup/build identity cannot support a causal-candidate ceiling",
        )
    _code_identity(obj["code_identity"], "$.code_identity")
    integrity = _object(obj["integrity"], "$.integrity")
    _keys(
        integrity,
        "$.integrity",
        required={"datasets_verified", "records_streamed", "segment_applicability_verified", "deterministic_ordering"},
    )
    for name in ("datasets_verified", "segment_applicability_verified"):
        if integrity[name] is not True:
            _fail(f"$.integrity.{name}", "evidence sets may only be built from verified inputs")
    _integer(integrity["records_streamed"], "$.integrity.records_streamed", minimum=0)
    if integrity["deterministic_ordering"] != "unit_id_lexicographic":
        _fail("$.integrity.deterministic_ordering", "unsupported ordering guarantee")
    _strings(obj["limitations"], "$.limitations")
    return obj
