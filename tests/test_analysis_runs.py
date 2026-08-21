from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import DATASET_MANIFEST, ROOT, all_files, run_cli

from apex_labs.analysis import run_analysis, verify_analysis_run
from apex_labs.analysis.runner import _run_hash
from apex_labs.errors import AnalysisError, ContractValidationError, IntegrityError
from apex_labs.ingestion import ingest_dataset
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import sha256_bytes
from apex_labs.schemas import validate_analysis_definition, validate_analysis_run

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - reproducible test extra is required
    raise RuntimeError("Install the declared test extra: pip install -e .[test]") from exc

DEFINITION_PATH = ROOT / "research" / "analyses" / "synthetic-demo-descriptive.json"
METRIC_PATH = ROOT / "research" / "metrics" / "demo-record-count.json"
RUN_ID = "synthetic-demo-run-001"
CREATED_AT = "2026-08-20T00:00:00Z"


def _run_schema_validator() -> Draft202012Validator:
    schema_dir = ROOT / "contracts" / "v1"
    run_schema = json.loads((schema_dir / "analysis-run.schema.json").read_text(encoding="utf-8"))
    definition_schema = json.loads(
        (schema_dir / "analysis-definition.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in (run_schema, definition_schema)
    )
    return Draft202012Validator(run_schema, registry=registry, format_checker=FormatChecker())


class AnalysisRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-analysis-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.normalized = cls.base / "normalized"
        cls.manifest = ingest_dataset(DATASET_MANIFEST, cls.normalized, project_root=ROOT)

    def _run(self, output: Path, **overrides):
        arguments = {
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "metric_paths": [METRIC_PATH],
            "project_root": ROOT,
        }
        arguments.update(overrides)
        return run_analysis(DEFINITION_PATH, self.normalized, output, **arguments)

    def _result(self, artifact: dict, computation_id: str) -> dict:
        return next(
            item for item in artifact["results"] if item["computation_id"] == computation_id
        )

    def test_run_is_deterministic_contract_valid_and_reproducible(self) -> None:
        first = self._run(self.base / "run-first")
        second = self._run(self.base / "run-second")
        self.assertEqual(first, second)
        self.assertEqual(all_files(self.base / "run-first"), all_files(self.base / "run-second"))

        stored = read_json(self.base / "run-first" / "analysis-run.json")
        self.assertEqual(stored, first)
        validate_analysis_run(stored)
        _run_schema_validator().validate(stored)

        self.assertEqual(stored["classification"], "descriptive_summary_not_scientific_evidence")
        self.assertTrue(stored["synthetic"])
        self.assertEqual(stored["dataset"]["fingerprint"], self.manifest["dataset_fingerprint"])
        self.assertEqual(
            stored["integrity"]["records_validated"],
            sum(self.manifest["record_counts"].values()),
        )

        inventory = self._result(stored, "inventory")
        self.assertEqual(inventory["record_counts"], self.manifest["record_counts"])
        self.assertEqual(
            inventory["quality_flag_counts"],
            self.manifest["integrity_summary"]["quality_flag_counts"],
        )

        availability = self._result(stored, "sample-availability")
        self.assertEqual(availability["records_scanned"], self.manifest["record_counts"]["telemetry_sample"])
        self.assertEqual(availability["concepts"]["brake"]["measured"], 8)
        self.assertEqual(availability["concepts"]["fuel_mass"]["present"], 0)

        brake = self._result(stored, "brake-distribution")
        self.assertEqual(brake["attrition"]["values_included"], 8)
        self.assertEqual(brake["attrition"]["values_unavailable"], 0)
        summary = brake["summary"]
        self.assertEqual(summary["count"], 8)
        self.assertEqual(summary["minimum"], 0.0)
        self.assertEqual(summary["maximum"], 0.6)
        self.assertAlmostEqual(summary["mean"], 0.235, places=12)
        self.assertAlmostEqual(summary["median"], 0.175, places=12)
        self.assertAlmostEqual(summary["q1"], 0.06, places=12)
        self.assertAlmostEqual(summary["q3"], 0.3625, places=12)
        self.assertAlmostEqual(summary["mad"], 0.15, places=12)

        speed = self._result(stored, "speed-per-lap")
        self.assertEqual(len(speed["per_lap"]), self.manifest["record_counts"]["lap"])
        for lap_summary in speed["per_lap"].values():
            self.assertEqual(lap_summary["count"], 4)

        sample_yield = self._result(stored, "sample-yield")
        self.assertEqual(sample_yield["total"], 8)
        self.assertEqual(sum(sample_yield["per_lap"].values()), 8)

        metric = read_json(METRIC_PATH)
        self.assertEqual(
            stored["metric_definitions"],
            [
                {
                    "metric_id": metric["metric_id"],
                    "version": metric["version"],
                    "sha256": sha256_bytes(canonical_json_bytes(metric)),
                }
            ],
        )

        report = verify_analysis_run(self.base / "run-first", self.normalized, project_root=ROOT)
        self.assertTrue(report["valid"])
        self.assertTrue(report["code_identity_match"])
        self.assertEqual(report["results_reproduced"], len(stored["results"]))

    def test_duplicate_metric_identity_is_refused(self) -> None:
        with self.assertRaises(AnalysisError):
            self._run(self.base / "run-duplicate-metric", metric_paths=[METRIC_PATH, METRIC_PATH])

    def test_existing_output_is_never_overwritten(self) -> None:
        target = self.base / "run-occupied"
        target.mkdir()
        with self.assertRaises(AnalysisError):
            self._run(target)

    def test_tampered_records_definitions_and_results_are_refused(self) -> None:
        tampered = self.base / "normalized-tampered"
        shutil.copytree(self.normalized, tampered)
        with (tampered / "records.jsonl").open("ab") as handle:
            handle.write(b"\n")
        with self.assertRaises(IntegrityError):
            run_analysis(
                DEFINITION_PATH,
                tampered,
                self.base / "run-tampered",
                run_id=RUN_ID,
                created_at=CREATED_AT,
                project_root=ROOT,
            )

        artifact = self._run(self.base / "run-for-tamper")
        run_path = self.base / "run-for-tamper" / "analysis-run.json"

        corrupted = copy.deepcopy(artifact)
        corrupted["results"][0]["record_counts"]["telemetry_sample"] += 1
        write_json(run_path, corrupted)
        with self.assertRaises(IntegrityError):
            verify_analysis_run(run_path, self.normalized, project_root=ROOT)

        corrupted["run_sha256"] = _run_hash(corrupted)
        write_json(run_path, corrupted)
        with self.assertRaises(IntegrityError):
            verify_analysis_run(run_path, self.normalized, project_root=ROOT)

        write_json(run_path, artifact)
        with self.assertRaises(IntegrityError):
            verify_analysis_run(run_path, tampered, project_root=ROOT)

    def test_real_datasets_require_a_clean_committed_code_identity(self) -> None:
        real = self.base / "normalized-real"
        shutil.copytree(self.normalized, real)
        manifest = read_json(real / "manifest.json")
        manifest["synthetic"] = False
        write_json(real / "manifest.json", manifest)
        dirty_identity = dict(self.manifest["code_identity"])
        dirty_identity["git_state"] = "dirty"
        with self.assertRaises(IntegrityError):
            run_analysis(
                DEFINITION_PATH,
                real,
                self.base / "run-real",
                run_id=RUN_ID,
                created_at=CREATED_AT,
                project_root=ROOT,
                code_identity=dirty_identity,
            )

    def test_definition_validator_rejects_semantic_violations(self) -> None:
        base = read_json(DEFINITION_PATH)
        validate_analysis_definition(base)

        duplicate = copy.deepcopy(base)
        duplicate["computations"].append(dict(duplicate["computations"][0]))
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(duplicate)

        boolean_summary = copy.deepcopy(base)
        boolean_summary["computations"][2]["concept"] = "lap_valid"
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(boolean_summary)

        session_per_lap = copy.deepcopy(base)
        session_per_lap["computations"][3]["record_type"] = "session"
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(session_per_lap)

        lap_yield = copy.deepcopy(base)
        lap_yield["computations"][4]["record_type"] = "lap"
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(lap_yield)

        unknown_field = copy.deepcopy(base)
        unknown_field["unexpected"] = True
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(unknown_field)

        inferential = copy.deepcopy(base)
        inferential["classification"] = "confirmatory"
        with self.assertRaises(ContractValidationError):
            validate_analysis_definition(inferential)

    def test_run_validator_rejects_incomplete_or_reclassified_artifacts(self) -> None:
        artifact = self._run(self.base / "run-validator")

        missing_result = copy.deepcopy(artifact)
        missing_result["results"].pop()
        missing_result["run_sha256"] = _run_hash(missing_result)
        with self.assertRaises(ContractValidationError):
            validate_analysis_run(missing_result)

        reordered = copy.deepcopy(artifact)
        reordered["results"].reverse()
        reordered["run_sha256"] = _run_hash(reordered)
        with self.assertRaises(ContractValidationError):
            validate_analysis_run(reordered)

        reclassified = copy.deepcopy(artifact)
        reclassified["classification"] = "scientific_evidence"
        with self.assertRaises(ContractValidationError):
            validate_analysis_run(reclassified)

        unverified = copy.deepcopy(artifact)
        unverified["integrity"]["fingerprint_verified"] = False
        with self.assertRaises(ContractValidationError):
            validate_analysis_run(unverified)

    def test_cli_analyze_verify_and_validate(self) -> None:
        output = self.base / "run-cli"
        completed = run_cli(
            "analyze",
            str(DEFINITION_PATH),
            "--dataset",
            str(self.normalized),
            "--run-id",
            "synthetic-demo-run-cli",
            "--created-at",
            CREATED_AT,
            "--metric",
            str(METRIC_PATH),
            "--output",
            str(output),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["classification"], "descriptive_summary_not_scientific_evidence")

        verified = run_cli("verify-analysis", str(output), "--dataset", str(self.normalized))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["valid"])

        validated = run_cli("validate", "analysis-run", str(output / "analysis-run.json"))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        definition_validated = run_cli("validate", "analysis-definition", str(DEFINITION_PATH))
        self.assertEqual(definition_validated.returncode, 0, definition_validated.stderr)

        rejected = run_cli("verify-analysis", str(output), "--dataset", str(self.base / "missing"))
        self.assertEqual(rejected.returncode, 2)


if __name__ == "__main__":
    unittest.main()
