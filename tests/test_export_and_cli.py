from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import (
    DATASET_MANIFEST,
    EXPORT_DEFINITION,
    ROOT,
    VALIDATION,
    all_files,
    run_cli,
)

from apex_labs.errors import ContractValidationError, ExportError, IntegrityError
from apex_labs.exports import generate_product_export, verify_product_export
from apex_labs.io import read_json, write_json
from apex_labs.provenance import sha256_file


class ProductExportTests(unittest.TestCase):
    def test_deterministic_across_directories_order_locale_timezone_and_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            portable_root = base / "portable-root"
            shutil.copytree(ROOT / "research", portable_root / "research")
            (portable_root / "product-exports").mkdir(parents=True)
            first_metric = read_json(ROOT / "research" / "metrics" / "demo-record-count.json")
            second_metric = copy.deepcopy(first_metric)
            second_metric["metric_id"] = "demo-record-count-secondary"
            write_json(portable_root / "research" / "metrics" / "secondary.json", second_metric)
            definition = read_json(EXPORT_DEFINITION)
            definition["metric_paths"] = [
                "research/metrics/demo-record-count.json",
                "research/metrics/secondary.json",
            ]
            first_definition = portable_root / "product-exports" / "first.json"
            write_json(first_definition, definition)
            reversed_definition = copy.deepcopy(definition)
            reversed_definition["metric_paths"].reverse()
            reversed_definition["finding_paths"].reverse()
            reversed_definition["validation_paths"].reverse()
            second_definition = portable_root / "product-exports" / "second.json"
            write_json(second_definition, reversed_definition)

            original_cwd = Path.cwd()
            original_tz = os.environ.get("TZ")
            original_locale = os.environ.get("LC_ALL")
            try:
                os.environ["TZ"] = "Pacific/Auckland"
                os.environ["LC_ALL"] = "C"
                os.chdir(base)
                first = generate_product_export(
                    first_definition, base / "export-first", portable_root
                )
                os.environ["TZ"] = "America/Denver"
                os.environ["LC_ALL"] = "en_US.UTF-8"
                second = generate_product_export(
                    second_definition, base / "export-second", portable_root
                )
            finally:
                os.chdir(original_cwd)
                if original_tz is None:
                    os.environ.pop("TZ", None)
                else:
                    os.environ["TZ"] = original_tz
                if original_locale is None:
                    os.environ.pop("LC_ALL", None)
                else:
                    os.environ["LC_ALL"] = original_locale
            self.assertEqual(first, second)
            self.assertEqual(all_files(base / "export-first"), all_files(base / "export-second"))
            leaked = str(base).encode("utf-8")
            self.assertTrue(
                all(leaked not in content for content in all_files(base / "export-first").values())
            )

    def test_verification_detects_missing_extra_and_corrupted_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for failure in ("missing", "extra", "corrupted"):
                export_dir = base / failure
                generate_product_export(EXPORT_DEFINITION, export_dir, ROOT)
                if failure == "missing":
                    (export_dir / "README.md").unlink()
                elif failure == "extra":
                    (export_dir / "extra.txt").write_text("extra", encoding="utf-8")
                else:
                    (export_dir / "README.md").write_text("tampered", encoding="utf-8")
                with self.subTest(failure=failure), self.assertRaises(IntegrityError):
                    verify_product_export(export_dir)

    def test_integrity_hashes_cannot_hide_inconsistent_scientific_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            export_dir = Path(directory) / "export"
            generate_product_export(EXPORT_DEFINITION, export_dir, ROOT)
            manifest = read_json(export_dir / "manifest.json")
            validation_entry = next(
                item for item in manifest["files"] if item["role"] == "validation"
            )
            validation_path = export_dir / validation_entry["path"]
            validation = read_json(validation_path)
            validation["datasets"][0]["fingerprint"] = "f" * 64
            write_json(validation_path, validation)
            digest = sha256_file(validation_path)
            validation_entry["sha256"] = digest
            manifest["findings"][0]["validation_sha256"] = digest
            write_json(export_dir / "manifest.json", manifest)
            with self.assertRaises(ContractValidationError):
                verify_product_export(export_dir)

    def test_export_refuses_silent_overwrite_and_concurrent_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "export"
            generate_product_export(EXPORT_DEFINITION, output, ROOT)
            before = all_files(output)
            with self.assertRaises(ExportError):
                generate_product_export(EXPORT_DEFINITION, output, ROOT)
            self.assertEqual(before, all_files(output))

            locked = base / "locked"
            (base / ".locked.apex-labs.lock").write_text("held", encoding="utf-8")
            with self.assertRaises(ExportError):
                generate_product_export(EXPORT_DEFINITION, locked, ROOT)
            self.assertFalse(locked.exists())

    def test_failed_staged_write_is_atomic_and_orphan_stage_is_not_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "export"
            orphan = base / ".apex-labs-product-export-orphan"
            orphan.mkdir()
            (orphan / "manifest.json").write_text("partial", encoding="utf-8")
            with patch(
                "apex_labs.exports.product.write_json", side_effect=OSError("simulated interruption")
            ), self.assertRaises(OSError):
                generate_product_export(EXPORT_DEFINITION, output, ROOT)
            self.assertFalse(output.exists())
            self.assertFalse((base / ".export.apex-labs.lock").exists())
            self.assertEqual("partial", (orphan / "manifest.json").read_text(encoding="utf-8"))

    def test_readme_states_narrow_export_trust_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            export_dir = Path(directory) / "export"
            generate_product_export(EXPORT_DEFINITION, export_dir, ROOT)
            readme = (export_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("does not establish authorship", readme)
            self.assertIn("scientific correctness", readme)
            self.assertIn("production approval", readme)
            self.assertIn("Human and production-engineering review is required", readme)


class CliTests(unittest.TestCase):
    def test_cli_validation_ingestion_inspection_guard_and_export_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            normalized = base / "normalized"
            export = base / "export"
            commands = [
                ("validate", "dataset", str(DATASET_MANIFEST)),
                ("ingest", str(DATASET_MANIFEST), "--output", str(normalized)),
                ("inspect", str(normalized / "manifest.json")),
                (
                    "findings",
                    "verify",
                    str(ROOT / "research" / "findings" / "inconclusive" / "synthetic-mechanics-demo.json"),
                    str(VALIDATION),
                ),
                (
                    "export-product-findings",
                    str(EXPORT_DEFINITION),
                    "--output",
                    str(export),
                    "--root",
                    str(ROOT),
                ),
                ("verify-export", str(export)),
                ("repository-guard", "--root", str(ROOT)),
            ]
            for command in commands:
                result = run_cli(*command)
                with self.subTest(command=command):
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIsInstance(json.loads(result.stdout), dict)

    def test_cli_malformed_input_returns_controlled_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "bad.json"
            invalid.write_text('{"broken":', encoding="utf-8")
            result = run_cli("validate", "dataset", str(invalid))
            self.assertEqual(2, result.returncode)
            self.assertIn("error:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
