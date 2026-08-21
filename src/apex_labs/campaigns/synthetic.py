"""Deterministic synthetic campaigns with known answers.

Each campaign fabricates a tiny corpus whose correct interpretation is obvious
by construction, materializes it through the real ingestion path, and drives the
real evidence and inference path over it. The campaigns prove that the machinery
behaves as designed. They prove nothing whatsoever about driving.

Campaign specifications are small, checked-in, and readable on purpose: a
reviewer can see the fabricated numbers and confirm the expected answer by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_labs.errors import ContractValidationError, EvidenceError
from apex_labs.ingestion import ingest_dataset
from apex_labs.io import read_json, write_json
from apex_labs.provenance import sha256_file
from apex_labs.schemas.validation import _enum, _fail, _keys, _list, _object, _string

_COLUMNS = ["time_s", "lap", "lap_distance_m", "speed_mps", "brake_fraction", "lap_valid", "off_track"]
_COLUMN_MAPPING = {
    "time_s": {"concept": "timestamp", "provenance": "measured", "unit": "s"},
    "lap_distance_m": {"concept": "lap_distance", "provenance": "measured", "unit": "m"},
    "speed_mps": {"concept": "speed", "provenance": "measured", "unit": "m/s"},
    "brake_fraction": {"concept": "brake", "provenance": "measured", "unit": "ratio"},
    "lap_valid": {"concept": "lap_valid", "provenance": "measured", "unit": "boolean"},
    "off_track": {"concept": "off_track_state", "provenance": "measured", "unit": "boolean"},
}
_TEMPORAL_POLICY = {
    "source_clock": "synthetic_session_relative_seconds",
    "normalized_clock_origin": "session_start",
    "clock_resolution_seconds": 0.1,
    "duplicate_timestamp_policy": "reject",
    "clock_reset_policy": "reject",
    "expected_sample_period_seconds": None,
    "gap_tolerance_seconds": None,
    "lap_distance_regression_policy": "reject",
    "interpolation": {"performed": False, "method": None, "affected_concepts": []},
}
_CONVENTIONS = {
    "vehicle_frame": "right_handed_x_forward_y_left_z_up",
    "steering_sign": "positive_left",
    "yaw_rate_sign": "positive_counterclockwise_viewed_from_above",
    "lateral_acceleration_sign": "positive_left",
    "longitudinal_acceleration_sign": "positive_forward",
    "track_position_frame": "right_handed_adapter_normalized",
}
_OUTCOMES = {"analysed", "evidence_refused"}


def validate_campaign_spec(value: Any) -> dict[str, Any]:
    """Validate a campaign specification; specs are fabricated fixtures, not evidence."""
    obj = _object(value, "$")
    _keys(
        obj,
        "$",
        required={
            "campaign_id", "title", "purpose", "synthetic", "outcome", "expectations",
            "protocol_freeze", "segment", "metric", "evidence_definition", "analysis_definition",
            "session", "profile", "datasets",
        },
        optional={"replication_analysis_definition"},
    )
    _string(obj["campaign_id"], "$.campaign_id")
    _string(obj["title"], "$.title")
    _string(obj["purpose"], "$.purpose")
    if obj["synthetic"] is not True:
        _fail("$.synthetic", "campaigns fabricate their evidence and are always synthetic")
    _enum(obj["outcome"], _OUTCOMES, "$.outcome")
    _object(obj["expectations"], "$.expectations")
    for name in ("protocol_freeze", "segment", "metric", "evidence_definition", "analysis_definition"):
        _string(obj[name], f"$.{name}")
    if "replication_analysis_definition" in obj:
        _string(obj["replication_analysis_definition"], "$.replication_analysis_definition")
    session = _object(obj["session"], "$.session")
    _keys(session, "$.session", required={"simulator", "driver_id", "car", "track", "layout"})
    profile = _object(obj["profile"], "$.profile")
    _keys(
        profile,
        "$.profile",
        required={"outside_before_m", "segment_distances_m", "base_speed_mps", "base_brake", "outside_after_m"},
    )
    distances = _list(profile["segment_distances_m"], "$.profile.segment_distances_m", nonempty=True)
    for name in ("base_speed_mps", "base_brake"):
        if len(_list(profile[name], f"$.profile.{name}", nonempty=True)) != len(distances):
            _fail(f"$.profile.{name}", "must supply one value per fabricated segment distance")
    datasets = _list(obj["datasets"], "$.datasets", nonempty=True)
    for index, item in enumerate(datasets):
        path = f"$.datasets[{index}]"
        dataset = _object(item, path)
        _keys(
            dataset,
            path,
            required={"dataset_id", "session_id", "condition_id", "block_id", "laps"},
            optional={
                "layout", "car", "track", "simulator", "driver_id",
                "configuration_identity", "product_build_identity",
            },
        )
        for name in ("dataset_id", "session_id", "condition_id", "block_id"):
            _string(dataset[name], f"{path}.{name}")
        for name in ("configuration_identity", "product_build_identity"):
            if name in dataset and dataset[name] is not None:
                _string(dataset[name], f"{path}.{name}")
        laps = _list(dataset["laps"], f"{path}.laps", nonempty=True)
        for lap_index, lap in enumerate(laps):
            lap_path = f"{path}.laps[{lap_index}]"
            entry = _object(lap, lap_path)
            _keys(
                entry,
                lap_path,
                required={"lap"},
                optional={"speed_offset", "brake_release_index", "valid", "off_track", "speed_unavailable", "samples", "speed_absolute"},
            )
    return obj


def _lap_rows(profile: dict[str, Any], lap: dict[str, Any], lap_number: int, start_time: float) -> list[list[str]]:
    """Fabricate one lap as explicit CSV cells.

    An empty speed cell becomes an explicitly unavailable value downstream. A
    fabricated zero stays a measured zero. The two are different facts and the
    campaigns rely on them staying different.
    """
    distances = list(profile["outside_before_m"]) + list(profile["segment_distances_m"]) + list(profile["outside_after_m"])
    inside_start = len(profile["outside_before_m"])
    inside_end = inside_start + len(profile["segment_distances_m"])
    limit = lap.get("samples")
    speed_offset = lap.get("speed_offset", 0.0)
    absolute = lap.get("speed_absolute")
    release_index = lap.get("brake_release_index")
    valid = "true" if lap.get("valid", True) else "false"
    off_track = "true" if lap.get("off_track", False) else "false"
    unavailable = lap.get("speed_unavailable", False)

    rows: list[list[str]] = []
    for index, distance in enumerate(distances):
        inside = inside_start <= index < inside_end
        position = index - inside_start
        if inside and limit is not None and position >= limit:
            continue
        if inside:
            if absolute is not None:
                speed = absolute[position]
            else:
                speed = profile["base_speed_mps"][position] + speed_offset
            brake = (
                profile["base_brake"][position]
                if release_index is None
                else (1.0 if position <= release_index else 0.0)
            )
        else:
            speed = 60.0 + speed_offset
            brake = 0.0
        speed_cell = "" if (inside and unavailable) else f"{speed:.4f}"
        rows.append(
            [
                f"{start_time + index * 0.1:.4f}",
                str(lap_number),
                f"{distance:.4f}",
                speed_cell,
                f"{brake:.4f}",
                valid,
                off_track,
            ]
        )
    return rows


def _write_dataset(
    spec: dict[str, Any],
    dataset: dict[str, Any],
    freeze: dict[str, Any],
    freeze_source: Path,
    directory: Path,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    freeze_path = directory / "protocol.freeze.json"
    write_json(freeze_path, freeze)
    configuration_path = directory / "configuration-setup.json"
    configuration_identity = dataset.get(
        "configuration_identity", "synthetic-fixed-setup-v1"
    )
    if configuration_identity is not None:
        write_json(
            configuration_path,
            {
                "classification": "synthetic_demo_only",
                "configuration_identity": configuration_identity,
                "description": "Fabricated fixed setup identity; not a real vehicle configuration.",
            },
        )
    product_build_path = directory / "product-build.json"
    product_build_identity = dataset.get(
        "product_build_identity", "synthetic-campaign-generator-v1"
    )
    if product_build_identity is not None:
        write_json(
            product_build_path,
            {
                "classification": "synthetic_demo_only",
                "product_build_identity": product_build_identity,
                "description": "Fabricated build identity; not an Apex Sim Coach product build.",
            },
        )

    session = {**spec["session"], **{key: dataset[key] for key in ("simulator", "driver_id", "car", "track", "layout") if key in dataset}}
    rows: list[list[str]] = []
    start_time = 0.0
    for lap in dataset["laps"]:
        lap_rows = _lap_rows(spec["profile"], lap, lap["lap"], start_time)
        rows.extend(lap_rows)
        start_time += len(lap_rows) * 0.1 + 10.0
    telemetry_path = directory / "corner-samples.csv"
    telemetry_path.write_text(
        "\n".join([",".join(_COLUMNS)] + [",".join(row) for row in rows]) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = {
        "schema_version": "apex-labs.dataset-manifest/v1",
        "dataset_id": dataset["dataset_id"],
        "title": f"Fabricated campaign block {dataset['block_id']} for {spec['campaign_id']}",
        "description": (
            "Hand-specified fabricated values generated from a checked-in campaign specification. "
            "There is no human, simulator, or product source behind any number in this file."
        ),
        "created_at": "2026-08-20T00:00:00Z",
        "synthetic": True,
        "data_classification": "synthetic",
        "driver_identifiers": "none",
        "simulator": session["simulator"],
        "privacy": {
            "participant_data": False,
            "pseudonymized": False,
            "direct_identifiers_present": False,
            "pseudonymization_method": None,
            "consent_or_authority": "not_applicable_synthetic_fixture",
            "retention_policy": "generated_into_a_temporary_workspace_and_never_tracked",
        },
        "source": {
            "description": "Deterministically generated from a checked-in synthetic campaign specification.",
            "format": "text/csv",
        },
        "tags": ["synthetic", "campaign", "not-scientific-evidence"],
        "collection_context": {
            "protocol_snapshot": {
                "path": "protocol.freeze.json",
                "file_sha256": sha256_file(freeze_path),
                "freeze_id": freeze["freeze_id"],
                "freeze_sha256": freeze["freeze_sha256"],
                "experiment_id": freeze["protocol_id"],
                "experiment_version": freeze["protocol_version"],
                "schedule_id": freeze["randomization"]["schedule_id"],
                "schedule_sha256": freeze["randomization"]["schedule_sha256"],
            },
            "condition_id": dataset["condition_id"],
            "block_id": dataset["block_id"],
            "schedule_assignment_id": dataset["block_id"],
        },
        "source_files": [
            {
                "path": "corner-samples.csv",
                "sha256": sha256_file(telemetry_path),
                "role": "telemetry",
                "media_type": "text/csv",
            },
            {
                "path": "protocol.freeze.json",
                "sha256": sha256_file(freeze_path),
                "role": "protocol",
                "media_type": "application/json",
            },
            *(
                [{
                    "path": "configuration-setup.json",
                    "sha256": sha256_file(configuration_path),
                    "role": "metadata",
                    "media_type": "application/json",
                }]
                if configuration_identity is not None
                else []
            ),
            *(
                [{
                    "path": "product-build.json",
                    "sha256": sha256_file(product_build_path),
                    "role": "metadata",
                    "media_type": "application/json",
                }]
                if product_build_identity is not None
                else []
            ),
        ],
        "adapter": {
            "id": "tabular-csv",
            "version": "1.1.0",
            "configuration": {
                "telemetry_file": "corner-samples.csv",
                "delimiter": ",",
                "lap_number_column": "lap",
                "session": {
                    "session_id": dataset["session_id"],
                    "driver_id": session["driver_id"],
                    "car": session["car"],
                    "track": session["track"],
                    "layout": session["layout"],
                },
                "column_mapping": _COLUMN_MAPPING,
                "temporal_policy": _TEMPORAL_POLICY,
                "conventions": _CONVENTIONS,
            },
        },
    }
    manifest_path = directory / "dataset.manifest.json"
    write_json(manifest_path, manifest)
    _ = freeze_source
    return manifest_path


def materialize(spec: dict[str, Any], workspace: Path, root: Path) -> list[Path]:
    """Generate and ingest every fabricated dataset a campaign declares.

    Generated bytes live only in the caller's workspace. Nothing fabricated here
    is ever written into the repository.
    """
    spec = validate_campaign_spec(spec)
    freeze_source = root / "research" / "campaigns" / "frozen" / f"{spec['protocol_freeze']}.freeze.json"
    freeze = read_json(freeze_source)
    normalized_dirs: list[Path] = []
    for dataset in spec["datasets"]:
        source_dir = workspace / "source" / dataset["dataset_id"]
        manifest_path = _write_dataset(spec, dataset, freeze, freeze_source, source_dir)
        normalized = workspace / "normalized" / dataset["dataset_id"]
        ingest_dataset(manifest_path, normalized, project_root=root)
        normalized_dirs.append(normalized)
    return normalized_dirs


def campaign_paths(spec: dict[str, Any], root: Path) -> dict[str, Path]:
    """Resolve every checked-in artifact a campaign binds."""
    return {
        "protocol_freeze": root / "research" / "campaigns" / "frozen" / f"{spec['protocol_freeze']}.freeze.json",
        "segment": root / "research" / "segments" / f"{spec['segment']}.json",
        "metric": root / "research" / "metrics" / f"{spec['metric']}.json",
        "evidence_definition": root / "research" / "evidence-sets" / f"{spec['evidence_definition']}.json",
        "analysis_definition": root / "research" / "analyses" / f"{spec['analysis_definition']}.json",
    }


__all__ = ["campaign_paths", "materialize", "validate_campaign_spec"]

# Re-exported for callers that want the refusal types without importing errors directly.
REFUSAL_ERRORS = (EvidenceError, ContractValidationError)
