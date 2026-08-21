"""Preregistered inferential analysis over one comparable evidence set.

A run here answers exactly the question the definition declared, over exactly
the evidence the evidence set preserved, at exactly the unit both agreed on. It
produces an estimate, an interval whose meaning is stated, raw and adjusted
statistical evidence, sensitivity results, and an interpretation ceiling.

It does not produce a finding, a status, or a truth. Crossing an adjusted
threshold is not a discovery, and an adjusted p-value is not the probability
that a hypothesis is true.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

from apex_labs.analysis import statistics as stats
from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import InferenceError, IntegrityError
from apex_labs.experiments import verify_protocol_freeze
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import apex_labs_code_identity, require_research_code_identity, sha256_bytes
from apex_labs.schemas import (
    validate_evidence_set,
    validate_inferential_analysis_definition,
    validate_inferential_analysis_run,
)
from apex_labs.schemas.science_vocabulary import CEILING_RANK, weakest_ceiling
from apex_labs.schemas.versions import INFERENTIAL_ANALYSIS_RUN, INFERENTIAL_METHOD_ID

_INTERVAL_SEMANTICS = (
    "Percentile interval over a deterministic cluster bootstrap at the declared resampling unit. "
    "It describes the sampling variability of this estimator on this evidence under resampling of whole "
    "clusters. It is not a probability that the true effect lies inside it, and it does not account for "
    "confounding, selection, or any unmeasured limitation recorded beside it."
)
_NO_EFFECT_REFERENCE = {"dispersion_ratio": 1.0}


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _run_hash(artifact: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in artifact.items() if key != "run_sha256"})


def _resolve(path: Path, filename: str) -> Path:
    return path / filename if path.is_dir() else path


def _paired_statistic(effect_size: str) -> Callable[[Sequence[float]], float | None]:
    return stats.median if effect_size == "median_paired_difference" else stats.mean


def _unpaired_statistic(effect_size: str) -> Callable[[Sequence[Any]], float | None]:
    reducer = stats.median if effect_size == "median_difference" else stats.mean

    def statistic(observations: Sequence[Any]) -> float | None:
        baseline = [value for arm, value in observations if arm == "baseline"]
        intervention = [value for arm, value in observations if arm == "intervention"]
        if not baseline or not intervention:
            return None
        return reducer(intervention) - reducer(baseline)

    return statistic


def _ratio_statistic(observations: Sequence[Any]) -> float | None:
    baseline = [value for arm, value in observations if arm == "baseline"]
    intervention = [value for arm, value in observations if arm == "intervention"]
    if not baseline or not intervention:
        return None
    return stats.dispersion_ratio(baseline, intervention)["ratio"]


def _subset_matches(subset: dict[str, Any] | None, unit: dict[str, Any]) -> bool:
    if subset is None:
        return True
    return str(unit[subset["field"]]) == subset["value"]


def _pair_subset_matches(
    subset: dict[str, Any] | None, pair: dict[str, Any], units: dict[str, dict[str, Any]]
) -> bool:
    if subset is None:
        return True
    if subset["field"] == "pair_key":
        return pair["pair_key"] == subset["value"]
    baseline = units[pair["baseline_unit_id"]]
    intervention = units[pair["intervention_unit_id"]]
    return _subset_matches(subset, baseline) and _subset_matches(subset, intervention)


def _uncertainty(
    definition: dict[str, Any],
    clusters: list[list[Any]],
    statistic: Callable[[Sequence[Any]], float | None],
    label: str,
) -> dict[str, Any]:
    settings = definition["uncertainty"]
    resampling_unit = settings["resampling_unit"]
    base = {
        "method": settings["method"],
        "coverage_level": settings["coverage_level"],
        "interval": None,
        "draws": settings["bootstrap_draws"],
        "random_seed": settings["random_seed"],
        "resampling_unit": resampling_unit,
        "clusters": len(clusters),
        "usable": False,
        "semantics": _INTERVAL_SEMANTICS if settings["method"] != "none" else "No uncertainty method was declared.",
        "unusable_reason": None,
    }
    if settings["method"] == "none":
        base["unusable_reason"] = "The analysis definition declares no uncertainty method."
        return base
    if len(clusters) < settings["minimum_resampling_clusters"]:
        base["unusable_reason"] = (
            f"{len(clusters)} resampling cluster(s) at the {resampling_unit} level is below the declared "
            f"minimum of {settings['minimum_resampling_clusters']}; an interval from this evidence would be meaningless."
        )
        return base
    distribution = stats.cluster_bootstrap_distribution(
        clusters,
        statistic,
        draws=settings["bootstrap_draws"],
        seed=settings["random_seed"],
        label=label,
    )
    if len(distribution) < settings["bootstrap_draws"] // 2:
        base["unusable_reason"] = (
            f"Only {len(distribution)} of {settings['bootstrap_draws']} resampling draws produced a defined "
            "statistic; the interval is withheld rather than reported from a truncated distribution."
        )
        return base
    interval = stats.percentile_interval(distribution, settings["coverage_level"])
    if interval is None:
        base["unusable_reason"] = "The resampling distribution was empty."
        return base
    base["interval"] = [interval[0], interval[1]]
    base["usable"] = True
    return base


def _practical(
    comparison: dict[str, Any], estimate: float | None, uncertainty: dict[str, Any]
) -> dict[str, Any]:
    threshold = comparison["practical_threshold"]
    reference = _NO_EFFECT_REFERENCE.get(comparison["effect_size"], 0.0)
    result: dict[str, Any] = {
        "threshold_magnitude": threshold["magnitude"],
        "threshold_unit": threshold["unit"],
        "threshold_source": threshold["source"],
        "estimate_exceeds_threshold": None,
        "direction_matches_hypothesis": None,
        "interval_excludes_no_effect": None,
    }
    if estimate is not None:
        result["estimate_exceeds_threshold"] = abs(estimate - reference) >= threshold["magnitude"]
        if comparison["directionality"] == "decrease_is_improvement":
            result["direction_matches_hypothesis"] = estimate < reference
        elif comparison["directionality"] == "increase_is_improvement":
            result["direction_matches_hypothesis"] = estimate > reference
    if uncertainty["usable"]:
        lower, upper = uncertainty["interval"]
        result["interval_excludes_no_effect"] = not (lower <= reference <= upper)
    return result


def _compute_comparison(
    definition: dict[str, Any],
    comparison: dict[str, Any],
    units_by_id: dict[str, dict[str, Any]],
    scope_units: list[dict[str, Any]],
    scope_pairs: list[dict[str, Any]],
    unit_of_measure: str,
) -> tuple[dict[str, Any], list[list[Any]]]:
    method = comparison["method"]
    effect_size = comparison["effect_size"]
    subset = comparison["subset"]
    notes: list[str] = []
    result: dict[str, Any] = {
        "comparison_id": comparison["comparison_id"],
        "subset": subset,
        "role": comparison["role"],
        "method": method,
        "metric_id": comparison["metric_id"],
        "unit_of_measure": unit_of_measure,
        "state": "not_computable",
        "effect": None,
        "uncertainty": {},
        "statistical_evidence": {
            "test": "none",
            "raw_p_value": None,
            "detail": {},
            "interpretation": "No hypothesis test is defined for this comparison method.",
        },
        "practical": {},
        "notes": notes,
    }
    if subset is not None:
        notes.append(
            f"Evaluated on the subgroup where {subset['field']} is {subset['value']!r}. A subgroup result is "
            "exploratory: it was one of several searched slices and requires independent replication."
        )

    if method in {"paired_difference", "trend"}:
        pairs = [pair for pair in scope_pairs if _pair_subset_matches(subset, pair, units_by_id)]
        differences = [
            units_by_id[pair["intervention_unit_id"]]["value"] - units_by_id[pair["baseline_unit_id"]]["value"]
            for pair in pairs
        ]
        baseline_values = [units_by_id[pair["baseline_unit_id"]]["value"] for pair in pairs]
        intervention_values = [units_by_id[pair["intervention_unit_id"]]["value"] for pair in pairs]
        clusters_map: dict[str, list[Any]] = defaultdict(list)
        for pair, difference in zip(pairs, differences):
            clusters_map[pair["cluster_id"]].append(difference)
        clusters = [clusters_map[key] for key in sorted(clusters_map)]
        if not pairs:
            notes.append("No pair survived the declared scope and subgroup selection.")
            result["uncertainty"] = _uncertainty(definition, [], stats.median, comparison["comparison_id"])
            result["practical"] = _practical(comparison, None, result["uncertainty"])
            return result, []
        if method == "paired_difference":
            statistic = _paired_statistic(effect_size)
            estimate = statistic(differences)
            secondary = (
                stats.mean(differences) if effect_size == "median_paired_difference" else stats.median(differences)
            )
            uncertainty = _uncertainty(definition, clusters, statistic, comparison["comparison_id"])
            sign = stats.exact_sign_test(differences)
            result["statistical_evidence"] = {
                "test": "exact_paired_sign_test",
                "raw_p_value": sign["p_value"],
                "detail": {
                    "positive": sign["positive"],
                    "negative": sign["negative"],
                    "ties": sign["ties"],
                    "trials": sign["trials"],
                },
                "interpretation": (
                    "Exact two-sided binomial probability of a split at least this lopsided if improvement and "
                    "worsening were equally likely. It is not the probability that the hypothesis is true, and it "
                    "says nothing about how large the difference is."
                ),
            }
        else:
            points = [(float(index), difference) for index, difference in enumerate(differences)]
            estimate = stats.theil_sen_slope(points)
            secondary = None
            ordered_clusters = [[value for value in cluster] for cluster in clusters]
            uncertainty = _uncertainty(
                definition,
                ordered_clusters,
                lambda values: stats.theil_sen_slope(
                    [(float(index), value) for index, value in enumerate(values)]
                ),
                comparison["comparison_id"],
            )
            notes.append(
                "The trend is the robust slope of the paired difference across ordered pairs. Order is an "
                "ordering, not a cause: a non-zero slope is an order effect to be explained, never evidence "
                "that coaching caused it."
            )
        result["uncertainty"] = uncertainty
        if estimate is None:
            result["practical"] = _practical(comparison, None, uncertainty)
            return result, clusters
        result["state"] = "computed"
        result["effect"] = {
            "effect_size": effect_size,
            "estimate": estimate,
            "secondary_estimate": secondary,
            "n": len(pairs),
            "per_unit_differences": differences,
            "group_summaries": {
                "baseline": stats.group_summary(baseline_values),
                "intervention": stats.group_summary(intervention_values),
            },
        }
        result["practical"] = _practical(comparison, estimate, uncertainty)
        return result, clusters

    units = [unit for unit in scope_units if _subset_matches(subset, unit)]
    baseline_values = [unit["value"] for unit in units if unit["arm"] == "baseline"]
    intervention_values = [unit["value"] for unit in units if unit["arm"] == "intervention"]
    clusters_map = defaultdict(list)
    for unit in units:
        clusters_map[unit["_cluster_id"]].append((unit["arm"], unit["value"]))
    clusters = [clusters_map[key] for key in sorted(clusters_map)]
    if not baseline_values or not intervention_values:
        notes.append("At least one arm carries no unit under the declared scope and subgroup selection.")
        result["uncertainty"] = _uncertainty(definition, [], _ratio_statistic, comparison["comparison_id"])
        result["practical"] = _practical(comparison, None, result["uncertainty"])
        return result, clusters

    if method == "unpaired_difference":
        statistic = _unpaired_statistic(effect_size)
        estimate = statistic([(unit["arm"], unit["value"]) for unit in units])
        secondary = None
        notes.append(
            "This contrast is unpaired: "
            + str(definition["grouping"]["unpaired_justification"])
            + " Group imbalance and every unmeasured confound recorded beside this result apply in full."
        )
        notes.append(
            f"Arm sizes are {len(baseline_values)} baseline and {len(intervention_values)} intervention unit(s)."
        )
        uncertainty = _uncertainty(definition, clusters, statistic, comparison["comparison_id"])
    else:
        dispersion = stats.dispersion_ratio(baseline_values, intervention_values)
        estimate = dispersion["ratio"]
        secondary = dispersion["intervention_mad"]
        notes.append(
            "A dispersion ratio below one means the intervention arm varied less. Less variation is not "
            "automatically better: it can equally reflect a narrower sample or a driver who stopped exploring."
        )
        uncertainty = _uncertainty(definition, clusters, _ratio_statistic, comparison["comparison_id"])
    result["uncertainty"] = uncertainty
    if estimate is None:
        notes.append("The estimator is undefined for this evidence and no number is reported in its place.")
        result["practical"] = _practical(comparison, None, uncertainty)
        return result, clusters
    result["state"] = "computed"
    result["effect"] = {
        "effect_size": effect_size,
        "estimate": estimate,
        "secondary_estimate": secondary,
        "n": len(units),
        "per_unit_differences": [],
        "group_summaries": {
            "baseline": stats.group_summary(baseline_values),
            "intervention": stats.group_summary(intervention_values),
        },
    }
    result["practical"] = _practical(comparison, estimate, uncertainty)
    return result, clusters


def _sensitivity(
    test: dict[str, Any],
    comparison: dict[str, Any],
    result: dict[str, Any],
    clusters: list[list[Any]],
) -> dict[str, Any]:
    """Deterministic falsification checks that never replace the primary estimate."""
    entry = {
        "test_id": test["test_id"],
        "kind": test["kind"],
        "comparison_id": comparison["comparison_id"],
        "outcome": "not_computable",
        "detail": {},
    }
    if result["state"] != "computed" or comparison["method"] != "paired_difference":
        entry["detail"] = {
            "reason": "This check is defined for a computed paired difference and was not applicable here."
        }
        return entry
    differences = result["effect"]["per_unit_differences"]
    statistic = _paired_statistic(comparison["effect_size"])
    full = result["effect"]["estimate"]
    reference = 0.0
    direction = 1 if full > reference else -1 if full < reference else 0
    threshold = comparison["practical_threshold"]["magnitude"]

    def sign_of(value: float | None) -> int:
        if value is None:
            return 0
        return 1 if value > reference else -1 if value < reference else 0

    kind = test["kind"]
    if kind == "leave_one_unit_out":
        if len(differences) < 3:
            entry["detail"] = {"reason": "Fewer than three pairs; leaving one out is uninformative."}
            return entry
        estimates = [
            statistic(differences[:index] + differences[index + 1 :]) for index in range(len(differences))
        ]
        flips = sum(1 for value in estimates if sign_of(value) != direction)
        entry["outcome"] = "robust" if flips == 0 else "fragile"
        entry["detail"] = {
            "estimates_minimum": min(estimates),
            "estimates_maximum": max(estimates),
            "direction_changes": flips,
        }
        return entry
    if kind == "leave_one_cluster_out":
        if len(clusters) < 3:
            entry["detail"] = {"reason": "Fewer than three resampling clusters; leaving one out is uninformative."}
            return entry
        estimates = []
        for index in range(len(clusters)):
            remaining = [value for position, cluster in enumerate(clusters) if position != index for value in cluster]
            estimates.append(statistic(remaining))
        flips = sum(1 for value in estimates if sign_of(value) != direction)
        entry["outcome"] = "robust" if flips == 0 else "fragile"
        entry["detail"] = {
            "estimates_minimum": min(estimates),
            "estimates_maximum": max(estimates),
            "direction_changes": flips,
            "clusters": len(clusters),
        }
        return entry
    if kind == "outlier_dependence":
        if len(differences) < 3:
            entry["detail"] = {"reason": "Fewer than three pairs; outlier dependence cannot be separated."}
            return entry
        centre = stats.median(differences)
        extreme_index = max(range(len(differences)), key=lambda index: (abs(differences[index] - centre), index))
        without = differences[:extreme_index] + differences[extreme_index + 1 :]
        estimate = statistic(without)
        carried = sign_of(estimate) != direction or abs(estimate) < threshold <= abs(full)
        entry["outcome"] = "fragile" if carried else "robust"
        entry["detail"] = {
            "removed_difference": differences[extreme_index],
            "estimate_without_outlier": estimate,
            "full_estimate": full,
            "practical_threshold": threshold,
        }
        return entry
    if kind == "order_effect_early_versus_late":
        if len(differences) < 4:
            entry["detail"] = {"reason": "Fewer than four pairs; an early/late split is uninformative."}
            return entry
        half = len(differences) // 2
        early = statistic(differences[:half])
        late = statistic(differences[half:])
        entry["outcome"] = "robust" if sign_of(early) == direction == sign_of(late) else "fragile"
        entry["detail"] = {"early_estimate": early, "late_estimate": late, "split_at": half}
        return entry
    if kind == "isolation_by_cluster":
        if len(clusters) < 2:
            entry["detail"] = {"reason": "A single resampling cluster cannot show isolation."}
            return entry
        estimates = [statistic(cluster) for cluster in clusters]
        agreeing = sum(1 for value in estimates if sign_of(value) == direction)
        entry["outcome"] = "robust" if agreeing * 2 > len(clusters) else "fragile"
        entry["detail"] = {
            "per_cluster_estimates": estimates,
            "clusters_agreeing_with_direction": agreeing,
            "clusters": len(clusters),
        }
        return entry
    concordant = sum(1 for value in differences if sign_of(value) == direction)
    entry["outcome"] = "robust" if concordant * 2 > len(differences) else "fragile"
    entry["detail"] = {"concordant_pairs": concordant, "pairs": len(differences)}
    return entry


def _sufficiency(
    definition: dict[str, Any],
    evidence: dict[str, Any],
    scope_units: list[dict[str, Any]],
    scope_pairs: list[dict[str, Any]],
    clusters: set[str],
    participants: int,
    uncertainty_usable: bool,
    protocol_requirements: list[str],
) -> dict[str, Any]:
    rule = definition["sufficiency_rule"]
    baseline = sum(1 for unit in scope_units if unit["arm"] == "baseline")
    intervention = sum(1 for unit in scope_units if unit["arm"] == "intervention")
    unmet: list[str] = []
    checks = (
        ("minimum_experimental_units", len(scope_units), "comparable experimental unit(s)"),
        ("minimum_pairs", len(scope_pairs), "comparable pair(s)"),
        ("minimum_resampling_clusters", len(clusters), f"{definition['resampling_unit']}-level resampling cluster(s)"),
        ("minimum_participants", participants, "participant(s)"),
    )
    for name, available, label in checks:
        required = rule[name]
        if required is not None and available < required:
            unmet.append(f"{available} {label} available; the declared requirement is {required}.")
    if rule["source"] == "not_declared":
        unmet.append(
            "No sample requirement is preregistered or documented, so sufficiency cannot be established."
        )
    if evidence["comparability"]["status"] == "inadequate":
        unmet.append("Comparability is inadequate: " + "; ".join(evidence["comparability"]["violations"]))
    if evidence["post_hoc_exclusions_present"] and definition["classification"] == "confirmatory":
        unmet.append(
            "Evidence was removed by a rule the frozen protocol did not preregister, which forecloses "
            "confirmatory interpretation."
        )
    if rule["source"] == "frozen_protocol":
        uncited = [item for item in rule["source_declarations"] if item not in protocol_requirements]
        if uncited:
            unmet.append(
                f"{len(uncited)} cited sample requirement(s) do not appear verbatim in the frozen protocol."
            )
    if not uncertainty_usable and definition["classification"] == "confirmatory":
        unmet.append(
            "No usable uncertainty estimate could be produced for the primary comparison, so a confirmatory "
            "claim cannot be supported."
        )

    if rule["source"] == "not_declared":
        status = "undetermined"
    elif unmet:
        status = "insufficient"
    else:
        status = "sufficient"
    descriptive_only = status != "sufficient" or evidence["comparability"]["status"] == "inadequate"
    confirmatory_permitted = (
        status == "sufficient"
        and definition["classification"] == "confirmatory"
        and not evidence["post_hoc_exclusions_present"]
        and not descriptive_only
    )
    return {
        "status": status,
        "source": rule["source"],
        "available_units": len(scope_units),
        "required_units": rule["minimum_experimental_units"],
        "available_pairs": len(scope_pairs),
        "required_pairs": rule["minimum_pairs"],
        "available_clusters": len(clusters),
        "required_clusters": rule["minimum_resampling_clusters"],
        "available_participants": participants,
        "required_participants": rule["minimum_participants"],
        "unpaired_units": evidence["counts"]["unpaired_units"],
        "condition_balance": {
            "baseline_units": baseline,
            "intervention_units": intervention,
            "balanced": baseline == intervention,
        },
        "replication_count": 1 if definition["replication_policy"]["state"] == "this_run_is_the_replication" else 0,
        "holdout_available": evidence["counts"]["holdout_units"] > 0,
        "total_attrition": sum(entry["excluded"] for entry in evidence["attrition"]),
        "uncertainty_usable": uncertainty_usable,
        "descriptive_only": descriptive_only,
        "confirmatory_permitted": confirmatory_permitted,
        "unmet_requirements": unmet,
    }


def run_inferential_analysis(
    definition_path: Path,
    evidence_path: Path,
    protocol_freeze_path: Path,
    output_dir: Path,
    *,
    run_id: str,
    created_at: str,
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = validate_inferential_analysis_definition(read_json(definition_path))
    evidence = validate_evidence_set(read_json(_resolve(evidence_path, "evidence-set.json")))
    freeze = verify_protocol_freeze(read_json(protocol_freeze_path))

    evidence_definition = evidence["definition"]
    if evidence["evidence_set_id"] != definition["evidence_set"]["evidence_set_id"]:
        raise IntegrityError("Analysis is bound to a different evidence set")
    if evidence["version"] != definition["evidence_set"]["version"]:
        raise IntegrityError("Analysis is bound to a different evidence-set version")
    if evidence["definition_sha256"] != definition["evidence_set"]["definition_sha256"]:
        raise IntegrityError("Evidence-set definition hash does not match the analysis binding")
    if evidence["protocol"]["freeze_sha256"] != definition["protocol"]["freeze_sha256"]:
        raise IntegrityError("Evidence set and analysis are bound to different frozen protocols")
    if freeze["freeze_sha256"] != definition["protocol"]["freeze_sha256"]:
        raise IntegrityError("Supplied frozen protocol does not match the analysis binding")
    if definition["synthetic"] != evidence["synthetic"]:
        raise IntegrityError("Analysis and evidence disagree about synthetic classification")
    if definition["experimental_unit"] != evidence["units_declaration"]["experimental_unit"]:
        raise IntegrityError("Analysis experimental unit differs from the evidence set")
    if definition["resampling_unit"] != evidence["units_declaration"]["resampling_unit"]:
        raise IntegrityError("Analysis resampling unit differs from the evidence set")
    if definition["grouping"]["kind"] != evidence_definition["pairing"]["kind"]:
        raise IntegrityError("Analysis grouping differs from the evidence-set pairing design")

    structural = evidence["structural_interpretation_ceiling"]
    requested = definition["interpretation_ceiling"]
    if CEILING_RANK[requested] > CEILING_RANK[structural]:
        raise InferenceError(
            f"The analysis requests a {requested!r} interpretation but the frozen protocol and evidence design "
            f"support at most {structural!r}. A stronger interpretation than the design permits is refused."
        )

    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=definition["synthetic"])

    scope = definition["evidence_scope"]
    want_holdout = scope == "holdout"
    resampling_unit = definition["resampling_unit"]
    context_participants = {dataset["participant"] for dataset in evidence["datasets"]}
    dataset_by_id = {dataset["dataset_id"]: dataset for dataset in evidence["datasets"]}

    units_by_id: dict[str, dict[str, Any]] = {}
    for unit in evidence["units"]:
        enriched = dict(unit)
        enriched["_cluster_id"] = _cluster_id(resampling_unit, unit, dataset_by_id)
        units_by_id[unit["unit_id"]] = enriched
    scope_units = [unit for unit in units_by_id.values() if unit["holdout"] == want_holdout]
    scope_units.sort(key=lambda item: item["unit_id"])
    scope_pairs = [pair for pair in evidence["pairs"] if pair["holdout"] == want_holdout]
    # A paired difference belongs to the block pair that produced it, so the
    # independent-replicate count for a paired design comes from the pairs.
    clusters = (
        {pair["cluster_id"] for pair in scope_pairs}
        if definition["grouping"]["kind"] == "paired"
        else {unit["_cluster_id"] for unit in scope_units}
    )

    unit_of_measure = evidence_definition["unit_metric"]["unit"]
    results: list[dict[str, Any]] = []
    cluster_sets: dict[str, list[list[Any]]] = {}
    for comparison in definition["comparisons"]:
        result, comparison_clusters = _compute_comparison(
            definition, comparison, units_by_id, scope_units, scope_pairs, unit_of_measure
        )
        results.append(result)
        cluster_sets[comparison["comparison_id"]] = comparison_clusters

    primary = next(
        (item for item in results if item["role"] == "primary"),
        results[0],
    )
    sufficiency = _sufficiency(
        definition,
        evidence,
        scope_units,
        scope_pairs,
        clusters,
        len(context_participants),
        bool(primary["uncertainty"].get("usable")),
        freeze["protocol"]["minimum_sample_requirements"]["requirements"],
    )

    family = definition["family"]
    raw_values = [
        next(item["statistical_evidence"]["raw_p_value"] for item in results if item["comparison_id"] == member)
        for member in family["members"]
    ]
    adjusted = stats.CORRECTIONS[family["correction"]](raw_values)
    entries = sorted(
        (
            {
                "comparison_id": member,
                "raw_p_value": raw,
                "adjusted_p_value": value,
                "rejected_at_alpha": value is not None and value <= family["alpha"],
            }
            for member, raw, value in zip(family["members"], raw_values, adjusted)
        ),
        key=lambda item: item["comparison_id"],
    )
    multiplicity = {
        "family_id": family["family_id"],
        "role": family["role"],
        "correction": family["correction"],
        "members": family["members"],
        "alpha": family["alpha"],
        "entries": entries,
        "interpretation": (
            "Adjusted values control the declared error rate across this fixed family. They are not the "
            "probability that any hypothesis is true, and crossing the threshold is not a discovery: an "
            "exploratory survivor still requires independent replication, and a confirmatory one still "
            "requires the practical threshold, the sensitivity results, and human scientific review."
        ),
    }

    sensitivity = [
        _sensitivity(test, comparison, result, cluster_sets[comparison["comparison_id"]])
        for comparison, result in zip(definition["comparisons"], results)
        for test in definition["falsification_tests"]
    ]
    sensitivity.sort(key=lambda item: (item["comparison_id"], item["test_id"]))

    analysis_state = "computed" if primary["state"] == "computed" and sufficiency["status"] != "insufficient" else "inconclusive"
    effective = weakest_ceiling(requested, structural)
    if sufficiency["descriptive_only"]:
        effective = "descriptive"
    limitations = list(evidence["limitations"]) + list(definition["limitations"])
    if analysis_state == "inconclusive":
        limitations.append(
            "This run is INCONCLUSIVE. The result is preserved so the attempt is not repeated blindly; it is "
            "not evidence for or against the hypothesis."
        )
    fragile = [item for item in sensitivity if item["outcome"] == "fragile"]
    if fragile:
        limitations.append(
            f"{len(fragile)} falsification check(s) returned fragile. The primary estimate is preserved unchanged "
            "beside them; a fragile direction is a reason for doubt, not a reason to re-estimate."
        )

    artifact: dict[str, Any] = {
        "schema_version": INFERENTIAL_ANALYSIS_RUN,
        "run_id": run_id,
        "created_at": created_at,
        "classification": "inferential_result_not_a_finding",
        "synthetic": definition["synthetic"],
        "method_id": INFERENTIAL_METHOD_ID,
        "run_sha256": "0" * 64,
        "definition": definition,
        "definition_sha256": _canonical_sha(definition),
        "evidence_set": {
            "evidence_set_id": evidence["evidence_set_id"],
            "version": evidence["version"],
            "evidence_set_sha256": evidence["evidence_set_sha256"],
            "definition_sha256": evidence["definition_sha256"],
            "segment_definition_sha256": evidence["segment_definition_sha256"],
            "protocol_freeze_sha256": evidence["protocol"]["freeze_sha256"],
            "dataset_fingerprints": sorted(dataset["fingerprint"] for dataset in evidence["datasets"]),
            "scope": scope,
            "units_used": len(scope_units),
            "clusters_used": len(clusters),
        },
        "analysis_state": analysis_state,
        "sufficiency": sufficiency,
        "comparisons": results,
        "multiplicity": multiplicity,
        "sensitivity": sensitivity,
        "confounds": evidence["confounds"],
        "interpretation": {
            "requested_ceiling": requested,
            "structural_ceiling": structural,
            "effective_ceiling": effective,
            "rationale": (
                f"The frozen protocol and evidence design support at most {structural!r}; the analysis requested "
                f"{requested!r}; the evidence actually supports {effective!r}."
            ),
        },
        "scientific_eligibility": {
            "eligible": False if definition["synthetic"] else analysis_state == "computed",
            "reason": (
                "Synthetic evidence demonstrates mechanics only and is permanently ineligible for scientific promotion."
                if definition["synthetic"]
                else (
                    "A computed result over real evidence may be cited by a finding; eligibility is not validity."
                    if analysis_state == "computed"
                    else "An inconclusive result cannot support promotion."
                )
            ),
        },
        "code_identity": identity,
        "integrity": {
            "evidence_set_verified": True,
            "units_used": len(scope_units),
            "clusters_used": len(clusters),
            "deterministic_resampling": "sha256_counter_stream_rejection_sampled",
        },
        "limitations": limitations,
    }
    artifact["run_sha256"] = _run_hash(artifact)
    validate_inferential_analysis_run(artifact)
    with atomic_output_directory(output_dir, operation="inferential-run", error_type=InferenceError) as staged:
        write_json(staged / "inferential-analysis-run.json", artifact)
    return artifact


def _cluster_id(
    resampling_unit: str, unit: dict[str, Any], dataset_by_id: dict[str, dict[str, Any]]
) -> str:
    if resampling_unit in {"lap", "segment_opportunity"}:
        return unit["unit_id"]
    if resampling_unit == "block":
        return unit["block_id"]
    if resampling_unit == "session":
        return unit["session_id"]
    return dataset_by_id[unit["dataset_id"]]["participant"]


def verify_inferential_analysis_run(
    run_path: Path,
    evidence_path: Path,
    protocol_freeze_path: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Recompute the whole result from the bound evidence and compare it.

    Verification re-runs the analysis rather than re-hashing the stored answer,
    so a tampered result, definition, or evidence set is detected.
    """
    artifact = validate_inferential_analysis_run(
        read_json(_resolve(run_path, "inferential-analysis-run.json"))
    )
    if artifact["run_sha256"] != _run_hash(artifact):
        raise IntegrityError("Inferential run hash does not match its content")
    if artifact["definition_sha256"] != _canonical_sha(artifact["definition"]):
        raise IntegrityError("Inferential run definition hash does not match the embedded definition")
    evidence = validate_evidence_set(read_json(_resolve(evidence_path, "evidence-set.json")))
    if evidence["evidence_set_sha256"] != artifact["evidence_set"]["evidence_set_sha256"]:
        raise IntegrityError("Inferential run was produced from a different evidence set")

    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="apex-labs-inference-verify-") as directory:
        definition_path = Path(directory) / "definition.json"
        write_json(definition_path, artifact["definition"])
        rebuilt = run_inferential_analysis(
            definition_path,
            evidence_path,
            protocol_freeze_path,
            Path(directory) / "rebuilt",
            run_id=artifact["run_id"],
            created_at=artifact["created_at"],
            project_root=project_root,
            code_identity=artifact["code_identity"],
        )
    if rebuilt != artifact:
        differing = sorted(
            key for key in set(rebuilt) | set(artifact) if rebuilt.get(key) != artifact.get(key)
        )
        raise IntegrityError(
            f"Inferential run is not reproducible from its bound evidence; differing sections: {differing}"
        )
    current = apex_labs_code_identity(project_root)
    primary = next((item for item in artifact["comparisons"] if item["role"] == "primary"), artifact["comparisons"][0])
    return {
        "valid": True,
        "run_id": artifact["run_id"],
        "analysis_id": artifact["definition"]["analysis_id"],
        "analysis_state": artifact["analysis_state"],
        "sufficiency": artifact["sufficiency"]["status"],
        "effective_ceiling": artifact["interpretation"]["effective_ceiling"],
        "primary_comparison": primary["comparison_id"],
        "primary_estimate": None if primary["effect"] is None else primary["effect"]["estimate"],
        "scientific_eligibility": artifact["scientific_eligibility"]["eligible"],
        "code_identity_match": (
            current["code_and_schema_sha256"] == artifact["code_identity"]["code_and_schema_sha256"]
        ),
    }
