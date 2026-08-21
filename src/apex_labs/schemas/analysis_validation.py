"""Runtime validation for descriptive analysis definitions and run artifacts."""

from __future__ import annotations

from typing import Any

from apex_labs.normalization.concepts import (
    NORMALIZED_CONCEPTS,
    NUMERIC_SUMMARY_CONCEPTS,
    RECORD_TYPES,
)
from apex_labs.schemas import versions
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
from apex_labs.schemas.research_validation import _code_identity

COMPUTATION_KINDS = {"record_inventory", "concept_availability", "descriptive_summary", "event_yield"}
EVENT_YIELD_RECORD_TYPES = {"segment", "telemetry_sample", "distance_bin", "driver_input_event"}


def _computation(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    kind = _enum(obj.get("kind"), COMPUTATION_KINDS, f"{path}.kind")
    if kind == "record_inventory":
        _keys(obj, path, required={"computation_id", "kind"})
    elif kind == "concept_availability":
        _keys(obj, path, required={"computation_id", "kind", "record_type"})
        if obj["record_type"] is not None:
            _enum(obj["record_type"], RECORD_TYPES, f"{path}.record_type")
    elif kind == "descriptive_summary":
        _keys(obj, path, required={"computation_id", "kind", "record_type", "concept", "group_by"})
        _enum(obj["record_type"], RECORD_TYPES, f"{path}.record_type")
        concept = _enum(obj["concept"], NORMALIZED_CONCEPTS, f"{path}.concept")
        if concept not in NUMERIC_SUMMARY_CONCEPTS:
            _fail(f"{path}.concept", "boolean and textual concepts cannot receive a numeric summary")
        group_by = _enum(obj["group_by"], {"dataset", "lap"}, f"{path}.group_by")
        if group_by == "lap" and obj["record_type"] == "session":
            _fail(f"{path}.group_by", "session records carry no lap identity and cannot be grouped per lap")
    else:
        _keys(obj, path, required={"computation_id", "kind", "record_type"})
        _enum(obj["record_type"], EVENT_YIELD_RECORD_TYPES, f"{path}.record_type")
    _id(obj["computation_id"], f"{path}.computation_id")
    return obj


def validate_analysis_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.ANALYSIS_DEFINITION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "analysis_id", "version", "title", "purpose",
            "classification", "computations", "limitations",
        },
    )
    _id(obj["analysis_id"], "$.analysis_id")
    _string(obj["version"], "$.version")
    _string(obj["title"], "$.title")
    _string(obj["purpose"], "$.purpose")
    if obj["classification"] != "descriptive_observational":
        _fail("$.classification", "must be descriptive_observational; no inferential analysis kind exists in v1")
    computations = _list(obj["computations"], "$.computations", nonempty=True)
    seen: set[str] = set()
    for index, item in enumerate(computations):
        computation = _computation(item, f"$.computations[{index}]")
        if computation["computation_id"] in seen:
            _fail(f"$.computations[{index}].computation_id", "must be unique within the definition")
        seen.add(computation["computation_id"])
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj


def _count(value: Any, path: str) -> int:
    return _integer(value, path, minimum=0)


def _count_map(value: Any, path: str) -> dict[str, int]:
    obj = _object(value, path)
    for name, count in obj.items():
        _string(name, f"{path} key")
        _count(count, f"{path}.{name}")
    return obj


def _summary(value: Any, path: str) -> None:
    obj = _object(value, path)
    _keys(obj, path, required={"count", "minimum", "maximum", "mean", "median", "q1", "q3", "mad"})
    _integer(obj["count"], f"{path}.count", minimum=1)
    for name in ("minimum", "maximum", "mean", "median", "q1", "q3"):
        _number(obj[name], f"{path}.{name}")
    if _number(obj["mad"], f"{path}.mad") < 0:
        _fail(f"{path}.mad", "must be non-negative")
    if obj["minimum"] > obj["maximum"]:
        _fail(path, "minimum must not exceed maximum")


