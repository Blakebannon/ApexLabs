"""Local-only adapter for the Apex Sim Coach Research Recorder profile.

The product owns capture and bundle completion. Labs independently revalidates the
portable inventory and streams the high-frequency CSV into normalized v1 records.
No code in this module writes to, configures, or controls the product repository.
"""

from __future__ import annotations

import csv
import math
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ContractValidationError, IngestionError, IntegrityError
from apex_labs.io import canonical_json_bytes, iter_json_lines, parse_json_bytes, read_json, write_json
from apex_labs.normalization.concepts import CANONICAL_CONVENTIONS, CANONICAL_UNITS, NORMALIZED_CONCEPTS
from apex_labs.normalization.integrity import NormalizedIntegrityTracker
from apex_labs.provenance import (
    apex_labs_code_identity,
    build_dataset_fingerprint,
    normalized_dataset_fingerprint_basis,
    require_research_code_identity,
    sha256_bytes,
    sha256_file,
)
from apex_labs.schemas import (
    validate_collection_record,
    validate_exploratory_intake,
    validate_normalized_manifest,
    validate_normalized_record,
    validate_protocol_freeze,
    validate_research_recorder_manifest,
)
from apex_labs.schemas.versions import (
    APEX_RESEARCH_EXPORT,
    NORMALIZATION_VERSION,
    NORMALIZED_MANIFEST,
    NORMALIZED_RECORD,
)

ADAPTER_ID = "apex-research-recorder"
ADAPTER_VERSION = "1.2.0"
PROFILE_ID = "apex-labs-research-recorder-profile/1.0.0"
PROFILE_SHA256 = "20b547de4ef89d8b4a33bd8eb1bed282268b4b8e0b5f521108279e13961b800f"
BASE_SCHEMA_SHA256 = "5432cf9034b72bc8dc9c99c45c76dac07e320036460b0a7e4092c029bbf698b6"
COMPLETE_VERSION = "apex-research-complete/v1"
COLD_PRESSURE_DERIVATION = (
    "garage-set cold inflation pressure from {source} (kPa) multiplied by 1000; "
    "this is setup state, not live running tyre pressure, which iRacing does not expose"
)
MAX_SAMPLES = 5_000_000
MAX_CSV_FIELD_BYTES = 64 * 1024
SENSITIVE_TEXT = re.compile(
    r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|sk_(live|test)_|whsec_|"
    r"cus_[a-z0-9]+|sub_[a-z0-9]+|license.{0,8}[A-Z0-9-]{16,}|"
    r"driveruserid|subsessionid|machine.?fingerprint|[A-Z]:\\Users\\)"
)

# Exact ordered samples.csv header. The Apex Sim Coach recorder pins the identical list in
# ResearchContract.SampleColumns; the two must change together or every bundle is rejected.
SAMPLE_HEADERS = [
    "capture_sequence", "simulator_tick", "observed_utc", "session_time_s", "lap",
    "lap_time_s", "lap_distance_fraction", "brake", "throttle", "steering_angle_rad",
    "speed_mps", "gear", "rpm", "longitudinal_acceleration_mps2", "lateral_acceleration_mps2",
    "yaw_rate_radps", "fuel_liters", "fuel_fraction", "tire_temp_lf_left_c",
    "tire_temp_lf_middle_c", "tire_temp_lf_right_c", "tire_temp_rf_left_c",
    "tire_temp_rf_middle_c", "tire_temp_rf_right_c", "tire_temp_lr_left_c",
    "tire_temp_lr_middle_c", "tire_temp_lr_right_c", "tire_temp_rr_left_c",
    "tire_temp_rr_middle_c", "tire_temp_rr_right_c", "tire_wear_lf_left_pct",
    "tire_wear_lf_middle_pct", "tire_wear_lf_right_pct", "tire_wear_rf_left_pct",
    "tire_wear_rf_middle_pct", "tire_wear_rf_right_pct", "tire_wear_lr_left_pct",
    "tire_wear_lr_middle_pct", "tire_wear_lr_right_pct", "tire_wear_rr_left_pct",
    "tire_wear_rr_middle_pct", "tire_wear_rr_right_pct", "tire_cold_pressure_lf_kpa",
    "tire_cold_pressure_rf_kpa", "tire_cold_pressure_lr_kpa", "tire_cold_pressure_rr_kpa",
    "tire_odometer_lf_m", "tire_odometer_rf_m", "tire_odometer_lr_m", "tire_odometer_rr_m",
    "tire_compound", "brake_bias_setting", "abs_setting", "traction_control_setting",
    "abs_active", "pit_speed_limiter_active", "steering_ffb_enabled", "air_temp_c",
    "air_pressure_pa", "air_density_kgm3", "relative_humidity_pct", "precipitation_pct",
    "fog_level_pct", "wind_velocity_mps", "wind_direction_rad", "skies_index",
    "weather_declared_wet", "track_temp_crew_c", "track_wetness", "track_surface_material",
    "session_flags", "pace_mode", "pits_open", "car_distance_ahead_m", "car_distance_behind_m",
    "car_left_right", "on_pit_road", "incident_count", "session_state", "track_surface",
    "is_replay", "read_error_count",
]

INTEGER_COLUMNS = frozenset((
        "car_left_right",
        "gear",
        "incident_count",
        "lap",
        "pace_mode",
        "read_error_count",
        "session_flags",
        "session_state",
        "skies_index",
        "tire_compound",
        "track_surface",
        "track_surface_material",
        "track_wetness",
    ))

BOOLEAN_COLUMNS = frozenset((
        "abs_active",
        "is_replay",
        "on_pit_road",
        "pit_speed_limiter_active",
        "pits_open",
        "steering_ffb_enabled",
        "weather_declared_wet",
    ))

