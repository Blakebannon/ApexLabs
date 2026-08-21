"""Segment identity, comparability guards, and comparable evidence sets."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from _support import (
    BUILT_AT,
    ROOT,
    SEGMENT_DIR,
    all_files,
    prepared_campaign,
)

from apex_labs.errors import ContractValidationError, EvidenceError, IntegrityError
from apex_labs.campaigns import campaign_paths, materialize
from apex_labs.evidence import build_evidence_set, verify_evidence_set
from apex_labs.evidence import comparability as comparability_module
from apex_labs.evidence import segments as segment_module
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import sha256_bytes
from apex_labs.schemas import (
    validate_evidence_set,
    validate_evidence_set_definition,
    validate_experiment,
    validate_segment_definition,
)

CORNER_A = SEGMENT_DIR / "synthetic-corner-a.json"


def _segment(**overrides) -> dict:
    segment = copy.deepcopy(read_json(CORNER_A))
    segment.update(overrides)
    return segment


class SegmentIdentityTests(unittest.TestCase):
    def test_checked_in_segments_are_contract_valid(self) -> None:
        for path in sorted(SEGMENT_DIR.glob("*.json")):
            with self.subTest(segment=path.name):
                validate_segment_definition(read_json(path))

    def test_region_membership_respects_declared_boundary_inclusivity(self) -> None:
        segment = _segment()
        self.assertTrue(segment_module.in_region(segment, 90.0), "start is declared inclusive")
        self.assertTrue(segment_module.in_region(segment, 199.999))
        self.assertFalse(segment_module.in_region(segment, 200.0), "end is declared exclusive")
        self.assertFalse(segment_module.in_region(segment, 89.999))
        self.assertFalse(segment_module.in_region(segment, None))

        closed = _segment()
        closed["region"]["boundary"] = {"start_inclusive": True, "end_inclusive": True}
        closed["boundary_sample_resolution"] = "closed_both_ends"
        validate_segment_definition(closed)
        self.assertTrue(segment_module.in_region(closed, 200.0))

    def test_wraparound_region_spans_the_start_finish_line(self) -> None:
        segment = _segment()
        segment["region"] = {
            "kind": "distance_range",
            "start": 950.0,
            "end": 60.0,
            "wraparound": True,
            "lap_length_m": 1000.0,
            "boundary": {"start_inclusive": True, "end_inclusive": False},
        }
        validate_segment_definition(segment)
        self.assertTrue(segment_module.in_region(segment, 980.0))
        self.assertTrue(segment_module.in_region(segment, 10.0))
        self.assertTrue(segment_module.in_region(segment, 950.0))
        self.assertFalse(segment_module.in_region(segment, 60.0))
        self.assertFalse(segment_module.in_region(segment, 500.0))

    def test_boundary_resolution_must_agree_with_declared_inclusivity(self) -> None:
        segment = _segment()
        segment["boundary_sample_resolution"] = "closed_both_ends"
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)

    def test_a_wrapping_region_requires_a_declared_lap_length(self) -> None:
        segment = _segment()
        segment["region"] = {
            "kind": "distance_range",
            "start": 950.0,
            "end": 60.0,
            "wraparound": True,
            "lap_length_m": None,
            "boundary": {"start_inclusive": True, "end_inclusive": False},
        }
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)

    def test_a_non_wrapping_region_must_advance(self) -> None:
        segment = _segment()
        segment["region"]["start"] = 200.0
        segment["region"]["end"] = 200.0
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)

    def test_a_distance_segment_may_not_claim_catalog_corner_identity(self) -> None:
        segment = _segment()
        segment["corner_identity"] = {
            "catalog_id": "invented-catalog",
            "catalog_version": "1.0.0",
            "corner_reference": "Turn 4",
            "catalog_sha256": "a" * 64,
        }
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)

    def test_verified_corner_identity_requires_a_bound_catalog(self) -> None:
        segment = _segment()
        segment["identity_source"] = "verified_corner_identity"
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)

    def test_applicability_refuses_an_uncovered_layout(self) -> None:
        segment = _segment()
        with self.assertRaises(EvidenceError) as error:
            segment_module.applicability(
                segment, "synthetic-simulator", "synthetic-track-a", "synthetic-layout-c"
            )
        self.assertIn("does not apply to", str(error.exception))

    def test_shared_corner_name_over_different_geometry_is_refused(self) -> None:
        multi = read_json(SEGMENT_DIR / "synthetic-corner-4-multi-layout.json")
        entries = [
            segment_module.applicability(multi, "synthetic-simulator", "synthetic-track-a", layout)
            for layout in ("synthetic-layout-a", "synthetic-layout-b")
        ]
        self.assertEqual(entries[0]["geometry_fingerprint"], entries[0]["geometry_fingerprint"])
        with self.assertRaises(EvidenceError) as error:
            segment_module.require_single_geometry(entries, multi["segment_definition_id"])
        self.assertIn("geometrically different regions are never comparable", str(error.exception))
        # One layout on its own resolves to a single geometry and is accepted.
        self.assertEqual(
            segment_module.require_single_geometry(entries[:1], multi["segment_definition_id"]),
            entries[0]["geometry_fingerprint"],
        )

    def test_unavailable_values_count_as_missing_coverage_not_as_zero(self) -> None:
        segment = _segment()
        segment["coverage_requirements"]["required_concepts"] = ["speed"]
        present = {"fields": {"speed": {"value": 0.0, "provenance": "measured", "unit": "m/s"}}}
        absent = {"fields": {"speed": {"value": None, "provenance": "unavailable", "unit": "m/s"}}}
        ratio, counts = segment_module.concept_coverage(segment, [present, present, absent, absent])
        self.assertEqual(ratio, 0.5)
        self.assertEqual(counts["speed"], 2)

    def test_a_phase_only_selects_records_meeting_its_reproducible_rule(self) -> None:
        segment = _segment()
        segment["phase"] = {
            "phase_id": "braking",
            "method_id": "apex-labs.threshold-phase/1.0.0",
            "definition": "Records inside the region whose brake value is at or above 0.5.",
            "deterministic": True,
            "concept": "brake",
            "comparison": "at_or_above",
            "threshold": 0.5,
        }
        validate_segment_definition(segment)
        braking = {
            "record_type": "telemetry_sample",
            "fields": {
                "lap_distance": {"value": 120.0, "provenance": "measured", "unit": "m"},
                "brake": {"value": 0.9, "provenance": "measured", "unit": "ratio"},
            },
        }
        coasting = copy.deepcopy(braking)
        coasting["fields"]["brake"]["value"] = 0.1
        self.assertTrue(segment_module.selects(segment, braking))
        self.assertFalse(segment_module.selects(segment, coasting))

    def test_a_phase_method_other_than_the_supported_one_is_refused(self) -> None:
        segment = _segment()
        segment["phase"] = {
            "phase_id": "braking",
            "method_id": "someones.private-heuristic/9.9.9",
            "definition": "An undocumented heuristic.",
            "deterministic": True,
            "concept": "brake",
            "comparison": "at_or_above",
            "threshold": 0.5,
        }
        with self.assertRaises(ContractValidationError):
            validate_segment_definition(segment)


class ComparabilityGuardTests(unittest.TestCase):
    @staticmethod
    def _definition() -> dict:
        return read_json(ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json")

    @staticmethod
    def _key(**overrides) -> dict:
        key = {
            "participant": "synthetic-driver-001",
            "simulator": "synthetic-simulator",
            "car": "synthetic-car-a",
            "track": "synthetic-track-a",
            "layout": "synthetic-layout-a",
            "protocol_version": "1.0.0",
            "condition_semantics": "synthetic-baseline",
            "coaching_state": "disabled",
            "configuration_identity": "sha256:" + "a" * 64,
            "segment_definition": "synthetic-corner-a@1.0.0",
            "metric_definition": "segment-minimum-speed@1.0.0",
            "normalization_contract": "1.2.0/tabular-csv@1.1.0",
            "product_build": "sha256:" + "b" * 64,
        }
        key.update(overrides)
        return key

    def test_matching_evidence_from_both_arms_is_adequate_or_limited(self) -> None:
        result = comparability_module.assess(
            self._definition(),
            [self._key(), self._key(condition_semantics="synthetic-intervention", coaching_state="enabled")],
            {"baseline", "intervention"},
        )
        self.assertIn(result["status"], {"adequate", "limited"})
        self.assertEqual(result["violations"], [])

    def test_incompatible_evidence_is_refused_for_every_guarded_field(self) -> None:
        definition = self._definition()
        baseline = self._key()
        for field, value, subject in (
            ("participant", "synthetic-driver-002", "drivers"),
            ("simulator", "other-simulator", "simulators"),
            ("car", "synthetic-car-b", "cars"),
            ("track", "synthetic-track-b", "tracks"),
            ("layout", "synthetic-layout-b", "track layouts"),
            ("protocol_version", "2.0.0", "protocol versions"),
            ("segment_definition", "other-segment@1.0.0", "segment definitions"),
            ("metric_definition", "other-metric@1.0.0", "metric definitions"),
            ("normalization_contract", "9.9.9/other@1.0.0", "sampling/normalization contracts"),
            ("configuration_identity", "sha256:" + "c" * 64, "configuration/setup states"),
            ("product_build", "sha256:" + "d" * 64, "product builds"),
        ):
            with self.subTest(field=field):
                other = self._key(
                    condition_semantics="synthetic-intervention", coaching_state="enabled", **{field: value}
                )
                with self.assertRaises(EvidenceError) as error:
                    comparability_module.assess(definition, [baseline, other], {"baseline", "intervention"})
                message = str(error.exception)
                self.assertIn("may not be combined across incompatible", message)
                self.assertIn(subject, message)

    def test_a_single_arm_is_an_inadequate_contrast(self) -> None:
        result = comparability_module.assess(self._definition(), [self._key()], {"baseline"})
        self.assertEqual(result["status"], "inadequate")
        self.assertTrue(any("arm is represented" in item for item in result["violations"]))

    def test_every_guarded_field_must_be_declared(self) -> None:
        definition = self._definition()
        definition["comparability"]["must_match"] = ["participant"]
        definition["comparability"]["permitted_variation"] = []
        with self.assertRaises(EvidenceError) as error:
            comparability_module.assess(definition, [self._key()], {"baseline", "intervention"})
        self.assertIn("neither required to match nor explicitly permitted to vary", str(error.exception))

    def test_permitted_variation_is_preserved_as_a_stated_limitation(self) -> None:
        definition = self._definition()
        definition["comparability"]["must_match"].remove("track")
        definition["comparability"]["permitted_variation"].append(
            {
                "field": "track",
                "justification": "A preregistered nuisance variation used by this guard test.",
                "retained_as": "limitation",
            }
        )
        result = comparability_module.assess(
            definition,
            [
                self._key(),
                self._key(
                    condition_semantics="synthetic-intervention",
                    coaching_state="enabled",
                    track="synthetic-track-b",
                ),
            ],
            {"baseline", "intervention"},
        )
        self.assertTrue(any("track was permitted to vary" in item for item in result["limitations"]))
        self.assertIn("condition_semantics", result["covariate_fields"])

    def test_missing_configuration_identity_is_not_a_match(self) -> None:
        result = comparability_module.assess(
            self._definition(),
            [
                self._key(configuration_identity=None),
                self._key(
                    condition_semantics="synthetic-intervention",
                    coaching_state="enabled",
                    configuration_identity=None,
                ),
            ],
            {"baseline", "intervention"},
        )
        self.assertEqual("limited", result["status"])
        self.assertTrue(result["identity_limitations"])
        self.assertTrue(any("could not be verified as matching" in item for item in result["violations"]))

    def test_protected_variation_requires_a_structured_frozen_protocol_plan(self) -> None:
        definition = self._definition()
        definition["comparability"]["must_match"].remove("product_build")
        definition["comparability"]["permitted_variation"].append(
            {
                "field": "product_build",
                "justification": "The future protocol studies a build factor.",
                "retained_as": "covariate",
            }
        )
        with self.assertRaises(ContractValidationError):
            validate_evidence_set_definition(definition)

        definition["comparability"]["permitted_variation"][-1][
            "protocol_variation_plan_id"
        ] = "future-build-plan"
        validate_evidence_set_definition(definition)
        protocol = read_json(ROOT / "protocols" / "synthetic-inference-controlled.json")
        protocol["identity_variation_plans"] = [
            {
                "plan_id": "future-build-plan",
                "field": "product_build",
                "varying_factor": "assigned-build",
                "rationale": "A future protocol explicitly studies build variation.",
                "assignment_or_balancing": "Build is counterbalanced across blocks.",
                "analysis_handling": "Build enters the preregistered contrast as a factor.",
                "confounding_implications": "Build effects cannot be separated from unmeasured build changes.",
                "interpretation_ceiling": "associational",
            }
        ]
        validate_experiment(protocol)
        self.assertEqual(
            ["associational"],
            comparability_module.identity_variation_limits(definition, protocol),
        )

    def test_mismatched_build_or_setup_is_refused_before_confirmatory_analysis(self) -> None:
        for field, value in (
            ("configuration_identity", "synthetic-other-setup-v1"),
            ("product_build_identity", "synthetic-other-build-v1"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                spec = read_json(ROOT / "research" / "campaigns" / "clear-paired-improvement.campaign.json")
                spec["datasets"][1][field] = value
                paths = campaign_paths(spec, ROOT)
                datasets = materialize(spec, base / "campaign", ROOT)
                with self.assertRaises(EvidenceError) as error:
                    build_evidence_set(
                        paths["evidence_definition"], paths["segment"], paths["protocol_freeze"],
                        paths["metric"], datasets, base / "evidence", built_at=BUILT_AT,
                        project_root=ROOT,
                    )
                self.assertIn("may not be combined across incompatible", str(error.exception))

    def test_missing_setup_identity_caps_a_counterbalanced_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            spec = read_json(ROOT / "research" / "campaigns" / "counterbalanced-causal-candidate.campaign.json")
            for dataset in spec["datasets"]:
                dataset["configuration_identity"] = None
            paths = campaign_paths(spec, ROOT)
            datasets = materialize(spec, base / "campaign", ROOT)
            evidence = build_evidence_set(
                paths["evidence_definition"], paths["segment"], paths["protocol_freeze"],
                paths["metric"], datasets, base / "evidence", built_at=BUILT_AT,
                project_root=ROOT,
            )
            self.assertEqual("limited", evidence["comparability"]["status"])
            self.assertEqual("intervention_associated", evidence["structural_interpretation_ceiling"])
            self.assertTrue(evidence["comparability"]["identity_limitations"])

    def test_single_arm_remains_valid_descriptive_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            spec = read_json(ROOT / "research" / "campaigns" / "clear-paired-improvement.campaign.json")
            baseline_condition = spec["datasets"][0]["condition_id"]
            spec["datasets"] = [
                dataset for dataset in spec["datasets"] if dataset["condition_id"] == baseline_condition
            ]
            paths = campaign_paths(spec, ROOT)
            datasets = materialize(spec, base / "campaign", ROOT)
            evidence = build_evidence_set(
                paths["evidence_definition"], paths["segment"], paths["protocol_freeze"],
                paths["metric"], datasets, base / "evidence", built_at=BUILT_AT,
                project_root=ROOT,
            )
            self.assertEqual("inadequate", evidence["comparability"]["status"])
            self.assertEqual("descriptive", evidence["structural_interpretation_ceiling"])


class EvidenceSetConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-evidence-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.prepared = prepared_campaign(cls.base / "demo")
        cls.evidence = cls.prepared["evidence"]

    def _rebuild(self, output: Path, **overrides):
        arguments = {
            "definition_path": self.prepared["paths"]["evidence_definition"],
            "segment_path": self.prepared["paths"]["segment"],
            "protocol_freeze_path": self.prepared["paths"]["protocol_freeze"],
            "metric_path": self.prepared["paths"]["metric"],
            "dataset_dirs": self.prepared["dataset_dirs"],
        }
        arguments.update(overrides)
        return build_evidence_set(
            arguments["definition_path"],
            arguments["segment_path"],
            arguments["protocol_freeze_path"],
            arguments["metric_path"],
            arguments["dataset_dirs"],
            output,
            built_at=BUILT_AT,
            project_root=ROOT,
        )

    def test_build_is_byte_deterministic_and_contract_valid(self) -> None:
        second = self._rebuild(self.base / "second")
        self.assertEqual(self.evidence, second)
        self.assertEqual(
            all_files(self.prepared["evidence_dir"]), all_files(self.base / "second")
        )
        validate_evidence_set(read_json(self.prepared["evidence_dir"] / "evidence-set.json"))
        self.assertEqual(
            self.evidence["classification"], "comparable_evidence_not_scientific_evidence"
        )

    def test_dataset_order_does_not_change_the_evidence_set(self) -> None:
        reordered = self._rebuild(
            self.base / "reordered", dataset_dirs=list(reversed(self.prepared["dataset_dirs"]))
        )
        self.assertEqual(reordered, self.evidence)

    def test_units_sit_at_the_declared_experimental_unit_and_are_sorted(self) -> None:
        unit_ids = [unit["unit_id"] for unit in self.evidence["units"]]
        self.assertEqual(unit_ids, sorted(unit_ids))
        self.assertTrue(all(unit["unit_level"] == "lap" for unit in self.evidence["units"]))
        self.assertEqual(self.evidence["counts"]["included_units"], 36)

    def test_every_unit_preserves_its_source_accounting_and_within_unit_spread(self) -> None:
        for unit in self.evidence["units"]:
            self.assertEqual(
                unit["source_records_used"] + unit["source_records_missing"],
                unit["source_records_considered"],
            )
            self.assertIsNotNone(unit["within_unit_dispersion"])
            self.assertIn("lap_number", unit["covariates"])
            self.assertIn("concept_coverage_ratio", unit["covariates"])

    def test_attrition_is_a_continuous_funnel_at_every_level(self) -> None:
        remaining: dict[str, int] = {}
        for entry in self.evidence["attrition"]:
            level = entry["level"]
            if level in remaining:
                self.assertEqual(entry["considered"], remaining[level])
            self.assertEqual(entry["considered"] - entry["excluded"], entry["remaining"])
            remaining[level] = entry["remaining"]
        stages = {entry["stage"] for entry in self.evidence["attrition"]}
        for required in (
            "records_streamed", "protocol_mismatch", "out_of_order_or_corrupt", "outside_segment",
            "invalid_lap", "missing_required_channel", "incident_affected",
            "pit_replay_discontinuity", "units_formed", "insufficient_coverage",
            "duplicate_evidence", "confound_based", "holdout_reserved", "pairable_units",
            "unpaired_units",
        ):
            self.assertIn(required, stages)

    def test_pairs_are_within_bucket_and_clustered_by_block_pair(self) -> None:
        by_id = {unit["unit_id"]: unit for unit in self.evidence["units"]}
        self.assertEqual(self.evidence["counts"]["pairs"], 18)
        for pair in self.evidence["pairs"]:
            baseline = by_id[pair["baseline_unit_id"]]
            intervention = by_id[pair["intervention_unit_id"]]
            self.assertEqual(baseline["arm"], "baseline")
            self.assertEqual(intervention["arm"], "intervention")
            self.assertEqual(baseline["pair_key"], intervention["pair_key"])
            self.assertEqual(baseline["order_index"], intervention["order_index"])
            self.assertEqual(
                pair["cluster_id"], f"{baseline['block_id']}+{intervention['block_id']}"
            )
        # Three block pairs, not six blocks: a pair is one independent replicate.
        self.assertEqual(self.evidence["counts"]["resampling_clusters"], 3)

    def test_structural_ceiling_is_read_from_the_frozen_protocol(self) -> None:
        self.assertEqual(
            self.evidence["structural_interpretation_ceiling"], "intervention_associated"
        )
        self.assertEqual(self.evidence["protocol"]["randomization_strategy"], "fixed")
        self.assertEqual(self.evidence["protocol"]["collection_classification"], "experimental")

    def test_verification_rebuilds_rather_than_rehashing(self) -> None:
        result = verify_evidence_set(
            self.prepared["evidence_dir"],
            self.prepared["paths"]["evidence_definition"],
            self.prepared["paths"]["segment"],
            self.prepared["paths"]["protocol_freeze"],
            self.prepared["paths"]["metric"],
            self.prepared["dataset_dirs"],
            project_root=ROOT,
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["included_units"], 36)

    def test_tampering_with_the_stored_evidence_set_is_detected(self) -> None:
        tampered_dir = self.base / "tampered"
        tampered_dir.mkdir()
        artifact = copy.deepcopy(self.evidence)
        artifact["units"][0]["value"] = 99.0
        write_json(tampered_dir / "evidence-set.json", artifact)
        with self.assertRaises(IntegrityError) as error:
            verify_evidence_set(
                tampered_dir,
                self.prepared["paths"]["evidence_definition"],
                self.prepared["paths"]["segment"],
                self.prepared["paths"]["protocol_freeze"],
                self.prepared["paths"]["metric"],
                self.prepared["dataset_dirs"],
                project_root=ROOT,
            )
        self.assertIn("hash does not match", str(error.exception))

    def test_tampering_with_a_bound_dataset_is_detected(self) -> None:
        import shutil

        copied = self.base / "tampered-dataset"
        shutil.copytree(self.prepared["dataset_dirs"][0], copied)
        records = (copied / "records.jsonl").read_text(encoding="utf-8")
        (copied / "records.jsonl").write_text(records.replace("34.0", "44.0", 1), encoding="utf-8")
        datasets = [copied] + list(self.prepared["dataset_dirs"][1:])
        with self.assertRaises((IntegrityError, ContractValidationError)):
            verify_evidence_set(
                self.prepared["evidence_dir"],
                self.prepared["paths"]["evidence_definition"],
                self.prepared["paths"]["segment"],
                self.prepared["paths"]["protocol_freeze"],
                self.prepared["paths"]["metric"],
                datasets,
                project_root=ROOT,
            )

    def test_a_segment_whose_hash_does_not_match_the_binding_is_refused(self) -> None:
        altered = self.base / "altered-segment.json"
        segment = read_json(self.prepared["paths"]["segment"])
        segment["title"] = segment["title"] + " (edited)"
        write_json(altered, segment)
        with self.assertRaises(IntegrityError):
            self._rebuild(self.base / "altered-segment-out", segment_path=altered)

    def test_a_metric_whose_hash_does_not_match_the_binding_is_refused(self) -> None:
        altered = self.base / "altered-metric.json"
        metric = read_json(self.prepared["paths"]["metric"])
        metric["definition"] = metric["definition"] + " (edited)"
        write_json(altered, metric)
        with self.assertRaises(IntegrityError):
            self._rebuild(self.base / "altered-metric-out", metric_path=altered)

    def test_output_directory_is_never_overwritten(self) -> None:
        with self.assertRaises(EvidenceError) as error:
            self._rebuild(self.prepared["evidence_dir"])
        self.assertIn("already exists", str(error.exception))

    def test_a_failed_build_leaves_no_partial_output(self) -> None:
        target = self.base / "atomic-failure"
        altered = self.base / "atomic-metric.json"
        metric = read_json(self.prepared["paths"]["metric"])
        metric["name"] = "Edited"
        write_json(altered, metric)
        with self.assertRaises(IntegrityError):
            self._rebuild(target, metric_path=altered)
        self.assertFalse(target.exists(), "a refused build must not leave a directory behind")

    def test_holdout_units_are_flagged_and_never_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-holdout-") as directory:
            prepared = prepared_campaign(Path(directory), "holdout-fails-to-replicate")
            evidence = prepared["evidence"]
            self.assertEqual(evidence["counts"]["holdout_units"], 24)
            self.assertEqual(
                sorted(evidence["holdout"]["reserved_unit_ids"]),
                sorted(unit["unit_id"] for unit in evidence["units"] if unit["holdout"]),
            )
            self.assertTrue(evidence["holdout"]["primary_scope_excludes_holdout"])
            reserved = set(evidence["holdout"]["reserved"])
            for unit in evidence["units"]:
                self.assertEqual(unit["holdout"], unit["block_id"] in reserved)


class PseudoreplicationGuardTests(unittest.TestCase):
    @staticmethod
    def _definition() -> dict:
        return read_json(ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json")

    def test_frames_and_events_are_refused_as_experimental_units(self) -> None:
        for level in ("telemetry_frame", "event"):
            with self.subTest(level=level):
                definition = self._definition()
                definition["experimental_unit"] = level
                with self.assertRaises(ContractValidationError) as error:
                    validate_evidence_set_definition(definition)
                self.assertIn("never independent experimental units", str(error.exception))

    def test_resampling_below_the_experimental_unit_is_refused(self) -> None:
        definition = self._definition()
        definition["resampling_unit"] = "segment_opportunity"
        with self.assertRaises(ContractValidationError) as error:
            validate_evidence_set_definition(definition)
        self.assertIn("at or above the experimental unit", str(error.exception))

    def test_resampling_below_the_factor_variation_level_is_refused(self) -> None:
        # The condition varies between blocks, so resampling laps would treat
        # nested laps as independent evidence about a block-level intervention.
        definition = self._definition()
        definition["resampling_unit"] = "lap"
        with self.assertRaises(ContractValidationError) as error:
            validate_evidence_set_definition(definition)
        self.assertIn("factor varies", str(error.exception))

    def test_a_summarized_unit_must_preserve_within_unit_variability(self) -> None:
        definition = self._definition()
        definition["aggregation"]["dispersion"] = "not_applicable"
        with self.assertRaises(ContractValidationError) as error:
            validate_evidence_set_definition(definition)
        self.assertIn("within-unit variability", str(error.exception))

    def test_an_unsupported_experimental_unit_is_refused_by_the_builder(self) -> None:
        definition = self._definition()
        definition["experimental_unit"] = "stint"
        definition["resampling_unit"] = "block"
        validate_evidence_set_definition(definition)
        with tempfile.TemporaryDirectory(prefix="apex-labs-stint-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo")
            altered = base / "stint-definition.json"
            write_json(altered, definition)
            with self.assertRaises(EvidenceError) as error:
                build_evidence_set(
                    altered,
                    prepared["paths"]["segment"],
                    prepared["paths"]["protocol_freeze"],
                    prepared["paths"]["metric"],
                    prepared["dataset_dirs"],
                    base / "out",
                    built_at=BUILT_AT,
                    project_root=ROOT,
                )
            self.assertIn("no normalized v1 representation", str(error.exception))


class EvidenceDefinitionContractTests(unittest.TestCase):
    def test_checked_in_definitions_are_contract_valid(self) -> None:
        paths = sorted((ROOT / "research" / "evidence-sets").glob("*.json"))
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            with self.subTest(definition=path.name):
                validate_evidence_set_definition(read_json(path))

    def test_a_paired_design_must_not_carry_an_unpaired_justification(self) -> None:
        definition = read_json(ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json")
        definition["pairing"]["unpaired_justification"] = "Because it is convenient."
        with self.assertRaises(ContractValidationError):
            validate_evidence_set_definition(definition)

    def test_an_unpaired_design_must_justify_itself(self) -> None:
        definition = read_json(ROOT / "research" / "evidence-sets" / "synthetic-unpaired-delivered-cue.json")
        self.assertIsInstance(definition["pairing"]["unpaired_justification"], str)
        definition["pairing"]["unpaired_justification"] = None
        with self.assertRaises(ContractValidationError):
            validate_evidence_set_definition(definition)

    def test_a_condition_may_belong_to_only_one_arm(self) -> None:
        definition = read_json(ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed.json")
        definition["factor"]["arms"][1]["condition_ids"] = definition["factor"]["arms"][0]["condition_ids"]
        with self.assertRaises(ContractValidationError):
            validate_evidence_set_definition(definition)

    def test_a_reserved_holdout_policy_requires_reserved_identifiers(self) -> None:
        definition = read_json(
            ROOT / "research" / "evidence-sets" / "synthetic-paired-corner-speed-holdout.json"
        )
        definition["holdout"]["reserved"] = []
        with self.assertRaises(ContractValidationError):
            validate_evidence_set_definition(definition)

    def test_definition_hashes_bound_by_analyses_match_their_files(self) -> None:
        for path in sorted((ROOT / "research" / "analyses").glob("*.json")):
            definition = read_json(path)
            if definition["schema_version"] != "apex-labs.inferential-analysis-definition/v1":
                continue
            evidence_id = definition["evidence_set"]["evidence_set_id"]
            evidence = read_json(ROOT / "research" / "evidence-sets" / f"{evidence_id}.json")
            with self.subTest(analysis=path.name):
                self.assertEqual(
                    definition["evidence_set"]["definition_sha256"],
                    sha256_bytes(canonical_json_bytes(evidence)),
                )


if __name__ == "__main__":
    unittest.main()
