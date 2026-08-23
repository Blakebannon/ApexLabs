"""Retrospective admission of real pilot sessions collected before any protocol freeze.

The rule these tests protect is narrow and load-bearing: a real session that nobody
planned in advance may still be normalized and described, but it can never be
mistaken for — or quietly pooled with — evidence collected under a frozen protocol.

Every test here is written against the same real (non-synthetic) recorder bundle, so
the primary gate and the exploratory door are exercised on identical bytes. That
matters: it means the difference between "refused" and "admitted as exploratory" is
the intake artifact alone, never some property of the data.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, run_cli
from recorder_bundle import FIXTURE, FIXTURE_COLLECTION, rebind

from apex_labs.errors import (
    ApexLabsError, ContractValidationError, IngestionError, IntegrityError,
)
from apex_labs.evidence.builder import EvidenceError
from apex_labs.ingestion.apex_research import ingest_research_bundle
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import sha256_bytes, sha256_file
from apex_labs.schemas import validate_exploratory_intake, validate_normalized_manifest

import shutil

PARTICIPANT = "participant-" + "ab12cd34ef56ab78cd90ef12"


def build_real_bundle(destination: Path) -> Path:
    """The committed recorder fixture, re-declared as REAL private evidence.

    Only the two declarations that decide syntheticity are changed — the privacy
    classification and the participant pseudonym shape — and the bundle is then
    re-sealed. The samples, events and channel profile stay exactly as the product
    recorder wrote them, so these tests still fail if the recorder's contract drifts.
    """
    shutil.copytree(FIXTURE, destination)
    manifest = read_json(destination / "manifest.json")
    manifest["privacy"]["classification"] = "private"
    manifest["session"]["participant_pseudonym"] = PARTICIPANT
    (destination / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    metadata = read_json(destination / "recorder-metadata.json")
    metadata["privacy"]["classification"] = "private"
    (destination / "recorder-metadata.json").write_bytes(canonical_json_bytes(metadata))
    rebind(destination)
    return destination


def build_real_collection(bundle: Path, destination: Path) -> Path:
    """An observational collection record binding the real bundle, with no protocol."""
    record = read_json(FIXTURE_COLLECTION)
    manifest = read_json(bundle / "manifest.json")
    session = manifest["session"]
    record["collection_record_id"] = "pilot-collection-record"
    record["dataset_id"] = "pilot-dataset"
    record["synthetic"] = False
    record["collection_classification"] = "observational"
    record["privacy"] = {
        "classification": "private", "pseudonymized": True, "direct_identifiers_present": False,
    }
    record["participant"]["pseudonymous_participant_id"] = session["participant_pseudonym"]
    record["protocol"] = None
    record["blocks"] = []
    record["lap_assignments"] = []
    record["source_bundle"] = {
        "schema_version": "apex-research-session-export/1.0.0",
        "sha256": sha256_bytes((bundle / "manifest.json").read_bytes()),
    }
    record["session_identity"] = {
        "simulator": session["simulator"]["id"],
        "car": session["car"]["id"],
        "track": session["track"]["id"],
        "layout": session["track"]["layout"],
        "confirmation_method": "recorder-captured live session metadata",
    }
    record["coaching"] = {"state": "disabled", "notes": "pilot fixture"}
    destination.write_bytes(canonical_json_bytes(record))
    return destination


def build_intake(bundle: Path, collection_path: Path, destination: Path, **overrides) -> Path:
    manifest = read_json(bundle / "manifest.json")
    collection = read_json(collection_path)
    intake = {
        "schema_version": "apex-labs.exploratory-intake/v1",
        "intake_id": "pilot-intake",
        "version": "1.0.0",
        "created_at": "2026-08-22T00:00:00Z",
        "synthetic": False,
        "source_session_id": manifest["session"]["session_id"],
        "source_manifest_sha256": sha256_bytes((bundle / "manifest.json").read_bytes()),
        "collection_record_id": collection["collection_record_id"],
        "collection_record_sha256": sha256_file(collection_path),
        "collection_classification": "observational",
        "eligibility": {
            "classification": "exploratory_pilot",
            "descriptive_analysis_eligible": True,
            "hypothesis_generation_eligible": True,
            "confirmatory_eligible": False,
            "causal_eligible": False,
            "primary_effect_estimate_eligible": False,
            "primary_corpus_pooling_eligible": False,
        },
        "collection_timeline": {
            "collected_before_protocol_freeze": True,
            "prospective_protocol_existed": False,
            "randomization_performed": False,
            "retained_after_outcome_known": True,
            "retention_decision_rationale": "Kept once the outcome was known; disclosed as selection bias.",
        },
        "deviations": ["No prospective plan, randomization, or schedule governed this collection."],
        "permitted_uses": ["Descriptive summaries", "Hypothesis generation"],
        "prohibited_uses": ["Confirmatory claims", "Causal claims", "Primary pooling"],
        "review": {
            "reviewer_id": "reviewer-pilot-01",
            "status": "approved_exploratory_only",
            "reviewed_at": "2026-08-22T00:00:00Z",
            "statement": "Approved for exploratory use only, after collection.",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(intake.get(key), dict):
            intake[key] = {**intake[key], **value}
        else:
            intake[key] = value
    destination.write_bytes(canonical_json_bytes(intake))
    return destination


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.bundle = build_real_bundle(self.tmp / "bundle")
        self.collection = build_real_collection(self.bundle, self.tmp / "collection-record.json")
        self.intake = build_intake(self.bundle, self.collection, self.tmp / "intake.json")

    def ingest(self, output: str = "normalized", **kwargs) -> dict:
        # integration_validation mirrors every other real-bundle test in this suite: it
        # only relaxes the clean-committed-tree requirement, which no development
        # worktree can satisfy. It never touches the protocol or intake gates, and
        # PrimaryGateTests proves exactly that.
        kwargs.setdefault("integration_validation", True)
        return ingest_research_bundle(
            self.bundle, self.tmp / output, self.collection, project_root=ROOT, **kwargs
        )


# ======================================================================
# 1-2. The primary gate is untouched.
# ======================================================================

class PrimaryGateTests(_Fixture):
    def test_real_bundle_without_protocol_or_intake_still_fails(self) -> None:
        with self.assertRaises(IngestionError) as caught:
            self.ingest()
        self.assertIn("requires --protocol-snapshot", str(caught.exception))
        self.assertFalse((self.tmp / "normalized").exists())

    def test_real_bundle_with_a_collection_protocol_but_no_snapshot_still_fails(self) -> None:
        record = read_json(self.collection)
        record["collection_classification"] = "experimental"
        record["protocol"] = {
            "freeze_id": "some-freeze", "freeze_sha256": "0" * 64,
            "experiment_id": "some-experiment", "experiment_version": "1.0.0",
            "schedule_id": "some-schedule", "schedule_sha256": "1" * 64,
            "schedule_assignment_id": "assignment-1",
        }
        record["blocks"] = [{"block_id": "b1", "condition_id": "c1", "start_lap": 0, "end_lap": 1}]
        record["lap_assignments"] = [{"lap_number": 1, "block_id": "b1"}]
        self.collection.write_bytes(canonical_json_bytes(record))
        with self.assertRaises(ApexLabsError):
            self.ingest()

    def test_protocol_and_intake_together_are_refused_as_contradictory(self) -> None:
        with self.assertRaises(IngestionError) as caught:
            self.ingest(
                protocol_snapshot_path=self.tmp / "protocol.json",
                exploratory_intake_path=self.intake,
            )
        self.assertIn("cannot be both", str(caught.exception))

    def test_no_bypass_flag_exists_on_the_cli(self) -> None:
        help_text = run_cli("apex-research", "ingest", "--help").stdout
        for forbidden in ("--force", "--skip-protocol", "--allow-missing-protocol"):
            self.assertNotIn(forbidden, help_text)

    def test_integration_validation_still_does_not_bypass_the_protocol_gate(self) -> None:
        with self.assertRaises(IngestionError) as caught:
            self.ingest(integration_validation=True)
        self.assertIn("requires --protocol-snapshot", str(caught.exception))


# ======================================================================
# 3-8. The exploratory door and the ways it must refuse.
# ======================================================================

class ExploratoryIntakeTests(_Fixture):
    def test_valid_hash_bound_intake_admits_the_session(self) -> None:
        manifest = self.ingest(exploratory_intake_path=self.intake)
        eligibility = manifest["scientific_eligibility"]
        self.assertEqual(eligibility["stratum"], "exploratory_pilot")
        self.assertTrue(eligibility["descriptive_analysis"])
        self.assertTrue(eligibility["hypothesis_generation"])
        self.assertFalse(eligibility["confirmatory"])
        self.assertFalse(eligibility["causal"])
        self.assertFalse(eligibility["primary_effect_estimate"])
        self.assertFalse(eligibility["primary_corpus_pooling"])
        self.assertTrue(eligibility["retained_after_outcome_known"])
        self.assertIsNone(manifest["collection_context"]["protocol_snapshot"])
        self.assertEqual(manifest["exploratory_intake"]["path"], "exploratory-intake.json")
        self.assertEqual(
            manifest["exploratory_intake"]["sha256"], sha256_file(self.intake)
        )
        staged = self.tmp / "normalized" / "exploratory-intake.json"
        self.assertEqual(staged.read_bytes(), self.intake.read_bytes())

    def test_missing_intake_file_fails(self) -> None:
        with self.assertRaises(OSError):
            self.ingest(exploratory_intake_path=self.tmp / "absent.json")

    def test_malformed_intake_fails(self) -> None:
        (self.tmp / "bad.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(Exception):
            self.ingest(exploratory_intake_path=self.tmp / "bad.json")

    def test_intake_missing_a_required_block_fails(self) -> None:
        document = read_json(self.intake)
        del document["collection_timeline"]
        (self.tmp / "partial.json").write_bytes(canonical_json_bytes(document))
        with self.assertRaises(ContractValidationError):
            self.ingest(exploratory_intake_path=self.tmp / "partial.json")

    def test_wrong_session_id_fails(self) -> None:
        other = build_intake(
            self.bundle, self.collection, self.tmp / "wrong-session.json",
            source_session_id="some-other-session",
        )
        with self.assertRaises(IntegrityError) as caught:
            self.ingest(exploratory_intake_path=other)
        self.assertIn("does not admit this session", str(caught.exception))

    def test_wrong_manifest_hash_fails(self) -> None:
        other = build_intake(
            self.bundle, self.collection, self.tmp / "wrong-manifest.json",
            source_manifest_sha256="0" * 64,
        )
        with self.assertRaises(IntegrityError) as caught:
            self.ingest(exploratory_intake_path=other)
        self.assertIn("exact completed research manifest", str(caught.exception))

    def test_wrong_collection_record_hash_fails(self) -> None:
        other = build_intake(
            self.bundle, self.collection, self.tmp / "wrong-collection.json",
            collection_record_sha256="0" * 64,
        )
        with self.assertRaises(IntegrityError) as caught:
            self.ingest(exploratory_intake_path=other)
        self.assertIn("exact collection record bytes", str(caught.exception))

    def test_editing_the_collection_record_after_review_invalidates_the_intake(self) -> None:
        record = read_json(self.collection)
        record["operator_notes"] = record["operator_notes"] + ["added after review"]
        self.collection.write_bytes(canonical_json_bytes(record))
        with self.assertRaises(IntegrityError):
            self.ingest(exploratory_intake_path=self.intake)

    def test_intake_claiming_confirmatory_eligibility_fails(self) -> None:
        for field in (
            "confirmatory_eligible", "causal_eligible",
            "primary_effect_estimate_eligible", "primary_corpus_pooling_eligible",
        ):
            with self.subTest(field=field):
                document = read_json(self.intake)
                document["eligibility"][field] = True
                path = self.tmp / f"claim-{field}.json"
                path.write_bytes(canonical_json_bytes(document))
                with self.assertRaises(ContractValidationError):
                    validate_exploratory_intake(read_json(path))

    def test_intake_claiming_experimental_classification_fails(self) -> None:
        document = read_json(self.intake)
        document["collection_classification"] = "experimental"
        with self.assertRaises(ContractValidationError):
            validate_exploratory_intake(document)

    def test_intake_claiming_a_prospective_protocol_fails(self) -> None:
        for field in ("prospective_protocol_existed", "randomization_performed"):
            with self.subTest(field=field):
                document = read_json(self.intake)
                document["collection_timeline"][field] = True
                with self.assertRaises(ContractValidationError):
                    validate_exploratory_intake(document)

    def test_missing_post_collection_disclosure_fails(self) -> None:
        document = read_json(self.intake)
        document["collection_timeline"]["collected_before_protocol_freeze"] = False
        with self.assertRaises(ContractValidationError):
            validate_exploratory_intake(document)

    def test_missing_post_outcome_disclosure_fails(self) -> None:
        document = read_json(self.intake)
        del document["collection_timeline"]["retained_after_outcome_known"]
        with self.assertRaises(ContractValidationError):
            validate_exploratory_intake(document)

    def test_review_status_cannot_widen_scope(self) -> None:
        document = read_json(self.intake)
        document["review"]["status"] = "approved"
        with self.assertRaises(ContractValidationError):
            validate_exploratory_intake(document)

    def test_intake_cannot_admit_a_protocol_bearing_collection_record(self) -> None:
        """Refused by whichever guard reaches it first. The collection-record
        contract already forces an observational record to carry no protocol, so a
        protocol-bearing record is necessarily experimental and contradicts the
        intake on either ground."""
        record = read_json(self.collection)
        record["collection_classification"] = "experimental"
        # Bound to the recorder's own declared identity, so the pre-existing
        # collection binding passes and the intake's refusal is what actually fires.
        record["protocol"] = {
            "freeze_id": "synthetic-protocol-freeze", "freeze_sha256": "0" * 64,
            "experiment_id": "some-experiment", "experiment_version": "1.0.0",
            "schedule_id": "some-schedule", "schedule_sha256": "1" * 64,
            "schedule_assignment_id": "assignment-1",
        }
        record["blocks"] = [
            {"block_id": "synthetic-block", "condition_id": "synthetic-disabled-control",
             "start_lap": 0, "end_lap": 1}
        ]
        record["lap_assignments"] = [{"lap_number": 1, "block_id": "synthetic-block"}]
        self.collection.write_bytes(canonical_json_bytes(record))
        intake = build_intake(self.bundle, self.collection, self.tmp / "protocol-intake.json")
        with self.assertRaises(IntegrityError) as caught:
            self.ingest(exploratory_intake_path=intake)
        message = str(caught.exception)
        self.assertTrue(
            "declares a frozen protocol" in message
            or "disagree about collection classification" in message,
            message,
        )

    def test_a_synthetic_intake_is_refused(self) -> None:
        document = read_json(self.intake)
        document["synthetic"] = True
        with self.assertRaises(ContractValidationError):
            validate_exploratory_intake(document)


# ======================================================================
# 9-11. The restriction survives everything downstream.
# ======================================================================

class DownstreamPropagationTests(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.manifest = self.ingest(exploratory_intake_path=self.intake)
        self.dataset = self.tmp / "normalized"

    def test_derived_manifest_on_disk_remains_exploratory(self) -> None:
        written = read_json(self.dataset / "manifest.json")
        self.assertEqual(written["scientific_eligibility"]["stratum"], "exploratory_pilot")
        validate_normalized_manifest(written)

    def test_a_copy_keeps_the_restriction(self) -> None:
        copied = self.tmp / "copied"
        shutil.copytree(self.dataset, copied)
        written = read_json(copied / "manifest.json")
        self.assertEqual(written["scientific_eligibility"]["stratum"], "exploratory_pilot")
        validate_normalized_manifest(written)

    def test_the_stratum_is_bound_into_the_dataset_fingerprint(self) -> None:
        from apex_labs.provenance.fingerprints import (
            build_dataset_fingerprint,
            normalized_dataset_fingerprint_basis,
        )

        basis = normalized_dataset_fingerprint_basis(self.manifest)
        self.assertIn("scientific_eligibility", basis)
        self.assertIn("exploratory_intake", basis)
        tampered = copy.deepcopy(self.manifest)
        tampered["scientific_eligibility"]["primary_corpus_pooling"] = True
        self.assertNotEqual(
            build_dataset_fingerprint(normalized_dataset_fingerprint_basis(tampered)),
            self.manifest["dataset_fingerprint"],
        )

    def test_a_later_protocol_cannot_upgrade_the_pilot_dataset(self) -> None:
        # Hand-editing the manifest to claim primary status is the attack; the
        # validator refuses it outright, before the fingerprint mismatch is reached.
        upgraded = copy.deepcopy(self.manifest)
        upgraded["scientific_eligibility"]["stratum"] = "primary_frozen_corpus"
        with self.assertRaises(ContractValidationError) as caught:
            validate_normalized_manifest(upgraded)
        self.assertIn("requires the bound frozen protocol snapshot", str(caught.exception))

    def test_claiming_primary_use_on_an_exploratory_dataset_is_refused(self) -> None:
        for field in ("confirmatory", "causal", "primary_effect_estimate", "primary_corpus_pooling"):
            with self.subTest(field=field):
                tampered = copy.deepcopy(self.manifest)
                tampered["scientific_eligibility"][field] = True
                with self.assertRaises(ContractValidationError):
                    validate_normalized_manifest(tampered)

    def test_dropping_the_intake_binding_is_refused(self) -> None:
        tampered = copy.deepcopy(self.manifest)
        del tampered["exploratory_intake"]
        with self.assertRaises(ContractValidationError) as caught:
            validate_normalized_manifest(tampered)
        self.assertIn("hash-verified exploratory intake", str(caught.exception))

    def test_real_research_normalization_must_state_a_stratum(self) -> None:
        tampered = copy.deepcopy(self.manifest)
        del tampered["scientific_eligibility"]
        del tampered["exploratory_intake"]
        with self.assertRaises(ContractValidationError) as caught:
            validate_normalized_manifest(tampered)
        self.assertIn("must declare its scientific stratum", str(caught.exception))

    def test_pilot_data_cannot_enter_comparable_evidence_or_primary_pooling(self) -> None:
        from apex_labs.evidence import builder

        with self.assertRaises(EvidenceError) as caught:
            builder._dataset_context(
                self.manifest, self.dataset / "manifest.json",
                {"session_id": "s", "driver_id": "d", "simulator": "iracing",
                 "car": "c", "track": "t", "layout": "l"},
                {}, {}, 0,
            )
        message = str(caught.exception)
        self.assertIn("exploratory_pilot", message)
        self.assertIn("permanently excluded", message)


# ======================================================================
# 12-13. Analysis eligibility.
# ======================================================================

class AnalysisEligibilityTests(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.manifest = self.ingest(exploratory_intake_path=self.intake)
        # A clean identity, supplied explicitly. The clean-tree rule is a separate,
        # already-tested guard; these tests are about scientific eligibility and must
        # not be hostage to whether the developer has uncommitted work.
        self.identity = {
            **self.manifest["code_identity"], "git_state": "clean", "git_commit": "a" * 40,
        }

    def test_descriptive_observational_remains_the_only_analysis_classification(self) -> None:
        definition = read_json(ROOT / "contracts" / "v1" / "analysis-definition.schema.json")
        self.assertEqual(
            definition["properties"]["classification"], {"const": "descriptive_observational"}
        )

    def test_descriptive_analysis_is_permitted_for_the_pilot_stratum(self) -> None:
        self.assertTrue(self.manifest["scientific_eligibility"]["descriptive_analysis"])
        self.assertTrue(self.manifest["scientific_eligibility"]["hypothesis_generation"])

    def test_a_descriptive_run_over_the_pilot_dataset_succeeds_and_carries_the_stratum(self) -> None:
        from apex_labs.analysis import run_analysis

        artifact = run_analysis(
            ROOT / "research" / "analyses" / "synthetic-demo-descriptive.json",
            self.tmp / "normalized",
            self.tmp / "run",
            run_id="pilot-descriptive-001",
            created_at="2026-08-22T00:00:00Z",
            project_root=ROOT,
            code_identity=self.identity,
        )
        # The run artifact labels itself as descriptive-only evidence, and the
        # definition it executed is the only classification the contract allows.
        self.assertEqual(
            artifact["classification"], "descriptive_summary_not_scientific_evidence"
        )
        stratum = artifact["dataset"]["scientific_eligibility"]
        self.assertEqual(stratum["stratum"], "exploratory_pilot")
        self.assertFalse(stratum["confirmatory"])
        self.assertFalse(stratum["causal"])
        self.assertFalse(stratum["primary_corpus_pooling"])

    def test_a_run_over_a_descriptive_ineligible_stratum_is_refused(self) -> None:
        from apex_labs.analysis import run_analysis
        from apex_labs.schemas.analysis_validation import validate_analysis_run

        artifact = run_analysis(
            ROOT / "research" / "analyses" / "synthetic-demo-descriptive.json",
            self.tmp / "normalized",
            self.tmp / "run-2",
            run_id="pilot-descriptive-002",
            created_at="2026-08-22T00:00:00Z",
            project_root=ROOT,
            code_identity=self.identity,
        )
        tampered = copy.deepcopy(artifact)
        tampered["dataset"]["scientific_eligibility"]["descriptive_analysis"] = False
        with self.assertRaises(ContractValidationError) as caught:
            validate_analysis_run(tampered)
        self.assertIn("permits descriptive analysis", str(caught.exception))


# ======================================================================
# 14-16. Nothing existing moved, and no source artifact was touched.
# ======================================================================

class UnchangedBehaviourTests(unittest.TestCase):
    def test_synthetic_ingestion_needs_no_intake_and_declares_no_stratum(self) -> None:
        from recorder_bundle import build_recorder_bundle, collection_record

        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle = build_recorder_bundle(tmp / "bundle")
            record = collection_record(bundle, tmp / "collection-record.json")
            manifest = ingest_research_bundle(
                bundle, tmp / "normalized", record, project_root=ROOT
            )
            self.assertTrue(manifest["synthetic"])
            self.assertNotIn("scientific_eligibility", manifest)
            self.assertNotIn("exploratory_intake", manifest)

    def test_source_bundle_and_collection_record_are_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle = build_real_bundle(tmp / "bundle")
            collection = build_real_collection(bundle, tmp / "collection-record.json")
            intake = build_intake(bundle, collection, tmp / "intake.json")
            before = {
                path.name: sha256_file(path)
                for path in sorted(bundle.iterdir())
            }
            before["collection-record.json"] = sha256_file(collection)
            before["intake.json"] = sha256_file(intake)

            ingest_research_bundle(
                bundle, tmp / "normalized", collection, project_root=ROOT,
                exploratory_intake_path=intake, integration_validation=True,
            )

            after = {
                path.name: sha256_file(path)
                for path in sorted(bundle.iterdir())
            }
            after["collection-record.json"] = sha256_file(collection)
            after["intake.json"] = sha256_file(intake)
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
