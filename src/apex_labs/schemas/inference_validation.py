"""Runtime validation for preregistered inferential analyses and their runs.

`apex-labs.analysis-definition/v1` is untouched by this module and remains
descriptive-observational only. Inference is a separately named contract so
that a descriptive definition can never be quietly promoted into evidence for
a hypothesis test.
"""

from __future__ import annotations

from typing import Any

from apex_labs.schemas import versions
from apex_labs.schemas.research_validation import _code_identity
from apex_labs.schemas.science_vocabulary import (
    CEILING_SET,
    FORBIDDEN_EXPERIMENTAL_UNITS,
    REPLICATION_SCOPES,
    UNIT_LEVEL_SET,
    at_or_above,
    ceiling_at_or_below,
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

CLASSIFICATIONS = {"confirmatory", "exploratory"}
COMPARISON_ROLES = {"primary", "secondary", "exploratory"}
COMPARISON_METHODS = {"paired_difference", "unpaired_difference", "trend", "consistency"}
DIRECTIONALITIES = {
    "decrease_is_improvement",
    "increase_is_improvement",
    "two_sided_no_preferred_direction",
}
EFFECT_SIZES = {
    "median_paired_difference",
    "mean_paired_difference",
    "median_difference",
    "mean_difference",
    "theil_sen_slope",
    "dispersion_ratio",
}
METHOD_EFFECT_SIZES = {
    "paired_difference": {"median_paired_difference", "mean_paired_difference"},
    "unpaired_difference": {"median_difference", "mean_difference"},
    "trend": {"theil_sen_slope"},
    "consistency": {"dispersion_ratio"},
}
FAMILY_ROLES = {"confirmatory_primary", "confirmatory_secondary", "exploratory"}
CORRECTIONS = {"holm_bonferroni", "benjamini_hochberg", "none"}
DECLARATION_SOURCES = {"frozen_protocol", "documented_pilot", "not_declared"}
UNCERTAINTY_METHODS = {"deterministic_cluster_percentile_bootstrap", "none"}
FALSIFICATION_KINDS = {
    "leave_one_unit_out",
    "leave_one_cluster_out",
    "outlier_dependence",
    "order_effect_early_versus_late",
    "isolation_by_cluster",
    "direction_sign_stability",
}
REPLICATION_STATES = {"not_required", "required_before_validation", "this_run_is_the_replication"}
SUFFICIENCY_STATUSES = {"sufficient", "insufficient", "undetermined"}


def _unit_level(value: Any, path: str) -> str:
    return _enum(value, UNIT_LEVEL_SET, path)


def _metric_binding(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(obj, path, required={"metric_id", "version", "sha256"})
    _id(obj["metric_id"], f"{path}.metric_id")
    _string(obj["version"], f"{path}.version")
    _sha(obj["sha256"], f"{path}.sha256")
    return obj


def _probability(value: Any, path: str) -> float | int:
    number = _number(value, path)
    if not 0 <= number <= 1:
        _fail(path, "must lie within [0, 1]")
    return number


def validate_inferential_analysis_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.INFERENTIAL_ANALYSIS_DEFINITION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "analysis_id", "version", "title", "scientific_question",
            "hypothesis", "null_hypothesis", "classification", "synthetic", "protocol",
            "evidence_set", "evidence_scope", "primary_metric", "secondary_metrics",
            "experimental_unit", "resampling_unit", "grouping", "comparisons", "family",
            "uncertainty", "missing_data_policy", "outlier_policy", "sufficiency_rule",
            "replication_policy", "interpretation_ceiling", "falsification_tests", "limitations",
        },
    )
    _id(obj["analysis_id"], "$.analysis_id")
    for name in ("version", "title", "scientific_question", "hypothesis", "null_hypothesis"):
        _string(obj[name], f"$.{name}")
    classification = _enum(obj["classification"], CLASSIFICATIONS, "$.classification")
    _boolean(obj["synthetic"], "$.synthetic")

    protocol = _object(obj["protocol"], "$.protocol")
    _keys(protocol, "$.protocol", required={"freeze_id", "freeze_sha256", "experiment_id", "experiment_version"})
    _id(protocol["freeze_id"], "$.protocol.freeze_id")
    _sha(protocol["freeze_sha256"], "$.protocol.freeze_sha256")
    _id(protocol["experiment_id"], "$.protocol.experiment_id")
    _string(protocol["experiment_version"], "$.protocol.experiment_version")

    evidence = _object(obj["evidence_set"], "$.evidence_set")
    _keys(evidence, "$.evidence_set", required={"evidence_set_id", "version", "definition_sha256"})
    _id(evidence["evidence_set_id"], "$.evidence_set.evidence_set_id")
    _string(evidence["version"], "$.evidence_set.version")
    _sha(evidence["definition_sha256"], "$.evidence_set.definition_sha256")
    scope = _enum(obj["evidence_scope"], {"primary", "holdout"}, "$.evidence_scope")

    _metric_binding(obj["primary_metric"], "$.primary_metric")
    secondary = _list(obj["secondary_metrics"], "$.secondary_metrics")
    for index, item in enumerate(secondary):
        _metric_binding(item, f"$.secondary_metrics[{index}]")

    experimental_unit = _unit_level(obj["experimental_unit"], "$.experimental_unit")
    resampling_unit = _unit_level(obj["resampling_unit"], "$.resampling_unit")
    if experimental_unit in FORBIDDEN_EXPERIMENTAL_UNITS:
        _fail(
            "$.experimental_unit",
            "telemetry frames and single events inside one opportunity are never independent experimental units",
        )
    if not at_or_above(resampling_unit, experimental_unit):
        _fail("$.resampling_unit", "must sit at or above the experimental unit")

    grouping = _object(obj["grouping"], "$.grouping")
    _keys(grouping, "$.grouping", required={"kind", "unpaired_justification"})
    grouping_kind = _enum(grouping["kind"], {"paired", "unpaired"}, "$.grouping.kind")
    if grouping_kind == "unpaired":
        _string(grouping["unpaired_justification"], "$.grouping.unpaired_justification")
    elif grouping["unpaired_justification"] is not None:
        _fail("$.grouping.unpaired_justification", "must be null for a paired design")

    comparisons = _list(obj["comparisons"], "$.comparisons", nonempty=True)
    seen: set[str] = set()
    primary_count = 0
    for index, item in enumerate(comparisons):
        path = f"$.comparisons[{index}]"
        comparison = _object(item, path)
        _keys(
            comparison,
            path,
            required={
                "comparison_id", "role", "method", "metric_id", "directionality",
                "effect_size", "practical_threshold", "subset",
            },
        )
        subset = comparison["subset"]
        if subset is not None:
            subset_path = f"{path}.subset"
            _keys(_object(subset, subset_path), subset_path, required={"field", "value"})
            _enum(
                subset["field"],
                {"pair_key", "block_id", "session_id", "condition_id"},
                f"{subset_path}.field",
            )
            _string(subset["value"], f"{subset_path}.value")
            if classification == "confirmatory" and comparison.get("role") == "primary":
                _fail(
                    subset_path,
                    "a confirmatory primary comparison is evaluated over the whole preregistered evidence set, not a subgroup",
                )
        comparison_id = _id(comparison["comparison_id"], f"{path}.comparison_id")
        if comparison_id in seen:
            _fail(f"{path}.comparison_id", "must be unique within the definition")
        seen.add(comparison_id)
        role = _enum(comparison["role"], COMPARISON_ROLES, f"{path}.role")
        if role == "primary":
            primary_count += 1
        method = _enum(comparison["method"], COMPARISON_METHODS, f"{path}.method")
        _id(comparison["metric_id"], f"{path}.metric_id")
        _enum(comparison["directionality"], DIRECTIONALITIES, f"{path}.directionality")
        effect_size = _enum(comparison["effect_size"], EFFECT_SIZES, f"{path}.effect_size")
        if effect_size not in METHOD_EFFECT_SIZES[method]:
            _fail(f"{path}.effect_size", f"is not defined for method {method!r}")
        if method == "paired_difference" and grouping_kind != "paired":
            _fail(f"{path}.method", "a paired comparison requires a paired design")
        if method == "unpaired_difference" and grouping_kind != "unpaired":
            _fail(f"{path}.method", "an unpaired comparison requires an explicitly unpaired design")
        if method == "trend" and grouping_kind != "paired":
            _fail(
                f"{path}.method",
                "trend is computed over ordered paired differences, so it requires a paired design",
            )
        if classification == "confirmatory" and role == "exploratory":
            _fail(f"{path}.role", "a confirmatory definition contains no exploratory comparison")
        if classification == "exploratory" and role != "exploratory":
            _fail(f"{path}.role", "an exploratory definition contains only exploratory comparisons")
        threshold = _object(comparison["practical_threshold"], f"{path}.practical_threshold")
        _keys(threshold, f"{path}.practical_threshold", required={"magnitude", "unit", "source", "rationale"})
        magnitude = _number(threshold["magnitude"], f"{path}.practical_threshold.magnitude")
        if magnitude < 0:
            _fail(f"{path}.practical_threshold.magnitude", "must be non-negative")
        _string(threshold["unit"], f"{path}.practical_threshold.unit")
        threshold_source = _enum(threshold["source"], DECLARATION_SOURCES, f"{path}.practical_threshold.source")
        _string(threshold["rationale"], f"{path}.practical_threshold.rationale")
        if classification == "confirmatory" and threshold_source == "not_declared":
            _fail(
                f"{path}.practical_threshold.source",
                "a confirmatory comparison requires a preregistered or documented practical threshold",
            )
    if classification == "confirmatory" and primary_count != 1:
        _fail("$.comparisons", "a confirmatory definition declares exactly one primary comparison")
    if classification == "exploratory" and primary_count:
        _fail("$.comparisons", "an exploratory definition declares no primary comparison")

    family = _object(obj["family"], "$.family")
    _keys(family, "$.family", required={"family_id", "role", "correction", "alpha", "members"})
    _id(family["family_id"], "$.family.family_id")
    family_role = _enum(family["role"], FAMILY_ROLES, "$.family.role")
    correction = _enum(family["correction"], CORRECTIONS, "$.family.correction")
    family_alpha = _number(family["alpha"], "$.family.alpha")
    if not 0 < family_alpha < 1:
        _fail("$.family.alpha", "must lie strictly within (0, 1)")
    members = _list(family["members"], "$.family.members", nonempty=True)
    seen_members: set[str] = set()
    for index, member in enumerate(members):
        name = _id(member, f"$.family.members[{index}]")
        if name in seen_members:
            _fail(f"$.family.members[{index}]", "must be unique")
        seen_members.add(name)
    if seen_members != seen:
        _fail(
            "$.family.members",
            "family membership is fixed at definition time and must name exactly the declared comparisons",
        )
    if classification == "confirmatory" and family_role == "exploratory":
        _fail("$.family.role", "a confirmatory definition does not carry an exploratory family")
    if classification == "exploratory" and family_role != "exploratory":
        _fail("$.family.role", "an exploratory definition carries an exploratory family")
    if correction == "none" and len(seen_members) > 1:
        _fail("$.family.correction", "a family with several comparisons requires a declared correction")
    if family_role == "exploratory" and correction == "holm_bonferroni":
        _fail(
            "$.family.correction",
            "false-discovery-rate control is the declared method for a broad exploratory family",
        )
    if family_role != "exploratory" and correction == "benjamini_hochberg":
        _fail(
            "$.family.correction",
            "a small preregistered confirmatory family uses conservative familywise control",
        )

    uncertainty = _object(obj["uncertainty"], "$.uncertainty")
    _keys(
        uncertainty,
        "$.uncertainty",
        required={
            "method", "coverage_level", "bootstrap_draws", "random_seed", "resampling_unit",
            "interval_semantics", "minimum_resampling_clusters",
        },
    )
    uncertainty_method = _enum(uncertainty["method"], UNCERTAINTY_METHODS, "$.uncertainty.method")
    if uncertainty_method == "none":
        for name in ("coverage_level", "bootstrap_draws", "random_seed"):
            if uncertainty[name] is not None:
                _fail(f"$.uncertainty.{name}", "must be null when no uncertainty method is declared")
    else:
        coverage = _number(uncertainty["coverage_level"], "$.uncertainty.coverage_level")
        if not 0 < coverage < 1:
            _fail("$.uncertainty.coverage_level", "must lie strictly within (0, 1)")
        draws = _integer(uncertainty["bootstrap_draws"], "$.uncertainty.bootstrap_draws", minimum=200)
        if draws > 100000:
            _fail("$.uncertainty.bootstrap_draws", "must not exceed 100000")
        _integer(uncertainty["random_seed"], "$.uncertainty.random_seed", minimum=0)
    uncertainty_unit = _unit_level(uncertainty["resampling_unit"], "$.uncertainty.resampling_unit")
    if uncertainty_unit != resampling_unit:
        _fail("$.uncertainty.resampling_unit", "must repeat the declared resampling unit")
    _string(uncertainty["interval_semantics"], "$.uncertainty.interval_semantics")
    _integer(uncertainty["minimum_resampling_clusters"], "$.uncertainty.minimum_resampling_clusters", minimum=2)

    _enum(obj["missing_data_policy"], {"exclude_unit_and_report", "refuse_analysis"}, "$.missing_data_policy")
    _enum(
        obj["outlier_policy"],
        {"retain_all_and_report_sensitivity", "preregistered_rule_only"},
        "$.outlier_policy",
    )

    rule = _object(obj["sufficiency_rule"], "$.sufficiency_rule")
    _keys(
        rule,
        "$.sufficiency_rule",
        required={
            "source", "minimum_experimental_units", "minimum_pairs", "minimum_resampling_clusters",
            "minimum_participants", "stopping_rule", "source_declarations", "pilot_reference",
        },
    )
    rule_source = _enum(rule["source"], DECLARATION_SOURCES, "$.sufficiency_rule.source")
    minimums = {
        "minimum_experimental_units": 1,
        "minimum_pairs": 1,
        "minimum_resampling_clusters": 2,
        "minimum_participants": 1,
    }
    for name, floor in minimums.items():
        if rule[name] is not None:
            _integer(rule[name], f"$.sufficiency_rule.{name}", minimum=floor)
    _string(rule["stopping_rule"], "$.sufficiency_rule.stopping_rule")
    declarations = _strings(rule["source_declarations"], "$.sufficiency_rule.source_declarations")
    pilot = rule["pilot_reference"]
    if pilot is not None:
        _keys(_object(pilot, "$.sufficiency_rule.pilot_reference"), "$.sufficiency_rule.pilot_reference", required={"document_id", "sha256", "completed_at"})
        _id(pilot["document_id"], "$.sufficiency_rule.pilot_reference.document_id")
        _sha(pilot["sha256"], "$.sufficiency_rule.pilot_reference.sha256")
        _timestamp(pilot["completed_at"], "$.sufficiency_rule.pilot_reference.completed_at")
    if rule_source == "frozen_protocol":
        if not declarations:
            _fail(
                "$.sufficiency_rule.source_declarations",
                "protocol-sourced requirements must cite the frozen protocol declarations verbatim",
            )
        if pilot is not None:
            _fail("$.sufficiency_rule.pilot_reference", "must be null when requirements come from the frozen protocol")
    elif rule_source == "documented_pilot":
        if pilot is None:
            _fail("$.sufficiency_rule.pilot_reference", "a pilot-sourced requirement must bind its completed document")
    else:
        if any(rule[name] is not None for name in minimums):
            _fail(
                "$.sufficiency_rule",
                "undeclared requirements must not invent numeric thresholds",
            )
        if classification == "confirmatory":
            _fail(
                "$.sufficiency_rule.source",
                "confirmatory analysis requires requirements preregistered in the protocol or a completed documented pilot",
            )

    replication = _object(obj["replication_policy"], "$.replication_policy")
    _keys(replication, "$.replication_policy", required={"state", "required_scope", "holdout_inspected"})
    replication_state = _enum(replication["state"], REPLICATION_STATES, "$.replication_policy.state")
    _enum(replication["required_scope"], REPLICATION_SCOPES, "$.replication_policy.required_scope")
    if replication["holdout_inspected"] is not False:
        _fail(
            "$.replication_policy.holdout_inspected",
            "a definition may never declare that it already inspected reserved replication evidence",
        )
    if scope == "holdout" and replication_state != "this_run_is_the_replication":
        _fail("$.evidence_scope", "reserved replication evidence may only be read by a declared replication run")
    if replication_state == "this_run_is_the_replication" and scope != "holdout":
        _fail("$.evidence_scope", "a replication run reads the reserved replication evidence")

    ceiling = _enum(obj["interpretation_ceiling"], CEILING_SET, "$.interpretation_ceiling")
    if classification == "exploratory" and not ceiling_at_or_below(ceiling, "associational"):
        _fail(
            "$.interpretation_ceiling",
            "exploratory work cannot claim more than an association; it requires independent replication",
        )

    tests = _list(obj["falsification_tests"], "$.falsification_tests", nonempty=True)
    seen_tests: set[str] = set()
    for index, item in enumerate(tests):
        path = f"$.falsification_tests[{index}]"
        test = _object(item, path)
        _keys(test, path, required={"test_id", "kind", "description"})
        test_id = _id(test["test_id"], f"{path}.test_id")
        if test_id in seen_tests:
            _fail(f"{path}.test_id", "must be unique")
        seen_tests.add(test_id)
        _enum(test["kind"], FALSIFICATION_KINDS, f"{path}.kind")
        _string(test["description"], f"{path}.description")
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj


