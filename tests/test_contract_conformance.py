from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _support import (
    BUILT_AT,
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
    validate_evidence_set,
    validate_evidence_set_definition,
    validate_finding_review_package,
    validate_hypothesis,
    validate_hypothesis_transition,
    validate_inferential_analysis_definition,
    validate_inferential_analysis_run,
    validate_segment_definition,
    validate_dataset_manifest,
    validate_experiment,
    validate_export_definition,
    validate_finding,
    validate_finding_validation,
    validate_protocol_freeze,
    validate_apex_session_manifest,
    validate_collection_record,
    validate_product_annotations,
    validate_product_export_manifest,
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


class SchemaConformanceMixin(unittest.TestCase):
    """Shared assertions; carries no tests so subclasses do not re-run them."""

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


class ContractConformanceTests(SchemaConformanceMixin):
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
        relabeled_finding = copy.deepcopy(finding)
        relabeled_finding["synthetic"] = False
        self.assert_both_reject("finding", validate_finding, relabeled_finding)
        finding["scientific_review_state"] = "self_approved"
        self.assert_both_reject("finding", validate_finding, finding)

    def test_synthetic_product_states_fail_both_schema_and_runtime_paths(self) -> None:
        finding = read_json(FINDING)
        for field, value in (
            ("product_review_state", "pending"),
            ("recommended_product_action", "research_only"),
        ):
            with self.subTest(artifact="finding", field=field):
                changed = copy.deepcopy(finding)
                changed[field] = value
                self.assert_both_reject("finding", validate_finding, changed)

        validation = read_json(VALIDATION)
        relabeled_validation = copy.deepcopy(validation)
        relabeled_validation["synthetic"] = False
        self.assert_both_reject(
            "finding-validation", validate_finding_validation, relabeled_validation
        )
        for state in ("pending", "approved", "rejected"):
            with self.subTest(artifact="finding-validation", state=state):
                changed = copy.deepcopy(validation)
                changed["product_review_state"] = state
                self.assert_both_reject(
                    "finding-validation", validate_finding_validation, changed
                )

        manifest = read_json(
            ROOT / "product-exports" / "synthetic-mechanics-demo-v1" / "manifest.json"
        )
        for field, value in (
            ("product_review_state", "pending"),
            ("recommended_product_action", "research_only"),
            ("safe_for_global_consideration", True),
        ):
            with self.subTest(artifact="product-export-manifest", field=field):
                changed = copy.deepcopy(manifest)
                changed["findings"][0][field] = value
                self.assert_both_reject(
                    "product-export-manifest", validate_product_export_manifest, changed
                )

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


class ScientificContractConformanceTests(SchemaConformanceMixin):
    """The L4.2-L5 contracts must be enforced by both the schema and the runtime."""

    def test_checked_in_scientific_artifacts_conform_to_both_paths(self) -> None:
        segments = ROOT / "research" / "segments"
        evidence_sets = ROOT / "research" / "evidence-sets"
        analyses = ROOT / "research" / "analyses"
        frozen = ROOT / "research" / "campaigns" / "frozen"
        cases = [
            ("segment-definition", validate_segment_definition, segments / "synthetic-corner-a.json"),
            ("segment-definition", validate_segment_definition, segments / "synthetic-corner-4-multi-layout.json"),
            (
                "evidence-set-definition",
                validate_evidence_set_definition,
                evidence_sets / "synthetic-paired-corner-speed.json",
            ),
            (
                "evidence-set-definition",
                validate_evidence_set_definition,
                evidence_sets / "synthetic-unpaired-delivered-cue.json",
            ),
            (
                "inferential-analysis-definition",
                validate_inferential_analysis_definition,
                analyses / "synthetic-paired-corner-speed-confirmatory.json",
            ),
            (
                "inferential-analysis-definition",
                validate_inferential_analysis_definition,
                analyses / "synthetic-exploratory-subgroup-search.json",
            ),
            (
                "protocol-freeze",
                validate_protocol_freeze,
                frozen / "synthetic-inference-controlled.freeze.json",
            ),
        ]
        for kind, validator, artifact_path in cases:
            with self.subTest(kind=kind, artifact=artifact_path.name):
                value = read_json(artifact_path)
                self.assert_schema_valid(kind, value)
                validator(value)

    def test_generated_scientific_artifacts_conform_to_both_paths(self) -> None:
        from _support import prepared_campaign, prepared_run
        from apex_labs.findings.review_package import build_review_package
        from apex_labs.hypotheses import (
            bindings_from_run,
            plan_bindings,
            record_transition,
            register_hypothesis,
            replay,
        )
        from apex_labs.science_demo import _finding, _hypothesis, _validation

        with tempfile.TemporaryDirectory(prefix="apex-labs-conformance-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo")
            executed = prepared_run(prepared, base, run_id="conformance-run")
            evidence = read_json(prepared["evidence_dir"] / "evidence-set.json")
            run = read_json(executed["run_dir"] / "inferential-analysis-run.json")
            self.assert_schema_valid("evidence-set", evidence)
            validate_evidence_set(evidence)
            self.assert_schema_valid("inferential-analysis-run", run)
            validate_inferential_analysis_run(run)

            identity = evidence["code_identity"]
            registry = base / "registry"
            register_hypothesis(
                _hypothesis(BUILT_AT), registry, recorded_at=BUILT_AT, code_identity=identity
            )
            record_transition(
                registry, "synthetic-corner-speed-demo", to_state="analysis_ready",
                rationale="Frozen before any run existed.", recorded_at=BUILT_AT,
                bindings=plan_bindings(evidence, run["definition"], run["definition_sha256"]),
                code_identity=identity,
            )
            record_transition(
                registry, "synthetic-corner-speed-demo", to_state="tested",
                rationale="Ran once and independently recomputed.", recorded_at=BUILT_AT,
                bindings=bindings_from_run(evidence, run, verified=True),
                reviewer={"state": "pending", "reviewer_id": None, "reviewed_at": None, "notes": []},
                code_identity=identity,
            )
            history = replay(registry, "synthetic-corner-speed-demo")
            self.assert_schema_valid("hypothesis", history["hypothesis"])
            validate_hypothesis(history["hypothesis"])
            for transition in history["transitions"]:
                self.assert_schema_valid("hypothesis-transition", transition)
                validate_hypothesis_transition(transition)

            manifest = read_json(prepared["dataset_dirs"][0] / "manifest.json")
            finding = _finding(evidence, run, identity, manifest)
            artifact = _validation(finding, evidence, run, identity)
            self.assert_schema_valid("finding", finding)
            self.assert_schema_valid("finding-validation", artifact)
            package = build_review_package(
                finding, artifact, prepared["evidence_dir"], executed["run_dir"], history,
                [prepared["paths"]["metric"]], base / "package",
                package_id="conformance-package", created_at=BUILT_AT,
                recomputed_and_verified=True, code_identity=identity,
            )
            self.assert_schema_valid("finding-review-package", package)
            validate_finding_review_package(package)
            relabeled_package = copy.deepcopy(package)
            relabeled_package["synthetic"] = False
            self.assert_both_reject(
                "finding-review-package",
                validate_finding_review_package,
                relabeled_package,
            )
            for state in (
                "investigate",
                "replication_required",
                "engineering_review_candidate",
            ):
                with self.subTest(artifact="finding-review-package", state=state):
                    changed = copy.deepcopy(package)
                    changed["product_recommendation"]["state"] = state
                    self.assert_both_reject(
                        "finding-review-package",
                        validate_finding_review_package,
                        changed,
                    )

    def test_required_unknown_and_enum_violations_fail_both_paths(self) -> None:
        cases = [
            (
                "segment-definition",
                validate_segment_definition,
                ROOT / "research" / "segments" / "synthetic-corner-a.json",
                "identity_confidence",
                "probably",
            ),
            (
                "evidence-set-definition",
                validate_evidence_set_definition,
                ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json",
                "experimental_unit",
                "telemetry_burst",
            ),
            (
                "inferential-analysis-definition",
                validate_inferential_analysis_definition,
                ROOT / "research" / "analyses" / "synthetic-paired-corner-speed-confirmatory.json",
                "classification",
                "probably_true",
            ),
        ]
        for kind, validator, artifact_path, field, bad_value in cases:
            base = read_json(artifact_path)
            with self.subTest(kind=kind, rule="missing"):
                missing = copy.deepcopy(base)
                del missing[field]
                self.assert_both_reject(kind, validator, missing)
            with self.subTest(kind=kind, rule="unknown"):
                unknown = copy.deepcopy(base)
                unknown["unexpected"] = True
                self.assert_both_reject(kind, validator, unknown)
            with self.subTest(kind=kind, rule="enum"):
                enum = copy.deepcopy(base)
                enum[field] = bad_value
                self.assert_both_reject(kind, validator, enum)
            with self.subTest(kind=kind, rule="version"):
                version = copy.deepcopy(base)
                version["schema_version"] = base["schema_version"].replace("/v1", "/v2")
                with self.assertRaises(ValidationError):
                    self.assert_schema_valid(kind, version)
                with self.assertRaises(UnsupportedVersionError):
                    validator(version)

    def test_the_descriptive_v1_contract_is_unchanged_by_this_milestone(self) -> None:
        # Backward compatibility: the L4.1 descriptive definition and its schema
        # still accept exactly what they accepted before inference existed, and
        # still refuse anything inferential.
        descriptive = read_json(ROOT / "research" / "analyses" / "synthetic-demo-descriptive.json")
        self.assert_schema_valid("analysis-definition", descriptive)
        validate_analysis_definition(descriptive)
        self.assertEqual(descriptive["classification"], "descriptive_observational")
        inferential = copy.deepcopy(descriptive)
        inferential["classification"] = "confirmatory"
        self.assert_both_reject("analysis-definition", validate_analysis_definition, inferential)

    def test_every_published_schema_has_a_runtime_validator(self) -> None:
        from apex_labs.cli import ALL_VALIDATORS

        # A few historical CLI keys are shorter than their published schema name.
        aliases = {
            "algorithm-recommendation": "algorithm",
            "apex-research-session-export": "research-export-manifest",
            "apex-session-bundle-manifest": "apex-session-manifest",
            "dataset-manifest": "dataset",
            "metric-definition": "metric",
            "product-export-definition": "export-definition",
        }
        for schema_path in sorted(SCHEMA_DIR.glob("*.schema.json")):
            name = schema_path.name.removesuffix(".schema.json")
            with self.subTest(schema=name):
                self.assertIn(aliases.get(name, name), ALL_VALIDATORS)


if __name__ == "__main__":
    unittest.main()
