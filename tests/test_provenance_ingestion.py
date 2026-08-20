from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import (
    DATASET_MANIFEST,
    FIXTURE_DIR,
    ROOT,
    all_files,
    copy_fixture,
    update_telemetry_hash,
)

from apex_labs.errors import IngestionError, IntegrityError
from apex_labs.ingestion import ingest_dataset, inspect_dataset
from apex_labs.io import read_json, write_json
from apex_labs.provenance import (
    build_dataset_fingerprint,
    dataset_fingerprint,
    normalized_dataset_fingerprint_basis,
    sha256_file,
    snapshot_source_files,
)
from apex_labs.schemas import validate_dataset_manifest


class ProvenanceAndIngestionTests(unittest.TestCase):
    def test_identical_inputs_in_separate_directories_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first_manifest = copy_fixture(base / "source-a")
            second_manifest = copy_fixture(base / "source-b")
            first_output = base / "normalized-a"
            second_output = base / "normalized-b"
            first = ingest_dataset(first_manifest, first_output, project_root=ROOT)
            second = ingest_dataset(second_manifest, second_output, project_root=ROOT)
            self.assertEqual(first["dataset_fingerprint"], second["dataset_fingerprint"])
            self.assertEqual(all_files(first_output), all_files(second_output))
            leaked = str(base).encode("utf-8")
            self.assertTrue(all(leaked not in content for content in all_files(first_output).values()))

    def test_declaration_order_does_not_change_scientific_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first_manifest = copy_fixture(base / "first")
            second_manifest = copy_fixture(base / "second")
            second = read_json(second_manifest)
            second["source_files"].reverse()
            second["tags"].reverse()
            write_json(second_manifest, second)
            first_result = ingest_dataset(first_manifest, base / "out-first", project_root=ROOT)
            second_result = ingest_dataset(second_manifest, base / "out-second", project_root=ROOT)
            self.assertEqual(
                first_result["dataset_fingerprint"], second_result["dataset_fingerprint"]
            )
            self.assertEqual(
                (base / "out-first" / "records.jsonl").read_bytes(),
                (base / "out-second" / "records.jsonl").read_bytes(),
            )

    def test_source_configuration_schema_and_output_changes_change_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            baseline_manifest = copy_fixture(base / "baseline")
            baseline = ingest_dataset(baseline_manifest, base / "out-baseline", project_root=ROOT)

            source_manifest = copy_fixture(base / "source-change")
            telemetry = source_manifest.parent / "telemetry.csv"
            telemetry.write_text(
                telemetry.read_text(encoding="utf-8").replace("31.0", "31.1", 1),
                encoding="utf-8",
            )
            update_telemetry_hash(source_manifest)
            source_changed = ingest_dataset(source_manifest, base / "out-source", project_root=ROOT)
            self.assertNotEqual(
                baseline["dataset_fingerprint"], source_changed["dataset_fingerprint"]
            )

            config_manifest = copy_fixture(base / "config-change")
            config = read_json(config_manifest)
            config["adapter"]["configuration"]["session"]["track"] = "synthetic-track-b"
            write_json(config_manifest, config)
            config_changed = ingest_dataset(config_manifest, base / "out-config", project_root=ROOT)
            self.assertNotEqual(
                baseline["dataset_fingerprint"], config_changed["dataset_fingerprint"]
            )

            schema_basis = normalized_dataset_fingerprint_basis(copy.deepcopy(baseline))
            schema_basis["code_identity"]["schema_sha256"][
                "contracts/v1/finding.schema.json"
            ] = "0" * 64
            self.assertNotEqual(
                baseline["dataset_fingerprint"], build_dataset_fingerprint(schema_basis)
            )

            output_basis = normalized_dataset_fingerprint_basis(copy.deepcopy(baseline))
            output_basis["records_sha256"] = "f" * 64
            self.assertNotEqual(
                baseline["dataset_fingerprint"], build_dataset_fingerprint(output_basis)
            )

    def test_dataset_identifier_and_fingerprint_are_explicit_distinct_fields(self) -> None:
        manifest = validate_dataset_manifest(read_json(DATASET_MANIFEST))
        self.assertEqual("synthetic-mechanics-demo", manifest["dataset_id"])
        self.assertEqual(64, len(dataset_fingerprint(manifest)))
        self.assertNotEqual(manifest["dataset_id"], dataset_fingerprint(manifest))

    def test_snapshot_hashes_and_parses_the_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest_path = copy_fixture(base / "source")
            manifest = validate_dataset_manifest(read_json(manifest_path))
            snapshots = snapshot_source_files(manifest, manifest_path.parent, base / "snapshots")
            original_snapshot = snapshots["telemetry.csv"].read_bytes()
            (manifest_path.parent / "telemetry.csv").write_bytes(b"changed after snapshot")
            self.assertEqual(original_snapshot, snapshots["telemetry.csv"].read_bytes())
            self.assertEqual(
                next(item["sha256"] for item in manifest["source_files"] if item["role"] == "telemetry"),
                sha256_file(snapshots["telemetry.csv"]),
            )

    def test_real_ingestion_requires_matching_clean_code_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = copy_fixture(Path(directory) / "source")
            manifest = read_json(manifest_path)
            manifest["synthetic"] = False
            manifest["data_classification"] = "private"
            manifest["driver_identifiers"] = "pseudonymized"
            manifest["privacy"] = {
                "participant_data": True,
                "pseudonymized": True,
                "direct_identifiers_present": False,
                "pseudonymization_method": "one-way research pseudonym assigned before ingest",
                "consent_or_authority": "test-only declaration",
                "retention_policy": "test-only declaration",
            }
            write_json(manifest_path, manifest)
            dirty = {
                "package_version": "0.1.1",
                "git_commit": "1234567",
                "git_state": "dirty",
                "code_and_schema_sha256": "1" * 64,
                "schema_sha256": {"contracts/v1/test.schema.json": "2" * 64},
            }
            with patch(
                "apex_labs.ingestion.service.apex_labs_code_identity", return_value=dirty
            ), self.assertRaises(IntegrityError):
                ingest_dataset(manifest_path, Path(directory) / "output", project_root=ROOT)

    def test_late_malformed_record_leaves_no_partial_artifact_or_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest_path = copy_fixture(base / "source")
            telemetry = manifest_path.parent / "telemetry.csv"
            telemetry.write_text(
                telemetry.read_text(encoding="utf-8") + "2,60.4,broken,140,35,0.1,0.5,0.0,0.0,0\n",
                encoding="utf-8",
            )
            update_telemetry_hash(manifest_path)
            output = base / "normalized"
            with self.assertRaises(IngestionError):
                ingest_dataset(manifest_path, output, project_root=ROOT)
            self.assertFalse(output.exists())
            self.assertFalse((base / ".normalized.apex-labs.lock").exists())
            self.assertFalse(any(path.name.startswith(".apex-labs-ingest-") for path in base.iterdir()))

    def test_hash_mismatch_existing_destination_and_concurrent_lock_refuse_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest_path = copy_fixture(base / "source")
            (manifest_path.parent / "telemetry.csv").write_bytes(b"tampered")
            with self.assertRaises(IntegrityError):
                ingest_dataset(manifest_path, base / "hash-output", project_root=ROOT)
            self.assertFalse((base / "hash-output").exists())

            output = base / "existing"
            output.mkdir()
            with self.assertRaises(IngestionError):
                ingest_dataset(DATASET_MANIFEST, output, project_root=ROOT)

            locked = base / "locked"
            (base / ".locked.apex-labs.lock").write_text("held", encoding="utf-8")
            with self.assertRaises(IngestionError):
                ingest_dataset(DATASET_MANIFEST, locked, project_root=ROOT)
            self.assertFalse(locked.exists())

    def test_inspection_detects_record_corruption_and_fingerprint_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "normalized"
            ingest_dataset(DATASET_MANIFEST, output, project_root=ROOT)
            summary = inspect_dataset(output / "manifest.json")
            self.assertEqual("verified", summary["integrity"])
            with (output / "records.jsonl").open("ab") as handle:
                handle.write(b"{}\n")
            with self.assertRaises(IntegrityError):
                inspect_dataset(output / "manifest.json")


if __name__ == "__main__":
    unittest.main()