# Columns each declared channel owns. A channel the recorder declares unavailable must
# leave every one of its columns empty. wheel_state, damage and setup own no columns:
# the simulator exposes nothing for them, and brake_bias_setting is driver-adjustable
# control state declared in configuration-setup.json rather than part of a full setup.
CHANNEL_COLUMNS = {
    "timestamp": ("session_time_s",),
    "brake": ("brake",),
    "throttle": ("throttle",),
    "steering_angle": ("steering_angle_rad",),
    "speed": ("speed_mps",),
    "gear": ("gear",),
    "rpm": ("rpm",),
    "longitudinal_acceleration": ("longitudinal_acceleration_mps2",),
    "lateral_acceleration": ("lateral_acceleration_mps2",),
    "yaw_rate": ("yaw_rate_radps",),
    "tire_state": (
        "tire_temp_lf_left_c", "tire_temp_lf_middle_c", "tire_temp_lf_right_c",
        "tire_temp_rf_left_c", "tire_temp_rf_middle_c", "tire_temp_rf_right_c",
        "tire_temp_lr_left_c", "tire_temp_lr_middle_c", "tire_temp_lr_right_c",
        "tire_temp_rr_left_c", "tire_temp_rr_middle_c", "tire_temp_rr_right_c",
        "tire_wear_lf_left_pct", "tire_wear_lf_middle_pct", "tire_wear_lf_right_pct",
        "tire_wear_rf_left_pct", "tire_wear_rf_middle_pct", "tire_wear_rf_right_pct",
        "tire_wear_lr_left_pct", "tire_wear_lr_middle_pct", "tire_wear_lr_right_pct",
        "tire_wear_rr_left_pct", "tire_wear_rr_middle_pct", "tire_wear_rr_right_pct",
        "tire_cold_pressure_lf_kpa", "tire_cold_pressure_rf_kpa", "tire_cold_pressure_lr_kpa",
        "tire_cold_pressure_rr_kpa", "tire_odometer_lf_m", "tire_odometer_rf_m",
        "tire_odometer_lr_m", "tire_odometer_rr_m", "tire_compound",
    ),
    "fuel": (
        "fuel_liters", "fuel_fraction",
    ),
    "assists": (
        "abs_setting", "traction_control_setting", "abs_active", "pit_speed_limiter_active",
        "steering_ffb_enabled",
    ),
    "flags": (
        "session_flags", "session_state", "pace_mode", "pits_open",
    ),
    "weather": (
        "air_temp_c", "air_pressure_pa", "air_density_kgm3", "relative_humidity_pct",
        "precipitation_pct", "fog_level_pct", "wind_velocity_mps", "wind_direction_rad",
        "skies_index", "weather_declared_wet",
    ),
    "traffic": (
        "car_distance_ahead_m", "car_distance_behind_m", "car_left_right",
    ),
    "track_conditions": (
        "track_temp_crew_c", "track_wetness", "track_surface", "track_surface_material",
    ),
}


# Sample columns carried into the bundle and validated, but deliberately NOT promoted to a
# normalized concept in this contract version. They are retained as declared source provenance
# so a later concept review can promote them deliberately rather than by accident.
RETAINED_SOURCE_COLUMNS = tuple(
    column for column in SAMPLE_HEADERS
    if column not in {
        "capture_sequence", "simulator_tick", "observed_utc", "read_error_count", "lap",
        "session_time_s", "lap_time_s", "lap_distance_fraction", "brake", "throttle",
        "steering_angle_rad", "speed_mps", "gear", "rpm",
        "longitudinal_acceleration_mps2", "lateral_acceleration_mps2", "yaw_rate_radps",
        "tire_temp_lf_middle_c", "tire_temp_rf_middle_c",
        "tire_temp_lr_middle_c", "tire_temp_rr_middle_c",
        "tire_cold_pressure_lf_kpa", "tire_cold_pressure_rf_kpa",
        "tire_cold_pressure_lr_kpa", "tire_cold_pressure_rr_kpa",
        "session_state", "incident_count",
        "air_temp_c", "track_temp_crew_c", "abs_active", "track_surface",
    }
)

# The value the product-declared irsdk_TrkLoc dictionary gives to being off track.
OFF_TRACK_MEANING = "off_track"


def _enum_dictionaries(metadata: dict[str, Any]) -> dict[str, Any]:
    """Read the recorder's declared enum semantics without trusting them blindly."""
    declared = metadata.get("enum_dictionaries")
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise ContractValidationError("recorder-metadata.json: enum_dictionaries must be an object")
    for column, entry in declared.items():
        if column not in SAMPLE_HEADERS:
            raise ContractValidationError(
                f"recorder-metadata.json: enum dictionary names unknown column {column!r}"
            )
        if not isinstance(entry, dict):
            raise ContractValidationError(f"recorder-metadata.json: enum dictionary {column!r} must be an object")
        required = {"enumeration", "kind", "dictionary_provenance", "unknown_value_behavior", "limitation"}
        if not required.issubset(entry):
            raise ContractValidationError(
                f"recorder-metadata.json: enum dictionary {column!r} is missing declared semantics"
            )
        if entry["dictionary_provenance"] not in {"product_declared", "sdk_variable_description", "unavailable"}:
            raise ContractValidationError(
                f"recorder-metadata.json: enum dictionary {column!r} has an unsupported provenance"
            )
        if entry["unknown_value_behavior"] != "preserve_raw_value":
            raise ContractValidationError(
                f"recorder-metadata.json: enum dictionary {column!r} must preserve unknown raw values"
            )
        values = entry.get("values")
        if entry["dictionary_provenance"] == "unavailable":
            if values is not None:
                raise ContractValidationError(
                    f"recorder-metadata.json: enum dictionary {column!r} declares no provenance but supplies values"
                )
        elif not isinstance(values, dict) or not values:
            raise ContractValidationError(
                f"recorder-metadata.json: enum dictionary {column!r} claims provenance without a value table"
            )
    return declared


def _off_track_values(
    dictionaries: dict[str, Any],
) -> tuple[frozenset[int], frozenset[int], str] | None:
    """Resolve which track_surface values mean off-track, or None when undecidable.

    Labs never guesses an enumeration. Without a declared dictionary the concept stays
    unavailable, and a value absent from the dictionary stays unavailable too.
    """
    entry = dictionaries.get("track_surface")
    if entry is None or entry["dictionary_provenance"] == "unavailable":
        return None
    known: dict[int, str] = {}
    for raw, meaning in entry["values"].items():
        try:
            known[int(raw)] = str(meaning)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "recorder-metadata.json: track_surface dictionary keys must be integers"
            ) from exc
    if OFF_TRACK_MEANING not in known.values():
        return None
    off_track = frozenset(value for value, meaning in known.items() if meaning == OFF_TRACK_MEANING)
    return off_track, frozenset(known), (
        f"track_surface resolved through the {entry['enumeration']} dictionary declared by the "
        f"recorder with {entry['dictionary_provenance']} provenance; values outside that dictionary "
        "stay unavailable"
    )


@dataclass(frozen=True)
class ResearchBundleAudit:
    root: Path
    manifest: dict[str, Any]
    metadata: dict[str, Any]
    manifest_sha256: str
    sample_count: int
    event_count: int


@contextmanager
def _snapshot_research_bundle(root: Path, *, temporary_parent: Path | None = None) -> Iterator[Path]:
    source = root.resolve()
    if not source.is_dir():
        raise ContractValidationError(f"Research bundle directory not found: {source}")
    expected = {
        "manifest.json", "COMPLETE", "samples.csv", "events.jsonl",
        "configuration-setup.json", "recorder-metadata.json",
    }
    entries = {path.name for path in source.iterdir()}
    if entries != expected or any(path.is_symlink() or not path.is_file() for path in source.iterdir()):
        raise ContractValidationError(
            f"Research bundle inventory mismatch; missing={sorted(expected - entries)}, extra={sorted(entries - expected)}"
        )
    if temporary_parent is not None:
        temporary_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="apex-labs-research-snapshot-", dir=temporary_parent,
    ) as temporary:
        snapshot = Path(temporary) / "bundle"
        snapshot.mkdir()
        for name in sorted(expected):
            with (source / name).open("rb") as source_handle, (snapshot / name).open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
        yield snapshot


