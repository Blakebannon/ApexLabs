"""Known-answer campaigns, the full scientific path, and its command-line surface."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import CAMPAIGN_DIR, ROOT, run_cli

from apex_labs.campaigns import (
    campaign_specs,
    regenerate_reference_artifacts,
    run_campaign,
    validate_campaign_spec,
)
from apex_labs.errors import ContractValidationError
from apex_labs.io import read_json
from apex_labs.science_demo import verify_science_demo

EXPECTED_CAMPAIGNS = {
    "clear-paired-improvement",
    "counterbalanced-causal-candidate",
    "delivered-versus-undelivered-cue",
    "exploratory-multiple-comparisons",
    "holdout-fails-to-replicate",
    "insufficient-sample-requirement",
    "measured-zero-versus-unavailable",
    "missing-and-unbalanced-pairs",
    "no-meaningful-effect",
    "observational-association-only",
    "outlier-driven-effect",
    "same-corner-number-incompatible-layouts",
    "segment-mismatch-refused",
}


class CampaignInventoryTests(unittest.TestCase):
    def test_every_expected_scenario_is_checked_in_and_valid(self) -> None:
        found = {path.name.removesuffix(".campaign.json") for path in campaign_specs(ROOT)}
        self.assertEqual(found, EXPECTED_CAMPAIGNS)
        for path in campaign_specs(ROOT):
            with self.subTest(campaign=path.name):
                spec = validate_campaign_spec(read_json(path))
                self.assertTrue(spec["synthetic"])
                self.assertTrue(spec["expectations"].get("notes"))

    def test_no_campaign_can_claim_scientific_or_product_standing(self) -> None:
        for path in campaign_specs(ROOT):
            spec = read_json(path)
            expectations = spec["expectations"]
            with self.subTest(campaign=spec["campaign_id"]):
                self.assertNotIn(
                    expectations.get("scientific_eligibility"), (True,),
                    "no fabricated campaign may expect scientific eligibility",
                )
                self.assertEqual("none", expectations.get("product_recommendation"))


class ReferenceRegenerationTests(unittest.TestCase):
    def test_reference_regeneration_is_atomic_complete_and_clean_commit_bound(self) -> None:
        identity = {
            "package_version": "0.3.0",
            "git_commit": "1" * 40,
            "git_state": "clean",
            "code_and_schema_sha256": "2" * 64,
            "schema_sha256": {"contracts/v1/experiment.schema.json": "3" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "references"
            result = regenerate_reference_artifacts(ROOT, output, code_identity=identity)
            self.assertEqual(19, result["count"])
            self.assertEqual(result["count"], len(result["artifacts"]))
            self.assertTrue(all((output / path).is_file() for path in result["artifacts"]))
            for path in sorted((output / "research/campaigns/frozen").glob("*.json")):
                self.assertEqual(identity, read_json(path)["code_identity"])
            with self.assertRaises(ContractValidationError):
                regenerate_reference_artifacts(ROOT, output, code_identity=identity)

            dirty = {**identity, "git_state": "dirty"}
            with self.assertRaises(ContractValidationError):
                regenerate_reference_artifacts(
                    ROOT, Path(directory) / "dirty-references", code_identity=dirty
                )


class CampaignKnownAnswerTests(unittest.TestCase):
    """Each campaign is run against the expectations worked out by hand."""

    def _run(self, campaign_id: str) -> dict:
        with tempfile.TemporaryDirectory(prefix=f"apex-labs-{campaign_id}-") as directory:
            return run_campaign(
                CAMPAIGN_DIR / f"{campaign_id}.campaign.json", Path(directory), ROOT, project_root=ROOT
            )

    def test_clear_paired_improvement(self) -> None:
        result = self._run("clear-paired-improvement")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["primary"]["estimate"], 0.5)
        self.assertEqual(observed["primary"]["interval"], [0.25, 0.5])
        self.assertTrue(observed["primary"]["rejected_at_alpha"])
        self.assertTrue(all(value == "robust" for value in observed["sensitivity"].values()))

    def test_no_meaningful_effect(self) -> None:
        result = self._run("no-meaningful-effect")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["primary"]["estimate"], 0.0)
        self.assertEqual(observed["primary"]["raw_p_value"], 1.0)
        self.assertFalse(observed["primary"]["estimate_exceeds_threshold"])

    def test_outlier_driven_effect(self) -> None:
        result = self._run("outlier-driven-effect")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        # The mean crosses the practical threshold while the sign test sees nothing.
        self.assertEqual(observed["primary"]["estimate"], 0.5)
        self.assertTrue(observed["primary"]["estimate_exceeds_threshold"])
        self.assertEqual(observed["primary"]["raw_p_value"], 1.0)
        self.assertEqual(observed["sensitivity"]["outlier-dependence"], "fragile")

    def test_missing_and_unbalanced_pairs(self) -> None:
        result = self._run("missing-and-unbalanced-pairs")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["evidence"]["pairs"], 9)
        self.assertEqual(observed["evidence"]["unpaired_units"], 9)
        self.assertFalse(observed["condition_balanced"])

    def test_insufficient_sample_requirement(self) -> None:
        result = self._run("insufficient-sample-requirement")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["analysis_state"], "inconclusive")
        self.assertEqual(observed["sufficiency"], "insufficient")
        self.assertEqual(observed["effective_ceiling"], "descriptive")
        self.assertFalse(observed["confirmatory_permitted"])

    def test_observational_association_only(self) -> None:
        result = self._run("observational-association-only")
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["observed"]["evidence"]["structural_ceiling"], "associational")
        self.assertEqual(result["observed"]["effective_ceiling"], "associational")
        self.assertIn(
            "stronger interpretation than the design permits is refused",
            result["refused_ceiling_reason"],
        )

    def test_delivered_versus_undelivered_cue(self) -> None:
        result = self._run("delivered-versus-undelivered-cue")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["primary_method"], "unpaired_difference")
        self.assertEqual(observed["evidence"]["pairs"], 0)
        self.assertEqual(observed["evidence"]["unpaired_units"], 30)

    def test_exploratory_multiple_comparisons(self) -> None:
        result = self._run("exploratory-multiple-comparisons")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["minimum_raw_p_value"], 0.03125)
        self.assertEqual(observed["minimum_adjusted_p_value"], 0.1875)
        self.assertFalse(observed["any_rejected_at_alpha"])

    def test_holdout_fails_to_replicate(self) -> None:
        result = self._run("holdout-fails-to-replicate")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["primary"]["estimate"], 0.5)
        self.assertEqual(observed["replication"]["estimate"], 0.0)
        self.assertFalse(observed["replication"]["estimate_exceeds_threshold"])
        self.assertIsNotNone(result["replication_run_sha256"])

    def test_segment_mismatch_is_refused(self) -> None:
        result = self._run("segment-mismatch-refused")
        self.assertEqual(result["outcome"], "evidence_refused")
        self.assertEqual(result["mismatches"], [])
        self.assertIn("does not apply to", result["reason"])

    def test_same_corner_number_on_incompatible_layouts_is_refused(self) -> None:
        result = self._run("same-corner-number-incompatible-layouts")
        self.assertEqual(result["outcome"], "evidence_refused")
        self.assertEqual(result["mismatches"], [])
        self.assertIn("geometrically different regions are never comparable", result["reason"])

    def test_measured_zero_is_not_an_unavailable_value(self) -> None:
        result = self._run("measured-zero-versus-unavailable")
        self.assertEqual(result["mismatches"], [])
        observed = result["observed"]
        self.assertEqual(observed["zero_valued_units"], 6, "fabricated zeros are real observations")
        self.assertEqual(
            observed["missing_required_channel_records"], 30, "unavailable values are attrition"
        )
        self.assertEqual(observed["evidence"]["baseline_units"], 12)
        self.assertEqual(observed["evidence"]["intervention_units"], 6)

    def test_counterbalanced_design_reaches_the_causal_candidate_ceiling(self) -> None:
        result = self._run("counterbalanced-causal-candidate")
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["observed"]["effective_ceiling"], "causal_candidate")
        # Even the strongest available ceiling promotes nothing synthetic.
        self.assertFalse(result["observed"]["scientific_eligibility"])
        self.assertEqual(result["product_recommendation"], "none")


class ScienceDemoTests(unittest.TestCase):
    def test_the_whole_scientific_path_reproduces_and_promotes_nothing(self) -> None:
        result = verify_science_demo(ROOT, run_campaigns=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["deterministic_evidence"])
        self.assertTrue(result["deterministic_inference"])
        self.assertTrue(result["deterministic_review_package"])
        self.assertTrue(result["review_package_verified"])
        self.assertEqual(result["hypothesis_state"], "replication_required")
        self.assertEqual(result["finding_status"], "inconclusive")
        self.assertEqual(result["scientific_gate"], "unresolved")
        self.assertFalse(result["scientific_promotion_eligible"])
        self.assertEqual(result["product_recommendation"], "do_not_implement")
        self.assertFalse(result["automatic_production_change"])
        self.assertEqual(result["classification"], "synthetic_demo_only_not_racing_research")

    def test_the_demo_is_reproducible_across_invocations(self) -> None:
        first = verify_science_demo(ROOT, run_campaigns=False)
        second = verify_science_demo(ROOT, run_campaigns=False)
        for key in ("evidence_set_sha256", "run_sha256", "package_sha256"):
            self.assertEqual(first[key], second[key])


class ScienceCommandLineTests(unittest.TestCase):
    def test_new_contracts_are_validatable_from_the_command_line(self) -> None:
        cases = [
            ("segment-definition", "research/segments/synthetic-corner-a.json"),
            ("evidence-set-definition", "research/evidence-sets/synthetic-paired-corner-speed.json"),
            (
                "inferential-analysis-definition",
                "research/analyses/synthetic-paired-corner-speed-confirmatory.json",
            ),
        ]
        for kind, path in cases:
            with self.subTest(kind=kind):
                result = run_cli("validate", kind, path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["valid"])

    def test_a_descriptive_definition_is_rejected_as_an_inferential_one(self) -> None:
        result = run_cli(
            "validate",
            "inferential-analysis-definition",
            "research/analyses/synthetic-demo-descriptive.json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)

    def test_campaign_list_and_verify_round_trip(self) -> None:
        listed = run_cli("campaign", "list", "--root", str(ROOT))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertEqual(len(payload["campaigns"]), len(EXPECTED_CAMPAIGNS))
        self.assertEqual(payload["classification"], "synthetic_demo_only_not_racing_research")

        verified = run_cli(
            "campaign", "verify",
            str(CAMPAIGN_DIR / "no-meaningful-effect.campaign.json"),
            "--root", str(ROOT),
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        result = json.loads(verified.stdout)
        self.assertTrue(result["ok"])
        self.assertFalse(result["scientific_promotion_eligible"])
        self.assertEqual(result["product_recommendation"], "none")

    def test_full_command_line_round_trip_through_evidence_inference_and_lifecycle(self) -> None:
        from apex_labs.campaigns import materialize

        with tempfile.TemporaryDirectory(prefix="apex-labs-cli-round-trip-") as directory:
            workspace = Path(directory)
            spec = read_json(CAMPAIGN_DIR / "clear-paired-improvement.campaign.json")
            dataset_dirs = materialize(spec, workspace, ROOT)
            datasets: list[str] = []
            for path in dataset_dirs:
                datasets.extend(["--dataset", str(path)])
            segment = str(ROOT / "research" / "segments" / "synthetic-corner-a.json")
            freeze = str(
                ROOT / "research" / "campaigns" / "frozen" / "synthetic-inference-controlled.freeze.json"
            )
            metric = str(ROOT / "research" / "metrics" / "segment-minimum-speed.json")
            definition = str(
                ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json"
            )
            analysis = str(
                ROOT / "research" / "analyses" / "synthetic-paired-corner-speed-confirmatory.json"
            )
            evidence_dir = workspace / "evidence"
            run_dir = workspace / "run"

            built = run_cli(
                "evidence", "build", definition, "--segment", segment,
                "--protocol-freeze", freeze, "--metric", metric, *datasets,
                "--built-at", "2026-08-20T00:00:00Z", "--output", str(evidence_dir),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertTrue(json.loads(built.stdout)["ok"])

            verified = run_cli(
                "evidence", "verify", definition, "--segment", segment,
                "--protocol-freeze", freeze, "--metric", metric, *datasets, str(evidence_dir),
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["valid"])

            ran = run_cli(
                "infer", "run", analysis, "--evidence", str(evidence_dir),
                "--protocol-freeze", freeze, "--run-id", "cli-round-trip",
                "--created-at", "2026-08-20T00:00:00Z", "--output", str(run_dir),
            )
            self.assertEqual(ran.returncode, 0, ran.stderr)
            run_payload = json.loads(ran.stdout)
            self.assertEqual(run_payload["primary_estimate"], 0.5)
            self.assertFalse(run_payload["scientific_eligibility"])

            checked = run_cli(
                "infer", "verify", str(run_dir), "--evidence", str(evidence_dir),
                "--protocol-freeze", freeze,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["valid"])

            hypothesis_path = workspace / "hypothesis.json"
            hypothesis_path.write_bytes(
                json.dumps(
                    {
                        "schema_version": "apex-labs.hypothesis/v1",
                        "hypothesis_id": "cli-round-trip-hypothesis",
                        "version": "1.0.0",
                        "created_at": "2026-08-20T00:00:00Z",
                        "synthetic": True,
                        "title": "Command-line round trip",
                        "statement": "Fabricated intervention laps show a higher segment minimum speed.",
                        "null_statement": "Fabricated intervention laps show no difference.",
                        "scientific_question": "Does the command-line lifecycle behave as declared?",
                        "scope": "session_specific",
                        "generation": {
                            "source": "deterministic_algorithm",
                            "actor": "apex-labs.tests",
                            "detail": "Written by the test suite.",
                            "is_evidence": False,
                        },
                        "hypothesis_sha256": "0" * 64,
                    }
                ).encode("utf-8")
            )
            registry = workspace / "registry"
            registered = run_cli(
                "hypothesis", "register", str(hypothesis_path), "--registry", str(registry),
                "--recorded-at", "2026-08-20T00:00:00Z",
            )
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertEqual(json.loads(registered.stdout)["state"], "generated")

            skipped = run_cli(
                "hypothesis", "transition", "cli-round-trip-hypothesis", "--registry", str(registry),
                "--to-state", "tested", "--rationale", "Skipping ahead.",
                "--recorded-at", "2026-08-20T01:00:00Z",
            )
            self.assertEqual(skipped.returncode, 2)
            self.assertIn("does not permit a transition", skipped.stderr)

            ready = run_cli(
                "hypothesis", "transition", "cli-round-trip-hypothesis", "--registry", str(registry),
                "--to-state", "analysis_ready", "--rationale", "Frozen before the run.",
                "--recorded-at", "2026-08-20T01:00:00Z", "--evidence", str(evidence_dir),
                "--analysis-definition", analysis,
            )
            self.assertEqual(ready.returncode, 0, ready.stderr)

            tested = run_cli(
                "hypothesis", "transition", "cli-round-trip-hypothesis", "--registry", str(registry),
                "--to-state", "tested", "--rationale", "Ran once and recomputed.",
                "--recorded-at", "2026-08-20T02:00:00Z", "--evidence", str(evidence_dir),
                "--run", str(run_dir), "--protocol-freeze", freeze, "--reviewer-state", "pending",
            )
            self.assertEqual(tested.returncode, 0, tested.stderr)

            state = run_cli(
                "hypothesis", "state", "cli-round-trip-hypothesis", "--registry", str(registry)
            )
            self.assertEqual(state.returncode, 0, state.stderr)
            self.assertEqual(json.loads(state.stdout)["state"], "tested")

            registry_check = run_cli("hypothesis", "verify", "--registry", str(registry))
            self.assertEqual(registry_check.returncode, 0, registry_check.stderr)
            self.assertTrue(json.loads(registry_check.stdout)["valid"])

            # A second build into the same directory is refused rather than overwriting.
            again = run_cli(
                "evidence", "build", definition, "--segment", segment,
                "--protocol-freeze", freeze, "--metric", metric, *datasets,
                "--built-at", "2026-08-20T00:00:00Z", "--output", str(evidence_dir),
            )
            self.assertEqual(again.returncode, 2)
            self.assertIn("already exists", again.stderr)

    def test_science_demo_runs_from_the_command_line(self) -> None:
        result = run_cli("verify-science-demo", "--root", str(ROOT), "--skip-campaigns")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["product_recommendation"], "do_not_implement")
        self.assertFalse(payload["scientific_promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
