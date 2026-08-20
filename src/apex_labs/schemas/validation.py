"""Dependency-free runtime validation for Apex Labs v1 JSON contracts."""

from __future__ import annotations

import math
import re
import hashlib
from datetime import datetime
from typing import Any, Callable

from apex_labs.errors import ContractValidationError, UnsupportedVersionError
from apex_labs.io import canonical_json_bytes, validate_contract_path
from apex_labs.normalization.concepts import (
    CANONICAL_CONVENTIONS,
    CANONICAL_UNITS,
    NORMALIZED_CONCEPTS,
    PROVENANCE_KINDS,
    RECORD_TYPES,
)
from apex_labs.schemas import versions

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{7,40}|UNCOMMITTED)$")
_STATUSES = {"validated", "provisional", "inconclusive", "rejected"}
_SCOPES = {
    "driver_specific",
    "car_specific",
    "track_specific",
    "corner_archetype_specific",
    "simulator_specific",
    "session_specific",
    "algorithmic",
    "population_hypothesis",
    "population_supported",
}
_LIMITED_SCOPES = _SCOPES - {"algorithmic", "population_supported"}
_BOOLEAN_CONCEPTS = {"lap_valid", "abs_active", "traction_control_active", "off_track_state"}
_INTEGER_CONCEPTS = {"gear"}
_TEXT_CONCEPTS = {"session_state", "incident_state"}


def _fail(path: str, message: str) -> None:
    raise ContractValidationError(f"{path}: {message}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _list(value: Any, path: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if nonempty and not value:
        _fail(path, "must not be empty")
    return value


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _fail(path, "must be a non-empty string" if nonempty else "must be a string")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "must be a boolean")
    return value


def _number(value: Any, path: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    if not math.isfinite(value):
        _fail(path, "must be finite")
    return value


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(path, f"must be >= {minimum}")
    return value


def _id(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _ID_RE.fullmatch(text):
        _fail(path, "must use 2-128 lowercase letters, digits, '.', '_' or '-'")
    return text


def _enum(value: Any, allowed: set[str], path: str) -> str:
    text = _string(value, path)
    if text not in allowed:
        _fail(path, f"must be one of {sorted(allowed)}")
    return text


def _timestamp(value: Any, path: str) -> str:
    text = _string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(path, "must be an ISO 8601 timestamp")
        raise AssertionError from exc
    if parsed.tzinfo is None:
        _fail(path, "must include a UTC offset or Z")
    return text


def _sha(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _SHA256_RE.fullmatch(text):
        _fail(path, "must be a lowercase SHA-256 hex digest")
    return text


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _commit(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _COMMIT_RE.fullmatch(text):
        _fail(path, "must be a 7-40 character lowercase Git SHA or UNCOMMITTED")
    return text


def _keys(
    obj: dict[str, Any],
    path: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - obj.keys()
    if missing:
        _fail(path, f"missing required fields {sorted(missing)}")
    unknown = obj.keys() - required - optional
    if unknown:
        _fail(path, f"unknown fields {sorted(unknown)}")


def _version(obj: dict[str, Any], expected: str, path: str = "$") -> None:
    actual = obj.get("schema_version")
    if actual != expected:
        raise UnsupportedVersionError(
            f"{path}.schema_version: expected {expected!r}, received {actual!r}"
        )


def _strings(value: Any, path: str, *, nonempty: bool = False) -> list[str]:
    items = _list(value, path, nonempty=nonempty)
    for index, item in enumerate(items):
        _string(item, f"{path}[{index}]")
    return items


def _qualified_value(value: Any, path: str, concept: str) -> None:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={"value", "provenance", "unit"},
        optional={"source_channel", "derivation", "quality_flags", "reference"},
    )
    provenance = _enum(obj["provenance"], PROVENANCE_KINDS, f"{path}.provenance")
    if provenance == "unavailable" and obj["value"] is not None:
        _fail(f"{path}.value", "must be null when provenance is unavailable")
    if provenance != "unavailable" and obj["value"] is None:
        _fail(f"{path}.value", f"must not be null when provenance is {provenance}")
    if provenance != "unavailable":
        if concept in _BOOLEAN_CONCEPTS:
            _boolean(obj["value"], f"{path}.value")
        elif concept in _INTEGER_CONCEPTS:
            _integer(obj["value"], f"{path}.value")
        elif concept in _TEXT_CONCEPTS:
            _string(obj["value"], f"{path}.value", nonempty=False)
        else:
            _number(obj["value"], f"{path}.value")
    unit = _string(obj["unit"], f"{path}.unit")
    if unit != CANONICAL_UNITS[concept]:
        _fail(f"{path}.unit", f"must use canonical unit {CANONICAL_UNITS[concept]!r}")
    if "source_channel" in obj:
        _string(obj["source_channel"], f"{path}.source_channel")
    if provenance == "measured" and "source_channel" not in obj:
        _fail(path, "measured values require source_channel")
    if provenance in {"derived", "estimated"} and "derivation" not in obj:
        _fail(path, f"{provenance} values require derivation")
    if "quality_flags" in obj:
        _strings(obj["quality_flags"], f"{path}.quality_flags")
    if "reference" in obj:
        _string(obj["reference"], f"{path}.reference")


def _source_provenance(value: Any, path: str) -> None:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={"source_file", "source_file_sha256", "adapter_id", "adapter_version"},
        optional={"row_start", "row_end", "source_record_id", "source_timestamp"},
    )
    _string(obj["source_file"], f"{path}.source_file")
    _sha(obj["source_file_sha256"], f"{path}.source_file_sha256")
    _id(obj["adapter_id"], f"{path}.adapter_id")
    _string(obj["adapter_version"], f"{path}.adapter_version")
    if "row_start" in obj:
        _integer(obj["row_start"], f"{path}.row_start", minimum=1)
    if "row_end" in obj:
        _integer(obj["row_end"], f"{path}.row_end", minimum=1)
    if obj.get("row_start", 0) > obj.get("row_end", obj.get("row_start", 0)):
        _fail(path, "row_start must not exceed row_end")
    if "source_timestamp" in obj:
        _string(obj["source_timestamp"], f"{path}.source_timestamp", nonempty=False)


def _temporal_policy(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={
            "source_clock", "normalized_clock_origin", "clock_resolution_seconds",
            "duplicate_timestamp_policy", "clock_reset_policy",
            "expected_sample_period_seconds", "gap_tolerance_seconds",
            "lap_distance_regression_policy", "interpolation",
        },
    )
    _string(obj["source_clock"], f"{path}.source_clock")
    _enum(obj["normalized_clock_origin"], {"session_start", "unix_epoch", "declared_source_epoch"}, f"{path}.normalized_clock_origin")
    resolution = obj["clock_resolution_seconds"]
    if resolution is not None and _number(resolution, f"{path}.clock_resolution_seconds") <= 0:
        _fail(f"{path}.clock_resolution_seconds", "must be positive when declared")
    _enum(obj["duplicate_timestamp_policy"], {"reject", "allow_with_quality_flag"}, f"{path}.duplicate_timestamp_policy")
    _enum(obj["clock_reset_policy"], {"reject", "allow_with_quality_flag"}, f"{path}.clock_reset_policy")
    expected = obj["expected_sample_period_seconds"]
    tolerance = obj["gap_tolerance_seconds"]
    if (expected is None) != (tolerance is None):
        _fail(path, "expected_sample_period_seconds and gap_tolerance_seconds must both be null or declared")
    if expected is not None and _number(expected, f"{path}.expected_sample_period_seconds") <= 0:
        _fail(f"{path}.expected_sample_period_seconds", "must be positive")
    if tolerance is not None and _number(tolerance, f"{path}.gap_tolerance_seconds") < 0:
        _fail(f"{path}.gap_tolerance_seconds", "must be non-negative")
    _enum(obj["lap_distance_regression_policy"], {"reject", "allow_with_quality_flag"}, f"{path}.lap_distance_regression_policy")
    interpolation = _object(obj["interpolation"], f"{path}.interpolation")
    _keys(interpolation, f"{path}.interpolation", required={"performed", "method", "affected_concepts"})
    performed = _boolean(interpolation["performed"], f"{path}.interpolation.performed")
    method = interpolation["method"]
    if performed:
        _string(method, f"{path}.interpolation.method")
        affected = _strings(interpolation["affected_concepts"], f"{path}.interpolation.affected_concepts", nonempty=True)
        for index, concept in enumerate(affected):
            if concept not in NORMALIZED_CONCEPTS:
                _fail(f"{path}.interpolation.affected_concepts[{index}]", "must be a normalized concept")
    else:
        if method is not None or interpolation["affected_concepts"] != []:
            _fail(f"{path}.interpolation", "must use null method and no affected concepts when not performed")
    return obj


def _conventions(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(obj, path, required=set(CANONICAL_CONVENTIONS))
    for name, expected in CANONICAL_CONVENTIONS.items():
        if obj[name] != expected:
            _fail(f"{path}.{name}", f"must be canonical convention {expected!r}")
    return obj


def validate_dataset_manifest(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.DATASET_MANIFEST)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "dataset_id", "title", "synthetic", "data_classification",
            "created_at", "simulator", "driver_identifiers", "privacy", "collection_context",
            "source", "source_files", "adapter",
        },
        optional={"description", "license", "consent_or_authority", "tags"},
    )
    _id(obj["dataset_id"], "$.dataset_id")
    _string(obj["title"], "$.title")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    classification = _enum(
        obj["data_classification"], {"synthetic", "sanitized", "private"}, "$.data_classification"
    )
    if synthetic != (classification == "synthetic"):
        _fail("$", "synthetic must be true exactly when data_classification is synthetic")
    _timestamp(obj["created_at"], "$.created_at")
    _string(obj["simulator"], "$.simulator")
    driver_identifiers = _enum(obj["driver_identifiers"], {"none", "pseudonymized", "identifiable"}, "$.driver_identifiers")
    privacy = _object(obj["privacy"], "$.privacy")
    _keys(
        privacy,
        "$.privacy",
        required={
            "participant_data", "pseudonymized", "direct_identifiers_present",
            "pseudonymization_method", "consent_or_authority", "retention_policy",
        },
    )
    participant_data = _boolean(privacy["participant_data"], "$.privacy.participant_data")
    pseudonymized = _boolean(privacy["pseudonymized"], "$.privacy.pseudonymized")
    direct_identifiers = _boolean(privacy["direct_identifiers_present"], "$.privacy.direct_identifiers_present")
    for name in ("consent_or_authority", "retention_policy"):
        _string(privacy[name], f"$.privacy.{name}")
    method = privacy["pseudonymization_method"]
    if method is not None:
        _string(method, "$.privacy.pseudonymization_method")
    if synthetic:
        if participant_data or pseudonymized or direct_identifiers or method is not None:
            _fail("$.privacy", "synthetic datasets cannot declare participant identity processing")
    else:
        if not participant_data or not pseudonymized or direct_identifiers:
            _fail("$.privacy", "real research requires participant_data=true, pseudonymization, and no direct identifiers")
        if driver_identifiers != "pseudonymized" or method is None:
            _fail("$.privacy", "real research requires pseudonymized driver identifiers and a method")
    collection = _object(obj["collection_context"], "$.collection_context")
    _keys(
        collection,
        "$.collection_context",
        required={"protocol_snapshot", "condition_id", "block_id", "schedule_assignment_id"},
    )
    protocol_snapshot = collection["protocol_snapshot"]
    if protocol_snapshot is not None:
        snapshot = _object(protocol_snapshot, "$.collection_context.protocol_snapshot")
        _keys(
            snapshot,
            "$.collection_context.protocol_snapshot",
            required={"path", "file_sha256", "freeze_id", "freeze_sha256", "experiment_id", "experiment_version", "schedule_id", "schedule_sha256"},
        )
        validate_contract_path(_string(snapshot["path"], "$.collection_context.protocol_snapshot.path"))
        for field in ("freeze_id", "experiment_id", "schedule_id"):
            _id(snapshot[field], f"$.collection_context.protocol_snapshot.{field}")
        _string(snapshot["experiment_version"], "$.collection_context.protocol_snapshot.experiment_version")
        _sha(snapshot["file_sha256"], "$.collection_context.protocol_snapshot.file_sha256")
        _sha(snapshot["freeze_sha256"], "$.collection_context.protocol_snapshot.freeze_sha256")
        _sha(snapshot["schedule_sha256"], "$.collection_context.protocol_snapshot.schedule_sha256")
    for field in ("condition_id", "block_id", "schedule_assignment_id"):
        if collection[field] is not None:
            _id(collection[field], f"$.collection_context.{field}")
    if not synthetic and (
        protocol_snapshot is None
        or collection["condition_id"] is None
        or collection["block_id"] is None
        or collection["schedule_assignment_id"] is None
    ):
        _fail("$.collection_context", "real research requires an exact frozen protocol, condition, block, and schedule assignment")
    source = _object(obj["source"], "$.source")
    _keys(source, "$.source", required={"format", "description"}, optional={"export_version"})
    _string(source["format"], "$.source.format")
    _string(source["description"], "$.source.description")
    source_files = _list(obj["source_files"], "$.source_files", nonempty=True)
    seen_paths: set[str] = set()
    for index, item in enumerate(source_files):
        path = f"$.source_files[{index}]"
        file_obj = _object(item, path)
        _keys(file_obj, path, required={"path", "sha256", "role", "media_type"})
        file_path = _string(file_obj["path"], f"{path}.path")
        validate_contract_path(file_path)
        casefolded_path = file_path.casefold()
        if casefolded_path in seen_paths:
            _fail(f"{path}.path", "must be unique under Windows case-insensitive semantics")
        seen_paths.add(casefolded_path)
        _sha(file_obj["sha256"], f"{path}.sha256")
        _enum(file_obj["role"], {"telemetry", "metadata", "events", "protocol"}, f"{path}.role")
        _string(file_obj["media_type"], f"{path}.media_type")
    adapter = _object(obj["adapter"], "$.adapter")
    _keys(adapter, "$.adapter", required={"id", "version", "configuration"})
    _id(adapter["id"], "$.adapter.id")
    _string(adapter["version"], "$.adapter.version")
    _object(adapter["configuration"], "$.adapter.configuration")
    if protocol_snapshot is not None:
        matching = [
            item for item in source_files
            if item["path"] == protocol_snapshot["path"] and item["role"] == "protocol"
        ]
        if len(matching) != 1 or matching[0]["sha256"] != protocol_snapshot["file_sha256"]:
            _fail("$.collection_context.protocol_snapshot", "must match one declared protocol source file and hash")
    if "tags" in obj:
        _strings(obj["tags"], "$.tags")
    return obj


def validate_normalized_record(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.NORMALIZED_RECORD)
    record_type = _enum(obj.get("record_type"), RECORD_TYPES, "$.record_type")
    common = {"schema_version", "record_type", "dataset_id", "session_id", "record_id", "sequence_index", "source_provenance"}
    per_type: dict[str, tuple[set[str], set[str]]] = {
        "session": ({"simulator", "driver_id", "car", "track", "layout", "fields"}, set()),
        "lap": ({"lap_id", "lap_number", "fields"}, set()),
        "segment": ({"lap_id", "segment_id", "segment_kind", "label", "fields"}, set()),
        "telemetry_sample": ({"lap_id", "sample_index", "fields"}, {"segment_id", "quality_flags"}),
        "distance_bin": (
            {
                "lap_id", "distance_bin_index", "distance_start_m", "distance_end_m",
                "sample_count", "has_sample", "aggregation", "fields",
            },
            {"quality_flags"},
        ),
        "driver_input_event": ({"lap_id", "event_type", "fields"}, {"segment_id", "quality_flags"}),
    }
    if record_type in {"session", "lap", "segment"}:
        per_type[record_type][1].add("quality_flags")
    required_extra, optional_extra = per_type[record_type]
    _keys(obj, "$", required=common | required_extra, optional=optional_extra)
    for field in ("dataset_id", "session_id", "record_id"):
        _id(obj[field], f"$.{field}")
    _integer(obj["sequence_index"], "$.sequence_index", minimum=0)
    if "quality_flags" in obj:
        _strings(obj["quality_flags"], "$.quality_flags")
    _source_provenance(obj["source_provenance"], "$.source_provenance")
    fields = _object(obj["fields"], "$.fields")
    for name, field_value in fields.items():
        if name not in NORMALIZED_CONCEPTS:
            _fail(f"$.fields.{name}", "is not a normalized v1 concept")
        _qualified_value(field_value, f"$.fields.{name}", name)
    if record_type == "session":
        for field in ("simulator", "driver_id", "car", "track", "layout"):
            _string(obj[field], f"$.{field}")
    if record_type in {"lap", "segment", "telemetry_sample", "distance_bin", "driver_input_event"}:
        _id(obj["lap_id"], "$.lap_id")
    if "segment_id" in obj:
        _id(obj["segment_id"], "$.segment_id")
    if record_type == "lap":
        _integer(obj["lap_number"], "$.lap_number", minimum=0)
    if record_type == "segment":
        _id(obj["segment_id"], "$.segment_id")
        _enum(obj["segment_kind"], {"corner", "straight", "custom"}, "$.segment_kind")
        _string(obj["label"], "$.label")
    if record_type == "telemetry_sample":
        _integer(obj["sample_index"], "$.sample_index", minimum=0)
        if "timestamp" not in fields:
            _fail("$.fields", "telemetry_sample requires timestamp")
        if fields["timestamp"].get("reference") != "normalized_monotonic_time":
            _fail("$.fields.timestamp.reference", "must identify normalized_monotonic_time")
    if record_type == "distance_bin":
        index = _integer(obj["distance_bin_index"], "$.distance_bin_index", minimum=0)
        start = _number(obj["distance_start_m"], "$.distance_start_m")
        end = _number(obj["distance_end_m"], "$.distance_end_m")
        if start < 0 or end <= start:
            _fail("$.distance_end_m", "must be greater than a non-negative distance_start_m")
        if index != int(start):
            _fail("$.distance_bin_index", "must equal the integer one-metre distance_start_m")
        sample_count = _integer(obj["sample_count"], "$.sample_count", minimum=0)
        has_sample = _boolean(obj["has_sample"], "$.has_sample")
        if has_sample != (sample_count > 0):
            _fail("$.has_sample", "must be true exactly when sample_count is positive")
        aggregation = _object(obj["aggregation"], "$.aggregation")
        _keys(
            aggregation,
            "$.aggregation",
            required={"source_semantics", "distance_bin_width_m", "channel_methods"},
        )
        if aggregation["source_semantics"] != "distance_binned_aggregate":
            _fail("$.aggregation.source_semantics", "must identify distance-binned aggregate source data")
        if _number(aggregation["distance_bin_width_m"], "$.aggregation.distance_bin_width_m") != 1:
            _fail("$.aggregation.distance_bin_width_m", "apex-session-export/1.0.0 bins must be one metre")
        methods = _object(aggregation["channel_methods"], "$.aggregation.channel_methods")
        expected_methods = {
            "brake": "maximum",
            "throttle": "arithmetic_mean",
            "steering_angle": "arithmetic_mean",
            "speed": "arithmetic_mean",
        }
        _keys(methods, "$.aggregation.channel_methods", required=set(expected_methods))
        for concept, expected in expected_methods.items():
            if methods[concept] != expected:
                _fail(f"$.aggregation.channel_methods.{concept}", f"must be {expected!r}")
        required_fields = {"lap_distance", "lap_fraction", *expected_methods}
        if set(fields) != required_fields:
            _fail("$.fields", f"distance_bin fields must be exactly {sorted(required_fields)}")
        for concept in expected_methods:
            value = fields[concept]
            if not has_sample and (value["value"] is not None or value["provenance"] != "unavailable"):
                _fail(f"$.fields.{concept}", "unsampled bins must preserve the channel as unavailable, not zero")
            if has_sample and value["provenance"] != "derived":
                _fail(f"$.fields.{concept}.provenance", "aggregated channel values must be derived")
    if record_type == "driver_input_event":
        _id(obj["event_type"], "$.event_type")
        if "timestamp" not in fields:
            _fail("$.fields", "driver_input_event requires timestamp")
        if fields["timestamp"].get("reference") != "normalized_monotonic_time":
            _fail("$.fields.timestamp.reference", "must identify normalized_monotonic_time")
    return obj


def validate_normalized_manifest(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.NORMALIZED_MANIFEST)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "dataset_id", "dataset_fingerprint", "synthetic", "created_at",
            "source_manifest_sha256", "canonical_source_manifest_sha256", "source_fingerprint",
            "normalization_version", "adapter", "code_identity", "preprocessing",
            "collection_context", "temporal_policy", "conventions", "integrity_summary", "records_file",
            "records_sha256", "record_counts", "source_files", "capabilities", "unknown_source_channels",
        },
        optional={
            "source_bundle", "source_semantics", "research_eligibility", "collection_record",
            "product_annotations", "adapter_conformance",
        },
    )
    _id(obj["dataset_id"], "$.dataset_id")
    _sha(obj["dataset_fingerprint"], "$.dataset_fingerprint")
    _boolean(obj["synthetic"], "$.synthetic")
    _timestamp(obj["created_at"], "$.created_at")
    _sha(obj["source_manifest_sha256"], "$.source_manifest_sha256")
    _sha(obj["canonical_source_manifest_sha256"], "$.canonical_source_manifest_sha256")
    _sha(obj["source_fingerprint"], "$.source_fingerprint")
    _string(obj["normalization_version"], "$.normalization_version")
    adapter = _object(obj["adapter"], "$.adapter")
    _keys(adapter, "$.adapter", required={"id", "version", "configuration"})
    _id(adapter["id"], "$.adapter.id")
    _string(adapter["version"], "$.adapter.version")
    _object(adapter["configuration"], "$.adapter.configuration")
    code_identity = _object(obj["code_identity"], "$.code_identity")
    _keys(
        code_identity,
        "$.code_identity",
        required={"package_version", "git_commit", "git_state", "code_and_schema_sha256", "schema_sha256"},
    )
    _string(code_identity["package_version"], "$.code_identity.package_version")
    _commit(code_identity["git_commit"], "$.code_identity.git_commit")
    _enum(code_identity["git_state"], {"clean", "dirty", "uncommitted"}, "$.code_identity.git_state")
    _sha(code_identity["code_and_schema_sha256"], "$.code_identity.code_and_schema_sha256")
    schema_hashes = _object(code_identity["schema_sha256"], "$.code_identity.schema_sha256")
    if not schema_hashes:
        _fail("$.code_identity.schema_sha256", "must not be empty")
    for schema_path, schema_hash in schema_hashes.items():
        validate_contract_path(schema_path)
        _sha(schema_hash, f"$.code_identity.schema_sha256.{schema_path}")
    preprocessing = _object(obj["preprocessing"], "$.preprocessing")
    _keys(preprocessing, "$.preprocessing", required={"pipeline_id", "pipeline_version", "configuration", "configuration_sha256"})
    _id(preprocessing["pipeline_id"], "$.preprocessing.pipeline_id")
    _string(preprocessing["pipeline_version"], "$.preprocessing.pipeline_version")
    _object(preprocessing["configuration"], "$.preprocessing.configuration")
    _sha(preprocessing["configuration_sha256"], "$.preprocessing.configuration_sha256")
    if preprocessing["configuration_sha256"] != _canonical_hash(preprocessing["configuration"]):
        _fail("$.preprocessing.configuration_sha256", "does not match canonical configuration content")
    collection = _object(obj["collection_context"], "$.collection_context")
    _keys(collection, "$.collection_context", required={"protocol_snapshot", "condition_id", "block_id", "schedule_assignment_id"})
    if collection["protocol_snapshot"] is not None:
        snapshot = _object(collection["protocol_snapshot"], "$.collection_context.protocol_snapshot")
        _keys(snapshot, "$.collection_context.protocol_snapshot", required={"path", "file_sha256", "freeze_id", "freeze_sha256", "experiment_id", "experiment_version", "schedule_id", "schedule_sha256"})
        validate_contract_path(_string(snapshot["path"], "$.collection_context.protocol_snapshot.path"))
        for field in ("freeze_id", "experiment_id", "schedule_id"):
            _id(snapshot[field], f"$.collection_context.protocol_snapshot.{field}")
        _string(snapshot["experiment_version"], "$.collection_context.protocol_snapshot.experiment_version")
        _sha(snapshot["file_sha256"], "$.collection_context.protocol_snapshot.file_sha256")
        _sha(snapshot["freeze_sha256"], "$.collection_context.protocol_snapshot.freeze_sha256")
        _sha(snapshot["schedule_sha256"], "$.collection_context.protocol_snapshot.schedule_sha256")
    for field in ("condition_id", "block_id", "schedule_assignment_id"):
        if collection[field] is not None:
            _id(collection[field], f"$.collection_context.{field}")
    _temporal_policy(obj["temporal_policy"], "$.temporal_policy")
    _conventions(obj["conventions"], "$.conventions")
    integrity_summary = _object(obj["integrity_summary"], "$.integrity_summary")
    _keys(
        integrity_summary,
        "$.integrity_summary",
        required={"record_order", "unique_record_ids", "parent_references", "quality_flag_counts", "interpolation", "gap_detection"},
    )
    if integrity_summary["record_order"] != "sequence_index_contiguous_parent_before_child":
        _fail("$.integrity_summary.record_order", "unsupported ordering guarantee")
    if integrity_summary["unique_record_ids"] is not True or integrity_summary["parent_references"] != "verified":
        _fail("$.integrity_summary", "must report verified record identities and parents")
    quality_counts = _object(integrity_summary["quality_flag_counts"], "$.integrity_summary.quality_flag_counts")
    for flag, count in quality_counts.items():
        _string(flag, f"$.integrity_summary.quality_flag_counts.{flag}")
        _integer(count, f"$.integrity_summary.quality_flag_counts.{flag}", minimum=0)
    _object(integrity_summary["interpolation"], "$.integrity_summary.interpolation")
    _enum(
        integrity_summary["gap_detection"],
        {"evaluated", "distance_coverage_evaluated", "not_evaluated_no_declared_cadence"},
        "$.integrity_summary.gap_detection",
    )
    _string(obj["records_file"], "$.records_file")
    _sha(obj["records_sha256"], "$.records_sha256")
    counts = _object(obj["record_counts"], "$.record_counts")
    for record_type, count in counts.items():
        _enum(record_type, RECORD_TYPES, f"$.record_counts.{record_type}")
        _integer(count, f"$.record_counts.{record_type}", minimum=0)
    _list(obj["source_files"], "$.source_files", nonempty=True)
    for index, source in enumerate(obj["source_files"]):
        path = f"$.source_files[{index}]"
        source_obj = _object(source, path)
        _keys(source_obj, path, required={"path", "sha256", "role", "media_type"})
        validate_contract_path(_string(source_obj["path"], f"{path}.path"))
        _sha(source_obj["sha256"], f"{path}.sha256")
        _string(source_obj["role"], f"{path}.role")
        _string(source_obj["media_type"], f"{path}.media_type")
    capabilities = _object(obj["capabilities"], "$.capabilities")
    if set(capabilities) != NORMALIZED_CONCEPTS:
        missing = sorted(NORMALIZED_CONCEPTS - capabilities.keys())
        unknown = sorted(capabilities.keys() - NORMALIZED_CONCEPTS)
        _fail("$.capabilities", f"must enumerate every normalized concept; missing={missing}, unknown={unknown}")
    for concept, capability in capabilities.items():
        path = f"$.capabilities.{concept}"
        item = _object(capability, path)
        _keys(item, path, required={"provenance"}, optional={"unit", "source_channel", "derivation"})
        provenance = _enum(item["provenance"], PROVENANCE_KINDS, f"{path}.provenance")
        if provenance == "measured" and "source_channel" not in item:
            _fail(path, "measured capability requires source_channel")
        if provenance in {"derived", "estimated"} and "derivation" not in item:
            _fail(path, f"{provenance} capability requires derivation")
        if provenance != "unavailable":
            if "unit" not in item or item["unit"] != CANONICAL_UNITS[concept]:
                _fail(f"{path}.unit", f"available capability requires canonical unit {CANONICAL_UNITS[concept]!r}")
        elif "unit" in item and item["unit"] is not None and item["unit"] != CANONICAL_UNITS[concept]:
            _fail(f"{path}.unit", f"must use canonical unit {CANONICAL_UNITS[concept]!r}")
        if "source_channel" in item:
            _string(item["source_channel"], f"{path}.source_channel")
    _strings(obj["unknown_source_channels"], "$.unknown_source_channels")
    if "source_bundle" in obj:
        bundle = _object(obj["source_bundle"], "$.source_bundle")
        _keys(bundle, "$.source_bundle", required={"schema_version", "sha256", "manifest_sha256", "privacy_mode"})
        if bundle["schema_version"] != versions.APEX_SESSION_EXPORT:
            _fail("$.source_bundle.schema_version", f"must be {versions.APEX_SESSION_EXPORT!r}")
        _sha(bundle["sha256"], "$.source_bundle.sha256")
        _sha(bundle["manifest_sha256"], "$.source_bundle.manifest_sha256")
        _string(bundle["privacy_mode"], "$.source_bundle.privacy_mode")
    if "source_semantics" in obj:
        semantics = _object(obj["source_semantics"], "$.source_semantics")
        _keys(semantics, "$.source_semantics", required={"record_semantics", "distance_bin_width_m", "interpolation_performed", "time_domain_available"})
        if semantics["record_semantics"] != "distance_binned_aggregate_not_raw_frames":
            _fail("$.source_semantics.record_semantics", "must not represent distance bins as raw frames")
        if _number(semantics["distance_bin_width_m"], "$.source_semantics.distance_bin_width_m") != 1:
            _fail("$.source_semantics.distance_bin_width_m", "must be one metre")
        if semantics["interpolation_performed"] is not False or semantics["time_domain_available"] is not False:
            _fail("$.source_semantics", "customer bundle contains neither interpolation nor time-domain samples")
    if "research_eligibility" in obj:
        eligibility = _object(obj["research_eligibility"], "$.research_eligibility")
        _keys(eligibility, "$.research_eligibility", required={"classification", "scientific_promotion_eligible", "reason"})
        classification = _enum(eligibility["classification"], {"observational", "experimental", "integration_validation_only", "synthetic_demo"}, "$.research_eligibility.classification")
        eligible = _boolean(eligibility["scientific_promotion_eligible"], "$.research_eligibility.scientific_promotion_eligible")
        _string(eligibility["reason"], "$.research_eligibility.reason")
        if classification in {"integration_validation_only", "synthetic_demo"} and eligible:
            _fail("$.research_eligibility.scientific_promotion_eligible", "integration and synthetic mechanics are ineligible")
    for name in ("collection_record", "product_annotations", "adapter_conformance"):
        if name in obj:
            bound = _object(obj[name], f"$.{name}")
            _keys(bound, f"$.{name}", required={"path", "sha256"})
            validate_contract_path(_string(bound["path"], f"$.{name}.path"))
            _sha(bound["sha256"], f"$.{name}.sha256")
    native_fields = {
        "source_bundle", "source_semantics", "research_eligibility", "collection_record",
        "product_annotations", "adapter_conformance",
    }
    present_native = native_fields & obj.keys()
    if present_native and present_native != native_fields:
        _fail("$", f"native Apex normalization requires the complete bound metadata set; missing={sorted(native_fields - present_native)}")
    if present_native:
        if adapter["id"] != "apex-session-export" or adapter["version"] != "1.0.0":
            _fail("$.adapter", "native source metadata requires apex-session-export adapter 1.0.0")
        if "distance_bin" not in counts:
            _fail("$.record_counts", "native customer-bundle normalization requires distance_bin records")
        source_is_synthetic = obj["source_bundle"]["privacy_mode"] == "Synthetic"
        if source_is_synthetic != obj["synthetic"]:
            _fail("$.source_bundle.privacy_mode", "must agree with normalized synthetic classification")
        if obj["synthetic"] and obj["research_eligibility"]["classification"] != "synthetic_demo":
            _fail("$.research_eligibility.classification", "synthetic native bundles must remain synthetic_demo")
    return obj


def _metric(value: Any, path: str) -> None:
    obj = _object(value, path)
    _keys(obj, path, required={"metric_id", "definition", "unit", "provenance_expectation"})
    _id(obj["metric_id"], f"{path}.metric_id")
    _string(obj["definition"], f"{path}.definition")
    _string(obj["unit"], f"{path}.unit", nonempty=False)
    _enum(obj["provenance_expectation"], PROVENANCE_KINDS - {"unavailable"}, f"{path}.provenance_expectation")


def validate_experiment(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.EXPERIMENT)
    required = {
        "schema_version", "experiment_id", "version", "status", "research_question", "hypothesis",
        "null_hypothesis", "independent_variable", "primary_dependent_metric", "secondary_metrics",
        "controlled_variables", "comparability_requirements", "exclusion_criteria",
        "minimum_sample_requirements", "baseline_condition", "intervention_conditions",
        "randomization_counterbalancing", "analysis_methods", "predeclared_success_criteria",
        "safety_constraints", "notes", "created_at", "apex_labs_source_commit", "synthetic",
    }
    _keys(obj, "$", required=required)
    _id(obj["experiment_id"], "$.experiment_id")
    _string(obj["version"], "$.version")
    status = _enum(obj["status"], {"draft", "preregistered", "active", "completed", "aborted"}, "$.status")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    for field in ("research_question", "hypothesis", "null_hypothesis", "baseline_condition", "randomization_counterbalancing"):
        _string(obj[field], f"$.{field}")
    independent = _object(obj["independent_variable"], "$.independent_variable")
    _keys(independent, "$.independent_variable", required={"name", "operational_definition", "levels"})
    _id(independent["name"], "$.independent_variable.name")
    _string(independent["operational_definition"], "$.independent_variable.operational_definition")
    _strings(independent["levels"], "$.independent_variable.levels", nonempty=True)
    _metric(obj["primary_dependent_metric"], "$.primary_dependent_metric")
    secondary = _list(obj["secondary_metrics"], "$.secondary_metrics")
    for index, metric in enumerate(secondary):
        _metric(metric, f"$.secondary_metrics[{index}]")
    for field in ("controlled_variables", "comparability_requirements", "exclusion_criteria", "intervention_conditions", "analysis_methods", "safety_constraints", "notes"):
        _strings(obj[field], f"$.{field}", nonempty=field in {"comparability_requirements", "exclusion_criteria", "analysis_methods", "safety_constraints"})
    minimum = _object(obj["minimum_sample_requirements"], "$.minimum_sample_requirements")
    _keys(minimum, "$.minimum_sample_requirements", required={"state", "requirements", "rationale"})
    sample_state = _enum(minimum["state"], {"to_be_determined", "declared"}, "$.minimum_sample_requirements.state")
    _strings(minimum["requirements"], "$.minimum_sample_requirements.requirements", nonempty=sample_state == "declared")
    _string(minimum["rationale"], "$.minimum_sample_requirements.rationale")
    success = _object(obj["predeclared_success_criteria"], "$.predeclared_success_criteria")
    _keys(success, "$.predeclared_success_criteria", required={"state", "criteria", "falsification_criteria"})
    success_state = _enum(success["state"], {"to_be_determined", "declared"}, "$.predeclared_success_criteria.state")
    _strings(success["criteria"], "$.predeclared_success_criteria.criteria", nonempty=success_state == "declared")
    _strings(success["falsification_criteria"], "$.predeclared_success_criteria.falsification_criteria", nonempty=success_state == "declared")
    if status != "draft" and (sample_state != "declared" or success_state != "declared"):
        _fail("$", "non-draft experiments require declared sample and success criteria")
    _timestamp(obj["created_at"], "$.created_at")
    commit = _commit(obj["apex_labs_source_commit"], "$.apex_labs_source_commit")
    if status != "draft" and commit == "UNCOMMITTED" and not synthetic:
        _fail("$.apex_labs_source_commit", "non-draft experiments require a source commit")
    return obj


def validate_finding(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.FINDING)
    required = {
        "schema_version", "finding_id", "version", "title", "research_question", "status", "scope",
        "evidence_classification", "hypothesis", "conclusion", "effect_estimate", "uncertainty",
        "sample_counts", "sample_sufficiency", "comparability_assessment", "dataset_references",
        "protocol_reference", "preprocessing", "analysis",
        "analysis_code_identity", "analyst_claim", "validation_artifact_reference",
        "scientific_review_state", "product_review_state",
        "limitations", "possible_confounders", "generalizability_assessment", "falsification_attempts",
        "product_implication", "recommended_product_action", "safe_for_global_consideration",
        "required_future_validation", "created_at", "apex_labs_source_commit", "synthetic",
    }
    _keys(obj, "$", required=required)
    _id(obj["finding_id"], "$.finding_id")
    _string(obj["version"], "$.version")
    for field in ("title", "research_question", "hypothesis", "conclusion", "generalizability_assessment", "product_implication"):
        _string(obj[field], f"$.{field}")
    status = _enum(obj["status"], _STATUSES, "$.status")
    scope = _enum(obj["scope"], _SCOPES, "$.scope")
    evidence = _enum(obj["evidence_classification"], {"controlled", "observational", "synthetic_demo"}, "$.evidence_classification")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if synthetic != (evidence == "synthetic_demo"):
        _fail("$", "synthetic must be true exactly for synthetic_demo evidence")
    action = _enum(obj["recommended_product_action"], {"consider", "personalize_only", "research_only", "do_not_implement"}, "$.recommended_product_action")
    safe_global = _boolean(obj["safe_for_global_consideration"], "$.safe_for_global_consideration")
    analyst_claim = _object(obj["analyst_claim"], "$.analyst_claim")
    _keys(analyst_claim, "$.analyst_claim", required={"proposed_status", "rationale"})
    _enum(analyst_claim["proposed_status"], _STATUSES, "$.analyst_claim.proposed_status")
    _string(analyst_claim["rationale"], "$.analyst_claim.rationale")
    artifact_reference = obj["validation_artifact_reference"]
    if artifact_reference is not None:
        artifact_ref = _object(artifact_reference, "$.validation_artifact_reference")
        _keys(artifact_ref, "$.validation_artifact_reference", required={"validation_id", "version"})
        _id(artifact_ref["validation_id"], "$.validation_artifact_reference.validation_id")
        _string(artifact_ref["version"], "$.validation_artifact_reference.version")
    scientific_review = _enum(obj["scientific_review_state"], {"unresolved", "pending", "approved", "rejected"}, "$.scientific_review_state")
    product_review = _enum(obj["product_review_state"], {"not_requested", "pending", "approved", "rejected"}, "$.product_review_state")
    if status in {"validated", "provisional", "rejected"} and (
        artifact_reference is None or scientific_review != "approved"
    ):
        _fail("$.status", "validated, provisional, and rejected dispositions require a linked approved validation artifact")
    if scientific_review in {"unresolved", "pending"} and status != "inconclusive":
        _fail("$.status", "unresolved or pending scientific review must remain inconclusive")
    if product_review == "approved" and scientific_review != "approved":
        _fail("$.product_review_state", "product approval cannot precede scientific review approval")
    if synthetic and status not in {"inconclusive", "rejected"}:
        _fail("$.status", "synthetic evidence may only produce inconclusive or rejected demo findings")
    if synthetic and action != "do_not_implement":
        _fail("$.recommended_product_action", "synthetic findings must be do_not_implement")
    if safe_global and (status != "validated" or scope not in {"algorithmic", "population_supported"}):
        _fail("$.safe_for_global_consideration", "requires validated algorithmic or population_supported scope")
    if scope in _LIMITED_SCOPES and safe_global:
        _fail("$.safe_for_global_consideration", "limited-scope findings cannot be globally safe")
    if scope == "population_supported" and status != "validated":
        _fail("$.scope", "population_supported requires validated status")
    if scope == "population_hypothesis" and status == "validated":
        _fail("$.scope", "a validated population claim must use population_supported")
    effect = obj["effect_estimate"]
    if effect is not None:
        effect_obj = _object(effect, "$.effect_estimate")
        _keys(effect_obj, "$.effect_estimate", required={"metric_id", "estimate", "unit", "method"})
        _id(effect_obj["metric_id"], "$.effect_estimate.metric_id")
        _number(effect_obj["estimate"], "$.effect_estimate.estimate")
        _string(effect_obj["unit"], "$.effect_estimate.unit", nonempty=False)
        _string(effect_obj["method"], "$.effect_estimate.method")
    uncertainty = _object(obj["uncertainty"], "$.uncertainty")
    _keys(uncertainty, "$.uncertainty", required={"method", "interval", "confidence_level", "interpretation"})
    _string(uncertainty["method"], "$.uncertainty.method")
    interval = uncertainty["interval"]
    if interval is not None:
        values = _list(interval, "$.uncertainty.interval")
        if len(values) != 2:
            _fail("$.uncertainty.interval", "must contain [lower, upper]")
        lower = _number(values[0], "$.uncertainty.interval[0]")
        upper = _number(values[1], "$.uncertainty.interval[1]")
        if lower > upper:
            _fail("$.uncertainty.interval", "lower must not exceed upper")
    level = uncertainty["confidence_level"]
    if level is not None and not (0 < _number(level, "$.uncertainty.confidence_level") < 1):
        _fail("$.uncertainty.confidence_level", "must be between 0 and 1")
    _string(uncertainty["interpretation"], "$.uncertainty.interpretation")
    counts = _object(obj["sample_counts"], "$.sample_counts")
    expected_counts = {"drivers", "cars", "tracks", "sessions", "laps", "corners_or_events", "observations"}
    _keys(counts, "$.sample_counts", required=expected_counts)
    for name in expected_counts:
        _integer(counts[name], f"$.sample_counts.{name}", minimum=0)
    sufficiency = _object(obj["sample_sufficiency"], "$.sample_sufficiency")
    _keys(sufficiency, "$.sample_sufficiency", required={"status", "method", "rationale"})
    sufficiency_status = _enum(sufficiency["status"], {"sufficient", "insufficient", "undetermined"}, "$.sample_sufficiency.status")
    _string(sufficiency["method"], "$.sample_sufficiency.method")
    _string(sufficiency["rationale"], "$.sample_sufficiency.rationale")
    comparability = _object(obj["comparability_assessment"], "$.comparability_assessment")
    _keys(comparability, "$.comparability_assessment", required={"status", "criteria_applied", "violations"})
    comparability_status = _enum(comparability["status"], {"adequate", "limited", "inadequate", "undetermined"}, "$.comparability_assessment.status")
    _strings(comparability["criteria_applied"], "$.comparability_assessment.criteria_applied", nonempty=True)
    _strings(comparability["violations"], "$.comparability_assessment.violations")
    if status == "validated" and (sufficiency_status != "sufficient" or comparability_status != "adequate"):
        _fail("$.status", "validated findings require sufficient samples and adequate comparability")
    references = _list(obj["dataset_references"], "$.dataset_references", nonempty=True)
    for index, reference in enumerate(references):
        path = f"$.dataset_references[{index}]"
        ref_obj = _object(reference, path)
        _keys(ref_obj, path, required={"dataset_id", "fingerprint", "normalized_manifest_sha256", "records_sha256", "synthetic"})
        _id(ref_obj["dataset_id"], f"{path}.dataset_id")
        _sha(ref_obj["fingerprint"], f"{path}.fingerprint")
        _sha(ref_obj["normalized_manifest_sha256"], f"{path}.normalized_manifest_sha256")
        _sha(ref_obj["records_sha256"], f"{path}.records_sha256")
        ref_synthetic = _boolean(ref_obj["synthetic"], f"{path}.synthetic")
        if ref_synthetic != synthetic:
            _fail(path, "dataset synthetic flag must agree with finding")
    protocol = _object(obj["protocol_reference"], "$.protocol_reference")
    _keys(protocol, "$.protocol_reference", required={"experiment_id", "version", "freeze_id", "freeze_sha256"})
    _id(protocol["experiment_id"], "$.protocol_reference.experiment_id")
    _string(protocol["version"], "$.protocol_reference.version")
    _id(protocol["freeze_id"], "$.protocol_reference.freeze_id")
    _sha(protocol["freeze_sha256"], "$.protocol_reference.freeze_sha256")
    preprocessing = _object(obj["preprocessing"], "$.preprocessing")
    _keys(preprocessing, "$.preprocessing", required={"pipeline_id", "pipeline_version", "normalization_version", "configuration", "configuration_sha256"})
    _id(preprocessing["pipeline_id"], "$.preprocessing.pipeline_id")
    _string(preprocessing["pipeline_version"], "$.preprocessing.pipeline_version")
    _string(preprocessing["normalization_version"], "$.preprocessing.normalization_version")
    _object(preprocessing["configuration"], "$.preprocessing.configuration")
    _sha(preprocessing["configuration_sha256"], "$.preprocessing.configuration_sha256")
    if preprocessing["configuration_sha256"] != _canonical_hash(preprocessing["configuration"]):
        _fail("$.preprocessing.configuration_sha256", "does not match canonical configuration content")
    analysis = _object(obj["analysis"], "$.analysis")
    _keys(analysis, "$.analysis", required={"algorithm_id", "algorithm_version", "configuration", "random_seed"})
    _id(analysis["algorithm_id"], "$.analysis.algorithm_id")
    _string(analysis["algorithm_version"], "$.analysis.algorithm_version")
    _object(analysis["configuration"], "$.analysis.configuration")
    if analysis["random_seed"] is not None:
        _integer(analysis["random_seed"], "$.analysis.random_seed", minimum=0)
    code_identity = _object(obj["analysis_code_identity"], "$.analysis_code_identity")
    _keys(code_identity, "$.analysis_code_identity", required={"package_version", "git_commit", "git_state", "code_and_schema_sha256"})
    _string(code_identity["package_version"], "$.analysis_code_identity.package_version")
    _commit(code_identity["git_commit"], "$.analysis_code_identity.git_commit")
    _enum(code_identity["git_state"], {"clean", "dirty", "uncommitted"}, "$.analysis_code_identity.git_state")
    _sha(code_identity["code_and_schema_sha256"], "$.analysis_code_identity.code_and_schema_sha256")
    for field in ("limitations", "possible_confounders", "falsification_attempts", "required_future_validation"):
        _strings(obj[field], f"$.{field}", nonempty=field in {"limitations", "required_future_validation"})
    _timestamp(obj["created_at"], "$.created_at")
    commit = _commit(obj["apex_labs_source_commit"], "$.apex_labs_source_commit")
    if not synthetic and commit == "UNCOMMITTED":
        _fail("$.apex_labs_source_commit", "real findings require a source commit")
    if not synthetic and (
        code_identity["git_state"] != "clean" or code_identity["git_commit"] != commit
    ):
        _fail("$.analysis_code_identity", "real findings require analysis from the matching clean commit")
    return obj


