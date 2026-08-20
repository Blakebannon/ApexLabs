from __future__ import annotations

import copy
import hashlib
import json
import shutil
import stat
import tempfile
import threading
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from _support import ROOT, all_files, run_cli

from apex_labs.errors import ApexLabsError, ContractValidationError, IngestionError, IntegrityError, UnsupportedVersionError
from apex_labs.ingestion.apex_session import (
    REQUIRED_ENTRIES,
    ingest_apex_session_bundle,
    inspect_apex_session_bundle,
    validate_apex_session_bundle,
)
from apex_labs.ingestion.service import inspect_dataset
from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.schemas import validate_collection_record, validate_product_annotations


FIXTURE = ROOT / "tests" / "fixtures" / "apex_session_export_v1"
BUNDLE_SOURCE = FIXTURE / "bundle"
ORDER = [
    "README.md", "session-summary.md", "analysis-prompt.md", "data-dictionary.md",
    "findings.json", "laps.csv", "telemetry.csv", "manifest.json",
]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
    info.create_system = 0
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0
    return info


def build_zip(destination: Path, source: Path = BUNDLE_SOURCE, entries=None, *, compression=zipfile.ZIP_STORED) -> Path:
    values = entries if entries is not None else [(name, (source / name).read_bytes(), None) for name in ORDER]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with zipfile.ZipFile(destination, "w", compression=compression) as archive:
            for name, content, custom_info in values:
                info = custom_info or _zip_info(name)
                info.compress_type = compression
                archive.writestr(info, content)
    return destination