def _effect(value: Any, path: str, declared_effect_size: str) -> None:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={"effect_size", "estimate", "secondary_estimate", "n", "per_unit_differences", "group_summaries"},
    )
    if _enum(obj["effect_size"], EFFECT_SIZES, f"{path}.effect_size") != declared_effect_size:
        _fail(f"{path}.effect_size", "must repeat the declared effect-size definition")
    _number(obj["estimate"], f"{path}.estimate")
    if obj["secondary_estimate"] is not None:
        _number(obj["secondary_estimate"], f"{path}.secondary_estimate")
    count = _integer(obj["n"], f"{path}.n", minimum=0)
    differences = _list(obj["per_unit_differences"], f"{path}.per_unit_differences")
    for index, item in enumerate(differences):
        _number(item, f"{path}.per_unit_differences[{index}]")
    if declared_effect_size in {"median_paired_difference", "mean_paired_difference"} and len(differences) != count:
        _fail(f"{path}.per_unit_differences", "a paired effect must preserve one raw difference per pair")
    _object(obj["group_summaries"], f"{path}.group_summaries")


def _uncertainty_result(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={
            "method", "coverage_level", "interval", "draws", "random_seed", "resampling_unit",
            "clusters", "usable", "semantics", "unusable_reason",
        },
    )
    method = _enum(obj["method"], UNCERTAINTY_METHODS, f"{path}.method")
    if obj["coverage_level"] is not None:
        coverage = _number(obj["coverage_level"], f"{path}.coverage_level")
        if not 0 < coverage < 1:
            _fail(f"{path}.coverage_level", "must lie strictly within (0, 1)")
    interval = obj["interval"]
    if interval is not None:
        bounds = _list(interval, f"{path}.interval")
        if len(bounds) != 2:
            _fail(f"{path}.interval", "must contain exactly a lower and an upper bound")
        lower = _number(bounds[0], f"{path}.interval[0]")
        upper = _number(bounds[1], f"{path}.interval[1]")
        if lower > upper:
            _fail(f"{path}.interval", "lower bound must not exceed upper bound")
    if obj["draws"] is not None:
        _integer(obj["draws"], f"{path}.draws", minimum=0)
    if obj["random_seed"] is not None:
        _integer(obj["random_seed"], f"{path}.random_seed", minimum=0)
    _unit_level(obj["resampling_unit"], f"{path}.resampling_unit")
    _integer(obj["clusters"], f"{path}.clusters", minimum=0)
    usable = _boolean(obj["usable"], f"{path}.usable")
    _string(obj["semantics"], f"{path}.semantics")
    if usable:
        if interval is None:
            _fail(f"{path}.interval", "a usable uncertainty estimate must carry an interval")
        if obj["unusable_reason"] is not None:
            _fail(f"{path}.unusable_reason", "must be null when the estimate is usable")
        if method == "none":
            _fail(f"{path}.method", "no uncertainty method can produce a usable interval")
    else:
        _string(obj["unusable_reason"], f"{path}.unusable_reason")
        if interval is not None:
            _fail(f"{path}.interval", "an unusable estimate must not publish an interval")
    return obj