def _result(value: Any, path: str, definition_by_id: dict[str, dict[str, Any]]) -> str:
    obj = _object(value, path)
    kind = _enum(obj.get("kind"), COMPUTATION_KINDS, f"{path}.kind")
    computation_id = _id(obj.get("computation_id"), f"{path}.computation_id")
    declared = definition_by_id.get(computation_id)
    if declared is None:
        _fail(f"{path}.computation_id", "does not correspond to a declared computation")
    if declared["kind"] != kind:
        _fail(f"{path}.kind", f"declared computation {computation_id} has kind {declared['kind']!r}")
    if kind == "record_inventory":
        _keys(obj, path, required={"computation_id", "kind", "record_counts", "quality_flag_counts"})
        counts = _count_map(obj["record_counts"], f"{path}.record_counts")
        for record_type in counts:
            _enum(record_type, RECORD_TYPES, f"{path}.record_counts key")
        _count_map(obj["quality_flag_counts"], f"{path}.quality_flag_counts")
    elif kind == "concept_availability":
        _keys(obj, path, required={"computation_id", "kind", "record_type", "records_scanned", "concepts"})
        if obj["record_type"] != declared["record_type"]:
            _fail(f"{path}.record_type", "must repeat the declared computation record_type")
        _count(obj["records_scanned"], f"{path}.records_scanned")
        concepts = _object(obj["concepts"], f"{path}.concepts")
        if set(concepts) != NORMALIZED_CONCEPTS:
            missing = sorted(NORMALIZED_CONCEPTS - concepts.keys())
            unknown = sorted(concepts.keys() - NORMALIZED_CONCEPTS)
            _fail(f"{path}.concepts", f"must enumerate every normalized concept; missing={missing}, unknown={unknown}")
        for concept, availability in concepts.items():
            concept_path = f"{path}.concepts.{concept}"
            item = _object(availability, concept_path)
            _keys(item, concept_path, required={"present", "measured", "derived", "estimated", "unavailable"})
            present = _count(item["present"], f"{concept_path}.present")
            provenance_total = sum(
                _count(item[name], f"{concept_path}.{name}")
                for name in ("measured", "derived", "estimated", "unavailable")
            )
            if provenance_total != present:
                _fail(concept_path, "provenance counts must sum to the present count")
    elif kind == "descriptive_summary":
        required = {"computation_id", "kind", "record_type", "concept", "group_by", "attrition"}
        group_by = declared["group_by"]
        required.add("summary" if group_by == "dataset" else "per_lap")
        _keys(obj, path, required=required)
        for field in ("record_type", "concept", "group_by"):
            if obj[field] != declared[field]:
                _fail(f"{path}.{field}", f"must repeat the declared computation {field}")
        attrition = _object(obj["attrition"], f"{path}.attrition")
        _keys(
            attrition,
            f"{path}.attrition",
            required={"records_scanned", "records_of_type", "field_present", "values_included", "values_unavailable"},
        )
        for name in ("records_scanned", "records_of_type", "field_present", "values_included", "values_unavailable"):
            _count(attrition[name], f"{path}.attrition.{name}")
        if attrition["values_included"] + attrition["values_unavailable"] != attrition["field_present"]:
            _fail(f"{path}.attrition", "included and unavailable values must sum to field_present")
        if attrition["field_present"] > attrition["records_of_type"] or attrition["records_of_type"] > attrition["records_scanned"]:
            _fail(f"{path}.attrition", "counts must be monotone: field_present <= records_of_type <= records_scanned")
        if group_by == "dataset":
            summary = obj["summary"]
            if attrition["values_included"] == 0:
                if summary is not None:
                    _fail(f"{path}.summary", "must be null when no values were included")
            else:
                _summary(summary, f"{path}.summary")
        else:
            per_lap = _object(obj["per_lap"], f"{path}.per_lap")
            for lap_id, summary in per_lap.items():
                _id(lap_id, f"{path}.per_lap key")
                if summary is not None:
                    _summary(summary, f"{path}.per_lap.{lap_id}")
    else:
        required = {"computation_id", "kind", "record_type", "total", "per_lap"}
        if declared["record_type"] == "driver_input_event":
            required.add("per_event_type")
        _keys(obj, path, required=required)
        if obj["record_type"] != declared["record_type"]:
            _fail(f"{path}.record_type", "must repeat the declared computation record_type")
        total = _count(obj["total"], f"{path}.total")
        per_lap = _count_map(obj["per_lap"], f"{path}.per_lap")
        if sum(per_lap.values()) != total:
            _fail(f"{path}.per_lap", "per-lap counts must sum to total")
        if "per_event_type" in obj:
            per_event = _count_map(obj["per_event_type"], f"{path}.per_event_type")
            if sum(per_event.values()) != total:
                _fail(f"{path}.per_event_type", "per-event-type counts must sum to total")
    return computation_id


