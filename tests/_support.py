from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apex_labs.io import read_json, write_json  # noqa: E402
from apex_labs.provenance import sha256_file  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "synthetic_demo"
DATASET_MANIFEST = FIXTURE_DIR / "dataset.manifest.json"
FROZEN_PROTOCOL = FIXTURE_DIR / "protocol.freeze.json"
DEMO_PROTOCOL = ROOT / "protocols" / "synthetic-mechanics-demo.json"
CAMPAIGN_PROTOCOL = ROOT / "protocols" / "first-controlled-campaign.json"
FINDING = ROOT / "research" / "findings" / "inconclusive" / "synthetic-mechanics-demo.json"
VALIDATION = ROOT / "research" / "validations" / "synthetic-mechanics-demo-validation.json"
EXPORT_DEFINITION = ROOT / "product-exports" / "synthetic-demo-export-definition.json"


def copy_fixture(destination: Path) -> Path:
    shutil.copytree(FIXTURE_DIR, destination)
    return destination / "dataset.manifest.json"


def update_telemetry_hash(manifest_path: Path) -> None:
    manifest = read_json(manifest_path)
    telemetry = next(item for item in manifest["source_files"] if item["role"] == "telemetry")
    telemetry["sha256"] = sha256_file(manifest_path.parent / telemetry["path"])
    write_json(manifest_path, manifest)


def all_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def run_cli(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "apex_labs", *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def temporal_policy() -> dict[str, Any]:
    return copy.deepcopy(
        read_json(DATASET_MANIFEST)["adapter"]["configuration"]["temporal_policy"]
    )


def provenance() -> dict[str, Any]:
    return {
        "source_file": "synthetic.csv",
        "source_file_sha256": "1" * 64,
        "adapter_id": "test-adapter",
        "adapter_version": "1.0.0",
    }


def qualified(
    value: Any,
    unit: str,
    *,
    concept: str = "value",
    reference: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": value,
        "provenance": "unavailable" if value is None else "measured",
        "unit": unit,
        "source_channel": concept,
    }
    if reference is not None:
        result["reference"] = reference
    return result


def base_record_stream() -> list[dict[str, Any]]:
    common = {
        "schema_version": "apex-labs.normalized-record/v1",
        "dataset_id": "integrity-dataset",
        "session_id": "session-01",
        "source_provenance": provenance(),
    }
    return [
        {
            **common,
            "record_type": "session",
            "record_id": "session-01.record",
            "sequence_index": 0,
            "simulator": "synthetic",
            "driver_id": "driver-01",
            "car": "car-01",
            "track": "track-01",
            "layout": "layout-01",
            "fields": {},
        },
        {
            **common,
            "record_type": "lap",
            "record_id": "lap-01.record",
            "sequence_index": 1,
            "lap_id": "lap-01",
            "lap_number": 1,
            "fields": {},
        },
        {
            **common,
            "record_type": "segment",
            "record_id": "segment-01.record",
            "sequence_index": 2,
            "lap_id": "lap-01",
            "segment_id": "segment-01",
            "segment_kind": "corner",
            "label": "Synthetic segment",
            "fields": {},
        },
        {
            **common,
            "record_type": "telemetry_sample",
            "record_id": "sample-00.record",
            "sequence_index": 3,
            "lap_id": "lap-01",
            "segment_id": "segment-01",
            "sample_index": 0,
            "fields": {
                "timestamp": qualified(
                    0.0, "s", concept="time", reference="normalized_monotonic_time"
                ),
                "lap_distance": qualified(0.0, "m", concept="distance"),
                "brake": qualified(0.0, "ratio", concept="brake"),
            },
        },
        {
            **common,
            "record_type": "driver_input_event",
            "record_id": "event-00.record",
            "sequence_index": 4,
            "lap_id": "lap-01",
            "segment_id": "segment-01",
            "event_type": "brake-onset",
            "fields": {
                "timestamp": qualified(
                    0.0, "s", concept="time", reference="normalized_monotonic_time"
                )
            },
        },
    ]