def _comparison_result(value: Any, path: str, declared: dict[str, Any]) -> str:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={
            "comparison_id", "role", "method", "metric_id", "unit_of_measure", "state",
            "subset", "effect", "uncertainty", "statistical_evidence", "practical", "notes",
        },
    )
    if obj["subset"] != declared["subset"]:
        _fail(f"{path}.subset", "must repeat the declared comparison subset")
    comparison_id = _id(obj["comparison_id"], f"{path}.comparison_id")
    for name in ("role", "method", "metric_id"):
        if obj[name] != declared[name]:
            _fail(f"{path}.{name}", f"must repeat the declared comparison {name}")
    _enum(obj["role"], COMPARISON_ROLES, f"{path}.role")
    _enum(obj["method"], COMPARISON_METHODS, f"{path}.method")
    _string(obj["unit_of_measure"], f"{path}.unit_of_measure")
    state = _enum(obj["state"], {"computed", "not_computable"}, f"{path}.state")
    if state == "computed":
        _effect(obj["effect"], f"{path}.effect", declared["effect_size"])
    elif obj["effect"] is not None:
        _fail(f"{path}.effect", "must be null when the comparison is not computable")
    _uncertainty_result(obj["uncertainty"], f"{path}.uncertainty")

    evidence = _object(obj["statistical_evidence"], f"{path}.statistical_evidence")
    _keys(evidence, f"{path}.statistical_evidence", required={"test", "raw_p_value", "detail", "interpretation"})
    test = _enum(evidence["test"], {"exact_paired_sign_test", "none"}, f"{path}.statistical_evidence.test")
    if evidence["raw_p_value"] is not None:
        _probability(evidence["raw_p_value"], f"{path}.statistical_evidence.raw_p_value")
    if test == "none" and evidence["raw_p_value"] is not None:
        _fail(f"{path}.statistical_evidence.raw_p_value", "must be null when no test was performed")
    _object(evidence["detail"], f"{path}.statistical_evidence.detail")
    _string(evidence["interpretation"], f"{path}.statistical_evidence.interpretation")

    practical = _object(obj["practical"], f"{path}.practical")
    _keys(
        practical,
        f"{path}.practical",
        required={
            "threshold_magnitude", "threshold_unit", "threshold_source",
            "estimate_exceeds_threshold", "direction_matches_hypothesis", "interval_excludes_no_effect",
        },
    )
    magnitude = _number(practical["threshold_magnitude"], f"{path}.practical.threshold_magnitude")
    if magnitude < 0:
        _fail(f"{path}.practical.threshold_magnitude", "must be non-negative")
    if magnitude != declared["practical_threshold"]["magnitude"]:
        _fail(f"{path}.practical.threshold_magnitude", "must repeat the preregistered practical threshold")
    _string(practical["threshold_unit"], f"{path}.practical.threshold_unit")
    _enum(practical["threshold_source"], DECLARATION_SOURCES, f"{path}.practical.threshold_source")
    for name in ("estimate_exceeds_threshold", "direction_matches_hypothesis", "interval_excludes_no_effect"):
        if practical[name] is not None:
            _boolean(practical[name], f"{path}.practical.{name}")
    if state == "not_computable" and any(
        practical[name] is not None
        for name in ("estimate_exceeds_threshold", "direction_matches_hypothesis")
    ):
        _fail(f"{path}.practical", "a comparison that could not be computed decides nothing")
    _strings(obj["notes"], f"{path}.notes")
    return comparison_id


