"""Preregistered inferential runs: estimates, ceilings, multiplicity, and refusals."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from _support import ANALYSIS_DIR, BUILT_AT, ROOT, all_files, prepared_campaign, prepared_run

from apex_labs.analysis import run_inferential_analysis, verify_inferential_analysis_run
from apex_labs.errors import ContractValidationError, InferenceError, IntegrityError
from apex_labs.io import read_json, write_json
from apex_labs.schemas import (
    validate_inferential_analysis_definition,
    validate_inferential_analysis_run,
)

CONFIRMATORY = ANALYSIS_DIR / "synthetic-paired-corner-speed-confirmatory.json"


def _primary(run: dict) -> dict:
    return next(item for item in run["comparisons"] if item["role"] == "primary")


class InferentialRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-inference-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.prepared = prepared_campaign(cls.base / "demo")
        cls.executed = prepared_run(cls.prepared, cls.base, run_id="inference-tests-run")
        cls.run_artifact = cls.executed["run"]

    def _run(self, output: Path, definition_path: Path | None = None):
        return run_inferential_analysis(
            definition_path or self.prepared["paths"]["analysis_definition"],
            self.prepared["evidence_dir"],
            self.prepared["paths"]["protocol_freeze"],
            output,
            run_id="inference-tests-run",
            created_at=BUILT_AT,
            project_root=ROOT,
        )

    def test_run_is_byte_deterministic_and_contract_valid(self) -> None:
        second = self._run(self.base / "second")
        self.assertEqual(self.run_artifact, second)
        self.assertEqual(all_files(self.executed["run_dir"]), all_files(self.base / "second"))
        validate_inferential_analysis_run(
            read_json(self.executed["run_dir"] / "inferential-analysis-run.json")
        )
        self.assertEqual(self.run_artifact["classification"], "inferential_result_not_a_finding")

    def test_primary_estimate_matches_the_hand_computed_answer(self) -> None:
        primary = _primary(self.run_artifact)
        # Eighteen fabricated pairs whose differences are 0.25 (x8), 0.5 (x6) and
        # 0.75 (x4); the median of that multiset is exactly 0.5 m/s.
        self.assertEqual(primary["effect"]["estimate"], 0.5)
        self.assertEqual(primary["effect"]["n"], 18)
        self.assertEqual(len(primary["effect"]["per_unit_differences"]), 18)
        self.assertEqual(primary["unit_of_measure"], "m/s")

    def test_sign_test_matches_the_exact_binomial_tail(self) -> None:
        evidence = _primary(self.run_artifact)["statistical_evidence"]
        self.assertEqual(evidence["test"], "exact_paired_sign_test")
        self.assertEqual(evidence["detail"], {"positive": 18, "negative": 0, "ties": 0, "trials": 18})
        self.assertEqual(evidence["raw_p_value"], 2 / 2**18)

    def test_holm_adjustment_uses_the_declared_family_size(self) -> None:
        entries = {item["comparison_id"]: item for item in self.run_artifact["multiplicity"]["entries"]}
        self.assertEqual(self.run_artifact["multiplicity"]["members"], ["corner-minimum-speed", "corner-speed-consistency"])
        self.assertEqual(entries["corner-minimum-speed"]["adjusted_p_value"], 2 * (2 / 2**18))
        self.assertTrue(entries["corner-minimum-speed"]["rejected_at_alpha"])
        # A comparison with no test contributes no p-value and cannot be rejected.
        self.assertIsNone(entries["corner-speed-consistency"]["raw_p_value"])
        self.assertIsNone(entries["corner-speed-consistency"]["adjusted_p_value"])
        self.assertFalse(entries["corner-speed-consistency"]["rejected_at_alpha"])

    def test_interval_is_a_cluster_bootstrap_at_the_declared_unit(self) -> None:
        uncertainty = _primary(self.run_artifact)["uncertainty"]
        self.assertTrue(uncertainty["usable"])
        self.assertEqual(uncertainty["resampling_unit"], "block")
        self.assertEqual(uncertainty["clusters"], 3)
        self.assertEqual(uncertainty["interval"], [0.25, 0.5])
        self.assertIn("not a probability", uncertainty["semantics"])

    def test_practical_threshold_is_separate_from_statistical_evidence(self) -> None:
        practical = _primary(self.run_artifact)["practical"]
        self.assertEqual(practical["threshold_magnitude"], 0.3)
        self.assertEqual(practical["threshold_source"], "frozen_protocol")
        self.assertTrue(practical["estimate_exceeds_threshold"])
        self.assertTrue(practical["direction_matches_hypothesis"])
        self.assertTrue(practical["interval_excludes_no_effect"])

    def test_every_declared_falsification_test_runs_against_every_comparison(self) -> None:
        declared = {item["test_id"] for item in self.run_artifact["definition"]["falsification_tests"]}
        comparisons = {item["comparison_id"] for item in self.run_artifact["comparisons"]}
        observed = {(item["comparison_id"], item["test_id"]) for item in self.run_artifact["sensitivity"]}
        self.assertEqual(observed, {(c, t) for c in comparisons for t in declared})
        primary_outcomes = {
            item["test_id"]: item["outcome"]
            for item in self.run_artifact["sensitivity"]
            if item["comparison_id"] == "corner-minimum-speed"
        }
        self.assertTrue(all(outcome == "robust" for outcome in primary_outcomes.values()))

    def test_sensitivity_never_replaces_the_primary_estimate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-outlier-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo", "outlier-driven-effect")
            executed = prepared_run(prepared, base, run_id="outlier-run")
            run = executed["run"]
            primary = _primary(run)
            # The mean is carried by one pair and still stands unchanged beside the
            # checks that expose it.
            self.assertEqual(primary["effect"]["estimate"], 0.5)
            self.assertEqual(primary["effect"]["secondary_estimate"], 0.0)
            self.assertEqual(primary["statistical_evidence"]["raw_p_value"], 1.0)
            outcomes = {
                item["test_id"]: item["outcome"]
                for item in run["sensitivity"]
                if item["comparison_id"] == primary["comparison_id"]
            }
            self.assertEqual(outcomes["outlier-dependence"], "fragile")
            self.assertEqual(outcomes["isolation-by-block"], "fragile")

    def test_interpretation_ceiling_is_capped_by_the_design(self) -> None:
        self.assertEqual(self.run_artifact["interpretation"]["structural_ceiling"], "intervention_associated")
        self.assertEqual(self.run_artifact["interpretation"]["effective_ceiling"], "intervention_associated")

    def test_a_stronger_interpretation_than_the_design_permits_is_refused(self) -> None:
        definition = read_json(self.prepared["paths"]["analysis_definition"])
        definition["interpretation_ceiling"] = "causal_candidate"
        path = self.base / "over-strong.json"
        write_json(path, definition)
        with self.assertRaises(InferenceError) as error:
            self._run(self.base / "over-strong-run", path)
        self.assertIn("stronger interpretation than the design permits is refused", str(error.exception))

    def test_synthetic_evidence_is_never_scientifically_eligible(self) -> None:
        self.assertFalse(self.run_artifact["scientific_eligibility"]["eligible"])
        self.assertIn("permanently ineligible", self.run_artifact["scientific_eligibility"]["reason"])

    def test_verification_recomputes_the_result(self) -> None:
        result = verify_inferential_analysis_run(
            self.executed["run_dir"],
            self.prepared["evidence_dir"],
            self.prepared["paths"]["protocol_freeze"],
            project_root=ROOT,
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["primary_estimate"], 0.5)

    def test_tampering_with_a_stored_result_is_detected(self) -> None:
        tampered = self.base / "tampered-run"
        tampered.mkdir()
        artifact = copy.deepcopy(self.run_artifact)
        artifact["comparisons"][0]["effect"]["estimate"] = 5.0
        write_json(tampered / "inferential-analysis-run.json", artifact)
        with self.assertRaises(IntegrityError) as error:
            verify_inferential_analysis_run(
                tampered,
                self.prepared["evidence_dir"],
                self.prepared["paths"]["protocol_freeze"],
                project_root=ROOT,
            )
        self.assertIn("hash does not match", str(error.exception))

    def test_a_run_bound_to_a_different_evidence_set_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-other-evidence-") as directory:
            other = prepared_campaign(Path(directory), "no-meaningful-effect")
            with self.assertRaises(IntegrityError):
                verify_inferential_analysis_run(
                    self.executed["run_dir"],
                    other["evidence_dir"],
                    self.prepared["paths"]["protocol_freeze"],
                    project_root=ROOT,
                )

    def test_a_mismatched_frozen_protocol_is_refused(self) -> None:
        other_freeze = (
            ROOT / "research" / "campaigns" / "frozen" / "synthetic-inference-observational.freeze.json"
        )
        with self.assertRaises(IntegrityError):
            run_inferential_analysis(
                self.prepared["paths"]["analysis_definition"],
                self.prepared["evidence_dir"],
                other_freeze,
                self.base / "wrong-protocol",
                run_id="wrong-protocol",
                created_at=BUILT_AT,
                project_root=ROOT,
            )

    def test_output_directory_is_never_overwritten(self) -> None:
        with self.assertRaises(InferenceError) as error:
            self._run(self.executed["run_dir"])
        self.assertIn("already exists", str(error.exception))

    def test_a_refused_run_leaves_no_partial_output(self) -> None:
        target = self.base / "atomic-inference-failure"
        definition = read_json(self.prepared["paths"]["analysis_definition"])
        definition["interpretation_ceiling"] = "causal_candidate"
        path = self.base / "atomic-over-strong.json"
        write_json(path, definition)
        with self.assertRaises(InferenceError):
            self._run(target, path)
        self.assertFalse(target.exists())


class SmallSampleAndScopeTests(unittest.TestCase):
    def test_an_unmet_preregistered_requirement_yields_a_preserved_inconclusive_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-underpowered-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo", "insufficient-sample-requirement")
            executed = prepared_run(prepared, base, run_id="underpowered-run")
            run = executed["run"]
            self.assertEqual(run["analysis_state"], "inconclusive")
            self.assertEqual(run["sufficiency"]["status"], "insufficient")
            self.assertFalse(run["sufficiency"]["confirmatory_permitted"])
            self.assertTrue(run["sufficiency"]["descriptive_only"])
            self.assertEqual(run["interpretation"]["effective_ceiling"], "descriptive")
            self.assertGreaterEqual(len(run["sufficiency"]["unmet_requirements"]), 3)
            # The attempt is preserved rather than refused.
            self.assertTrue((executed["run_dir"] / "inferential-analysis-run.json").is_file())
            self.assertTrue(any("INCONCLUSIVE" in item for item in run["limitations"]))

    def test_the_primary_scope_never_reads_reserved_replication_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-holdout-scope-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo", "holdout-fails-to-replicate")
            primary = prepared_run(prepared, base, run_id="holdout-primary")["run"]
            self.assertEqual(primary["evidence_set"]["scope"], "primary")
            reserved = set(prepared["evidence"]["holdout"]["reserved_unit_ids"])
            self.assertEqual(
                primary["evidence_set"]["units_used"],
                prepared["evidence"]["counts"]["included_units"] - len(reserved),
            )
            replication = run_inferential_analysis(
                ROOT / "research" / "analyses" / "synthetic-holdout-replication.json",
                prepared["evidence_dir"],
                prepared["paths"]["protocol_freeze"],
                base / "replication",
                run_id="holdout-replication",
                created_at=BUILT_AT,
                project_root=ROOT,
            )
            self.assertEqual(replication["evidence_set"]["scope"], "holdout")
            self.assertEqual(replication["evidence_set"]["units_used"], len(reserved))
            # The reserved evidence does not reproduce the primary direction.
            self.assertEqual(_primary(primary)["effect"]["estimate"], 0.5)
            self.assertEqual(_primary(replication)["effect"]["estimate"], 0.0)
            self.assertFalse(_primary(replication)["practical"]["estimate_exceeds_threshold"])

    def test_exploratory_search_survives_correction_only_by_chance_and_is_corrected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-exploratory-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo", "exploratory-multiple-comparisons")
            run = prepared_run(prepared, base, run_id="exploratory-run")["run"]
            entries = run["multiplicity"]["entries"]
            raw = [item["raw_p_value"] for item in entries if item["raw_p_value"] is not None]
            # One fabricated subgroup has six concordant pairs: 2 / 2**6 = 0.03125.
            self.assertEqual(min(raw), 0.03125)
            adjusted = [item["adjusted_p_value"] for item in entries if item["adjusted_p_value"] is not None]
            # Six searched subgroups: Benjamini-Hochberg lifts it to 6 * 0.03125.
            self.assertEqual(min(adjusted), 6 * 0.03125)
            self.assertFalse(any(item["rejected_at_alpha"] for item in entries))
            self.assertEqual(run["multiplicity"]["correction"], "benjamini_hochberg")
            self.assertEqual(run["interpretation"]["effective_ceiling"], "associational")


class InferentialDefinitionContractTests(unittest.TestCase):
    @staticmethod
    def _definition() -> dict:
        return read_json(CONFIRMATORY)

    def test_checked_in_inferential_definitions_are_contract_valid(self) -> None:
        found = 0
        for path in sorted(ANALYSIS_DIR.glob("*.json")):
            definition = read_json(path)
            if definition["schema_version"] != "apex-labs.inferential-analysis-definition/v1":
                continue
            found += 1
            with self.subTest(definition=path.name):
                validate_inferential_analysis_definition(definition)
        self.assertGreaterEqual(found, 10)

    def test_the_descriptive_v1_contract_is_not_accepted_as_inferential(self) -> None:
        descriptive = read_json(ANALYSIS_DIR / "synthetic-demo-descriptive.json")
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(descriptive)

    def test_family_membership_must_name_exactly_the_declared_comparisons(self) -> None:
        definition = self._definition()
        definition["family"]["members"] = ["corner-minimum-speed"]
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("fixed at definition time", str(error.exception))

    def test_a_confirmatory_family_may_not_use_false_discovery_control(self) -> None:
        definition = self._definition()
        definition["family"]["correction"] = "benjamini_hochberg"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)

    def test_an_exploratory_family_may_not_use_familywise_control(self) -> None:
        definition = read_json(ANALYSIS_DIR / "synthetic-exploratory-subgroup-search.json")
        definition["family"]["correction"] = "holm_bonferroni"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)

    def test_several_comparisons_require_a_declared_correction(self) -> None:
        definition = self._definition()
        definition["family"]["correction"] = "none"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)

    def test_a_confirmatory_analysis_requires_preregistered_sample_requirements(self) -> None:
        definition = self._definition()
        definition["sufficiency_rule"] = {
            "source": "not_declared",
            "minimum_experimental_units": None,
            "minimum_pairs": None,
            "minimum_resampling_clusters": None,
            "minimum_participants": None,
            "stopping_rule": "Whenever the result looks good.",
            "source_declarations": [],
            "pilot_reference": None,
        }
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("preregistered in the protocol or a completed documented pilot", str(error.exception))

    def test_undeclared_requirements_may_not_invent_numeric_thresholds(self) -> None:
        definition = read_json(ANALYSIS_DIR / "synthetic-exploratory-subgroup-search.json")
        definition["sufficiency_rule"]["source"] = "not_declared"
        definition["sufficiency_rule"]["source_declarations"] = []
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("must not invent numeric thresholds", str(error.exception))

    def test_a_confirmatory_primary_comparison_may_not_be_a_subgroup(self) -> None:
        definition = self._definition()
        definition["comparisons"][0]["subset"] = {"field": "block_id", "value": "block-01"}
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("not a subgroup", str(error.exception))

    def test_exploratory_work_cannot_claim_more_than_association(self) -> None:
        definition = read_json(ANALYSIS_DIR / "synthetic-exploratory-subgroup-search.json")
        definition["interpretation_ceiling"] = "intervention_associated"
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("requires independent replication", str(error.exception))

    def test_reserved_evidence_may_only_be_read_by_a_declared_replication(self) -> None:
        definition = self._definition()
        definition["evidence_scope"] = "holdout"
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("only be read by a declared replication run", str(error.exception))

    def test_a_definition_may_not_declare_that_it_already_inspected_the_holdout(self) -> None:
        definition = self._definition()
        definition["replication_policy"]["holdout_inspected"] = True
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)

    def test_a_paired_method_requires_a_paired_design(self) -> None:
        definition = read_json(ANALYSIS_DIR / "synthetic-unpaired-delivered-cue-contrast.json")
        definition["comparisons"][0]["method"] = "paired_difference"
        definition["comparisons"][0]["effect_size"] = "median_paired_difference"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)

    def test_a_trend_requires_ordered_paired_differences(self) -> None:
        definition = read_json(ANALYSIS_DIR / "synthetic-unpaired-delivered-cue-contrast.json")
        definition["comparisons"][0]["method"] = "trend"
        definition["comparisons"][0]["effect_size"] = "theil_sen_slope"
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_definition(definition)
        self.assertIn("requires a paired design", str(error.exception))

    def test_an_effect_size_undefined_for_a_method_is_refused(self) -> None:
        definition = self._definition()
        definition["comparisons"][0]["effect_size"] = "theil_sen_slope"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_definition(definition)


class RunArtifactContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-run-contract-")
        cls.addClassCleanup(cls._directory.cleanup)
        base = Path(cls._directory.name)
        prepared = prepared_campaign(base / "demo")
        cls.run_artifact = prepared_run(prepared, base, run_id="contract-run")["run"]

    def _artifact(self) -> dict:
        return copy.deepcopy(self.run_artifact)

    def test_a_result_may_not_be_added_after_the_family_was_fixed(self) -> None:
        artifact = self._artifact()
        extra = copy.deepcopy(artifact["comparisons"][0])
        extra["comparison_id"] = "smuggled-comparison"
        artifact["comparisons"].append(extra)
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_a_declared_comparison_may_not_be_dropped(self) -> None:
        artifact = self._artifact()
        artifact["comparisons"] = artifact["comparisons"][:1]
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_an_adjusted_value_may_never_be_stronger_than_its_raw_value(self) -> None:
        artifact = self._artifact()
        entry = artifact["multiplicity"]["entries"][0]
        entry["adjusted_p_value"] = entry["raw_p_value"] / 2
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_run(artifact)
        self.assertIn("never makes evidence stronger", str(error.exception))

    def test_rejection_requires_an_adjusted_value_at_or_below_alpha(self) -> None:
        artifact = self._artifact()
        entry = next(
            item for item in artifact["multiplicity"]["entries"] if item["adjusted_p_value"] is None
        )
        entry["rejected_at_alpha"] = True
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_family_alpha_may_not_change_after_the_fact(self) -> None:
        artifact = self._artifact()
        artifact["multiplicity"]["alpha"] = 0.5
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_synthetic_evidence_may_not_declare_scientific_eligibility(self) -> None:
        artifact = self._artifact()
        artifact["scientific_eligibility"]["eligible"] = True
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_run(artifact)
        self.assertIn("permanently scientifically ineligible", str(error.exception))

    def test_an_unusable_estimate_may_not_publish_an_interval(self) -> None:
        artifact = self._artifact()
        uncertainty = artifact["comparisons"][0]["uncertainty"]
        uncertainty["usable"] = False
        uncertainty["unusable_reason"] = "Withheld."
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_confirmatory_interpretation_requires_sufficient_evidence(self) -> None:
        artifact = self._artifact()
        artifact["sufficiency"]["status"] = "insufficient"
        artifact["sufficiency"]["unmet_requirements"] = ["Not enough pairs."]
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_run(artifact)
        self.assertIn("requires sufficient evidence", str(error.exception))

    def test_an_effective_ceiling_above_the_structural_one_is_refused(self) -> None:
        artifact = self._artifact()
        artifact["interpretation"]["effective_ceiling"] = "causal_candidate"
        with self.assertRaises(ContractValidationError):
            validate_inferential_analysis_run(artifact)

    def test_a_paired_effect_must_preserve_one_raw_difference_per_pair(self) -> None:
        artifact = self._artifact()
        artifact["comparisons"][0]["effect"]["per_unit_differences"] = []
        with self.assertRaises(ContractValidationError) as error:
            validate_inferential_analysis_run(artifact)
        self.assertIn("one raw difference per pair", str(error.exception))


if __name__ == "__main__":
    unittest.main()
