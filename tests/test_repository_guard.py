from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import ROOT, copy_fixture

from apex_labs.errors import ContractValidationError
from apex_labs.io import resolve_relative_file, validate_contract_path
from apex_labs.repository_guard import run_repository_guard, scan_repository_files


class ContractPathSafetyTests(unittest.TestCase):
    def test_traversal_absolute_drive_unc_device_and_ambiguous_paths_are_refused(self) -> None:
        unsafe = [
            "../secret.csv",
            "folder/../secret.csv",
            "/var/data/session.csv",
            "C:/data/session.csv",
            "c:/data/session.csv",
            "C:\\data\\session.csv",
            "//server/share/session.csv",
            "\\\\server\\share\\session.csv",
            "//?/C:/session.csv",
            "//./NUL",
            "/??/C:/session.csv",
            "GLOBALROOT/device/harddisk0",
            "folder//session.csv",
            "folder/./session.csv",
            "NUL.csv",
            "folder/COM1.txt",
            "folder/trailing. ",
        ]
        for value in unsafe:
            with self.subTest(value=value), self.assertRaises(ContractValidationError):
                validate_contract_path(value)
        self.assertEqual(
            "portable/session.csv", validate_contract_path("portable/session.csv")
        )

    def test_symlink_or_reparse_escape_is_refused_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside) / "outside.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "linked.json"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable: {exc}")
            with self.assertRaises(ContractValidationError):
                resolve_relative_file(root, "linked.json")


class RepositoryGuardTests(unittest.TestCase):
    def test_current_repository_passes_heuristic_guard(self) -> None:
        result = run_repository_guard(ROOT)
        self.assertTrue(result["ok"], result["findings"])
        self.assertIn("does not prove", result["limitations"])

    def test_prohibited_data_secret_environment_and_identifier_content_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "results.db"
            database.write_bytes(b"database")
            environment = root / ".env.local"
            environment.write_text("TOKEN=value", encoding="utf-8")
            key = root / "notes.txt"
            key.write_text(
                "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----",
                encoding="utf-8",
            )
            data = root / "datasets" / "participant.json"
            data.parent.mkdir(parents=True)
            data.write_text(
                '{"' + "email" + '":"participant@example.invalid"}', encoding="utf-8"
            )
            findings = scan_repository_files(root, [database, environment, key, data])
            rules = {item.rule for item in findings}
            self.assertTrue(
                {"prohibited-binary", "environment-file", "private-key", "direct-identifier"}
                <= rules
            )

    def test_suspicious_content_inside_valid_synthetic_fixture_is_still_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "tests" / "fixtures" / "demo"
            copy_fixture(fixture)
            suspicious = fixture / "notes.txt"
            suspicious.write_text(
                "-----BEGIN " + "PRIVATE KEY-----\nfixture-placeholder",
                encoding="utf-8",
            )
            files = [path for path in fixture.rglob("*") if path.is_file()]
            rules = {item.rule for item in scan_repository_files(root, files)}
            self.assertIn("private-key", rules)

    def test_unclassified_or_oversized_synthetic_fixture_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "tests" / "fixtures" / "unclassified"
            fixture.mkdir(parents=True)
            telemetry = fixture / "telemetry.csv"
            telemetry.write_text("time,value\n0,0\n", encoding="utf-8")
            with patch(
                "apex_labs.repository_guard.MAX_SYNTHETIC_FIXTURE_FILE_BYTES", 1
            ):
                findings = scan_repository_files(root, [telemetry])
            rules = {item.rule for item in findings}
            self.assertTrue(
                {"fixture-classification", "fixture-size", "raw-telemetry"} <= rules
            )

    def test_gitignore_is_supplemented_not_replaced(self) -> None:
        ignored = [
            "datasets/raw/private-session.csv",
            "datasets/private/identity.json",
            "raw-session.ibt",
            "external-session.zip",
            ".env",
            "product-exports/generated/local/manifest.json",
        ]
        for path in ignored:
            result = subprocess.run(
                ["git", "check-ignore", "-q", path], cwd=ROOT, check=False
            )
            self.assertEqual(0, result.returncode, path)
        result = subprocess.run(
            ["git", "check-ignore", "-q", "tests/fixtures/synthetic_demo/telemetry.csv"],
            cwd=ROOT,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)

    def test_force_visible_zip_is_refused_even_if_gitignore_would_hide_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "session.zip"
            archive.write_bytes(b"not-real-telemetry")
            rules = {item.rule for item in scan_repository_files(root, [archive])}
            self.assertIn("prohibited-binary", rules)


if __name__ == "__main__":
    unittest.main()
