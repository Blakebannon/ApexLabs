from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, run_cli

from apex_labs.errors import ApexLabsError, ContractValidationError, IntegrityError
from apex_labs.ingestion.apex_research import (
    PROFILE_SHA256,
    SAMPLE_HEADERS,
    ingest_research_bundle,
    inspect_research_bundle,
    validate_research_bundle,
)
from apex_labs.ingestion.service import inspect_dataset
from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.schemas import (
    validate_research_export_manifest,
    validate_research_recorder_manifest,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _line(values: dict[str, object | None]) -> str:
    fields = []
    for name in SAMPLE_HEADERS:
        value = values.get(name)
        if value is None:
            fields.append("")
        elif isinstance(value, bool):
            fields.append("true" if value else "false")
        else:
            fields.append(str(value))
    return ",".join(fields)


def build_bundle(root: Path) -> Path:
    root.mkdir()
    manifest = read_json(ROOT / "contracts" / "examples" / "apex-research-session-export-v1.example.json")
    manifest["session"].update({
        "session_id": "synthetic-m54r-session",
        "participant_pseudonym": "synthetic-participant",
        "simulator": {"id": "iracing", "version": "synthetic-sdk"},
        "car": {"id": "synthetic-car"},
        "track": {"id": "synthetic-track", "layout": "synthetic-layout"},
        "start_utc": "2000-01-01T00:00:00Z", "end_utc": "2000-01-01T00:00:01Z",
    })
    if not any(item["name"] == "traffic" for item in manifest["channels"]):
        manifest["channels"].insert(-1, {
            "name": "traffic", "availability": "unavailable", "provenance": "unavailable",
            "unit": None, "axis_and_sign": None, "missing_value": "explicitly unavailable",
        })
    configuration = canonical_json_bytes({
        "schema_version": "apex-research-configuration-setup/1.0.0",
        "setup": {"availability": "unavailable", "provenance": "unavailable", "value": None},
        "recorder_configuration": {"queue_capacity": 16},
    })
    samples = (
        ",".join(SAMPLE_HEADERS) + "\n" +
        _line({
            "capture_sequence": 0, "simulator_tick": 100,
            "observed_utc": "2000-01-01T00:00:00Z", "session_time_s": 0,
            "lap": 1, "lap_time_s": 0, "lap_distance_fraction": 0,
            "brake": None, "throttle": 0.5, "steering_angle_rad": 0,
            "speed_mps": 20, "gear": 3, "rpm": 4000, "read_error_count": 0,
        }) + "\n" +
        _line({
            "capture_sequence": 1, "simulator_tick": 101,
            "observed_utc": "2000-01-01T00:00:00.016Z", "session_time_s": 0.016,
            "lap": 1, "lap_time_s": 0.016, "lap_distance_fraction": 0.016,
            "brake": 0, "throttle": 0.5, "steering_angle_rad": 0,
            "speed_mps": 20, "gear": 3, "rpm": 4000, "read_error_count": 0,
        }) + "\n"
    ).encode("utf-8")
    events = b"".join(canonical_json_bytes(event) for event in (
        {
            "schema_version": "apex-research-event/1.0.0", "sequence": 0,
            "observed_utc": "2000-01-01T00:00:00Z", "session_time_s": None,
            "kind": "collection-condition",
            "data": {"block_id": "synthetic-block", "condition_id": "synthetic-disabled-control", "coaching_state": "disabled", "protocol_identity": "synthetic-protocol-freeze"},
        },
        {
            "schema_version": "apex-research-event/1.0.0", "sequence": 1,
            "observed_utc": "2000-01-01T00:00:01Z", "session_time_s": None,
            "kind": "coaching-disabled-control",
            "data": {"authorization_count": 0, "delivery_receipt_count": 0, "coaching_state": "disabled"},
        },
    ))
    metadata = canonical_json_bytes({
        "schema_version": "apex-research-recorder-metadata/1.0.0",
        "contract": {
            "schema_version": "apex-research-session-export/1.0.0",
            "schema_sha256": "5432cf9034b72bc8dc9c99c45c76dac07e320036460b0a7e4092c029bbf698b6",
            "profile_id": "apex-labs-research-recorder-profile/1.0.0",
            "profile_sha256": PROFILE_SHA256,
        },
        "recorder": {"product_version": "synthetic", "source_revision": "1" * 40, "local_only": True, "automatic_upload": False},
        "collection": {"protocol_identity": "synthetic-protocol-freeze", "experimental_block_id": "synthetic-block", "condition_id": "synthetic-disabled-control", "coaching_state": "disabled"},
        "metrics": {"samples_written": 2, "samples_dropped_by_backpressure": 0, "events_written": 2, "events_dropped": 0, "peak_backlog": 2},
        "privacy": {
            "classification": "synthetic", "direct_identifiers_recorded": False,
            "raw_driver_user_id_recorded": False, "raw_subsession_id_recorded": False,
            "pseudonym_key_material_recorded": False, "absolute_paths_recorded": False,
        },
    })
    payloads = {
        "samples.csv": (samples, "timestamped-samples"),
        "events.jsonl": (events, "session-events"),
        "configuration-setup.json": (configuration, "configuration-setup-declaration"),
        "recorder-metadata.json": (metadata, "recorder-provenance-and-metrics"),
    }
    for name, (content, _) in payloads.items():
        (root / name).write_bytes(content)
    manifest["collection"]["configuration_setup_hash"] = _sha(configuration)
    manifest["files"] = [
        {"path": name, "size_bytes": len(content), "sha256": _sha(content), "role": role}
        for name, (content, role) in payloads.items()
    ]
    (root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    (root / "COMPLETE").write_bytes(
        f"apex-research-complete/v1\n{_sha((root / 'manifest.json').read_bytes())}\n".encode("utf-8")
    )
    return root


def collection_record(bundle: Path, destination: Path) -> Path:
    record = read_json(ROOT / "tests" / "fixtures" / "apex_session_export_v1" / "collection-record.json")
    record["dataset_id"] = "synthetic-m54r-dataset"
    record["participant"]["pseudonymous_participant_id"] = "synthetic-participant"
    record["source_bundle"] = {
        "schema_version": "apex-research-session-export/1.0.0",
        "sha256": _sha((bundle / "manifest.json").read_bytes()),
    }
    record["session_identity"] = {
        "simulator": "iracing", "car": "synthetic-car", "track": "synthetic-track",
        "layout": "synthetic-layout", "confirmation_method": "synthetic recorder fixture",
    }
    destination.write_bytes(canonical_json_bytes(record))
    return destination


def rebind(bundle: Path) -> None:
    manifest = read_json(bundle / "manifest.json")
    manifest["files"] = [
        {**entry, "size_bytes": (bundle / entry["path"]).stat().st_size, "sha256": _sha((bundle / entry["path"]).read_bytes())}
        for entry in manifest["files"]
    ]
    manifest["collection"]["configuration_setup_hash"] = _sha((bundle / "configuration-setup.json").read_bytes())
    (bundle / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    (bundle / "COMPLETE").write_bytes(
        f"apex-research-complete/v1\n{_sha((bundle / 'manifest.json').read_bytes())}\n".encode("utf-8")
    )


class ApexResearchAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = build_bundle(self.root / "bundle")
        self.collection = collection_record(self.bundle, self.root / "collection-record.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_v1_legacy_manifest_remains_valid_while_recorder_profile_requires_traffic(self) -> None:
        legacy = read_json(ROOT / "contracts" / "examples" / "apex-research-session-export-v1.example.json")
        legacy["channels"] = [item for item in legacy["channels"] if item["name"] != "traffic"]
        validate_research_export_manifest(legacy)
        with self.assertRaises(ContractValidationError):
            validate_research_recorder_manifest(legacy)
        recorder = read_json(self.bundle / "manifest.json")
        validate_research_export_manifest(recorder)
        validate_research_recorder_manifest(recorder)
        recorder["channels"].append({
            "name": "invented", "availability": "unavailable", "provenance": "unavailable",
            "unit": None, "axis_and_sign": None, "missing_value": "unavailable",
        })
        with self.assertRaises(ContractValidationError):
            validate_research_export_manifest(recorder)
        duplicate = read_json(self.bundle / "manifest.json")
        duplicate["files"].append(copy.deepcopy(duplicate["files"][0]))
        with self.assertRaises(ContractValidationError):
            validate_research_recorder_manifest(duplicate)

    def test_valid_bundle_collection_binding_and_null_is_not_zero(self) -> None:
        report = validate_research_bundle(self.bundle, self.collection)
        self.assertTrue(report["valid"])
        self.assertEqual(report["sample_count"], 2)
        output = self.root / "normalized"
        manifest = ingest_research_bundle(self.bundle, output, self.collection, project_root=ROOT)
        records = [json.loads(line) for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        samples = [record for record in records if record["record_type"] == "telemetry_sample"]
        self.assertIsNone(samples[0]["fields"]["brake"]["value"])
        self.assertEqual(samples[0]["fields"]["brake"]["provenance"], "unavailable")
        self.assertEqual(samples[1]["fields"]["brake"]["value"], 0.0)
        self.assertEqual(manifest["record_counts"], {"session": 1, "lap": 1, "telemetry_sample": 2})
        inspected = inspect_dataset(output / "manifest.json")
        self.assertEqual(inspected["integrity"], "verified")

    def test_ingestion_is_deterministic_and_one_way(self) -> None:
        first = ingest_research_bundle(self.bundle, self.root / "first", self.collection, project_root=ROOT)
        second = ingest_research_bundle(self.bundle, self.root / "second", self.collection, project_root=ROOT)
        self.assertEqual(first, second)
        self.assertEqual((self.root / "first" / "records.jsonl").read_bytes(), (self.root / "second" / "records.jsonl").read_bytes())
        self.assertFalse(any("ApexTrackCoach" in str(path) for path in (self.root / "first").rglob("*")))

    def test_hash_channel_path_unavailable_and_completion_corruption_are_rejected(self) -> None:
        cases = []
        for name in ("hash", "channel", "path", "unavailable", "marker", "privacy"):
            target = self.root / name
            shutil.copytree(self.bundle, target)
            cases.append((name, target))
        (cases[0][1] / "samples.csv").write_bytes((cases[0][1] / "samples.csv").read_bytes() + b"x")
        manifest = read_json(cases[1][1] / "manifest.json")
        manifest["channels"] = [item for item in manifest["channels"] if item["name"] != "traffic"]
        (cases[1][1] / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        (cases[1][1] / "COMPLETE").write_bytes(f"apex-research-complete/v1\n{_sha((cases[1][1] / 'manifest.json').read_bytes())}\n".encode("utf-8"))
        manifest = read_json(cases[2][1] / "manifest.json")
        manifest["files"][0]["path"] = "../samples.csv"
        (cases[2][1] / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        (cases[2][1] / "COMPLETE").write_bytes(f"apex-research-complete/v1\n{_sha((cases[2][1] / 'manifest.json').read_bytes())}\n".encode("utf-8"))
        samples = (cases[3][1] / "samples.csv").read_text(encoding="utf-8").splitlines()
        columns = samples[1].split(",")
        columns[SAMPLE_HEADERS.index("longitudinal_acceleration_mps2")] = "0"
        samples[1] = ",".join(columns)
        (cases[3][1] / "samples.csv").write_text("\n".join(samples) + "\n", encoding="utf-8")
        rebind(cases[3][1])
        (cases[4][1] / "COMPLETE").write_text("not-complete\n", encoding="utf-8")
        manifest = read_json(cases[5][1] / "manifest.json")
        manifest["session"]["participant_pseudonym"] = "iracing-123"
        (cases[5][1] / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        (cases[5][1] / "COMPLETE").write_bytes(
            f"apex-research-complete/v1\n{_sha((cases[5][1] / 'manifest.json').read_bytes())}\n".encode("utf-8")
        )
        for name, target in cases:
            with self.subTest(name=name), self.assertRaises(ApexLabsError):
                inspect_research_bundle(target)

    def test_cli_inspect_validate_and_ingest(self) -> None:
        inspected = run_cli("apex-research", "inspect", str(self.bundle))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        validated = run_cli("apex-research", "validate", str(self.bundle), "--collection-record", str(self.collection))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        ingested = run_cli("apex-research", "ingest", str(self.bundle), "--collection-record", str(self.collection), "--output", str(self.root / "cli-output"))
        self.assertEqual(ingested.returncode, 0, ingested.stderr)
        self.assertEqual(json.loads(ingested.stdout)["direction"], "research-bundle-to-labs-only")


if __name__ == "__main__":
    unittest.main()
