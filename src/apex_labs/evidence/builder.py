"""Deterministic construction of comparable evidence sets.

The pipeline reports every stage at which evidence left the funnel. Nothing is
silently discarded, nothing is repaired, and an unavailable value is never
coerced into a zero. The output binds the exact datasets, protocol, segment,
metric, and code that produced it, and it is reproducible from those bytes.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from apex_labs.analysis import statistics as stats
from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import EvidenceError, IntegrityError
from apex_labs.evidence import comparability as comparability_module
from apex_labs.evidence import segments as segment_module
from apex_labs.experiments import verify_protocol_freeze
from apex_labs.ingestion import inspect_dataset
from apex_labs.io import (
    canonical_json_bytes,
    iter_json_lines,
    read_json,
    resolve_relative_file,
    write_json,
)
from apex_labs.provenance import apex_labs_code_identity, require_research_code_identity, sha256_bytes, sha256_file
from apex_labs.schemas import (
    validate_evidence_set,
    validate_evidence_set_definition,
    validate_metric_definition,
    validate_normalized_manifest,
    validate_segment_definition,
)
from apex_labs.schemas.versions import EVIDENCE_METHOD_ID, EVIDENCE_SET
from apex_labs.schemas.science_vocabulary import CEILING_RANK

# Experimental units this milestone can actually construct from normalized v1
# records. Frames and single events are refused by contract; stints and
# participants have no normalized representation yet and are refused here.
_GROUPING = {
    "segment_opportunity": "lap",
    "lap": "lap",
    "block": "block",
    "session": "session",
}
_MAX_ID = 128


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _evidence_hash(artifact: dict[str, Any]) -> str:
    return _canonical_sha(
        {key: value for key, value in artifact.items() if key != "evidence_set_sha256"}
    )


def _identifier(*parts: str) -> str:
    """A stable, contract-valid identifier built from already-valid parts."""
    joined = "-".join(parts)
    if len(joined) <= _MAX_ID:
        return joined
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"{joined[: _MAX_ID - 17]}-{digest}"


class _Ledger:
    """Stage-by-stage attrition accounting for one funnel level."""

    def __init__(self, definition: dict[str, Any]) -> None:
        self.entries: list[dict[str, Any]] = []
        self._rules = {rule["stage"]: rule for rule in definition["exclusion_rules"]}
        self._remaining: dict[str, int] = {}

    def count(self, level: str, stage: str, total: int, detail: str) -> None:
        self.entries.append(
            {
                "level": level,
                "stage": stage,
                "rule_id": None,
                "disposition": "counted",
                "considered": total,
                "excluded": 0,
                "remaining": total,
                "detail": detail,
            }
        )
        self._remaining[level] = total

    def exclude(
        self,
        level: str,
        stage: str,
        excluded: int,
        detail: str,
        *,
        disposition: str | None = None,
        require_rule: bool = True,
    ) -> None:
        considered = self._remaining[level]
        if excluded > considered:
            raise EvidenceError(f"Stage {stage} cannot exclude more evidence than it considered")
        rule = self._rules.get(stage)
        if rule is None and excluded and require_rule:
            raise EvidenceError(
                f"{excluded} unit(s) were removed at stage {stage!r} but no declared exclusion rule permits it"
            )
        if disposition is None:
            if rule is None:
                disposition = "excluded_by_preregistered_rule"
            else:
                disposition = (
                    "excluded_by_preregistered_rule" if rule["preregistered"] else "post_hoc_exclusion"
                )
        elif rule is not None and not rule["preregistered"] and excluded:
            disposition = "post_hoc_exclusion"
        self.entries.append(
            {
                "level": level,
                "stage": stage,
                "rule_id": None if rule is None else rule["rule_id"],
                "disposition": disposition,
                "considered": considered,
                "excluded": excluded,
                "remaining": considered - excluded,
                "detail": detail,
            }
        )
        self._remaining[level] = considered - excluded

    def note(self, level: str, stage: str, detail: str) -> None:
        """Record a stage that preserved everything it saw, with a limitation."""
        considered = self._remaining[level]
        self.entries.append(
            {
                "level": level,
                "stage": stage,
                "rule_id": None,
                "disposition": "accepted_with_limitations",
                "considered": considered,
                "excluded": 0,
                "remaining": considered,
                "detail": detail,
            }
        )


def _verified_dataset(dataset_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    dataset_dir = dataset_dir.resolve()
    manifest_path = dataset_dir / "manifest.json"
    manifest = validate_normalized_manifest(read_json(manifest_path))
    records_path = resolve_relative_file(dataset_dir, manifest["records_file"])
    inspect_dataset(manifest_path)
    return manifest, manifest_path, records_path


def _session_record(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if record["record_type"] == "session":
            return record
    raise EvidenceError("A contributing dataset carries no session record")


def _structural_ceiling(
    protocol: dict[str, Any],
    freeze: dict[str, Any],
    comparability_status: str,
    identity_variation_limits: list[str],
    identity_unverified: bool,
) -> tuple[str, str, str]:
    """Derive the strongest interpretation the design itself can support.

    The ceiling is read from the frozen protocol, never from how the result
    turned out. A design without an intervention cannot exceed association; an
    intervention without randomization or counterbalancing and predeclared
    criteria cannot exceed intervention-association.
    """
    has_intervention = bool(protocol["intervention_conditions"])
    strategy = freeze["randomization"]["strategy"]
    criteria_declared = protocol["predeclared_success_criteria"]["state"] == "declared"
    classification = "experimental" if has_intervention else "observational"
    if comparability_status == "inadequate":
        return "descriptive", classification, (
            "The declared contrast is not present in this evidence, so nothing beyond description is supported."
        )
    if not has_intervention:
        ceiling = "associational"
        rationale = (
            "The frozen protocol declares no intervention condition, so the comparison is observational "
            "and cannot exceed association."
        )
    elif strategy in {"randomized", "counterbalanced"} and criteria_declared:
        ceiling = "causal_candidate"
        rationale = (
            f"The frozen protocol declares intervention conditions, a {strategy} assignment, and predeclared "
            "success criteria. A causal candidate still requires scientific review and replication."
        )
    else:
        ceiling = "intervention_associated"
        rationale = (
            f"The frozen protocol declares intervention conditions but assignment is {strategy!r} and success criteria "
            f"are {protocol['predeclared_success_criteria']['state']!r}, so the result can only be associated with the "
            "delivered intervention."
        )
    limits = list(identity_variation_limits)
    if identity_unverified:
        # An unavailable must-match identity can conceal arm-specific setup or
        # build changes. It cannot support a causal-candidate interpretation.
        limits.append("intervention_associated")
    if limits:
        limit = min(limits, key=lambda item: CEILING_RANK[item])
        if CEILING_RANK[ceiling] > CEILING_RANK[limit]:
            ceiling = limit
        rationale += (
            f" Protected build/setup comparability limits the design to {ceiling!r}; missing identity is not a match."
        )
    return ceiling, classification, rationale


def _extract_value(
    extractor: dict[str, Any], records: list[dict[str, Any]], aggregation: dict[str, Any]
) -> tuple[float | None, int, int, float | None, str]:
    """Reduce one unit's in-segment records to a single value.

    Returns the value, the number of records that supplied it, the number that
    could not, the within-unit dispersion, and the value provenance.
    """
    concept = extractor["concept"]
    kind = extractor["kind"]
    if kind == "segment_threshold_distance":
        candidates: list[tuple[float, float]] = []
        missing = 0
        for record in records:
            field = record["fields"].get(concept)
            position = segment_module.record_position(record, "distance_range")
            if field is None or field["provenance"] == "unavailable" or position is None:
                missing += 1
                continue
            if field["value"] >= extractor["threshold"]:
                candidates.append((position, field["value"]))
        if not candidates:
            return None, 0, len(records), None, "derived"
        candidates.sort()
        chosen = candidates[0] if extractor["direction"] == "first_at_or_above" else candidates[-1]
        return chosen[0], len(candidates), missing, None, "derived"

    values: list[float] = []
    missing = 0
    provenances: set[str] = set()
    for record in records:
        field = record["fields"].get(concept)
        if field is None or field["provenance"] == "unavailable":
            missing += 1
            continue
        values.append(field["value"])
        provenances.add(field["provenance"])
    if not values:
        return None, 0, len(records), None, "derived"
    if kind == "record_field":
        if len(values) != 1:
            raise EvidenceError(
                f"A single-record metric matched {len(values)} records for one unit; the experimental unit is ambiguous"
            )
        return values[0], 1, missing, None, sorted(provenances)[0]
    method = extractor["method"]
    if method == "minimum":
        value = min(values)
    elif method == "maximum":
        value = max(values)
    elif method == "arithmetic_mean":
        value = stats.mean(values)
    else:
        value = stats.median(values)
    dispersion = None
    if aggregation["dispersion"] == "median_absolute_deviation":
        dispersion = stats.median_absolute_deviation(values)
    return value, len(values), missing, dispersion, "derived"


def _dataset_context(
    manifest: dict[str, Any],
    manifest_path: Path,
    session: dict[str, Any],
    condition_to_arm: dict[str, str],
    condition_to_coaching: dict[str, str],
    records_considered: int,
) -> dict[str, Any]:
    collection = manifest["collection_context"]
    # Exploratory pilot evidence is refused here BY NAME rather than only falling
    # foul of the missing-condition rule below. Both refusals are correct, but a
    # reader of the error needs to know the dataset is permanently out of scope
    # for comparable evidence, not that someone forgot to declare a condition.
    eligibility = manifest.get("scientific_eligibility")
    if eligibility is not None and not eligibility["primary_corpus_pooling"]:
        raise EvidenceError(
            f"Dataset {manifest['dataset_id']} is {eligibility['stratum']} evidence and is "
            "permanently excluded from comparable evidence sets and primary pooling; "
            "it supports descriptive analysis and hypothesis generation only"
        )
    condition_id = collection["condition_id"]
    block_id = collection["block_id"]
    if condition_id is None or block_id is None:
        raise EvidenceError(
            f"Dataset {manifest['dataset_id']} declares no collection condition or block; "
            "comparable evidence requires an explicit experimental context"
        )
    arm = condition_to_arm.get(condition_id)
    return {
        "dataset_id": manifest["dataset_id"],
        "fingerprint": manifest["dataset_fingerprint"],
        "normalized_manifest_sha256": sha256_file(manifest_path),
        "records_sha256": manifest["records_sha256"],
        "synthetic": manifest["synthetic"],
        "session_id": session["session_id"],
        "participant": session["driver_id"],
        "simulator": session["simulator"],
        "car": session["car"],
        "track": session["track"],
        "layout": session["layout"],
        "condition_id": condition_id,
        "block_id": block_id,
        "arm": arm,
        "coaching_state": condition_to_coaching.get(condition_id, "unknown"),
        "configuration_identity": comparability_module.source_identity(
            manifest, "configuration_identity"
        ),
        "product_build": comparability_module.source_identity(manifest, "product_build"),
        "normalization_contract": (
            f"{manifest['normalization_version']}/{manifest['adapter']['id']}@{manifest['adapter']['version']}"
        ),
        "records_considered": records_considered,
    }


def build_evidence_set(
    definition_path: Path,
    segment_path: Path,
    protocol_freeze_path: Path,
    metric_path: Path,
    dataset_dirs: list[Path],
    output_dir: Path,
    *,
    built_at: str,
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = validate_evidence_set_definition(read_json(definition_path))
    segment = validate_segment_definition(read_json(segment_path))
    freeze = verify_protocol_freeze(read_json(protocol_freeze_path))
    metric = validate_metric_definition(read_json(metric_path))
    protocol = freeze["protocol"]

    if _canonical_sha(segment) != definition["segment"]["sha256"]:
        raise IntegrityError("Segment definition content does not match the hash bound by the evidence definition")
    if (
        segment["segment_definition_id"] != definition["segment"]["segment_definition_id"]
        or segment["version"] != definition["segment"]["version"]
    ):
        raise IntegrityError("Segment definition identity does not match the evidence definition binding")
    bound_protocol = definition["protocol"]
    if freeze["freeze_id"] != bound_protocol["freeze_id"] or freeze["freeze_sha256"] != bound_protocol["freeze_sha256"]:
        raise IntegrityError("Frozen protocol does not match the protocol bound by the evidence definition")
    if protocol["experiment_id"] != bound_protocol["experiment_id"] or protocol["version"] != bound_protocol["experiment_version"]:
        raise IntegrityError("Frozen protocol identity does not match the evidence definition binding")
    unit_metric = definition["unit_metric"]
    if _canonical_sha(metric) != unit_metric["sha256"]:
        raise IntegrityError("Metric definition content does not match the hash bound by the evidence definition")
    if metric["metric_id"] != unit_metric["metric_id"] or metric["version"] != unit_metric["version"]:
        raise IntegrityError("Metric definition identity does not match the evidence definition binding")
    if metric["directionality"] != unit_metric["directionality"] or metric["unit"] != unit_metric["unit"]:
        raise IntegrityError("Metric directionality/unit does not match the evidence definition binding")
    if definition["synthetic"] != freeze["synthetic"]:
        raise IntegrityError("Evidence definition and frozen protocol disagree about synthetic classification")
    identity_variation_limits = comparability_module.identity_variation_limits(
        definition, protocol
    )

    experimental_unit = definition["experimental_unit"]
    if experimental_unit not in _GROUPING:
        raise EvidenceError(
            f"Experimental unit {experimental_unit!r} has no normalized v1 representation; "
            f"supported units are {sorted(_GROUPING)}"
        )
    resampling_unit = definition["resampling_unit"]
    if resampling_unit not in set(_GROUPING) | {"participant"}:
        raise EvidenceError(f"Resampling unit {resampling_unit!r} has no normalized v1 representation")

    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=definition["synthetic"])

    condition_to_arm = {
        condition: arm["arm"] for arm in definition["factor"]["arms"] for condition in arm["condition_ids"]
    }
    condition_to_coaching = {
        condition: arm["coaching_state"]
        for arm in definition["factor"]["arms"]
        for condition in arm["condition_ids"]
    }
    extractor = unit_metric["extractor"]
    aggregation = definition["aggregation"]
    coverage = segment["coverage_requirements"]
    ledger = _Ledger(definition)

    contexts: list[dict[str, Any]] = []
    keys: list[dict[str, str | None]] = []
    applicability_entries: list[dict[str, Any]] = []
    candidate_records: dict[str, list[dict[str, Any]]] = {}
    lap_records: dict[str, dict[str, dict[str, Any]]] = {}
    records_streamed = 0
    other_type = 0
    out_of_order = 0
    protocol_mismatch = 0

    for dataset_dir in dataset_dirs:
        manifest, manifest_path, records_path = _verified_dataset(dataset_dir)
        if manifest["synthetic"] != definition["synthetic"]:
            raise EvidenceError(
                f"Dataset {manifest['dataset_id']} is {'synthetic' if manifest['synthetic'] else 'real'} "
                "and cannot join evidence of the other classification"
            )
        records = list(iter_json_lines(records_path))
        records_streamed += len(records)
        session = _session_record(records)
        context = _dataset_context(
            manifest, manifest_path, session, condition_to_arm, condition_to_coaching, len(records)
        )
        dataset_id = context["dataset_id"]
        if any(existing["dataset_id"] == dataset_id for existing in contexts):
            raise EvidenceError(f"Dataset {dataset_id} was supplied more than once")
        if context["arm"] is None:
            protocol_mismatch += len(records)
            continue
        applicability_entries.append(
            segment_module.applicability(segment, context["simulator"], context["track"], context["layout"])
        )
        contexts.append(context)
        keys.append(
            comparability_module.comparability_key(
                session=session,
                manifest=manifest,
                condition_id=context["condition_id"],
                coaching_state=context["coaching_state"],
                segment=segment,
                unit_metric=unit_metric,
            )
        )
        laps: dict[str, dict[str, Any]] = {}
        kept: list[dict[str, Any]] = []
        previous_index = -1
        for record in records:
            if record["sequence_index"] <= previous_index:
                out_of_order += 1
                continue
            previous_index = record["sequence_index"]
            if record["record_type"] == "lap":
                laps[record["lap_id"]] = record
            if record["record_type"] == extractor["record_type"]:
                kept.append(record)
            else:
                other_type += 1
        candidate_records[dataset_id] = kept
        lap_records[dataset_id] = laps

    if not contexts:
        raise EvidenceError(
            "No contributing dataset carries a condition the evidence definition assigns to an arm"
        )
    geometry_fingerprint = segment_module.require_single_geometry(
        applicability_entries, segment["segment_definition_id"]
    )

    ledger.count("record", "records_streamed", records_streamed, "All normalized records streamed from every supplied dataset.")
    ledger.exclude(
        "record",
        "protocol_mismatch",
        protocol_mismatch,
        "Records from datasets whose collection condition the protocol does not assign to a declared arm.",
    )
    ledger.exclude(
        "record",
        "out_of_order_or_corrupt",
        out_of_order,
        "Records whose sequence index did not advance monotonically within their dataset.",
        disposition="structurally_invalid",
        require_rule=False,
    )
    ledger.exclude(
        "record",
        "record_type_not_read",
        other_type,
        f"Records of a type the declared unit metric does not read (it reads {extractor['record_type']}).",
        require_rule=False,
    )

    # Segment, channel, and lap-validity filtering.
    outside_segment = 0
    missing_channel = 0
    invalid_lap = 0
    incident_affected = 0
    discontinuity = 0
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    limitations: list[str] = []
    if extractor["kind"] == "record_field":
        limitations.append(
            "The declared unit metric is a whole-lap record field. The segment definition constrains identity, "
            "applicability, and geometry, but not which records inside the lap contributed."
        )

    for context in contexts:
        dataset_id = context["dataset_id"]
        laps = lap_records[dataset_id]
        for record in candidate_records[dataset_id]:
            if extractor["kind"] != "record_field" and not segment_module.selects(segment, record):
                outside_segment += 1
                continue
            lap = laps.get(record.get("lap_id", ""))
            if lap is not None:
                validity = lap["fields"].get("lap_valid")
                if validity is not None and validity["provenance"] != "unavailable" and validity["value"] is False:
                    invalid_lap += 1
                    continue
            field = record["fields"].get(extractor["concept"])
            if field is None or field["provenance"] == "unavailable":
                missing_channel += 1
                continue
            incident = record["fields"].get("incident_state")
            off_track = record["fields"].get("off_track_state")
            if (incident is not None and incident["provenance"] != "unavailable" and incident["value"]) or (
                off_track is not None and off_track["provenance"] != "unavailable" and off_track["value"]
            ):
                incident_affected += 1
                continue
            if any(flag.startswith(("pit", "replay", "discontinuity")) for flag in record.get("quality_flags", [])):
                discontinuity += 1
                continue
            selected[dataset_id].append(record)

    ledger.exclude("record", "outside_segment", outside_segment, "Records positioned outside the declared segment region or phase.")
    ledger.exclude("record", "invalid_lap", invalid_lap, "Records belonging to a lap the source marked invalid.")
    ledger.exclude(
        "record",
        "missing_required_channel",
        missing_channel,
        "Records whose metric channel was absent or explicitly unavailable; unavailable is never read as zero.",
        disposition="unavailable",
        require_rule=False,
    )
    ledger.exclude("record", "incident_affected", incident_affected, "Records flagged with an incident or off-track state.")
    ledger.exclude(
        "record",
        "pit_replay_discontinuity",
        discontinuity,
        "Records carrying a pit, replay, or discontinuity quality flag.",
    )

    # Unit formation.
    grouping = _GROUPING[experimental_unit]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for context in contexts:
        dataset_id = context["dataset_id"]
        for record in selected[dataset_id]:
            if grouping == "lap":
                key = record["lap_id"]
            elif grouping == "block":
                key = context["block_id"]
            else:
                key = context["session_id"]
            groups[(dataset_id, key)].append(record)

    context_by_id = {context["dataset_id"]: context for context in contexts}

    raw_units: list[dict[str, Any]] = []
    insufficient_coverage = 0
    for (dataset_id, key), records in sorted(groups.items()):
        context = context_by_id[dataset_id]
        ratio, _ = segment_module.concept_coverage(segment, records)
        value, used, missing, dispersion, provenance = _extract_value(extractor, records, aggregation)
        enough_records = len(records) >= max(
            aggregation["minimum_source_records"],
            1 if extractor["kind"] == "record_field" else coverage["minimum_records_per_unit"],
        )
        if (
            value is None
            or not enough_records
            or (extractor["kind"] != "record_field" and ratio < coverage["minimum_concept_coverage_ratio"])
        ):
            insufficient_coverage += 1
            continue
        lap = lap_records[dataset_id].get(key if grouping == "lap" else "")
        lap_number = None if lap is None else lap["lap_number"]
        raw_units.append(
            {
                "unit_id": _identifier(dataset_id, key),
                "unit_level": experimental_unit,
                "dataset_id": dataset_id,
                "session_id": context["session_id"],
                "block_id": context["block_id"],
                "condition_id": context["condition_id"],
                "arm": context["arm"],
                "value": value,
                "unit_of_measure": unit_metric["unit"],
                "aggregation_method": aggregation["method"],
                "source_records_considered": used + missing,
                "source_records_used": used,
                "source_records_missing": missing,
                "within_unit_dispersion": dispersion,
                "provenance": provenance,
                "_sort_key": (dataset_id, lap_number if lap_number is not None else 0, key),
                "_lap_number": lap_number,
                "_coverage_ratio": ratio,
            }
        )

    ledger.count("unit", "units_formed", len(raw_units) + insufficient_coverage, "Candidate experimental units formed from the surviving records.")
    ledger.exclude(
        "unit",
        "insufficient_coverage",
        insufficient_coverage,
        "Units below the declared minimum record count, concept-coverage ratio, or with no extractable metric value.",
    )
    duplicates = len(raw_units) - len({unit["unit_id"] for unit in raw_units})
    if duplicates:
        raise EvidenceError("Two experimental units resolved to the same identity; evidence would be double counted")
    ledger.exclude("unit", "duplicate_evidence", 0, "No two units resolved to the same identity.")
    confound_rules = [rule for rule in definition["exclusion_rules"] if rule["stage"] == "confound_based"]
    ledger.exclude(
        "unit",
        "confound_based",
        0,
        "Declared confound-based rules: "
        + (", ".join(rule["rule_id"] for rule in confound_rules) if confound_rules else "none declared")
        + ". No unit met a confound-based exclusion.",
        require_rule=False,
    )

    comparability = comparability_module.assess(
        definition, keys, {context["arm"] for context in contexts}
    )
    limitations.extend(comparability["limitations"])

    # Pairing and holdout.
    holdout_policy = definition["holdout"]["policy"]
    reserved = set(definition["holdout"]["reserved"])
    for unit in raw_units:
        if holdout_policy == "reserved_blocks":
            unit["holdout"] = unit["block_id"] in reserved
        elif holdout_policy == "reserved_sessions":
            unit["holdout"] = unit["session_id"] in reserved
        else:
            unit["holdout"] = False

    bucket_fields = [field for field in definition["pairing"]["key"] if field != "order_index"]
    field_source = {
        "participant": lambda unit: context_by_id[unit["dataset_id"]]["participant"],
        "simulator": lambda unit: context_by_id[unit["dataset_id"]]["simulator"],
        "car": lambda unit: context_by_id[unit["dataset_id"]]["car"],
        "track": lambda unit: context_by_id[unit["dataset_id"]]["track"],
        "layout": lambda unit: context_by_id[unit["dataset_id"]]["layout"],
        "session_id": lambda unit: unit["session_id"],
        "block_id": lambda unit: unit["block_id"],
    }
    for unit in raw_units:
        parts = [f"{field}={field_source[field](unit)}" for field in bucket_fields]
        unit["pair_key"] = "|".join(parts) if parts else "all"

    ordinals: dict[tuple[str, str], int] = defaultdict(int)
    for unit in sorted(raw_units, key=lambda item: (item["pair_key"], item["arm"], item["_sort_key"])):
        bucket = (unit["pair_key"], unit["arm"])
        unit["order_index"] = ordinals[bucket]
        ordinals[bucket] += 1

    covariate_fields = comparability["covariate_fields"]
    key_by_dataset = {context["dataset_id"]: key for context, key in zip(contexts, keys)}
    units: list[dict[str, Any]] = []
    for unit in raw_units:
        covariates: dict[str, Any] = {
            "lap_number": unit["_lap_number"],
            "concept_coverage_ratio": unit["_coverage_ratio"],
            "order_index": unit["order_index"],
        }
        for field in covariate_fields:
            covariates[field] = key_by_dataset[unit["dataset_id"]][field]
        units.append(
            {
                key: value
                for key, value in {**unit, "covariates": covariates}.items()
                if not key.startswith("_")
            }
        )
    units.sort(key=lambda item: item["unit_id"])

    pairs: list[dict[str, Any]] = []
    paired_ids: set[str] = set()
    if definition["pairing"]["kind"] == "paired":
        by_bucket: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for unit in units:
            by_bucket[unit["pair_key"]][unit["arm"]].append(unit)
        for pair_key in sorted(by_bucket):
            baseline = sorted(by_bucket[pair_key]["baseline"], key=lambda item: item["order_index"])
            intervention = sorted(by_bucket[pair_key]["intervention"], key=lambda item: item["order_index"])
            for left, right in zip(baseline, intervention):
                if left["order_index"] != right["order_index"]:
                    continue
                pairs.append(
                    {
                        "pair_id": _identifier(left["unit_id"], right["unit_id"]),
                        "pair_key": pair_key,
                        "cluster_id": _pair_cluster_id(resampling_unit, left, right, context_by_id),
                        "baseline_unit_id": left["unit_id"],
                        "intervention_unit_id": right["unit_id"],
                        "holdout": bool(left["holdout"] or right["holdout"]),
                    }
                )
                paired_ids.update({left["unit_id"], right["unit_id"]})
        pairs.sort(key=lambda item: item["pair_id"])
    unpaired = sorted(unit["unit_id"] for unit in units if unit["unit_id"] not in paired_ids)

    holdout_units = [unit for unit in units if unit["holdout"]]
    ledger.note(
        "unit",
        "holdout_reserved",
        f"{len(holdout_units)} unit(s) reserved for replication and withheld from the primary analysis scope."
        if holdout_units
        else "No unit was reserved for replication under the declared holdout policy.",
    )
    ledger.count("pair", "pairable_units", len(units), "Units offered to the declared pairing rule.")
    ledger.exclude(
        "pair",
        "unpaired_units",
        len(unpaired),
        "Units with no counterpart under the declared pairing key; they are preserved and reported, never discarded.",
        require_rule=False,
    )

    structural_ceiling, collection_classification, ceiling_rationale = _structural_ceiling(
        protocol,
        freeze,
        comparability["status"],
        identity_variation_limits,
        bool(comparability["identity_limitations"]),
    )
    limitations.append(ceiling_rationale)
    limitations.append(
        f"Segment geometry fingerprint {geometry_fingerprint} was single-valued across every contributing dataset."
    )
    if definition["synthetic"]:
        limitations.append(
            "Synthetic evidence demonstrates mechanics only and is permanently ineligible for scientific promotion."
        )

    clusters = (
        {pair["cluster_id"] for pair in pairs}
        if definition["pairing"]["kind"] == "paired"
        else {_cluster_id(resampling_unit, unit, context_by_id) for unit in units}
    )
    counts = {
        "source_records": records_streamed,
        "included_units": len(units),
        "baseline_units": sum(1 for unit in units if unit["arm"] == "baseline"),
        "intervention_units": sum(1 for unit in units if unit["arm"] == "intervention"),
        "pairs": len(pairs),
        "unpaired_units": len(unpaired),
        "holdout_units": len(holdout_units),
        "participants": len({context["participant"] for context in contexts}),
        "sessions": len({context["session_id"] for context in contexts}),
        "blocks": len({context["block_id"] for context in contexts}),
        "resampling_clusters": len(clusters),
    }

    artifact: dict[str, Any] = {
        "schema_version": EVIDENCE_SET,
        "evidence_set_id": definition["evidence_set_id"],
        "version": definition["version"],
        "built_at": built_at,
        "synthetic": definition["synthetic"],
        "classification": "comparable_evidence_not_scientific_evidence",
        "method_id": EVIDENCE_METHOD_ID,
        "evidence_set_sha256": "0" * 64,
        "definition": definition,
        "definition_sha256": _canonical_sha(definition),
        "segment_definition": segment,
        "segment_definition_sha256": _canonical_sha(segment),
        "protocol": {
            "freeze_id": freeze["freeze_id"],
            "freeze_sha256": freeze["freeze_sha256"],
            "protocol_id": freeze["protocol_id"],
            "protocol_version": freeze["protocol_version"],
            "protocol_sha256": freeze["protocol_sha256"],
            "randomization_strategy": freeze["randomization"]["strategy"],
            "collection_classification": collection_classification,
            "minimum_sample_requirements_state": protocol["minimum_sample_requirements"]["state"],
        },
        "datasets": sorted(contexts, key=lambda item: item["dataset_id"]),
        "comparability": {
            "status": comparability["status"],
            "must_match_fields": comparability["must_match_fields"],
            "observed_values": comparability["observed_values"],
            "permitted_variation": comparability["permitted_variation"],
            "violations": comparability["violations"],
            "limitations": comparability["limitations"],
            "identity_limitations": comparability["identity_limitations"],
            "covariate_fields": comparability["covariate_fields"],
        },
        "units_declaration": {
            "experimental_unit": experimental_unit,
            "resampling_unit": resampling_unit,
            "factor_varies_at": definition["factor"]["varies_at"],
            "pseudoreplication_guard": "resampling_unit_at_or_above_factor_variation_level",
        },
        "attrition": ledger.entries,
        "post_hoc_exclusions_present": any(
            entry["disposition"] == "post_hoc_exclusion" for entry in ledger.entries
        ),
        "counts": counts,
        "units": units,
        "pairs": pairs,
        "unpaired_unit_ids": unpaired,
        "holdout": {
            "policy": holdout_policy,
            "reserved": definition["holdout"]["reserved"],
            "replication_scope": definition["holdout"]["replication_scope"],
            "reserved_unit_ids": sorted(unit["unit_id"] for unit in holdout_units),
            "primary_scope_excludes_holdout": True,
        },
        "confounds": definition["confounds"],
        "structural_interpretation_ceiling": structural_ceiling,
        "code_identity": identity,
        "integrity": {
            "datasets_verified": True,
            "records_streamed": records_streamed,
            "segment_applicability_verified": True,
            "deterministic_ordering": "unit_id_lexicographic",
        },
        "limitations": limitations,
    }
    artifact["evidence_set_sha256"] = _evidence_hash(artifact)
    validate_evidence_set(artifact)
    with atomic_output_directory(output_dir, operation="evidence-set", error_type=EvidenceError) as staged:
        write_json(staged / "evidence-set.json", artifact)
    return artifact


def _pair_cluster_id(
    resampling_unit: str,
    baseline: dict[str, Any],
    intervention: dict[str, Any],
    context_by_id: dict[str, dict[str, Any]],
) -> str:
    """The independent replicate a paired difference belongs to.

    A pair spans both arms, so its cluster is the pair of blocks (or sessions)
    that produced it, not the arbitrary choice of one side. Assigning a pair to
    one arm's block would overstate the number of independent replicates.
    """
    if resampling_unit in {"lap", "segment_opportunity"}:
        return _identifier(baseline["unit_id"], intervention["unit_id"])
    if resampling_unit == "block":
        return f"{baseline['block_id']}+{intervention['block_id']}"
    if resampling_unit == "session":
        return f"{baseline['session_id']}+{intervention['session_id']}"
    return context_by_id[baseline["dataset_id"]]["participant"]


def _cluster_id(
    resampling_unit: str, unit: dict[str, Any], context_by_id: dict[str, dict[str, Any]]
) -> str:
    if resampling_unit in {"lap", "segment_opportunity"}:
        return unit["unit_id"]
    if resampling_unit == "block":
        return unit["block_id"]
    if resampling_unit == "session":
        return unit["session_id"]
    return context_by_id[unit["dataset_id"]]["participant"]


def _resolve_evidence_path(path: Path) -> Path:
    return path / "evidence-set.json" if path.is_dir() else path


def verify_evidence_set(
    evidence_path: Path,
    definition_path: Path,
    segment_path: Path,
    protocol_freeze_path: Path,
    metric_path: Path,
    dataset_dirs: list[Path],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Rebuild the evidence set from its declared inputs and compare byte for byte.

    Verification recomputes rather than trusting the stored hashes, so tampering
    with the artifact, a dataset, the segment, the metric, or the protocol is
    detected rather than merely re-hashed.
    """
    artifact = validate_evidence_set(read_json(_resolve_evidence_path(evidence_path)))
    if artifact["evidence_set_sha256"] != _evidence_hash(artifact):
        raise IntegrityError("Evidence set hash does not match its content")
    if artifact["definition_sha256"] != _canonical_sha(artifact["definition"]):
        raise IntegrityError("Evidence set definition hash does not match the embedded definition")
    if artifact["segment_definition_sha256"] != _canonical_sha(artifact["segment_definition"]):
        raise IntegrityError("Evidence set segment hash does not match the embedded segment definition")

    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="apex-labs-evidence-verify-") as directory:
        rebuilt = build_evidence_set(
            definition_path,
            segment_path,
            protocol_freeze_path,
            metric_path,
            dataset_dirs,
            Path(directory) / "rebuilt",
            built_at=artifact["built_at"],
            project_root=project_root,
            code_identity=artifact["code_identity"],
        )
    if rebuilt != artifact:
        differing = sorted(
            key for key in set(rebuilt) | set(artifact) if rebuilt.get(key) != artifact.get(key)
        )
        raise IntegrityError(
            f"Evidence set is not reproducible from its declared inputs; differing sections: {differing}"
        )
    current = apex_labs_code_identity(project_root)
    return {
        "valid": True,
        "evidence_set_id": artifact["evidence_set_id"],
        "evidence_set_sha256": artifact["evidence_set_sha256"],
        "comparability": artifact["comparability"]["status"],
        "included_units": artifact["counts"]["included_units"],
        "pairs": artifact["counts"]["pairs"],
        "holdout_units": artifact["counts"]["holdout_units"],
        "structural_interpretation_ceiling": artifact["structural_interpretation_ceiling"],
        "code_identity_match": (
            current["code_and_schema_sha256"] == artifact["code_identity"]["code_and_schema_sha256"]
        ),
    }