def validate_inferential_analysis_run(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.INFERENTIAL_ANALYSIS_RUN)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "run_id", "created_at", "classification", "synthetic", "method_id",
            "run_sha256", "definition", "definition_sha256", "evidence_set", "analysis_state",
            "sufficiency", "comparisons", "multiplicity", "sensitivity", "confounds",
            "interpretation", "scientific_eligibility", "code_identity", "integrity", "limitations",
        },
    )
    _id(obj["run_id"], "$.run_id")
    _timestamp(obj["created_at"], "$.created_at")
    if obj["classification"] != "inferential_result_not_a_finding":
        _fail("$.classification", "an inferential result is never automatically a finding")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if obj["method_id"] != versions.INFERENTIAL_METHOD_ID:
        _fail("$.method_id", f"must be {versions.INFERENTIAL_METHOD_ID!r}")
    _sha(obj["run_sha256"], "$.run_sha256")
    definition = validate_inferential_analysis_definition(obj["definition"])
    _sha(obj["definition_sha256"], "$.definition_sha256")
    if synthetic != definition["synthetic"]:
        _fail("$.synthetic", "must agree with the definition synthetic classification")

    evidence = _object(obj["evidence_set"], "$.evidence_set")
    _keys(
        evidence,
        "$.evidence_set",
        required={
            "evidence_set_id", "version", "evidence_set_sha256", "definition_sha256",
            "segment_definition_sha256", "protocol_freeze_sha256", "dataset_fingerprints",
            "scope", "units_used", "clusters_used",
        },
    )
    _id(evidence["evidence_set_id"], "$.evidence_set.evidence_set_id")
    _string(evidence["version"], "$.evidence_set.version")
    for name in ("evidence_set_sha256", "definition_sha256", "segment_definition_sha256", "protocol_freeze_sha256"):
        _sha(evidence[name], f"$.evidence_set.{name}")
    fingerprints = _list(evidence["dataset_fingerprints"], "$.evidence_set.dataset_fingerprints", nonempty=True)
    for index, item in enumerate(fingerprints):
        _sha(item, f"$.evidence_set.dataset_fingerprints[{index}]")
    scope = _enum(evidence["scope"], {"primary", "holdout"}, "$.evidence_set.scope")
    if scope != definition["evidence_scope"]:
        _fail("$.evidence_set.scope", "must repeat the declared evidence scope")
    units_used = _integer(evidence["units_used"], "$.evidence_set.units_used", minimum=0)
    clusters_used = _integer(evidence["clusters_used"], "$.evidence_set.clusters_used", minimum=0)
    if evidence["evidence_set_id"] != definition["evidence_set"]["evidence_set_id"]:
        _fail("$.evidence_set.evidence_set_id", "must match the evidence set bound by the definition")
    if evidence["definition_sha256"] != definition["evidence_set"]["definition_sha256"]:
        _fail("$.evidence_set.definition_sha256", "must match the evidence-set definition hash bound by the analysis")
    if evidence["protocol_freeze_sha256"] != definition["protocol"]["freeze_sha256"]:
        _fail("$.evidence_set.protocol_freeze_sha256", "must match the frozen protocol bound by the analysis")

    analysis_state = _enum(obj["analysis_state"], {"computed", "inconclusive"}, "$.analysis_state")

    sufficiency = _object(obj["sufficiency"], "$.sufficiency")
    _keys(
        sufficiency,
        "$.sufficiency",
        required={
            "status", "source", "available_units", "required_units", "available_pairs",
            "required_pairs", "available_clusters", "required_clusters", "available_participants",
            "required_participants", "unpaired_units", "condition_balance", "replication_count",
            "holdout_available", "total_attrition", "uncertainty_usable", "descriptive_only",
            "confirmatory_permitted", "unmet_requirements",
        },
    )
    sufficiency_status = _enum(sufficiency["status"], SUFFICIENCY_STATUSES, "$.sufficiency.status")
    _enum(sufficiency["source"], DECLARATION_SOURCES, "$.sufficiency.source")
    for name in (
        "available_units", "available_pairs", "available_clusters", "available_participants",
        "unpaired_units", "replication_count", "total_attrition",
    ):
        _integer(sufficiency[name], f"$.sufficiency.{name}", minimum=0)
    for name, floor in (
        ("required_units", 1), ("required_pairs", 1), ("required_clusters", 2), ("required_participants", 1),
    ):
        if sufficiency[name] is not None:
            _integer(sufficiency[name], f"$.sufficiency.{name}", minimum=floor)
    balance = _object(sufficiency["condition_balance"], "$.sufficiency.condition_balance")
    _keys(balance, "$.sufficiency.condition_balance", required={"baseline_units", "intervention_units", "balanced"})
    _integer(balance["baseline_units"], "$.sufficiency.condition_balance.baseline_units", minimum=0)
    _integer(balance["intervention_units"], "$.sufficiency.condition_balance.intervention_units", minimum=0)
    _boolean(balance["balanced"], "$.sufficiency.condition_balance.balanced")
    _boolean(sufficiency["holdout_available"], "$.sufficiency.holdout_available")
    _boolean(sufficiency["uncertainty_usable"], "$.sufficiency.uncertainty_usable")
    descriptive_only = _boolean(sufficiency["descriptive_only"], "$.sufficiency.descriptive_only")
    confirmatory_permitted = _boolean(sufficiency["confirmatory_permitted"], "$.sufficiency.confirmatory_permitted")
    unmet = _strings(sufficiency["unmet_requirements"], "$.sufficiency.unmet_requirements")
    if sufficiency_status == "sufficient" and unmet:
        _fail("$.sufficiency.status", "unmet requirements cannot be sufficient")
    if sufficiency_status == "insufficient" and not unmet:
        _fail("$.sufficiency.unmet_requirements", "an insufficient assessment must record what is missing")
    if confirmatory_permitted and sufficiency_status != "sufficient":
        _fail("$.sufficiency.confirmatory_permitted", "confirmatory interpretation requires sufficient evidence")
    if confirmatory_permitted and definition["classification"] != "confirmatory":
        _fail("$.sufficiency.confirmatory_permitted", "an exploratory analysis never permits confirmatory interpretation")
    if analysis_state == "inconclusive" and confirmatory_permitted:
        _fail("$.analysis_state", "an inconclusive run permits no confirmatory interpretation")
    if descriptive_only and confirmatory_permitted:
        _fail("$.sufficiency", "a descriptive-only result permits no confirmatory interpretation")

    declared_by_id = {item["comparison_id"]: item for item in definition["comparisons"]}
    results = _list(obj["comparisons"], "$.comparisons", nonempty=True)
    covered: list[str] = []
    for index, item in enumerate(results):
        path = f"$.comparisons[{index}]"
        comparison_id = _id(_object(item, path).get("comparison_id"), f"{path}.comparison_id")
        declared = declared_by_id.get(comparison_id)
        if declared is None:
            _fail(f"{path}.comparison_id", "does not correspond to a declared comparison")
        covered.append(_comparison_result(item, path, declared))
    if covered != [item["comparison_id"] for item in definition["comparisons"]]:
        _fail(
            "$.comparisons",
            "must contain exactly one result per declared comparison, in declaration order; comparisons are never silently added or removed",
        )

    multiplicity = _object(obj["multiplicity"], "$.multiplicity")
    _keys(
        multiplicity,
        "$.multiplicity",
        required={"family_id", "role", "correction", "members", "alpha", "entries", "interpretation"},
    )
    _id(multiplicity["family_id"], "$.multiplicity.family_id")
    _enum(multiplicity["role"], FAMILY_ROLES, "$.multiplicity.role")
    _enum(multiplicity["correction"], CORRECTIONS, "$.multiplicity.correction")
    members = _strings(multiplicity["members"], "$.multiplicity.members", nonempty=True)
    for name in ("family_id", "role", "correction"):
        if multiplicity[name] != definition["family"][name]:
            _fail(f"$.multiplicity.{name}", f"must repeat the declared family {name}")
    if multiplicity["alpha"] != definition["family"]["alpha"]:
        _fail("$.multiplicity.alpha", "must repeat the preregistered family alpha")
    if members != definition["family"]["members"]:
        _fail("$.multiplicity.members", "family membership may not change after results are known")
    alpha = _number(multiplicity["alpha"], "$.multiplicity.alpha")
    if not 0 < alpha < 1:
        _fail("$.multiplicity.alpha", "must lie strictly within (0, 1)")
    entries = _list(multiplicity["entries"], "$.multiplicity.entries")
    entry_ids: list[str] = []
    for index, item in enumerate(entries):
        path = f"$.multiplicity.entries[{index}]"
        entry = _object(item, path)
        _keys(entry, path, required={"comparison_id", "raw_p_value", "adjusted_p_value", "rejected_at_alpha"})
        entry_ids.append(_id(entry["comparison_id"], f"{path}.comparison_id"))
        for name in ("raw_p_value", "adjusted_p_value"):
            if entry[name] is not None:
                _probability(entry[name], f"{path}.{name}")
        if entry["raw_p_value"] is None and entry["adjusted_p_value"] is not None:
            _fail(f"{path}.adjusted_p_value", "cannot adjust a p-value that was never computed")
        if entry["raw_p_value"] is not None and entry["adjusted_p_value"] is not None:
            if entry["adjusted_p_value"] < entry["raw_p_value"]:
                _fail(f"{path}.adjusted_p_value", "a correction never makes evidence stronger than its raw value")
        rejected = _boolean(entry["rejected_at_alpha"], f"{path}.rejected_at_alpha")
        if rejected and (entry["adjusted_p_value"] is None or entry["adjusted_p_value"] > alpha):
            _fail(f"{path}.rejected_at_alpha", "requires an adjusted p-value at or below alpha")
    if entry_ids != sorted(entry_ids):
        _fail("$.multiplicity.entries", "entries must be serialized in lexicographic comparison order")
    if set(entry_ids) - set(members):
        _fail("$.multiplicity.entries", "every entry must belong to the declared family")
    _string(multiplicity["interpretation"], "$.multiplicity.interpretation")

    sensitivity = _list(obj["sensitivity"], "$.sensitivity")
    for index, item in enumerate(sensitivity):
        path = f"$.sensitivity[{index}]"
        test = _object(item, path)
        _keys(test, path, required={"test_id", "kind", "comparison_id", "outcome", "detail"})
        _id(test["test_id"], f"{path}.test_id")
        _enum(test["kind"], FALSIFICATION_KINDS, f"{path}.kind")
        if _id(test["comparison_id"], f"{path}.comparison_id") not in declared_by_id:
            _fail(f"{path}.comparison_id", "must reference a declared comparison")
        _enum(test["outcome"], {"robust", "fragile", "not_computable"}, f"{path}.outcome")
        _object(test["detail"], f"{path}.detail")

    confounds = _object(obj["confounds"], "$.confounds")
    _keys(confounds, "$.confounds", required={"controlled", "measured_covariates", "unavailable"})
    for name in ("controlled", "measured_covariates", "unavailable"):
        _strings(confounds[name], f"$.confounds.{name}")

    interpretation = _object(obj["interpretation"], "$.interpretation")
    _keys(
        interpretation,
        "$.interpretation",
        required={"requested_ceiling", "structural_ceiling", "effective_ceiling", "rationale"},
    )
    requested = _enum(interpretation["requested_ceiling"], CEILING_SET, "$.interpretation.requested_ceiling")
    structural = _enum(interpretation["structural_ceiling"], CEILING_SET, "$.interpretation.structural_ceiling")
    effective = _enum(interpretation["effective_ceiling"], CEILING_SET, "$.interpretation.effective_ceiling")
    _string(interpretation["rationale"], "$.interpretation.rationale")
    if requested != definition["interpretation_ceiling"]:
        _fail("$.interpretation.requested_ceiling", "must repeat the declared interpretation ceiling")
    if not ceiling_at_or_below(requested, structural):
        _fail(
            "$.interpretation.requested_ceiling",
            "a requested interpretation stronger than the protocol and evidence design permits is refused",
        )
    if not ceiling_at_or_below(effective, requested) or not ceiling_at_or_below(effective, structural):
        _fail("$.interpretation.effective_ceiling", "must not exceed the requested or structural ceiling")
    if descriptive_only and effective != "descriptive":
        _fail("$.interpretation.effective_ceiling", "a descriptive-only result interprets descriptively")

    eligibility = _object(obj["scientific_eligibility"], "$.scientific_eligibility")
    _keys(eligibility, "$.scientific_eligibility", required={"eligible", "reason"})
    eligible = _boolean(eligibility["eligible"], "$.scientific_eligibility.eligible")
    _string(eligibility["reason"], "$.scientific_eligibility.reason")
    if synthetic and eligible:
        _fail("$.scientific_eligibility.eligible", "synthetic evidence is permanently scientifically ineligible")

    _code_identity(obj["code_identity"], "$.code_identity")
    integrity = _object(obj["integrity"], "$.integrity")
    _keys(
        integrity,
        "$.integrity",
        required={"evidence_set_verified", "units_used", "clusters_used", "deterministic_resampling"},
    )
    if integrity["evidence_set_verified"] is not True:
        _fail("$.integrity.evidence_set_verified", "inference may only run over a verified evidence set")
    if _integer(integrity["units_used"], "$.integrity.units_used", minimum=0) != units_used:
        _fail("$.integrity.units_used", "must agree with the bound evidence-set reference")
    if _integer(integrity["clusters_used"], "$.integrity.clusters_used", minimum=0) != clusters_used:
        _fail("$.integrity.clusters_used", "must agree with the bound evidence-set reference")
    if integrity["deterministic_resampling"] != "sha256_counter_stream_rejection_sampled":
        _fail("$.integrity.deterministic_resampling", "unsupported resampling determinism guarantee")
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj
