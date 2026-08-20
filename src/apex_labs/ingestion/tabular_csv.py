"""Manifest-driven CSV adapter for compatible research datasets.

This adapter has no Apex Sim Coach field-name assumptions. A source manifest must
explicitly map each CSV column to a v1 normalized concept.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from apex_labs.errors import IngestionError
from apex_labs.normalization.concepts import CANONICAL_UNITS, NORMALIZED_CONCEPTS, PROVENANCE_KINDS
from apex_labs.schemas.validation import _conventions, _temporal_policy
from apex_labs.schemas.versions import NORMALIZED_RECORD

ADAPTER_ID = "tabular-csv"
ADAPTER_VERSION = "1.1.0"

_BOOLEAN_CONCEPTS = {"abs_active", "traction_control_active", "off_track_state", "lap_valid"}
_INTEGER_CONCEPTS = {"gear"}
_TEXT_CONCEPTS = {"session_state", "incident_state"}


def _configuration(config: dict[str, Any], source_paths: dict[str, Path]) -> dict[str, Any]:
    required = {
        "telemetry_file", "delimiter", "lap_number_column", "session", "column_mapping",
        "temporal_policy", "conventions",
    }
    unknown = set(config) - required
    missing = required - set(config)
    if missing or unknown:
        raise IngestionError(f"tabular-csv configuration missing={sorted(missing)}, unknown={sorted(unknown)}")
    if config["telemetry_file"] not in source_paths:
        raise IngestionError("adapter.configuration.telemetry_file must reference a declared source file")
    delimiter = config["delimiter"]
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise IngestionError("adapter.configuration.delimiter must be one character")
    session = config["session"]
    session_required = {"session_id", "driver_id", "car", "track", "layout"}
    if not isinstance(session, dict) or set(session) != session_required:
        raise IngestionError(f"adapter.configuration.session must contain exactly {sorted(session_required)}")
    if not all(isinstance(value, str) and value for value in session.values()):
        raise IngestionError("adapter.configuration.session values must be non-empty strings")
    mapping = config["column_mapping"]
    if not isinstance(mapping, dict) or not mapping:
        raise IngestionError("adapter.configuration.column_mapping must be a non-empty object")
    concepts: set[str] = set()
    for source_column, definition in mapping.items():
        if not isinstance(source_column, str) or not source_column:
            raise IngestionError("source column names must be non-empty strings")
        if not isinstance(definition, dict):
            raise IngestionError(f"mapping for {source_column!r} must be an object")
        allowed = {"concept", "unit", "provenance", "derivation"}
        if set(definition) - allowed or not {"concept", "unit", "provenance"} <= set(definition):
            raise IngestionError(f"mapping for {source_column!r} has invalid fields")
        concept = definition["concept"]
        if concept not in NORMALIZED_CONCEPTS:
            raise IngestionError(f"mapping for {source_column!r} uses unknown concept {concept!r}")
        if concept in concepts:
            raise IngestionError(f"normalized concept {concept!r} is mapped more than once")
        concepts.add(concept)
        if definition["unit"] != CANONICAL_UNITS[concept]:
            raise IngestionError(
                f"mapping for {source_column!r} must convert to canonical unit {CANONICAL_UNITS[concept]!r}"
            )
        provenance = definition["provenance"]
        if provenance not in PROVENANCE_KINDS - {"unavailable"}:
            raise IngestionError(f"mapped concept {concept!r} cannot declare {provenance!r}")
        if provenance in {"derived", "estimated"} and not definition.get("derivation"):
            raise IngestionError(f"mapped {provenance} concept {concept!r} requires derivation")
    if "timestamp" not in concepts:
        raise IngestionError("tabular-csv mapping must include the timestamp concept")
    _temporal_policy(config["temporal_policy"], "adapter.configuration.temporal_policy")
    _conventions(config["conventions"], "adapter.configuration.conventions")
    return config


def _parse(raw: str | None, concept: str, row_number: int, column: str) -> Any:
    if raw is None:
        raise IngestionError(
            f"Missing column value at row {row_number}, column {column!r}"
        )
    if raw == "":
        return None
    try:
        if concept in _BOOLEAN_CONCEPTS:
            normalized = raw.strip().lower()
            if normalized in {"1", "true", "yes"}:
                return True
            if normalized in {"0", "false", "no"}:
                return False
            raise ValueError("expected boolean")
        if concept in _INTEGER_CONCEPTS:
            return int(raw)
        if concept in _TEXT_CONCEPTS:
            return raw
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise IngestionError(
            f"Cannot parse row {row_number}, column {column!r} as {concept}: {raw!r}"
        ) from exc


def normalize_csv(
    manifest: dict[str, Any], source_paths: dict[str, Path]
) -> tuple[Iterable[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    config = _configuration(manifest["adapter"]["configuration"], source_paths)
    telemetry_relative = config["telemetry_file"]
    telemetry_path = source_paths[telemetry_relative]
    source_hash = next(item["sha256"] for item in manifest["source_files"] if item["path"] == telemetry_relative)
    session = config["session"]
    mapping = config["column_mapping"]
    lap_column = config["lap_number_column"]
    timestamp_column = next(
        source_column for source_column, definition in mapping.items()
        if definition["concept"] == "timestamp"
    )

    with telemetry_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=config["delimiter"])
        if reader.fieldnames is None:
            raise IngestionError("telemetry CSV has no header")
        required_columns = set(mapping) | {lap_column}
        missing = required_columns - set(reader.fieldnames)
        if missing:
            raise IngestionError(f"telemetry CSV is missing columns {sorted(missing)}")
        unknown_channels = sorted(set(reader.fieldnames) - required_columns)

    base_provenance = {
        "source_file": telemetry_relative,
        "source_file_sha256": source_hash,
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
    }
    session_id = session["session_id"]
    capabilities: dict[str, dict[str, Any]] = {
        concept: {"provenance": "unavailable"} for concept in sorted(NORMALIZED_CONCEPTS)
    }
    for source_column, definition in mapping.items():
        capabilities[definition["concept"]] = {
            key: value
            for key, value in {
                "provenance": definition["provenance"],
                "unit": definition["unit"],
                "source_channel": source_column,
                "derivation": definition.get("derivation"),
            }.items()
            if value is not None
        }

    def records() -> Iterable[dict[str, Any]]:
        yield {
            "schema_version": NORMALIZED_RECORD,
            "record_type": "session",
            "dataset_id": manifest["dataset_id"],
            "session_id": session_id,
            "record_id": f"{session_id}.session",
            "source_provenance": base_provenance,
            "simulator": manifest["simulator"],
            "driver_id": session["driver_id"],
            "car": session["car"],
            "track": session["track"],
            "layout": session["layout"],
            "fields": {},
        }
        sample_count = 0
        seen_laps: set[int] = set()
        current_lap: int | None = None
        with telemetry_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=config["delimiter"])
            for sample_index, row in enumerate(reader):
                sample_count += 1
                csv_row_number = sample_index + 2
                try:
                    lap_number = int(row[lap_column])
                except (TypeError, ValueError) as exc:
                    raise IngestionError(
                        f"Cannot parse row {csv_row_number}, lap column {lap_column!r} as an integer"
                    ) from exc
                if lap_number < 0:
                    raise IngestionError(f"Lap number at row {csv_row_number} must be non-negative")
                if lap_number != current_lap:
                    if lap_number in seen_laps:
                        raise IngestionError(
                            f"Lap {lap_number} reappears non-contiguously at row {csv_row_number}"
                        )
                    if current_lap is not None and lap_number < current_lap:
                        raise IngestionError(
                            f"Lap number regressed from {current_lap} to {lap_number} at row {csv_row_number}"
                        )
                    current_lap = lap_number
                    seen_laps.add(lap_number)
                    lap_id = f"{session_id}.lap-{lap_number:03d}"
                    yield {
                        "schema_version": NORMALIZED_RECORD,
                        "record_type": "lap",
                        "dataset_id": manifest["dataset_id"],
                        "session_id": session_id,
                        "record_id": lap_id,
                        "source_provenance": {
                            **base_provenance,
                            "row_start": csv_row_number,
                        },
                        "lap_id": lap_id,
                        "lap_number": lap_number,
                        "fields": {},
                    }
                fields: dict[str, dict[str, Any]] = {}
                for source_column, definition in mapping.items():
                    concept = definition["concept"]
                    parsed = _parse(row[source_column], concept, csv_row_number, source_column)
                    if parsed is None:
                        qualified: dict[str, Any] = {
                            "value": None,
                            "provenance": "unavailable",
                            "source_channel": source_column,
                            "unit": definition["unit"],
                            "quality_flags": ["missing_source_value"],
                        }
                    else:
                        qualified = {
                            "value": parsed,
                            "provenance": definition["provenance"],
                            "source_channel": source_column,
                            "unit": definition["unit"],
                        }
                        if "derivation" in definition:
                            qualified["derivation"] = definition["derivation"]
                    if concept == "timestamp":
                        qualified["reference"] = "normalized_monotonic_time"
                    fields[concept] = qualified
                lap_id = f"{session_id}.lap-{lap_number:03d}"
                yield {
                    "schema_version": NORMALIZED_RECORD,
                    "record_type": "telemetry_sample",
                    "dataset_id": manifest["dataset_id"],
                    "session_id": session_id,
                    "record_id": f"{session_id}.sample-{sample_index:06d}",
                    "source_provenance": {
                        **base_provenance,
                        "row_start": csv_row_number,
                        "row_end": csv_row_number,
                        "source_timestamp": row[timestamp_column],
                    },
                    "lap_id": lap_id,
                    "sample_index": sample_index,
                    "fields": fields,
                }
        if sample_count == 0:
            raise IngestionError("telemetry CSV contains no data rows")
    return records(), capabilities, unknown_channels
