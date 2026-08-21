"""Finding review packages: determination, determinism, and the production boundary."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from _support import BUILT_AT, ROOT, all_files, prepared_campaign, prepared_run

from apex_labs.errors import ContractValidationError, ExportError, IntegrityError, LifecycleError
from apex_labs.findings.review_package import (
    build_review_package,
    product_recommendation,
    verify_review_package,
)
from apex_labs.hypotheses import (
    bindings_from_run,
    plan_bindings,
    record_transition,
    register_hypothesis,
    replay,
)
from apex_labs.io import read_json, write_json
from apex_labs.findings import finding_hash
from apex_labs.schemas import validate_finding_review_package
from apex_labs.science_demo import _finding, _hypothesis, _validation

PACKAGE_ID = "review-package-tests"
PENDING = {"state": "pending", "reviewer_id": None, "reviewed_at": None, "notes": []}


class ReviewPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-package-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.prepared = prepared_campaign(cls.base / "demo")
        cls.executed = prepared_run(cls.prepared, cls.base, run_id="package-run")
        cls.evidence = cls.prepared["evidence"]
        cls.run_artifact = cls.executed["run"]
        cls.identity = cls.evidence["code_identity"]

        registry = cls.base / "registry"
        register_hypothesis(
            _hypothesis(BUILT_AT), registry, recorded_at=BUILT_AT, code_identity=cls.identity
        )
        record_transition(
            registry, "synthetic-corner-speed-demo", to_state="analysis_ready",
            rationale="Frozen before any run existed.", recorded_at=BUILT_AT,
            bindings=plan_bindings(
                cls.evidence, cls.run_artifact["definition"], cls.run_artifact["definition_sha256"]
            ),
            code_identity=cls.identity,
        )
        record_transition(
            registry, "synthetic-corner-speed-demo", to_state="tested",
            rationale="Ran once and independently recomputed.", recorded_at=BUILT_AT,
            bindings=bindings_from_run(cls.evidence, cls.run_artifact, verified=True),
            reviewer=dict(PENDING), code_identity=cls.identity,
        )
        cls.registry = registry
        cls.history = replay(registry, "synthetic-corner-speed-demo")
        manifest = read_json(cls.prepared["dataset_dirs"][0] / "manifest.json")
        cls.finding = _finding(cls.evidence, cls.run_artifact, cls.identity, manifest)
        cls.artifact = _validation(cls.finding, cls.evidence, cls.run_artifact, cls.identity)
        cls.package = cls._build(cls, cls.base / "package")

    def _build(self, output: Path, finding=None, artifact=None, history=None):
        return build_review_package(
            finding or self.finding,
            artifact or self.artifact,
            self.prepared["evidence_dir"],
            self.executed["run_dir"],
            history or self.history,
            [self.prepared["paths"]["metric"]],
            output,
            package_id=PACKAGE_ID,
            created_at=BUILT_AT,
            recomputed_and_verified=True,
            code_identity=self.identity,
        )

    def test_package_and_report_are_byte_deterministic(self) -> None:
        second = self._build(self.base / "package-second")
        self.assertEqual(self.package, second)
        self.assertEqual(all_files(self.base / "package"), all_files(self.base / "package-second"))
        validate_finding_review_package(read_json(self.base / "package" / "review-package.json"))

    def test_package_binds_every_artifact_the_result_rests_on(self) -> None:
        package = self.package
        self.assertEqual(package["evidence"]["evidence_set_sha256"], self.evidence["evidence_set_sha256"])
        self.assertEqual(package["analysis_run"]["run_sha256"], self.run_artifact["run_sha256"])
        self.assertEqual(
            package["protocol"]["freeze_sha256"], self.evidence["protocol"]["freeze_sha256"]
        )
        self.assertEqual(
            package["hypothesis"]["head_transition_sha256"], self.history["head_transition_sha256"]
        )
        self.assertEqual(len(package["metric_definitions"]), 1)
        self.assertEqual(
            sorted(item["fingerprint"] for item in package["evidence"]["datasets"]),
            sorted(item["fingerprint"] for item in self.evidence["datasets"]),
        )

    def test_report_states_the_result_and_the_weak_evidence_together(self) -> None:
        report = (self.base / "package" / "review-report.md").read_text(encoding="utf-8")
        self.assertIn("**Status**: INCONCLUSIVE", report)
        self.assertIn("median paired difference of 0.5 m/s", report)
        self.assertIn("**Attrition**", report)
        self.assertIn("unavailable: Fuel state is not represented", report)
        self.assertIn("**Replication**", report)
        self.assertIn("required_before_validation", report)
        self.assertIn("do_not_implement", report)
        self.assertIn("Apex Labs never edits Apex Sim Coach", report)
        self.assertNotIn("None\n", report.split("**Limitations**")[1][:200])

    def test_report_does_not_repeat_a_limitation_twice(self) -> None:
        limitations = self.package["limitations"]
        self.assertEqual(len(limitations), len(set(limitations)))

    def test_verification_re_renders_the_report_from_the_bound_artifacts(self) -> None:
        result = verify_review_package(
            self.base / "package", self.executed["run_dir"], self.prepared["evidence_dir"]
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["product_recommendation"], "do_not_implement")
        self.assertFalse(result["automatic_production_change"])

    def test_editing_the_report_is_detected(self) -> None:
        import shutil

        tampered = self.base / "tampered-report"
        shutil.copytree(self.base / "package", tampered)
        path = tampered / "review-report.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nA quietly appended claim.\n", encoding="utf-8")
        with self.assertRaises(IntegrityError) as error:
            verify_review_package(tampered, self.executed["run_dir"], self.prepared["evidence_dir"])
        self.assertIn("does not match its recorded hash", str(error.exception))

    def test_editing_the_package_is_detected(self) -> None:
        tampered = self.base / "tampered-package"
        tampered.mkdir()
        package = copy.deepcopy(self.package)
        # A contract-legal edit: the hash, not the schema, is what catches it.
        package["evidence"]["counts"]["pairs"] = 99
        write_json(tampered / "review-package.json", package)
        (tampered / "review-report.md").write_bytes(
            (self.base / "package" / "review-report.md").read_bytes()
        )
        with self.assertRaises(IntegrityError) as error:
            verify_review_package(tampered, self.executed["run_dir"], self.prepared["evidence_dir"])
        self.assertIn("hash does not match", str(error.exception))

    def test_output_directory_is_never_overwritten(self) -> None:
        with self.assertRaises(ExportError):
            self._build(self.base / "package")

    def test_a_package_bound_to_a_different_run_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-other-run-") as directory:
            base = Path(directory)
            other = prepared_campaign(base / "demo", "no-meaningful-effect")
            other_run = prepared_run(other, base, run_id="other-run")
            # The hypothesis binding and the evidence/run cross-reference both
            # refuse this; whichever fires first, no package is produced.
            with self.assertRaises((IntegrityError, LifecycleError)):
                build_review_package(
                    self.finding, self.artifact, other["evidence_dir"], other_run["run_dir"],
                    self.history, [self.prepared["paths"]["metric"]], base / "package",
                    package_id=PACKAGE_ID, created_at=BUILT_AT, recomputed_and_verified=True,
                    code_identity=self.identity,
                )

    def test_a_hypothesis_not_bound_to_this_run_is_refused(self) -> None:
        registry = self.base / "unbound-registry"
        register_hypothesis(
            _hypothesis(BUILT_AT), registry, recorded_at=BUILT_AT, code_identity=self.identity
        )
        history = replay(registry, "synthetic-corner-speed-demo")
        with self.assertRaises(LifecycleError) as error:
            self._build(self.base / "unbound-package", history=history)
        self.assertIn("never invents that link", str(error.exception))

    def test_a_finding_disagreeing_with_its_validation_artifact_is_refused(self) -> None:
        finding = copy.deepcopy(self.finding)
        finding["effect_estimate"]["estimate"] = 9.0
        with self.assertRaises(ContractValidationError):
            self._build(self.base / "mismatched-package", finding=finding)

    def test_synthetic_evidence_cannot_be_laundered_by_relabeling_derived_artifacts(self) -> None:
        finding = copy.deepcopy(self.finding)
        artifact = copy.deepcopy(self.artifact)
        finding["synthetic"] = False
        finding["evidence_classification"] = "controlled"
        for dataset in finding["dataset_references"]:
            dataset["synthetic"] = False
        finding["analysis_code_identity"]["git_state"] = "clean"
        artifact["synthetic"] = False
        for dataset in artifact["datasets"]:
            dataset["synthetic"] = False
        artifact["analysis_code_identity"]["git_state"] = "clean"
        artifact["finding_sha256"] = finding_hash(finding)
        with self.assertRaises(IntegrityError) as error:
            self._build(self.base / "laundered-package", finding=finding, artifact=artifact)
        self.assertIn("disagree about synthetic classification", str(error.exception))


class ProductBoundaryTests(unittest.TestCase):
    @staticmethod
    def _inputs(**overrides):
        finding = {"synthetic": False, "status": "validated"}
        artifact = {
            "gate_evaluations": {"structural": "passed", "reproducibility": "passed", "scientific": "passed"},
            "review": {"state": "approved"},
        }
        run = {
            "analysis_state": "computed",
            "definition": {"replication_policy": {"state": "not_required"}},
        }
        state = "supported_provisionally"
        for key, value in overrides.items():
            if key == "finding":
                finding.update(value)
            elif key == "artifact":
                artifact.update(value)
            elif key == "run":
                run.update(value)
            else:
                state = value
        return finding, artifact, run, state

    def test_synthetic_evidence_can_only_recommend_do_not_implement(self) -> None:
        finding, artifact, run, state = self._inputs(finding={"synthetic": True})
        result = product_recommendation(finding, artifact, run, state)
        self.assertEqual(result["state"], "do_not_implement")
        self.assertFalse(result["automatic_production_change"])

    def test_an_engineering_candidate_requires_every_gate_and_no_open_replication(self) -> None:
        finding, artifact, run, state = self._inputs()
        self.assertEqual(product_recommendation(finding, artifact, run, state)["state"], "engineering_review_candidate")
        for label, overrides in (
            ("status", {"finding": {"status": "provisional"}}),
            ("scientific gate", {"artifact": {"gate_evaluations": {"structural": "passed", "reproducibility": "passed", "scientific": "unresolved"}}}),
            ("reproducibility gate", {"artifact": {"gate_evaluations": {"structural": "passed", "reproducibility": "failed", "scientific": "passed"}}}),
            ("review", {"artifact": {"review": {"state": "pending"}}}),
            ("replication", {"run": {"definition": {"replication_policy": {"state": "required_before_validation"}}}}),
        ):
            with self.subTest(missing=label):
                finding, artifact, run, state = self._inputs(**overrides)
                self.assertNotEqual(
                    product_recommendation(finding, artifact, run, state)["state"],
                    "engineering_review_candidate",
                )

    def test_an_open_replication_requirement_reports_replication_required(self) -> None:
        finding, artifact, run, state = self._inputs(
            run={"definition": {"replication_policy": {"state": "required_before_validation"}}}
        )
        self.assertEqual(
            product_recommendation(finding, artifact, run, state)["state"], "replication_required"
        )

    def test_no_recommendation_is_the_default(self) -> None:
        finding, artifact, run, state = self._inputs(
            finding={"status": "inconclusive"},
            artifact={"gate_evaluations": {"structural": "passed", "reproducibility": "unresolved", "scientific": "unresolved"}},
            run={"analysis_state": "inconclusive", "definition": {"replication_policy": {"state": "not_required"}}},
        )
        self.assertEqual(product_recommendation(finding, artifact, run, "inconclusive")["state"], "none")

    def test_no_recommendation_state_can_ever_change_production(self) -> None:
        for overrides in ({}, {"finding": {"synthetic": True}}, {"finding": {"status": "rejected"}}):
            finding, artifact, run, state = self._inputs(**overrides)
            self.assertFalse(
                product_recommendation(finding, artifact, run, state)["automatic_production_change"]
            )


class PackageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-package-contract-")
        cls.addClassCleanup(cls._directory.cleanup)
        base = Path(cls._directory.name)
        prepared = prepared_campaign(base / "demo")
        executed = prepared_run(prepared, base, run_id="contract-package-run")
        identity = prepared["evidence"]["code_identity"]
        registry = base / "registry"
        register_hypothesis(_hypothesis(BUILT_AT), registry, recorded_at=BUILT_AT, code_identity=identity)
        record_transition(
            registry, "synthetic-corner-speed-demo", to_state="analysis_ready",
            rationale="Frozen.", recorded_at=BUILT_AT,
            bindings=plan_bindings(
                prepared["evidence"], executed["run"]["definition"], executed["run"]["definition_sha256"]
            ),
            code_identity=identity,
        )
        record_transition(
            registry, "synthetic-corner-speed-demo", to_state="tested", rationale="Ran.",
            recorded_at=BUILT_AT,
            bindings=bindings_from_run(prepared["evidence"], executed["run"], verified=True),
            reviewer=dict(PENDING), code_identity=identity,
        )
        manifest = read_json(prepared["dataset_dirs"][0] / "manifest.json")
        finding = _finding(prepared["evidence"], executed["run"], identity, manifest)
        artifact = _validation(finding, prepared["evidence"], executed["run"], identity)
        cls.package = build_review_package(
            finding, artifact, prepared["evidence_dir"], executed["run_dir"],
            replay(registry, "synthetic-corner-speed-demo"), [prepared["paths"]["metric"]],
            base / "package", package_id="contract-package", created_at=BUILT_AT,
            recomputed_and_verified=True, code_identity=identity,
        )

    def _package(self) -> dict:
        return copy.deepcopy(self.package)

    def test_synthetic_evidence_may_never_be_validated(self) -> None:
        for status in ("provisional", "validated"):
            with self.subTest(status=status):
                package = self._package()
                package["finding"]["status"] = status
                with self.assertRaises(ContractValidationError):
                    validate_finding_review_package(package)

    def test_synthetic_evidence_may_not_recommend_production_work(self) -> None:
        for state in ("investigate", "replication_required", "engineering_review_candidate"):
            with self.subTest(state=state):
                package = self._package()
                package["product_recommendation"]["state"] = state
                with self.assertRaises(ContractValidationError) as error:
                    validate_finding_review_package(package)
                self.assertIn("only recommend none or do_not_implement", str(error.exception))

    def test_a_package_may_not_declare_an_automatic_production_change(self) -> None:
        package = self._package()
        package["product_recommendation"]["automatic_production_change"] = True
        with self.assertRaises(ContractValidationError) as error:
            validate_finding_review_package(package)
        self.assertIn("never automatically changes Apex Sim Coach", str(error.exception))

    def test_an_unresolved_scientific_gate_cannot_carry_a_stronger_status(self) -> None:
        package = self._package()
        package["synthetic"] = False
        for dataset in package["evidence"]["datasets"]:
            dataset["synthetic"] = False
        package["finding"]["evidence_classification"] = "controlled"
        package["finding"]["status"] = "rejected"
        with self.assertRaises(ContractValidationError) as error:
            validate_finding_review_package(package)
        self.assertIn("unresolved scientific gate", str(error.exception))

    def test_reserved_evidence_cannot_be_tested_when_none_was_reserved(self) -> None:
        package = self._package()
        package["replication"]["holdout_available"] = False
        package["replication"]["holdout_tested"] = True
        with self.assertRaises(ContractValidationError):
            validate_finding_review_package(package)

    def test_a_package_is_only_assembled_from_structurally_valid_artifacts(self) -> None:
        package = self._package()
        package["scientific_review"]["gate_structural"] = "failed"
        with self.assertRaises(ContractValidationError):
            validate_finding_review_package(package)


if __name__ == "__main__":
    unittest.main()
