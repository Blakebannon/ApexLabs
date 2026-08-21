from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _support import (
    DATASET_MANIFEST,
    DEMO_PROTOCOL,
    EXPORT_DEFINITION,
    FINDING,
    FROZEN_PROTOCOL,
    ROOT,
    VALIDATION,
)

from apex_labs.errors import ContractValidationError, UnsupportedVersionError
from apex_labs.io import parse_json_bytes, read_json
from apex_labs.schemas import (
    validate_analysis_definition,
    validate_dataset_manifest,
    validate_experiment,
    validate_export_definition,
    validate_finding,
    validate_finding_validation,
    validate_protocol_freeze,
    validate_apex_session_manifest,
    validate_collection_record,
    validate_product_annotations,
    validate_research_export_manifest,
    validate_research_recorder_manifest,
    validate_adapter_conformance,
)

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import ValidationError
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - reproducible test extra is required
    raise RuntimeError("Install the declared test extra: pip install -e .[test]") from exc


SCHEMA_DIR = ROOT / "contracts" / "v1"


def schema_registry() -> tuple[Registry, dict[str, dict]]:
    schemas = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCHEMA_DIR.glob("*.schema.json"))
    }
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return registry, schemas


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry, cls.schemas = schema_registry()

    def assert_schema_valid(self, kind: str, value: dict) -> None:
        Draft202012Validator(
            self.schemas[kind], registry=self.registry, format_checker=FormatChecker()
        ).validate(value)

    def assert_both_reject(self, kind: str, validator, value: dict) -> None:
        with self.assertRaises(ValidationError) as schema_error:
            self.assert_schema_valid(kind, value)
        self.assertIsNotNone(schema_error.exception)
        with self.assertRaises(ContractValidationError):
            validator(value)

    def test_published_schemas_are_unique_and_runtime_artifacts_conform(self) -> None:
        ids = [schema["$id"] for schema in self.schemas.values()]
        self.assertEqual(len(ids), len(set(ids)))
        cases = [
            ("dataset-manifest", validate_dataset_manifest, DATASET_MANIFEST),
            ("experiment", validate_experiment, DEMO_PROTOCOL),
            ("protocol-freeze", validate_protocol_freeze, FROZEN_PROTOCOL),
            ("finding", validate_finding, FINDING),
            ("finding-validation", validate_finding_validation, VALIDATION),
            ("product-export-definition", validate_export_definition, EXPORT_DEFINITION),
            (
                "analysis-definition",
                validate_analysis_definition,
                ROOT / "research" / "analyses" / "synthetic-demo-descriptive.json",
            ),
            (
                "apex-session-bundle-manifest",
                validate_apex_session_manifest,
                ROOT / "tests" / "fixtures" / "apex_session_export_v1" / "bundle" / "manifest.json",
            ),
            (
                "collection-record",
                validate_collection_record,
                ROOT / "tests" / "fixtures" / "apex_session_export_v1" / "collection-record.json",
            ),
            (
                "apex-research-session-export",
                validate_research_export_manifest,
                ROOT / "contracts" / "examples" / "apex-research-session-export-v1.example.json",
            ),
            (
                "adapter-conformance",
                validate_adapter_conformance,
                ROOT / "tests" / "fixtures" / "apex_session_export_v1" / "adapter-conformance.expected.json",
            ),
        ]
        for kind, validator, path in cases:
            with self.subTest(kind=kind):
                value = read_json(path)
                self.assert_schema_valid(kind, value)
                validator(value)

        annotation = {
            "schema_version": "apex-labs.product-annotations/v1",
            "source_schema_version": "apex-session-export/1.0.0",
            "source_file_sha256": "1" * 64,
            "classification": "product_generated_annotations_not_scientific_evidence",
            "scientific_evidence": False,
            "training_labels": False,
            "ground_truth": False,
            "product_recommendations": False,
            "scientific_promotion_allowed": False,
            "annotations": [],
        }
        self.assert_schema_valid("product-annotations", annotation)
        validate_product_annotations(annotation)

    def test_native_contract_required_unknown_enum_and_version_fail_both_paths(self) -> None:
        base = read_json(ROOT / "tests" / "fixtures" / "apex_session_export_v1" / "collection-record.json")
        missing = copy.deepcopy(base)
        del missing["privacy"]
        self.assert_both_reject("collection-record", validate_collection_record, missing)
        unknown = copy.deepcopy(base)
        unknown["unexpected"] = True
        self.assert_both_reject("collection-record", validate_collection_record, unknown)
        invalid_enum = copy.deepcopy(base)
        invalid_enum["collection_classification"] = "maybe_experimental"
        self.assert_both_reject("collection-record", validate_collection_record, invalid_enum)
        version = copy.deepcopy(base)
        version["schema_version"] = "apex-labs.collection-record/v2"
        with self.assertRaises(ValidationError):
            self.assert_schema_valid("collection-record", version)
        with self.assertRaises(UnsupportedVersionError):
            validate_collection_record(version)

        research_collection = copy.deepcopy(base)
        research_collection["source_bundle"]["schema_version"] = "apex-research-session-export/1.0.0"
        self.assert_schema_valid("collection-record", research_collection)
        validate_collection_record(research_collection)

        research = read_json(ROOT / "contracts" / "examples" / "apex-research-session-export-v1.example.json")
        research["timing"]["timestamped_samples"] = False
        self.assert_both_reject("apex-research-session-export", validate_research_export_manifest, research)

        annotation = {
            "schema_version": "apex-labs.product-annotations/v1",
            "source_schema_version": "apex-session-export/1.0.0",
            "source_file_sha256": "1" * 64,
            "classification": "product_generated_annotations_not_scientific_evidence",
            "scientific_evidence": False,
            "training_labels": False,
            "ground_truth": True,
            "product_recommendations": False,
            "scientific_promotion_allowed": False,
            "annotations": [],
        }
        self.assert_both_reject("product-annotations", validate_product_annotations, annotation)

    def test_research_recorder_profile_pin_and_traffic_compatibility(self) -> None:
        profile = ROOT / "contracts" / "v1" / "apex-research-recorder-profile-v1.json"
        self.assertEqual(
            hashlib.sha256(profile.read_bytes()).hexdigest(),
            "20b547de4ef89d8b4a33bd8eb1bed282268b4b8e0b5f521108279e13961b800f",
        )
        base = read_json(ROOT / "contracts" / "examples" / "apex-research-session-export-v1.example.json")
        validate_research_export_manifest(base)
        legacy = copy.deepcopy(base)
        legacy["channels"] = [item for item in legacy["channels"] if item["name"] != "traffic"]
        validate_research_export_manifest(legacy)
        with self.assertRaises(ContractValidationError):
            validate_research_recorder_manifest(base)

    def test_required_unknown_enum_and_version_fail_both_paths(self) -> None:
        base = read_json(DATASET_MANIFEST)
        missing = copy.deepcopy(base)
        del missing["privacy"]
        self.assert_both_reject("dataset-manifest", validate_dataset_manifest, missing)

        unknown = copy.deepcopy(base)
        unknown["unexpected"] = True
        self.assert_both_reject("dataset-manifest", validate_dataset_manifest, unknown)

        enum = copy.deepcopy(base)
        enum["data_classification"] = "public-ish"
        self.assert_both_reject("dataset-manifest", validate_dataset_manifest, enum)

        version = copy.deepcopy(base)
        version["schema_version"] = "apex-labs.dataset-manifest/v2"
        with self.assertRaises(ValidationError):
            self.assert_schema_valid("dataset-manifest", version)
        with self.assertRaises(UnsupportedVersionError):
            validate_dataset_manifest(version)

    def test_nested_structure_and_finding_review_enum_fail_both_paths(self) -> None:
        dataset = read_json(DATASET_MANIFEST)
        dataset["privacy"]["unknown"] = "not allowed"
        self.assert_both_reject("dataset-manifest", validate_dataset_manifest, dataset)

        finding = read_json(FINDING)
        finding["scientific_review_state"] = "self_approved"
        self.assert_both_reject("finding", validate_finding, finding)

    def test_duplicate_keys_and_nonfinite_json_are_refused_before_validation(self) -> None:
        with self.assertRaises(ContractValidationError):
            parse_json_bytes(b'{"field":1,"field":2}')
        with self.assertRaises(ContractValidationError):
            parse_json_bytes(b'{"value":NaN}')

    def test_runtime_authority_enforces_cross_identity_rules(self) -> None:
        dataset = read_json(DATASET_MANIFEST)
        duplicate = copy.deepcopy(dataset["source_files"][0])
        duplicate["sha256"] = "f" * 64
        duplicate["role"] = "metadata"
        dataset["source_files"].append(duplicate)
        # JSON Schema validates portable structure. Runtime authority rejects the
        # duplicate Windows-case-insensitive path as a cross-entry semantic rule.
        self.assert_schema_valid("dataset-manifest", dataset)
        with self.assertRaises(ContractValidationError):
            validate_dataset_manifest(dataset)

    def test_malformed_utf8_and_json_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_bytes(b"\xff")
            with self.assertRaises(ContractValidationError):
                read_json(invalid)
            invalid.write_text('{"broken":', encoding="utf-8")
            with self.assertRaises(ContractValidationError):
                read_json(invalid)


if __name__ == "__main__":
    unittest.main()