def validate_export_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.EXPORT_DEFINITION)
    _keys(
        obj,
        "$",
        required={"schema_version", "export_id", "created_at", "apex_labs_version", "apex_labs_source_commit", "summary", "finding_paths", "validation_paths", "metric_paths", "algorithm_paths"},
    )
    _id(obj["export_id"], "$.export_id")
    _timestamp(obj["created_at"], "$.created_at")
    _string(obj["apex_labs_version"], "$.apex_labs_version")
    _commit(obj["apex_labs_source_commit"], "$.apex_labs_source_commit")
    _string(obj["summary"], "$.summary")
    _strings(obj["finding_paths"], "$.finding_paths", nonempty=True)
    _strings(obj["validation_paths"], "$.validation_paths", nonempty=True)
    _strings(obj["metric_paths"], "$.metric_paths")
    _strings(obj["algorithm_paths"], "$.algorithm_paths")
    return obj


def validate_metric_definition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.METRIC_DEFINITION)
    _keys(
        obj,
        "$",
        required={"schema_version", "metric_id", "version", "name", "definition", "unit", "directionality", "required_inputs", "computation", "output_provenance", "limitations"},
    )
    _id(obj["metric_id"], "$.metric_id")
    _string(obj["version"], "$.version")
    _string(obj["name"], "$.name")
    _string(obj["definition"], "$.definition")
    _string(obj["unit"], "$.unit", nonempty=False)
    _enum(obj["directionality"], {"higher_is_better", "lower_is_better", "target_range", "descriptive_only"}, "$.directionality")
    inputs = _strings(obj["required_inputs"], "$.required_inputs", nonempty=True)
    for index, concept in enumerate(inputs):
        if concept not in NORMALIZED_CONCEPTS:
            _fail(f"$.required_inputs[{index}]", "must be a normalized v1 concept")
    _string(obj["computation"], "$.computation")
    _enum(obj["output_provenance"], {"derived", "estimated"}, "$.output_provenance")
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj


def validate_algorithm_recommendation(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.ALGORITHM_RECOMMENDATION)
    _keys(
        obj,
        "$",
        required={"schema_version", "algorithm_id", "version", "title", "recommendation_status", "scope", "finding_references", "purpose", "required_inputs", "output", "procedure", "parameters", "assumptions", "validation_requirements", "implementation_caveats", "safe_for_global_consideration"},
    )
    _id(obj["algorithm_id"], "$.algorithm_id")
    _string(obj["version"], "$.version")
    _string(obj["title"], "$.title")
    _enum(obj["recommendation_status"], {"recommended", "experimental", "not_recommended"}, "$.recommendation_status")
    scope = _enum(obj["scope"], _SCOPES, "$.scope")
    _strings(obj["finding_references"], "$.finding_references", nonempty=True)
    _string(obj["purpose"], "$.purpose")
    inputs = _strings(obj["required_inputs"], "$.required_inputs", nonempty=True)
    for index, concept in enumerate(inputs):
        if concept not in NORMALIZED_CONCEPTS:
            _fail(f"$.required_inputs[{index}]", "must be a normalized v1 concept")
    _string(obj["output"], "$.output")
    _strings(obj["procedure"], "$.procedure", nonempty=True)
    _object(obj["parameters"], "$.parameters")
    _strings(obj["assumptions"], "$.assumptions", nonempty=True)
    _strings(obj["validation_requirements"], "$.validation_requirements", nonempty=True)
    _strings(obj["implementation_caveats"], "$.implementation_caveats", nonempty=True)
    safe = _boolean(obj["safe_for_global_consideration"], "$.safe_for_global_consideration")
    if safe and scope not in {"algorithmic", "population_supported"}:
        _fail("$.safe_for_global_consideration", "requires algorithmic or population_supported scope")
    if safe and obj["recommendation_status"] != "recommended":
        _fail("$.safe_for_global_consideration", "requires recommended status")
    return obj