def update_manifest(directory: Path) -> None:
    manifest = read_json(directory / "manifest.json")
    files = []
    for item in manifest["files"]:
        content = (directory / item["name"]).read_bytes()
        files.append({"name": item["name"], "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    manifest["files"] = files
    (directory / "manifest.json").write_bytes(canonical_json_bytes(manifest))


class ApexSessionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = build_zip(self.root / "fixture.zip")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_synthetic_bundle_and_audit_semantics(self) -> None:
        report = validate_apex_session_bundle(self.bundle, FIXTURE / "collection-record.json")
        self.assertEqual(report["source_schema_version"], "apex-session-export/1.0.0")
        self.assertEqual(report["counts"]["laps"], 3)
        self.assertEqual(report["counts"]["telemetry_distance_bins"], 12)
        self.assertEqual(report["counts"]["source_frames_represented"], 14)
        self.assertEqual(report["source_semantics"], "distance_binned_aggregate_not_raw_frames")
        self.assertIn("integer_total_bins", report["lap_fraction_rule"])
        self.assertNotIn(str(BUNDLE_SOURCE), json.dumps(report))

    def test_normalization_is_deterministic_and_preserves_missing_versus_zero(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        first_manifest = ingest_apex_session_bundle(self.bundle, first, FIXTURE / "collection-record.json", project_root=ROOT)
        second_manifest = ingest_apex_session_bundle(self.bundle, second, FIXTURE / "collection-record.json", project_root=ROOT)
        self.assertEqual(first_manifest["dataset_fingerprint"], second_manifest["dataset_fingerprint"])
        self.assertEqual(all_files(first), all_files(second))
        records = [json.loads(line) for line in (first / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        bins = [record for record in records if record["record_type"] == "distance_bin"]
        measured_zero = next(record for record in bins if record["lap_id"].endswith("000001") and record["distance_bin_index"] == 0)
        missing = next(record for record in bins if record["lap_id"].endswith("000001") and record["distance_bin_index"] == 3)
        self.assertEqual(measured_zero["fields"]["brake"]["value"], 0.0)
        self.assertEqual(measured_zero["fields"]["brake"]["provenance"], "derived")
        self.assertIsNone(missing["fields"]["brake"]["value"])
        self.assertEqual(missing["fields"]["brake"]["provenance"], "unavailable")
        self.assertEqual(first_manifest["record_counts"], {"session": 1, "lap": 3, "distance_bin": 12})
        self.assertFalse(first_manifest["source_semantics"]["time_domain_available"])
        inspect_dataset(first / "manifest.json")

    def test_product_annotations_are_permanently_non_scientific(self) -> None:
        output = self.root / "normalized"
        ingest_apex_session_bundle(self.bundle, output, FIXTURE / "collection-record.json", project_root=ROOT)
        annotations = validate_product_annotations(read_json(output / "product-annotations.json"))
        for field in ("scientific_evidence", "training_labels", "ground_truth", "product_recommendations", "scientific_promotion_allowed"):
            self.assertFalse(annotations[field])
        records_text = (output / "records.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("performanceVerdict", records_text)
        self.assertNotIn("recommendedAction", records_text)
        mutated = copy.deepcopy(annotations)
        mutated["scientific_evidence"] = True
        with self.assertRaises(ContractValidationError):
            validate_product_annotations(mutated)

    def test_sidecar_observational_and_experimental_rules(self) -> None:
        observational = read_json(FIXTURE / "collection-record.json")
        validate_collection_record(observational)
        invalid = copy.deepcopy(observational)
        invalid["protocol"] = {
            "freeze_id": "freeze-01", "freeze_sha256": "1" * 64,
            "experiment_id": "experiment-01", "experiment_version": "1.0.0",
            "schedule_id": "schedule-01", "schedule_sha256": "2" * 64,
            "schedule_assignment_id": "assignment-01",
        }
        with self.assertRaises(ContractValidationError):
            validate_collection_record(invalid)
        experimental = copy.deepcopy(invalid)
        experimental["collection_classification"] = "experimental"
        experimental["blocks"] = [{"block_id": "block-01", "condition_id": "condition-01", "start_lap": 1, "end_lap": 2}]
        experimental["lap_assignments"] = [{"lap_number": 1, "block_id": "block-01"}]
        validate_collection_record(experimental)
        experimental["lap_assignments"][0]["block_id"] = "missing-block"
        with self.assertRaises(ContractValidationError):
            validate_collection_record(experimental)

    def test_sidecar_hash_identity_and_assignment_binding(self) -> None:
        sidecar = read_json(FIXTURE / "collection-record.json")
        sidecar["source_bundle"]["sha256"] = "f" * 64
        path = self.root / "sidecar.json"
        path.write_bytes(canonical_json_bytes(sidecar))
        with self.assertRaises(IntegrityError):
            validate_apex_session_bundle(self.bundle, path)
        sidecar = read_json(FIXTURE / "collection-record.json")
        sidecar["session_identity"]["track"] = "different-track"
        path.write_bytes(canonical_json_bytes(sidecar))
        with self.assertRaises(IntegrityError):
            validate_apex_session_bundle(self.bundle, path)

    def test_cli_inspect_validate_and_ingest(self) -> None:
        inspected = run_cli("apex-session", "inspect", str(self.bundle))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(json.loads(inspected.stdout)["counts"]["laps"], 3)
        validated = run_cli("apex-session", "validate", str(self.bundle), "--collection-record", str(FIXTURE / "collection-record.json"))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        output = self.root / "cli-output"
        ingested = run_cli("apex-session", "ingest", str(self.bundle), "--collection-record", str(FIXTURE / "collection-record.json"), "--output", str(output))
        self.assertEqual(ingested.returncode, 0, ingested.stderr)
        result = json.loads(ingested.stdout)
        self.assertEqual(result["research_eligibility"]["classification"], "synthetic_demo")
        self.assertFalse(result["research_eligibility"]["scientific_promotion_eligible"])

    def test_failure_atomicity_existing_destination_and_concurrency(self) -> None:
        output = self.root / "output"
        output.mkdir()
        marker = output / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(IngestionError):
            ingest_apex_session_bundle(self.bundle, output, FIXTURE / "collection-record.json", project_root=ROOT)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
        target = self.root / "concurrent"
        errors: list[Exception] = []
        successes: list[dict] = []
        barrier = threading.Barrier(2)

        def run() -> None:
            try:
                barrier.wait()
                successes.append(ingest_apex_session_bundle(self.bundle, target, FIXTURE / "collection-record.json", project_root=ROOT))
            except Exception as exc:  # expected for one local contender
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        inspect_dataset(target / "manifest.json")
        self.assertFalse(any(path.name.startswith(".concurrent.") for path in self.root.iterdir()))

    def test_real_session_content_is_not_in_fixture(self) -> None:
        visible = b"".join(path.read_bytes() for path in FIXTURE.rglob("*") if path.is_file())
        self.assertIn(b"Synthetic", visible)
        self.assertNotIn(b'"privacyMode":"Anonymized"', visible)
        self.assertLess(sum(path.stat().st_size for path in FIXTURE.rglob("*") if path.is_file()), 100_000)

    def test_malformed_semantics_and_rounding_are_rejected(self) -> None:
        source = self.root / "source"
        shutil.copytree(BUNDLE_SOURCE, source)
        telemetry = (source / "telemetry.csv").read_text(encoding="utf-8")
        telemetry = telemetry.replace(",43.20,3,1,1,0,0,", ",43.90,3,1,1,0,0,", 1)
        (source / "telemetry.csv").write_text(telemetry, encoding="utf-8", newline="")
        update_manifest(source)
        bad = build_zip(self.root / "rounding.zip", source)
        with self.assertRaises(IntegrityError):
            inspect_apex_session_bundle(bad)
        finding_source = self.root / "finding-source"
        shutil.copytree(BUNDLE_SOURCE, finding_source)
        findings = read_json(finding_source / "findings.json")
        findings["findings"][0]["coverage"] = 0.5
        (finding_source / "findings.json").write_bytes(canonical_json_bytes(findings))
        update_manifest(finding_source)
        bad_coverage = build_zip(self.root / "bad-coverage.zip", finding_source)
        with self.assertRaises(IntegrityError):
            inspect_apex_session_bundle(bad_coverage)

    def test_late_malformed_row_leaves_no_output(self) -> None:
        source = self.root / "late-source"
        shutil.copytree(BUNDLE_SOURCE, source)
        telemetry = (source / "telemetry.csv").read_text(encoding="utf-8") + "3,broken\n"
        (source / "telemetry.csv").write_text(telemetry, encoding="utf-8", newline="")
        update_manifest(source)
        bad = build_zip(self.root / "late.zip", source)
        output = self.root / "late-output"
        with self.assertRaises(ContractValidationError):
            ingest_apex_session_bundle(bad, output, FIXTURE / "collection-record.json", project_root=ROOT)
        self.assertFalse(output.exists())
        self.assertFalse(any(path.name.startswith(".late-output.") for path in self.root.iterdir()))


class ApexSessionArchiveSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.standard = [(name, (BUNDLE_SOURCE / name).read_bytes(), None) for name in ORDER]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_rejected(self, entries, error=ApexLabsError, *, compression=zipfile.ZIP_STORED) -> None:
        path = build_zip(self.root / f"case-{len(list(self.root.glob('*.zip')))}.zip", entries=entries, compression=compression)
        with self.assertRaises(error):
            inspect_apex_session_bundle(path)

    def test_duplicate_case_separator_traversal_absolute_and_device_paths(self) -> None:
        self.assert_rejected(self.standard + [("README.md", b"duplicate", None)])
        renamed = [("readme.MD" if name == "README.md" else name, data, info) for name, data, info in self.standard]
        self.assert_rejected(self.standard + [("readme.MD", b"ambiguous", None)])
        for hostile in ("../README.md", "/README.md", r"C:\README.md", r"\\server\share\README.md", r"\\?\C:\README.md", r"folder\README.md", "CON"):
            entries = [(hostile if name == "README.md" else name, data, info) for name, data, info in self.standard]
            with self.subTest(hostile=hostile):
                self.assert_rejected(entries)
        self.assertTrue(renamed)  # retain explicit case-only construction coverage

    def test_symlink_extra_missing_and_entry_limit(self) -> None:
        symlink = _zip_info("README.md")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        entries = [(name, data, symlink if name == "README.md" else info) for name, data, info in self.standard]
        self.assert_rejected(entries)
        self.assert_rejected(self.standard[:-1])
        self.assert_rejected(self.standard + [("extra.txt", b"extra", None)])
        many = self.standard + [(f"extra-{index}.txt", b"x", None) for index in range(40)]
        self.assert_rejected(many)

    def test_zip_bomb_ratio_is_rejected(self) -> None:
        entries = [(name, (b"0" * 1_000_000 if name == "telemetry.csv" else data), info) for name, data, info in self.standard]
        self.assert_rejected(entries, compression=zipfile.ZIP_DEFLATED)

    def test_manifest_hash_size_inventory_and_version_fail(self) -> None:
        corrupt = [(name, (data + b"x" if name == "laps.csv" else data), info) for name, data, info in self.standard]
        self.assert_rejected(corrupt, IntegrityError)
        source = self.root / "version"
        shutil.copytree(BUNDLE_SOURCE, source)
        manifest = read_json(source / "manifest.json")
        manifest["schema"] = "apex-session-export/2.0.0"
        (source / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        path = build_zip(self.root / "version.zip", source)
        with self.assertRaises(UnsupportedVersionError):
            inspect_apex_session_bundle(path)
        manifest = read_json(BUNDLE_SOURCE / "manifest.json")
        manifest["files"].append(copy.deepcopy(manifest["files"][0]))
        entries = [(name, (canonical_json_bytes(manifest) if name == "manifest.json" else data), info) for name, data, info in self.standard]
        self.assert_rejected(entries, ContractValidationError)

    def test_malformed_utf8_json_csv_headers_width_and_nonfinite(self) -> None:
        cases = []
        cases.append(("README.md", b"\xff", ContractValidationError))
        cases.append(("findings.json", b'{"schema":', ContractValidationError))
        cases.append(("findings.json", b'{"schema":"a","schema":"b"}', ContractValidationError))
        telemetry = (BUNDLE_SOURCE / "telemetry.csv").read_text(encoding="utf-8")
        first, rest = telemetry.split("\n", 1)
        cases.append(("telemetry.csv", (first + ",lap_number\n" + rest).encode(), ContractValidationError))
        cases.append(("telemetry.csv", (telemetry + "3,broken\n").encode(), ContractValidationError))
        cases.append(("telemetry.csv", telemetry.replace("0.100000", "NaN", 1).encode(), ContractValidationError))
        for index, (target, replacement, error) in enumerate(cases):
            source = self.root / f"malformed-{index}"
            shutil.copytree(BUNDLE_SOURCE, source)
            (source / target).write_bytes(replacement)
            update_manifest(source)
            path = build_zip(self.root / f"malformed-{index}.zip", source)
            with self.subTest(target=target, index=index):
                with self.assertRaises(error):
                    inspect_apex_session_bundle(path)

    def test_row_limits_are_enforced(self) -> None:
        path = build_zip(self.root / "rows.zip")
        with patch("apex_labs.ingestion.apex_session.MAX_TELEMETRY_ROWS", 2):
            with self.assertRaises(IngestionError):
                inspect_apex_session_bundle(path)


if __name__ == "__main__":
    unittest.main()