def validate_analysis_run(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.ANALYSIS_RUN)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "run_id", "created_at", "classification", "synthetic", "method_id",
            "run_sha256", "definition", "definition_sha256", "dataset", "metric_definitions",
            "code_identity", "integrity", "results",
        },
    )
    _id(obj["run_id"], "$.run_id")
    _timestamp(obj["created_at"], "$.created_at")
    if obj["classification"] != "descriptive_summary_not_scientific_evidence":
        _fail("$.classification", "analysis runs are descriptive summaries, never scientific evidence")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if obj["method_id"] != versions.DESCRIPTIVE_METHOD_ID:
        _fail("$.method_id", f"must be {versions.DESCRIPTIVE_METHOD_ID!r}")
    _sha(obj["run_sha256"], "$.run_sha256")
    definition = validate_analysis_definition(obj["definition"])
    _sha(obj["definition_sha256"], "$.definition_sha256")
    dataset = _object(obj["dataset"], "$.dataset")
    _keys(
        dataset,
        "$.dataset",
        required={"dataset_id", "fingerprint", "normalized_manifest_sha256", "records_sha256", "synthetic"},
    )
    _id(dataset["dataset_id"], "$.dataset.dataset_id")
    for field in ("fingerprint", "normalized_manifest_sha256", "records_sha256"):
        _sha(dataset[field], f"$.dataset.{field}")
    if _boolean(dataset["synthetic"], "$.dataset.synthetic") != synthetic:
        _fail("$.dataset.synthetic", "must agree with the run synthetic classification")
    metrics = _list(obj["metric_definitions"], "$.metric_definitions")
    seen_metrics: set[tuple[str, str]] = set()
    for index, metric in enumerate(metrics):
        path = f"$.metric_definitions[{index}]"
        item = _object(metric, path)
        _keys(item, path, required={"metric_id", "version", "sha256"})
        identity = (_id(item["metric_id"], f"{path}.metric_id"), _string(item["version"], f"{path}.version"))
        if identity in seen_metrics:
            _fail(path, "metric identity must be unique")
        seen_metrics.add(identity)
        _sha(item["sha256"], f"{path}.sha256")
    _code_identity(obj["code_identity"], "$.code_identity")
    integrity = _object(obj["integrity"], "$.integrity")
    _keys(
        integrity,
        "$.integrity",
        required={"records_validated", "record_counts_verified", "quality_flags_verified", "fingerprint_verified"},
    )
    _count(integrity["records_validated"], "$.integrity.records_validated")
    for name in ("record_counts_verified", "quality_flags_verified", "fingerprint_verified"):
        if integrity[name] is not True:
            _fail(f"$.integrity.{name}", "analysis runs may only be produced from verified inputs")
    definition_by_id = {item["computation_id"]: item for item in definition["computations"]}
    results = _list(obj["results"], "$.results", nonempty=True)
    covered = [
        _result(result, f"$.results[{index}]", definition_by_id)
        for index, result in enumerate(results)
    ]
    if covered != [item["computation_id"] for item in definition["computations"]]:
        _fail("$.results", "must contain exactly one result per declared computation, in declaration order")
    return obj