def validate_product_export_manifest(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.PRODUCT_EXPORT_MANIFEST)
    _keys(
        obj,
        "$",
        required={"schema_version", "export_id", "created_at", "apex_labs_version", "apex_labs_source_commit", "summary", "review_gate", "findings", "files"},
    )
    _id(obj["export_id"], "$.export_id")
    _timestamp(obj["created_at"], "$.created_at")
    _string(obj["apex_labs_version"], "$.apex_labs_version")
    _commit(obj["apex_labs_source_commit"], "$.apex_labs_source_commit")
    _string(obj["summary"], "$.summary")
    if obj["review_gate"] != "human_and_production_engineering_review_required":
        _fail("$.review_gate", "must require human and production-engineering review")
    findings = _list(obj["findings"], "$.findings", nonempty=True)
    for index, finding in enumerate(findings):
        path = f"$.findings[{index}]"
        item = _object(finding, path)
        _keys(item, path, required={"finding_id", "version", "status", "scope", "evidence_classification", "synthetic", "scientific_review_state", "product_review_state", "safe_for_global_consideration", "recommended_product_action", "implementation_caveats", "path", "sha256", "validation_path", "validation_sha256"})
        _id(item["finding_id"], f"{path}.finding_id")
        _string(item["version"], f"{path}.version")
        _enum(item["status"], _STATUSES, f"{path}.status")
        _enum(item["scope"], _SCOPES, f"{path}.scope")
        _enum(item["evidence_classification"], {"controlled", "observational", "synthetic_demo"}, f"{path}.evidence_classification")
        _boolean(item["synthetic"], f"{path}.synthetic")
        _enum(item["scientific_review_state"], {"unresolved", "pending", "approved", "rejected"}, f"{path}.scientific_review_state")
        _enum(item["product_review_state"], {"not_requested", "pending", "approved", "rejected"}, f"{path}.product_review_state")
        _boolean(item["safe_for_global_consideration"], f"{path}.safe_for_global_consideration")
        _enum(item["recommended_product_action"], {"consider", "personalize_only", "research_only", "do_not_implement"}, f"{path}.recommended_product_action")
        _strings(item["implementation_caveats"], f"{path}.implementation_caveats", nonempty=True)
        _string(item["path"], f"{path}.path")
        _sha(item["sha256"], f"{path}.sha256")
        _string(item["validation_path"], f"{path}.validation_path")
        _sha(item["validation_sha256"], f"{path}.validation_sha256")
    files = _list(obj["files"], "$.files", nonempty=True)
    for index, file_item in enumerate(files):
        path = f"$.files[{index}]"
        item = _object(file_item, path)
        _keys(item, path, required={"path", "sha256", "media_type", "role"})
        _string(item["path"], f"{path}.path")
        _sha(item["sha256"], f"{path}.sha256")
        _string(item["media_type"], f"{path}.media_type")
        _enum(item["role"], {"finding", "validation", "metric", "algorithm", "provenance", "summary"}, f"{path}.role")
    return obj


