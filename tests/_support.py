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


CAMPAIGN_DIR = ROOT / "research" / "campaigns"
FROZEN_PROTOCOL_DIR = CAMPAIGN_DIR / "frozen"
SEGMENT_DIR = ROOT / "research" / "segments"
EVIDENCE_DEFINITION_DIR = ROOT / "research" / "evidence-sets"
ANALYSIS_DIR = ROOT / "research" / "analyses"
METRIC_DIR = ROOT / "research" / "metrics"
DEMO_CAMPAIGN = "clear-paired-improvement"
BUILT_AT = "2026-08-20T00:00:00Z"


def campaign_spec_path(campaign_id: str = DEMO_CAMPAIGN) -> Path:
    return CAMPAIGN_DIR / f"{campaign_id}.campaign.json"


def prepared_campaign(workspace: Path, campaign_id: str = DEMO_CAMPAIGN) -> dict[str, Any]:
    """Materialize, ingest, and build one campaign's evidence in a workspace."""
    from apex_labs.campaigns import campaign_paths, materialize
    from apex_labs.evidence import build_evidence_set

    spec = read_json(campaign_spec_path(campaign_id))
    paths = campaign_paths(spec, ROOT)
    dataset_dirs = materialize(spec, workspace, ROOT)
    evidence_dir = workspace / "evidence"
    evidence = build_evidence_set(
        paths["evidence_definition"],
        paths["segment"],
        paths["protocol_freeze"],
        paths["metric"],
        dataset_dirs,
        evidence_dir,
        built_at=BUILT_AT,
        project_root=ROOT,
    )
    return {
        "spec": spec,
        "paths": paths,
        "dataset_dirs": dataset_dirs,
        "evidence_dir": evidence_dir,
        "evidence": evidence,
    }


def prepared_run(prepared: dict[str, Any], workspace: Path, run_id: str = "support-run") -> dict[str, Any]:
    from apex_labs.analysis import run_inferential_analysis

    run_dir = workspace / run_id
    run = run_inferential_analysis(
        prepared["paths"]["analysis_definition"],
        prepared["evidence_dir"],
        prepared["paths"]["protocol_freeze"],
        run_dir,
        run_id=run_id,
        created_at=BUILT_AT,
        project_root=ROOT,
    )
    return {"run_dir": run_dir, "run": run}


def synthetic_hypothesis(hypothesis_id: str = "support-hypothesis") -> dict[str, Any]:
    return {
        "schema_version": "apex-labs.hypothesis/v1",
        "hypothesis_id": hypothesis_id,
        "version": "1.0.0",
        "created_at": BUILT_AT,
        "synthetic": True,
        "title": "Fabricated support hypothesis",
        "statement": "Fabricated intervention laps show a higher segment minimum speed.",
        "null_statement": "Fabricated intervention laps show no difference in segment minimum speed.",
        "scientific_question": "Does the lifecycle behave as declared?",
        "scope": "session_specific",
        "generation": {
            "source": "deterministic_algorithm",
            "actor": "apex-labs.tests",
            "detail": "Written by the test suite to exercise the lifecycle.",
            "is_evidence": False,
        },
        "hypothesis_sha256": "0" * 64,
    }