# The Research Recorder writes .NET round-trip timestamps with 100-nanosecond precision
# (seven fractional digits). That is valid ISO 8601, but datetime.fromisoformat accepts at
# most six, so excess fractional digits are truncated for parsing only. The declared text is
# never rewritten: the artifact keeps the recorder's exact bytes.
_EXCESS_FRACTION = re.compile(r"(\.\d{6})\d+")


def _parsable_timestamp(text: str) -> str:
    return _EXCESS_FRACTION.sub(r"", text).replace("Z", "+00:00")


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_parsable_timestamp(value))
    except ValueError as exc:
        raise ContractValidationError(f"{field}: invalid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractValidationError(f"{field}: timezone is required")
    return parsed


def _number(value: str, field: str) -> float | None:
    if value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ContractValidationError(f"{field}: expected a number or empty unavailable field") from exc
    if not math.isfinite(parsed):
        raise ContractValidationError(f"{field}: non-finite values are forbidden")
    return parsed


def _integer(value: str, field: str) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ContractValidationError(f"{field}: expected an integer or empty unavailable field") from exc


def _boolean(value: str, field: str) -> bool | None:
    if value == "":
        return None
    if value not in {"true", "false"}:
        raise ContractValidationError(f"{field}: expected true, false, or empty unavailable field")
    return value == "true"


def _sample_rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    old_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != SAMPLE_HEADERS:
                raise ContractValidationError(
                    f"samples.csv: exact header mismatch; expected={SAMPLE_HEADERS}, actual={reader.fieldnames}"
                )
            for row_number, row in enumerate(reader, start=2):
                if row_number - 1 > MAX_SAMPLES:
                    raise ContractValidationError(f"samples.csv: exceeds {MAX_SAMPLES} sample safety limit")
                if None in row or any(value is None for value in row.values()):
                    raise ContractValidationError(f"samples.csv row {row_number}: malformed column count")
                yield row_number, row
    except UnicodeDecodeError as exc:
        raise ContractValidationError("samples.csv: must be UTF-8") from exc
    finally:
        csv.field_size_limit(old_limit)


def _validate_samples(audit_root: Path, manifest: dict[str, Any], metadata: dict[str, Any]) -> int:
    unavailable = {
        channel["name"] for channel in manifest["channels"] if channel["availability"] == "unavailable"
    }
    previous_sequence: int | None = None
    sequence_gaps = 0
    count = 0
    for row_number, row in _sample_rows(audit_root / "samples.csv"):
        sequence = _integer(row["capture_sequence"], f"samples.csv row {row_number} capture_sequence")
        tick = _integer(row["simulator_tick"], f"samples.csv row {row_number} simulator_tick")
        if sequence is None or sequence < 0 or tick is None:
            raise ContractValidationError(f"samples.csv row {row_number}: sequence and simulator tick are required")
        if previous_sequence is not None:
            if sequence <= previous_sequence:
                raise ContractValidationError(f"samples.csv row {row_number}: capture sequence is not strictly increasing")
            sequence_gaps += sequence - previous_sequence - 1
        previous_sequence = sequence
        _timestamp(row["observed_utc"], f"samples.csv row {row_number} observed_utc")
        for field in SAMPLE_HEADERS:
            if field in {"capture_sequence", "simulator_tick", "observed_utc"}:
                continue
            if field in INTEGER_COLUMNS:
                _integer(row[field], f"samples.csv row {row_number} {field}")
            elif field in BOOLEAN_COLUMNS:
                _boolean(row[field], f"samples.csv row {row_number} {field}")
            else:
                _number(row[field], f"samples.csv row {row_number} {field}")
        for channel in unavailable:
            if any(row[column] != "" for column in CHANNEL_COLUMNS.get(channel, ())):
                raise ContractValidationError(
                    f"samples.csv row {row_number}: unavailable channel {channel!r} contains a value"
                )
        count += 1
    declared_drops = metadata["metrics"].get("samples_dropped_by_backpressure")
    if not isinstance(declared_drops, int) or declared_drops < 0:
        raise ContractValidationError("recorder-metadata.json: invalid dropped-sample accounting")
    if sequence_gaps > declared_drops:
        raise ContractValidationError(
            "samples.csv: capture-sequence gaps exceed declared backpressure drops"
        )
    if metadata["metrics"].get("samples_written") != count:
        raise ContractValidationError("recorder-metadata.json: samples_written does not match samples.csv")
    return count


def _validate_events(path: Path, metadata: dict[str, Any]) -> int:
    expected_sequence = 0
    kinds: set[str] = set()
    for event in iter_json_lines(path):
        if not isinstance(event, dict) or set(event) != {
            "schema_version", "sequence", "observed_utc", "session_time_s", "kind", "data"
        }:
            raise ContractValidationError(f"events.jsonl record {expected_sequence}: invalid shape")
        if event["schema_version"] != "apex-research-event/1.0.0" or event["sequence"] != expected_sequence:
            raise ContractValidationError(f"events.jsonl record {expected_sequence}: invalid schema or sequence")
        _timestamp(event["observed_utc"], f"events.jsonl record {expected_sequence} observed_utc")
        if event["session_time_s"] is not None and not isinstance(event["session_time_s"], (int, float)):
            raise ContractValidationError(f"events.jsonl record {expected_sequence}: invalid session time")
        if not isinstance(event["kind"], str) or not event["kind"] or not isinstance(event["data"], dict):
            raise ContractValidationError(f"events.jsonl record {expected_sequence}: invalid kind/data")
        kinds.add(event["kind"])
        expected_sequence += 1
    if "collection-condition" not in kinds:
        raise ContractValidationError("events.jsonl: missing experimental condition marker")
    coaching_state = metadata["collection"].get("coaching_state")
    if coaching_state == "disabled" and "coaching-disabled-control" not in kinds:
        raise ContractValidationError("events.jsonl: disabled control condition is not explicit")
    if coaching_state == "enabled" and "coaching-evidence-summary" not in kinds:
        raise ContractValidationError("events.jsonl: coached recording lacks authoritative evidence summary")
    if metadata["metrics"].get("events_written") != expected_sequence:
        raise ContractValidationError("recorder-metadata.json: events_written does not match events.jsonl")
    if metadata["metrics"].get("events_dropped") != 0:
        raise ContractValidationError("recorder-metadata.json: completed bundle declares dropped evidence events")
    return expected_sequence


def audit_research_bundle(root: Path) -> ResearchBundleAudit:
    root = root.resolve()
    if not root.is_dir():
        raise ContractValidationError(f"Research bundle directory not found: {root}")
    entries = {path.name for path in root.iterdir()}
    expected = {
        "manifest.json", "COMPLETE", "samples.csv", "events.jsonl",
        "configuration-setup.json", "recorder-metadata.json",
    }
    if entries != expected or any(path.is_symlink() or not path.is_file() for path in root.iterdir()):
        raise ContractValidationError(
            f"Research bundle inventory mismatch; missing={sorted(expected - entries)}, extra={sorted(entries - expected)}"
        )
    manifest_path = root / "manifest.json"
    manifest = validate_research_recorder_manifest(read_json(manifest_path))
    manifest_hash = sha256_file(manifest_path)
    marker = (root / "COMPLETE").read_bytes()
    expected_marker = f"{COMPLETE_VERSION}\n{manifest_hash}\n".encode("utf-8")
    if marker != expected_marker:
        raise IntegrityError("COMPLETE does not exactly bind the recorder manifest")
    for entry in manifest["files"]:
        source = root / entry["path"]
        if source.stat().st_size != entry["size_bytes"] or sha256_file(source) != entry["sha256"]:
            raise IntegrityError(f"Research bundle size/hash mismatch: {entry['path']}")
    for name in ("manifest.json", "samples.csv", "events.jsonl", "configuration-setup.json", "recorder-metadata.json"):
        try:
            with (root / name).open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if len(line) > MAX_CSV_FIELD_BYTES * 16:
                        raise ContractValidationError(
                            f"{name} line {line_number}: exceeds bounded text-line safety limit"
                        )
                    if SENSITIVE_TEXT.search(line):
                        raise ContractValidationError(
                            f"{name}: privacy scan found a prohibited identifier/secret shape"
                        )
        except UnicodeDecodeError as exc:
            raise ContractValidationError(f"{name}: recorder-profile text must be UTF-8") from exc
    configuration_hash = sha256_file(root / "configuration-setup.json")
    if configuration_hash != manifest["collection"]["configuration_setup_hash"]:
        raise IntegrityError("configuration_setup_hash does not bind configuration-setup.json")
    metadata = read_json(root / "recorder-metadata.json")
    contract = metadata.get("contract", {})
    if contract != {
        "schema_version": APEX_RESEARCH_EXPORT,
        "schema_sha256": BASE_SCHEMA_SHA256,
        "profile_id": PROFILE_ID,
        "profile_sha256": PROFILE_SHA256,
    }:
        raise ContractValidationError("recorder-metadata.json: unsupported contract/profile pin")
    recorder = metadata.get("recorder", {})
    if recorder.get("local_only") is not True or recorder.get("automatic_upload") is not False:
        raise ContractValidationError("recorder-metadata.json: local-only boundary is not declared")
    privacy = metadata.get("privacy", {})
    privacy_false = {
        "direct_identifiers_recorded", "raw_driver_user_id_recorded", "raw_subsession_id_recorded",
        "pseudonym_key_material_recorded", "absolute_paths_recorded",
    }
    if any(privacy.get(field) is not False for field in privacy_false):
        raise ContractValidationError("recorder-metadata.json: privacy exclusion declarations are incomplete")
    if privacy.get("classification") != manifest["privacy"]["classification"]:
        raise ContractValidationError("recorder-metadata.json: privacy classification mismatch")
    participant = manifest["session"]["participant_pseudonym"]
    if manifest["privacy"]["classification"] == "synthetic":
        if not participant.startswith("synthetic-"):
            raise ContractValidationError("$.session.participant_pseudonym: synthetic identity must be explicit")
    elif re.fullmatch(r"participant-[0-9a-f]{24}", participant) is None:
        raise ContractValidationError("$.session.participant_pseudonym: approved keyed pseudonym shape required")
    samples = _validate_samples(root, manifest, metadata)
    events = _validate_events(root / "events.jsonl", metadata)
    return ResearchBundleAudit(root, manifest, metadata, manifest_hash, samples, events)


def _protocol_snapshot_identity(freeze: dict[str, Any]) -> dict[str, Any]:
    """The six identity fields a collection record must declare, read from the freeze.

    Four of these do not exist at the snapshot's top level and never can:
    apex-labs.protocol-freeze/v1 sets ``additionalProperties: false`` and permits only
    freeze_id, freeze_sha256, protocol_id, protocol_version, protocol_sha256,
    source_commit, code_identity, frozen_at, synthetic, protocol, randomization and
    amendment_history. The experiment identity lives inside the hash-bound protocol
    document and the schedule identity inside randomization, so indexing the snapshot
    by the collection-record field names raised KeyError for every real
    protocol-governed bundle.

    The experiment identity is read from the protocol document rather than from the
    top-level protocol_id mirror, because the protocol document is what protocol_sha256
    binds. The mirror is then required to agree: a snapshot whose own two statements of
    its identity disagree is refused rather than silently resolved in favour of either.
    """
    protocol = freeze["protocol"]
    experiment_id = protocol["experiment_id"]
    experiment_version = protocol["version"]
    if freeze["protocol_id"] != experiment_id or freeze["protocol_version"] != experiment_version:
        raise IntegrityError(
            "Protocol snapshot disagrees with its own protocol document about experiment identity")
    return {
        "freeze_id": freeze["freeze_id"],
        "freeze_sha256": freeze["freeze_sha256"],
        "experiment_id": experiment_id,
        "experiment_version": experiment_version,
        "schedule_id": freeze["randomization"]["schedule_id"],
        "schedule_sha256": freeze["randomization"]["schedule_sha256"],
    }


def _bind_collection(collection: dict[str, Any], audit: ResearchBundleAudit) -> None:
    manifest = audit.manifest
    if collection["source_bundle"] != {
        "schema_version": APEX_RESEARCH_EXPORT,
        "sha256": audit.manifest_sha256,
    }:
        raise IntegrityError("Collection record does not bind the exact completed research manifest")
    session = manifest["session"]
    identity = collection["session_identity"]
    expected = {
        "simulator": session["simulator"]["id"],
        "car": session["car"]["id"],
        "track": session["track"]["id"],
        "layout": session["track"]["layout"],
    }
    if any(identity[name] != value for name, value in expected.items()):
        raise IntegrityError("Collection record session identity does not match the research bundle")
    if collection["participant"]["pseudonymous_participant_id"] != session["participant_pseudonym"]:
        raise IntegrityError("Collection record participant pseudonym does not match the research bundle")
    source_is_synthetic = manifest["privacy"]["classification"] == "synthetic"
    if collection["synthetic"] != source_is_synthetic:
        raise IntegrityError("Collection record synthetic classification does not match the research bundle")
    if collection["coaching"]["state"] != audit.metadata["collection"]["coaching_state"]:
        raise IntegrityError("Collection record coaching state does not match recorder evidence")
    recorded_collection = audit.metadata["collection"]
    if recorded_collection.get("protocol_identity") != manifest["collection"]["protocol_identity"]:
        raise IntegrityError("Recorder metadata protocol identity does not match its manifest")
    if collection["protocol"] is not None:
        # The recorder writes the PROTOCOL EXPERIMENT identity, not the freeze identity.
        # The collection record carries both, as separate contract fields, and only the
        # experiment identity is comparable to what the recorder wrote. Comparing the
        # freeze identity here made a protocol-governed real bundle unable to satisfy
        # this check and the snapshot equality below at the same time, because
        # freeze_id is f"{experiment_id}.freeze" and the two can never be equal.
        # apex-labs.corpus admission binds the same recorder field to the same
        # experiment identity, so the two gates now agree by construction.
        if collection["protocol"]["experiment_id"] != manifest["collection"]["protocol_identity"]:
            raise IntegrityError(
                "Collection protocol experiment identity does not match the recorder protocol identity")
        matching_blocks = [
            block for block in collection["blocks"]
            if block["block_id"] == recorded_collection.get("experimental_block_id")
            and block["condition_id"] == recorded_collection.get("condition_id")
        ]
        if len(matching_blocks) != 1:
            raise IntegrityError("Collection block/condition does not bind the recorder labels")


def _bind_exploratory_intake(
    intake: dict[str, Any],
    collection: dict[str, Any],
    collection_record_path: Path,
    audit: ResearchBundleAudit,
) -> None:
    """Prove the intake admits THIS bundle and THIS collection record, and nothing else.

    An intake is worthless unless it is welded to the exact bytes it approves.
    Every check here is an equality against content that already exists: the
    session id and manifest hash come from the completed bundle, and the
    collection-record hash is taken from the file on disk rather than from
    anything the intake itself asserts. Copying an intake next to a different
    bundle, editing the collection record after review, or approving a session
    whose collection record claims an experimental design all fail here.
    """
    session_id = audit.manifest["session"]["session_id"]
    if intake["source_session_id"] != session_id:
        raise IntegrityError(
            "Exploratory intake does not admit this session: "
            f"declared {intake['source_session_id']!r}, bundle {session_id!r}"
        )
    if intake["source_manifest_sha256"] != audit.manifest_sha256:
        raise IntegrityError("Exploratory intake does not bind the exact completed research manifest")
    if intake["collection_record_id"] != collection["collection_record_id"]:
        raise IntegrityError("Exploratory intake does not bind this collection record identity")
    if intake["collection_record_sha256"] != sha256_file(collection_record_path):
        raise IntegrityError("Exploratory intake does not bind the exact collection record bytes")
    if intake["collection_classification"] != collection["collection_classification"]:
        raise IntegrityError(
            "Exploratory intake and collection record disagree about collection classification"
        )
    # A collection record that names a frozen protocol is claiming prospective
    # governance; retrospective admission is then a contradiction, not a shortcut.
    if collection["protocol"] is not None:
        raise IntegrityError(
            "Exploratory intake cannot admit a collection record that declares a frozen protocol"
        )
    if collection["synthetic"]:
        raise IntegrityError("Synthetic collections ingest without a protocol and need no intake")


def _exploratory_eligibility(intake: dict[str, Any]) -> dict[str, Any]:
    """The permanent, fingerprint-bound stratum derived from a verified intake.

    Derived from the intake rather than accepted from an operator, so the
    normalized dataset states exactly what the reviewed artifact permitted and
    nothing wider.
    """
    timeline = intake["collection_timeline"]
    eligibility = intake["eligibility"]
    return {
        "stratum": "exploratory_pilot",
        "prospective_protocol": timeline["prospective_protocol_existed"],
        "collected_before_protocol_freeze": timeline["collected_before_protocol_freeze"],
        "retained_after_outcome_known": timeline["retained_after_outcome_known"],
        "descriptive_analysis": eligibility["descriptive_analysis_eligible"],
        "hypothesis_generation": eligibility["hypothesis_generation_eligible"],
        "confirmatory": eligibility["confirmatory_eligible"],
        "causal": eligibility["causal_eligible"],
        "primary_effect_estimate": eligibility["primary_effect_estimate_eligible"],
        "primary_corpus_pooling": eligibility["primary_corpus_pooling_eligible"],
        "reason": (
            f"Retrospectively admitted under exploratory intake {intake['intake_id']} "
            f"(reviewed {intake['review']['reviewed_at']}, {intake['review']['status']}). "
            "Collected before any protocol freeze; descriptive analysis and hypothesis "
            "generation only."
        ),
    }


def _primary_eligibility(protocol_document: dict[str, Any]) -> dict[str, Any]:
    """The stratum of a dataset collected under a reviewed prospective freeze."""
    return {
        "stratum": "primary_frozen_corpus",
        "prospective_protocol": True,
        "collected_before_protocol_freeze": False,
        "retained_after_outcome_known": False,
        "descriptive_analysis": True,
        "hypothesis_generation": True,
        "confirmatory": True,
        "causal": True,
        "primary_effect_estimate": True,
        "primary_corpus_pooling": True,
        "reason": (
            f"Collected under frozen protocol {protocol_document['freeze_id']} "
            f"({protocol_document['freeze_sha256']})."
        ),
    }


def _audit_report(audit: ResearchBundleAudit) -> dict[str, Any]:
    channels = {item["name"]: item["availability"] for item in audit.manifest["channels"]}
    return {
        "valid": True,
        "schema_version": APEX_RESEARCH_EXPORT,
        "profile_id": PROFILE_ID,
        "manifest_sha256": audit.manifest_sha256,
        "session_id": audit.manifest["session"]["session_id"],
        "sample_count": audit.sample_count,
        "event_count": audit.event_count,
        "channels": channels,
        "local_only": True,
    }


def inspect_research_bundle(root: Path) -> dict[str, Any]:
    with _snapshot_research_bundle(root) as snapshot:
        return _audit_report(audit_research_bundle(snapshot))


def validate_research_bundle(root: Path, collection_record_path: Path | None = None) -> dict[str, Any]:
    with _snapshot_research_bundle(root) as snapshot:
        audit = audit_research_bundle(snapshot)
        if collection_record_path is not None:
            collection = validate_collection_record(read_json(collection_record_path))
            _bind_collection(collection, audit)
        result = _audit_report(audit)
        result["collection_record_validated"] = collection_record_path is not None
        return result


def _qualified(
    value: float | int | bool | None,
    concept: str,
    source: str,
    *,
    scale: float = 1.0,
    derivation: str | None = None,
) -> dict[str, Any]:
    if value is None:
        return {"value": None, "provenance": "unavailable", "unit": CANONICAL_UNITS[concept]}
    converted = (
        value * scale
        if scale != 1.0 and isinstance(value, (int, float)) and not isinstance(value, bool)
        else value
    )
    if scale == 1.0:
        return {
            "value": converted,
            "provenance": "measured",
            "unit": CANONICAL_UNITS[concept],
            "source_channel": source,
        }
    return {
        "value": converted,
        "provenance": "derived",
        "unit": CANONICAL_UNITS[concept],
        "derivation": derivation or f"{source} multiplied by {scale:g}",
    }



def _qualified_text(value: int | None, concept: str, source: str, note: str) -> dict[str, Any]:
    """Carry an integer-valued text concept without pretending it has been decoded.

    session_state and incident_state are text concepts. The raw simulator integer is preserved
    verbatim as its decimal string; no enumeration is decoded here, because the inventory
    proves the enum identity but carries no value dictionary.
    """
    if value is None:
        return {"value": None, "provenance": "unavailable", "unit": CANONICAL_UNITS[concept]}
    return {
        "value": str(value),
        "provenance": "measured",
        "unit": CANONICAL_UNITS[concept],
        "source_channel": source,
        "quality_flags": [note],
    }


def _fields(
    row: dict[str, str],
    observed_origin: datetime,
    off_track: tuple[frozenset[int], frozenset[int], str] | None,
) -> dict[str, Any]:
    session_time = _number(row["session_time_s"], "session_time_s")
    observed = _timestamp(row["observed_utc"], "observed_utc")
    if session_time is None:
        timestamp = {
            "value": (observed - observed_origin).total_seconds(),
            "provenance": "derived",
            "unit": "s",
            "derivation": "host observed UTC minus research session start UTC",
            "reference": "normalized_monotonic_time",
        }
    else:
        timestamp = {
            "value": session_time, "provenance": "measured", "unit": "s",
            "source_channel": "SessionTime", "reference": "normalized_monotonic_time",
        }
    fields = {
        "timestamp": timestamp,
        "lap_time": _qualified(_number(row["lap_time_s"], "lap_time_s"), "lap_time", "LapCurrentLapTime"),
        "lap_fraction": _qualified(_number(row["lap_distance_fraction"], "lap_distance_fraction"), "lap_fraction", "LapDistPct"),
        "speed": _qualified(_number(row["speed_mps"], "speed_mps"), "speed", "Speed"),
        "longitudinal_acceleration": _qualified(_number(row["longitudinal_acceleration_mps2"], "longitudinal_acceleration_mps2"), "longitudinal_acceleration", "LongAccel"),
        "lateral_acceleration": _qualified(_number(row["lateral_acceleration_mps2"], "lateral_acceleration_mps2"), "lateral_acceleration", "LatAccel"),
        "yaw_rate": _qualified(_number(row["yaw_rate_radps"], "yaw_rate_radps"), "yaw_rate", "YawRate"),
        "steering_angle": _qualified(_number(row["steering_angle_rad"], "steering_angle_rad"), "steering_angle", "SteeringWheelAngle"),
        "throttle": _qualified(_number(row["throttle"], "throttle"), "throttle", "Throttle"),
        "brake": _qualified(_number(row["brake"], "brake"), "brake", "Brake"),
        "gear": _qualified(_integer(row["gear"], "gear"), "gear", "Gear"),
        "rpm": _qualified(_number(row["rpm"], "rpm"), "rpm", "RPM"),
        "tire_temperature_front_left": _qualified(
            _number(row["tire_temp_lf_middle_c"], "tire_temp_lf_middle_c"),
            "tire_temperature_front_left", "LFtempCM"),
        "tire_temperature_front_right": _qualified(
            _number(row["tire_temp_rf_middle_c"], "tire_temp_rf_middle_c"),
            "tire_temperature_front_right", "RFtempCM"),
        "tire_temperature_rear_left": _qualified(
            _number(row["tire_temp_lr_middle_c"], "tire_temp_lr_middle_c"),
            "tire_temperature_rear_left", "LRtempCM"),
        "tire_temperature_rear_right": _qualified(
            _number(row["tire_temp_rr_middle_c"], "tire_temp_rr_middle_c"),
            "tire_temperature_rear_right", "RRtempCM"),
        # Cold, garage-set pressure. iRacing exposes no hot/running tire pressure.
        "tire_pressure_front_left": _qualified(
            _number(row["tire_cold_pressure_lf_kpa"], "tire_cold_pressure_lf_kpa"),
            "tire_pressure_front_left", "LFcoldPressure", scale=1000.0,
            derivation=COLD_PRESSURE_DERIVATION.format(source="LFcoldPressure"),
        ),
        "tire_pressure_front_right": _qualified(
            _number(row["tire_cold_pressure_rf_kpa"], "tire_cold_pressure_rf_kpa"),
            "tire_pressure_front_right", "RFcoldPressure", scale=1000.0,
            derivation=COLD_PRESSURE_DERIVATION.format(source="RFcoldPressure"),
        ),
        "tire_pressure_rear_left": _qualified(
            _number(row["tire_cold_pressure_lr_kpa"], "tire_cold_pressure_lr_kpa"),
            "tire_pressure_rear_left", "LRcoldPressure", scale=1000.0,
            derivation=COLD_PRESSURE_DERIVATION.format(source="LRcoldPressure"),
        ),
        "tire_pressure_rear_right": _qualified(
            _number(row["tire_cold_pressure_rr_kpa"], "tire_cold_pressure_rr_kpa"),
            "tire_pressure_rear_right", "RRcoldPressure", scale=1000.0,
            derivation=COLD_PRESSURE_DERIVATION.format(source="RRcoldPressure"),
        ),
        "air_temperature": _qualified(_number(row["air_temp_c"], "air_temp_c"), "air_temperature", "AirTemp"),
        # Crew-measured track temperature, not a per-point surface temperature.
        "track_temperature": _qualified(_number(row["track_temp_crew_c"], "track_temp_crew_c"), "track_temperature", "TrackTempCrew"),
        # ABS INTERVENTION. The dcABS setting is a different question and is not this concept.
        "abs_active": _qualified(_boolean(row["abs_active"], "abs_active"), "abs_active", "BrakeABSactive"),
        "session_state": _qualified_text(
            _integer(row["session_state"], "session_state"), "session_state", "SessionState",
            "raw-irsdk-sessionstate-value-not-decoded",
        ),
        "incident_state": _qualified_text(
            _integer(row["incident_count"], "incident_count"), "incident_state",
            "PlayerCarMyIncidentCount", "participant-own-incident-count",
        ),
    }
    fields["off_track_state"] = _off_track_state(row, off_track)
    return fields


def _off_track_state(
    row: dict[str, str], off_track: tuple[frozenset[int], frozenset[int], str] | None
) -> dict[str, Any]:
    """Resolve off-track only through a declared enumeration dictionary.

    Without a dictionary, or for a value the dictionary does not define, the concept stays
    unavailable. An unknown simulator value never acquires a meaning here.
    """
    unavailable = {"value": None, "provenance": "unavailable", "unit": CANONICAL_UNITS["off_track_state"]}
    if off_track is None:
        return unavailable
    surface = _integer(row["track_surface"], "track_surface")
    if surface is None:
        return unavailable
    values, known, derivation = off_track
    if surface not in known:
        # A value the declared dictionary does not define never acquires a meaning.
        return unavailable
    return {
        "value": surface in values,
        "provenance": "derived",
        "unit": CANONICAL_UNITS["off_track_state"],
        "derivation": derivation,
    }


def _capabilities(
    manifest: dict[str, Any],
    off_track: tuple[frozenset[int], frozenset[int], str] | None = None,
) -> dict[str, dict[str, Any]]:
    capabilities = {name: {"provenance": "unavailable", "unit": CANONICAL_UNITS[name]} for name in NORMALIZED_CONCEPTS}
    available = {item["name"] for item in manifest["channels"] if item["availability"] == "available"}
    mapping = {
        "timestamp": ("timestamp", "SessionTime"), "brake": ("brake", "Brake"),
        "throttle": ("throttle", "Throttle"), "steering_angle": ("steering_angle", "SteeringWheelAngle"),
        "speed": ("speed", "Speed"), "gear": ("gear", "Gear"), "rpm": ("rpm", "RPM"),
        "longitudinal_acceleration": ("longitudinal_acceleration", "LongAccel"),
        "lateral_acceleration": ("lateral_acceleration", "LatAccel"), "yaw_rate": ("yaw_rate", "YawRate"),
    }
    for channel, (concept, source) in mapping.items():
        if channel in available:
            capabilities[concept] = {"provenance": "measured", "unit": CANONICAL_UNITS[concept], "source_channel": source}
    if "tire_state" in available:
        for concept, source in {
            "tire_temperature_front_left": "LFtempCM", "tire_temperature_front_right": "RFtempCM",
            "tire_temperature_rear_left": "LRtempCM", "tire_temperature_rear_right": "RRtempCM",
        }.items():
            capabilities[concept] = {"provenance": "measured", "unit": CANONICAL_UNITS[concept], "source_channel": source}
        for concept, source in {
            "tire_pressure_front_left": "LFcoldPressure", "tire_pressure_front_right": "RFcoldPressure",
            "tire_pressure_rear_left": "LRcoldPressure", "tire_pressure_rear_right": "RRcoldPressure",
        }.items():
            capabilities[concept] = {
                "provenance": "derived", "unit": CANONICAL_UNITS[concept],
                "derivation": COLD_PRESSURE_DERIVATION.format(source=source),
            }
    if "weather" in available:
        capabilities["air_temperature"] = {
            "provenance": "measured", "unit": CANONICAL_UNITS["air_temperature"],
            "source_channel": "AirTemp",
        }
    if "track_conditions" in available:
        capabilities["track_temperature"] = {
            "provenance": "measured", "unit": CANONICAL_UNITS["track_temperature"],
            "source_channel": "TrackTempCrew",
        }
    if "assists" in available:
        # ABS intervention only. dcABS is a driver setting and is deliberately not this concept,
        # and iRacing exposes no traction-control intervention variable at all.
        capabilities["abs_active"] = {
            "provenance": "measured", "unit": CANONICAL_UNITS["abs_active"],
            "source_channel": "BrakeABSactive",
        }
    if off_track is not None:
        capabilities["off_track_state"] = {
            "provenance": "derived", "unit": CANONICAL_UNITS["off_track_state"],
            "derivation": off_track[2],
        }
    return dict(sorted(capabilities.items()))


def _normalized_records(audit: ResearchBundleAudit, dataset_id: str) -> Iterator[dict[str, Any]]:
    manifest = audit.manifest
    session = manifest["session"]
    source_hash = next(item["sha256"] for item in manifest["files"] if item["path"] == "samples.csv")
    off_track = _off_track_values(_enum_dictionaries(audit.metadata))
    provenance = {
        "source_file": "samples.csv", "source_file_sha256": source_hash,
        "adapter_id": ADAPTER_ID, "adapter_version": ADAPTER_VERSION,
    }
    yield {
        "schema_version": NORMALIZED_RECORD, "record_type": "session", "dataset_id": dataset_id,
        "session_id": session["session_id"], "record_id": f"{session['session_id']}-session",
        "sequence_index": 0, "source_provenance": provenance, "simulator": session["simulator"]["id"],
        "driver_id": session["participant_pseudonym"], "car": session["car"]["id"],
        "track": session["track"]["id"], "layout": session["track"]["layout"], "fields": {},
    }
    known_laps: dict[int, str] = {}
    sequence_index = 1
    observed_origin = _timestamp(session["start_utc"], "$.session.start_utc")
    for row_number, row in _sample_rows(audit.root / "samples.csv"):
        lap_number = _integer(row["lap"], f"samples.csv row {row_number} lap")
        lap_number = 0 if lap_number is None else lap_number
        if lap_number < 0:
            raise ContractValidationError(f"samples.csv row {row_number}: negative lap is unsupported")
        lap_id = known_laps.get(lap_number)
        if lap_id is None:
            lap_id = f"{session['session_id']}-lap-{lap_number}"
            known_laps[lap_number] = lap_id
            yield {
                "schema_version": NORMALIZED_RECORD, "record_type": "lap", "dataset_id": dataset_id,
                "session_id": session["session_id"], "record_id": lap_id, "sequence_index": sequence_index,
                "source_provenance": {**provenance, "row_start": row_number, "row_end": row_number},
                "lap_id": lap_id, "lap_number": lap_number, "fields": {},
            }
            sequence_index += 1
        sample_index = _integer(row["capture_sequence"], "capture_sequence")
        assert sample_index is not None
        yield {
            "schema_version": NORMALIZED_RECORD, "record_type": "telemetry_sample", "dataset_id": dataset_id,
            "session_id": session["session_id"], "record_id": f"{session['session_id']}-sample-{sample_index}",
            "sequence_index": sequence_index,
            "source_provenance": {**provenance, "row_start": row_number, "row_end": row_number, "source_timestamp": row["observed_utc"]},
            "lap_id": lap_id, "sample_index": sample_index, "fields": _fields(row, observed_origin, off_track),
        }
        sequence_index += 1


def ingest_research_bundle(
    root: Path,
    output_dir: Path,
    collection_record_path: Path,
    *,
    project_root: Path | None = None,
    integration_validation: bool = False,
    protocol_snapshot_path: Path | None = None,
    exploratory_intake_path: Path | None = None,
) -> dict[str, Any]:
    with _snapshot_research_bundle(root, temporary_parent=output_dir.resolve().parent) as snapshot:
        return _ingest_research_snapshot(
            snapshot,
            output_dir,
            collection_record_path,
            project_root=project_root,
            integration_validation=integration_validation,
            protocol_snapshot_path=protocol_snapshot_path,
            exploratory_intake_path=exploratory_intake_path,
        )


def _ingest_research_snapshot(
    root: Path,
    output_dir: Path,
    collection_record_path: Path,
    *,
    project_root: Path | None = None,
    integration_validation: bool = False,
    protocol_snapshot_path: Path | None = None,
    exploratory_intake_path: Path | None = None,
) -> dict[str, Any]:
    audit = audit_research_bundle(root)
    collection = validate_collection_record(read_json(collection_record_path))
    _bind_collection(collection, audit)
    code_identity = apex_labs_code_identity(project_root)
    if not integration_validation:
        require_research_code_identity(code_identity, synthetic=collection["synthetic"])
    protocol_context = {"protocol_snapshot": None, "condition_id": None, "block_id": None, "schedule_assignment_id": None}
    protocol_document: dict[str, Any] | None = None
    protocol_bytes: bytes | None = None
    intake_document: dict[str, Any] | None = None
    intake_bytes: bytes | None = None
    if not collection["synthetic"]:
        # Two mutually exclusive doors into real ingestion, and no third one. The
        # PRIMARY door is unchanged: a reviewed protocol freeze bound to the
        # collection record. The EXPLORATORY door admits a session that was
        # collected before any freeze existed, and it costs a hash-bound intake
        # artifact that permanently forfeits confirmatory, causal, primary-estimate
        # and pooling use. Presenting both would be a contradiction — a session
        # cannot simultaneously have been governed by a prospective plan and have
        # predated one — so it is refused rather than silently preferred.
        if protocol_snapshot_path is not None and exploratory_intake_path is not None:
            raise IngestionError(
                "A session cannot be both protocol-governed and retrospectively admitted; "
                "supply either --protocol-snapshot or --exploratory-intake"
            )
        if exploratory_intake_path is not None:
            intake_bytes = exploratory_intake_path.read_bytes()
            intake_document = validate_exploratory_intake(
                parse_json_bytes(intake_bytes, source=str(exploratory_intake_path)))
            _bind_exploratory_intake(intake_document, collection, collection_record_path, audit)
        elif protocol_snapshot_path is None or collection["protocol"] is None:
            raise IngestionError("Real research ingestion requires --protocol-snapshot and a bound collection protocol")
    if not collection["synthetic"] and intake_document is None:
        assert protocol_snapshot_path is not None
        protocol_bytes = protocol_snapshot_path.read_bytes()
        protocol_document = validate_protocol_freeze(
            parse_json_bytes(protocol_bytes, source=str(protocol_snapshot_path)))
        declared = collection["protocol"]
        snapshot_identity = _protocol_snapshot_identity(protocol_document)
        for field, value in snapshot_identity.items():
            if declared[field] != value:
                raise IntegrityError(f"Protocol snapshot does not match collection field {field}")
        protocol_context = {
            "protocol_snapshot": {
                "path": "protocol-freeze.json", "file_sha256": sha256_bytes(protocol_bytes),
                **snapshot_identity,
            },
            "condition_id": audit.metadata["collection"]["condition_id"],
            "block_id": audit.metadata["collection"]["experimental_block_id"],
            "schedule_assignment_id": declared["schedule_assignment_id"],
        }
    nominal_hz = audit.manifest["timing"]["nominal_frequency_hz"]
    expected_period = None if nominal_hz is None else 1.0 / nominal_hz
    temporal_policy = {
        "source_clock": audit.manifest["timing"]["source_clock"],
        "normalized_clock_origin": "session_start",
        "clock_resolution_seconds": audit.manifest["timing"]["resolution_seconds"],
        "duplicate_timestamp_policy": "allow_with_quality_flag",
        "clock_reset_policy": "allow_with_quality_flag",
        "expected_sample_period_seconds": expected_period,
        "gap_tolerance_seconds": None if expected_period is None else expected_period * 2,
        "lap_distance_regression_policy": "allow_with_quality_flag",
        "interpolation": {"performed": False, "method": None, "affected_concepts": []},
    }
    configuration = {
        "source_schema_version": APEX_RESEARCH_EXPORT,
        "profile_id": PROFILE_ID,
        "profile_sha256": PROFILE_SHA256,
        "streaming_csv": True,
        "null_policy": "empty source fields remain unavailable; never coerce to zero",
        "interpolation": False,
    }
    with atomic_output_directory(output_dir, operation="apex-research-ingest", error_type=IngestionError) as staged:
        records_path = staged / "records.jsonl"
        tracker = NormalizedIntegrityTracker(collection["dataset_id"], temporal_policy)
        with records_path.open("xb") as handle:
            for sequence_index, record in enumerate(_normalized_records(audit, collection["dataset_id"])):
                if record["sequence_index"] != sequence_index:
                    raise IntegrityError("Research adapter emitted a non-contiguous normalized sequence")
                validate_normalized_record(record)
                tracker.add(record)
                handle.write(canonical_json_bytes(record))
        integrity = tracker.finalize()
        collection_output = staged / "collection-record.json"
        collection_output.write_bytes(canonical_json_bytes(collection))
        if protocol_document is not None and protocol_bytes is not None:
            (staged / "protocol-freeze.json").write_bytes(protocol_bytes)
        if intake_document is not None and intake_bytes is not None:
            # Verbatim source bytes, not a re-serialization: the intake's own hash is
            # what a reviewer checks, and re-encoding it would break that comparison.
            (staged / "exploratory-intake.json").write_bytes(intake_bytes)
        source_files = [
            {"path": entry["path"], "sha256": entry["sha256"], "role": entry["role"],
             "media_type": "text/csv" if entry["path"].endswith(".csv") else "application/x-ndjson" if entry["path"].endswith(".jsonl") else "application/json"}
            for entry in audit.manifest["files"]
        ]
        if protocol_document is not None:
            source_files.append({"path": "protocol-freeze.json", "sha256": sha256_file(staged / "protocol-freeze.json"), "role": "protocol", "media_type": "application/json"})
        if intake_document is not None:
            source_files.append({"path": "exploratory-intake.json", "sha256": sha256_file(staged / "exploratory-intake.json"), "role": "exploratory-intake", "media_type": "application/json"})
        source_basis = {
            "manifest_sha256": audit.manifest_sha256, "files": source_files,
            "collection_record_sha256": sha256_file(collection_output),
            "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION, "configuration": configuration},
            "normalization_version": NORMALIZATION_VERSION,
        }
        manifest: dict[str, Any] = {
            "schema_version": NORMALIZED_MANIFEST,
            "dataset_id": collection["dataset_id"], "dataset_fingerprint": "0" * 64,
            "synthetic": collection["synthetic"], "created_at": collection["created_at"],
            "source_manifest_sha256": audit.manifest_sha256,
            "canonical_source_manifest_sha256": sha256_bytes(canonical_json_bytes(audit.manifest)),
            "source_fingerprint": sha256_bytes(canonical_json_bytes(source_basis)),
            "normalization_version": NORMALIZATION_VERSION,
            "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION, "configuration": configuration},
            "code_identity": code_identity,
            "preprocessing": {
                "pipeline_id": "apex-research-stream-normalization", "pipeline_version": ADAPTER_VERSION,
                "configuration": configuration, "configuration_sha256": sha256_bytes(canonical_json_bytes(configuration)),
            },
            "collection_context": protocol_context, "temporal_policy": temporal_policy,
            "conventions": CANONICAL_CONVENTIONS, "integrity_summary": integrity,
            "records_file": "records.jsonl", "records_sha256": sha256_file(records_path),
            "record_counts": dict(tracker.counts), "source_files": source_files,
            "capabilities": _capabilities(
                audit.manifest, _off_track_values(_enum_dictionaries(audit.metadata))
            ),
            # Columns carried and validated but deliberately not promoted to a normalized
            # concept in this contract version. Retained as declared source provenance.
            "unknown_source_channels": list(RETAINED_SOURCE_COLUMNS),
            "collection_record": {
                "path": "collection-record.json", "sha256": sha256_file(collection_output),
            },
        }
        # The scientific stratum travels with the dataset from the moment it exists.
        # Synthetic fixtures keep their historic shape and declare nothing.
        if intake_document is not None:
            manifest["scientific_eligibility"] = _exploratory_eligibility(intake_document)
            manifest["exploratory_intake"] = {
                "path": "exploratory-intake.json",
                "sha256": sha256_file(staged / "exploratory-intake.json"),
            }
        elif protocol_document is not None:
            manifest["scientific_eligibility"] = _primary_eligibility(protocol_document)
        manifest["dataset_fingerprint"] = build_dataset_fingerprint(normalized_dataset_fingerprint_basis(manifest))
        validate_normalized_manifest(manifest)
        write_json(staged / "manifest.json", manifest)
    return manifest