def validate_product_provenance_summary(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.PRODUCT_PROVENANCE_SUMMARY)
    _keys(
        obj,
        "$",
        required={"schema_version", "export_id", "apex_labs_version", "apex_labs_source_commit", "finding_provenance"},
    )
    _id(obj["export_id"], "$.export_id")
    _string(obj["apex_labs_version"], "$.apex_labs_version")
    _commit(obj["apex_labs_source_commit"], "$.apex_labs_source_commit")
    entries = _list(obj["finding_provenance"], "$.finding_provenance", nonempty=True)
    identities: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        path = f"$.finding_provenance[{index}]"
        item = _object(entry, path)
        _keys(item, path, required={"finding_id", "finding_version", "dataset_references", "protocol_reference", "preprocessing", "analysis", "validation_artifact_reference", "scientific_review_state", "product_review_state"})
        identity = (_id(item["finding_id"], f"{path}.finding_id"), _string(item["finding_version"], f"{path}.finding_version"))
        if identity in identities:
            _fail(path, "finding identity must be unique")
        identities.add(identity)
        _list(item["dataset_references"], f"{path}.dataset_references", nonempty=True)
        _object(item["protocol_reference"], f"{path}.protocol_reference")
        _object(item["preprocessing"], f"{path}.preprocessing")
        _object(item["analysis"], f"{path}.analysis")
        _object(item["validation_artifact_reference"], f"{path}.validation_artifact_reference")
        _enum(item["scientific_review_state"], {"unresolved", "pending", "approved", "rejected"}, f"{path}.scientific_review_state")
        _enum(item["product_review_state"], {"not_requested", "pending", "approved", "rejected"}, f"{path}.product_review_state")
    return obj


VALIDATORS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "dataset": validate_dataset_manifest,
    "normalized-manifest": validate_normalized_manifest,
    "normalized-record": validate_normalized_record,
    "experiment": validate_experiment,
    "finding": validate_finding,
    "export-definition": validate_export_definition,
    "product-export-manifest": validate_product_export_manifest,
    "product-provenance-summary": validate_product_provenance_summary,
    "metric": validate_metric_definition,
    "algorithm": validate_algorithm_recommendation,
}
