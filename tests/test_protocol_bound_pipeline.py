"""The protocol-bound pipeline, end to end, on a real-shaped prospective bundle.

Why this file exists
--------------------
`test_corpus_admission` admitted bundles but never ingested them.
`test_apex_research_adapter` ingested bundles but only synthetic ones, which skip
protocol binding entirely. No test ever carried ONE real, protocol-governed bundle
through both, so a contract contradiction lived in the seam between them:

* corpus admission bound the recorder's ``protocol_identity`` to the frozen
  ``protocol.experiment_id``;
* research ingestion bound the SAME recorder field to the collection record's
  ``protocol.freeze_id``;
* ``freeze_protocol`` builds ``freeze_id`` as ``f"{experiment_id}.freeze"``.

Satisfying all three at once required ``experiment_id == experiment_id + ".freeze"``,
so every real bundle that admitted could not ingest and every bundle that could
ingest could not admit. Separately, the ingestion equality loop read
``experiment_id``, ``experiment_version``, ``schedule_id`` and ``schedule_sha256``
from the snapshot's top level, where ``apex-labs.protocol-freeze/v1`` forbids them
(``additionalProperties: false``) — a ``KeyError`` for every real bundle.

The contract, established from the artifacts rather than chosen
--------------------------------------------------------------
``freeze_id`` and ``experiment_id`` are DISTINCT identities everywhere they appear
together, and they always appear together:

* ``contracts/v1/collection-record.schema.json`` requires both in ``protocol``;
* ``validate_normalized_manifest`` requires both in ``collection_context.protocol_snapshot``;
* ``build_evidence_set`` compares ``freeze["freeze_id"]`` and
  ``protocol["experiment_id"]`` against the evidence definition SEPARATELY.

So ``freeze_id`` means the freeze artifact identity and nothing else, and the field
the recorder writes is the EXPERIMENT identity. These tests pin that reading down and
fail closed on every neighbouring value, so a future "accept either" relaxation
breaks here.

Nothing in this file uses the exploratory-intake door or a synthetic bundle.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _support import ROOT  # noqa: F401  (path bootstrap)
from recorder_bundle import build_protocol_block_bundle

from apex_labs.analysis.runner import run_analysis, verify_analysis_run
from apex_labs.corpus.admission import evaluate_bundle
from apex_labs.errors import ContractValidationError, IntegrityError
from apex_labs.experiments.preregistration import (
    freeze_hash,
    protocol_hash,
    schedule_hash,
    verify_protocol_freeze,
)
from apex_labs.ingestion.apex_research import (
    _protocol_snapshot_identity,
    ingest_research_bundle,
)
from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.schemas import validate_normalized_manifest

PARTICIPANT = "participant-" + "5c" * 12
EXPERIMENT_ID = "protocol-bound-pipeline-test"
BLOCK_ID = "pbp-b01-practice-oulton"
CONDITION_ID = "pbp-coached-practice"
ASSIGNMENT_ID = "pbp-assignment-01"
SCHEDULE_ID = "protocol-bound-pipeline-schedule"
# A real freeze requires code_identity.git_commit == protocol.apex_labs_source_commit,
# so the fixture states one commit and uses it in both places.
SOURCE_COMMIT = "9" * 40

# A clean identity supplied explicitly so these tests assert the CONTRACT rather than
# the state of whatever working tree they happen to run in. Ingestion has no such
# seam, so it uses integration_validation, which relaxes only the clean-tree rule and
# leaves every protocol binding in force.
CLEAN_IDENTITY = {
    "package_version": "0.3.0",
    "git_commit": SOURCE_COMMIT,
    "git_state": "clean",
    "code_and_schema_sha256": "c" * 64,
    "schema_sha256": {"contracts/v1/experiment.schema.json": "d" * 64},
}


def _protocol(experiment_id: str = EXPERIMENT_ID) -> dict:
    """A REAL (``synthetic: false``) preregistered protocol."""
    return {
        "schema_version": "apex-labs.experiment/v1",
        "synthetic": False,
        "experiment_id": experiment_id,
        "version": "1.0.0",
        "status": "preregistered",
        "research_question": "Does the protocol-bound pipeline carry one real block end to end?",
        "hypothesis": "Mechanical only; no scientific hypothesis is tested by this fixture.",
        "null_hypothesis": "Not applicable; no inferential comparison is defined.",
        "independent_variable": {
            "name": "coaching-delivery",
            "operational_definition": "Whether the coaching host delivered cues during the block.",
            "levels": ["coached-delivery-on"],
        },
        "primary_dependent_metric": {
            "metric_id": "pipeline-stage-completion",
            "definition": "Whether every declared pipeline stage completed.",
            "unit": "stages",
            "provenance_expectation": "measured",
        },
        "secondary_metrics": [],
        "controlled_variables": ["One participant, one car, one track and layout"],
        "comparability_requirements": ["Single block; nothing is compared across blocks"],
        "exclusion_criteria": ["Any bundle without a COMPLETE marker"],
        "minimum_sample_requirements": {
            "state": "declared",
            "requirements": ["Exactly 1 block"],
            "rationale": "A mechanical fixture, not an estimate.",
        },
        "baseline_condition": "No baseline; a single coached block.",
        "intervention_conditions": [CONDITION_ID],
        "randomization_counterbalancing": "None; a single fixed assignment.",
        "analysis_methods": ["Descriptive stage checklist only"],
        "predeclared_success_criteria": {
            "state": "declared",
            "criteria": ["Every stage completes"],
            "falsification_criteria": ["Any stage fails"],
        },
        "safety_constraints": ["Read-only against source evidence"],
        "notes": ["Mechanical qualification fixture; never corpus evidence."],
        "created_at": "2026-08-24T00:00:00Z",
        "apex_labs_source_commit": SOURCE_COMMIT,
    }


def _schedule(block_id: str = BLOCK_ID) -> list[dict]:
    return [{
        "recording_ordinal": 1,
        "arm_id": "coached-delivery-on",
        "coaching_state": "enabled",
        "block_id": block_id,
        "condition_id": CONDITION_ID,
        "car": "toyotagr86",
        "track": "oulton international",
        "layout": "International",
        "measured_session_type_required": "practice",
        "planned_minutes": 30,
    }]


def _freeze(protocol: dict | None = None, schedule: list[dict] | None = None) -> dict:
    """A prospective freeze in the exact shape ``freeze_protocol`` emits."""
    protocol = protocol or _protocol()
    schedule = schedule if schedule is not None else _schedule()
    snapshot: dict = {
        "schema_version": "apex-labs.protocol-freeze/v1",
        "freeze_id": f"{protocol['experiment_id']}.freeze",
        "freeze_sha256": "0" * 64,
        "protocol_id": protocol["experiment_id"],
        "protocol_version": protocol["version"],
        "protocol_sha256": protocol_hash(protocol),
        "source_commit": protocol["apex_labs_source_commit"],
        "code_identity": CLEAN_IDENTITY,
        "frozen_at": "2026-08-24T00:00:00Z",
        "synthetic": protocol["synthetic"],
        "protocol": protocol,
        "randomization": {
            "strategy": "fixed",
            "method": "single fixed assignment",
            "seed": None,
            "schedule_id": SCHEDULE_ID,
            "schedule": schedule,
            "schedule_sha256": schedule_hash(schedule),
        },
        "amendment_history": [],
    }
    snapshot["freeze_sha256"] = freeze_hash(snapshot)
    return verify_protocol_freeze(snapshot)


def _analysis_definition() -> dict:
    return {
        "schema_version": "apex-labs.analysis-definition/v1",
        "analysis_id": "protocol-bound-pipeline-descriptive",
        "version": "1.0.0",
        "title": "Protocol-bound pipeline descriptive check",
        "purpose": (
            "Exercises the deterministic descriptive path over a protocol-bound normalized "
            "dataset. Mechanical plumbing only; it makes no racing-performance claim."
        ),
        "classification": "descriptive_observational",
        "computations": [
            {"computation_id": "inventory", "kind": "record_inventory"},
            {
                "computation_id": "sample-availability",
                "kind": "concept_availability",
                "record_type": "telemetry_sample",
            },
        ],
        "limitations": [
            "Descriptive summaries carry no hypothesis test, interval, or confidence claim.",
            "A mechanical qualification fixture can support no racing-performance conclusion.",
        ],
    }


class ProtocolBoundPipelineTests(unittest.TestCase):
    """One real block, all the way through, with every binding enforced."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.freeze = _freeze()
        self.freeze_path = self.root / "protocol-freeze.json"
        self.freeze_path.write_bytes(canonical_json_bytes(self.freeze))
        self.bundle = build_protocol_block_bundle(
            self.root / "bundle",
            protocol_identity=EXPERIMENT_ID,
            block_id=BLOCK_ID,
            condition_id=CONDITION_ID,
            participant=PARTICIPANT,
        )

    # ---- collection record ----------------------------------------------------

    def collection_record(
        self,
        destination: Path | None = None,
        *,
        freeze_id: str | None = None,
        experiment_id: str | None = None,
        freeze_sha256: str | None = None,
        schedule_sha256: str | None = None,
        dataset_id: str = "protocol-bound-pipeline-dataset",
    ) -> Path:
        manifest = read_json(self.bundle / "manifest.json")
        session = manifest["session"]
        from apex_labs.provenance import sha256_bytes

        record = {
            "schema_version": "apex-labs.collection-record/v1",
            "collection_record_id": "protocol-bound-pipeline-record",
            "version": "1.0.0",
            "dataset_id": dataset_id,
            "synthetic": False,
            "collection_classification": "experimental",
            "participant": {
                "pseudonymous_participant_id": session["participant_pseudonym"],
                "external_identity_map_reference": None,
                "direct_identity_in_record": False,
            },
            "authority": {
                "declaration": "Operator-collected under a reviewed prospective freeze.",
                "recorded_at": "2026-10-05T09:59:00Z",
            },
            "privacy": {
                "classification": "private",
                "pseudonymized": True,
                "direct_identifiers_present": False,
            },
            "storage": {
                "source_bundle_location": "external_untracked",
                "retention_declaration": "Private local research evidence held outside both repositories.",
            },
            "source_bundle": {
                "schema_version": "apex-research-session-export/1.0.0",
                "sha256": sha256_bytes((self.bundle / "manifest.json").read_bytes()),
            },
            "session_identity": {
                "simulator": session["simulator"]["id"],
                "car": session["car"]["id"],
                "track": session["track"]["id"],
                "layout": session["track"]["layout"],
                "confirmation_method": "Recorder-captured live session metadata bound by manifest SHA-256.",
            },
            "session_condition": "Coached practice block under a prospective freeze.",
            "protocol": {
                # freeze_id is the FREEZE artifact identity...
                "freeze_id": freeze_id if freeze_id is not None else self.freeze["freeze_id"],
                "freeze_sha256": (
                    freeze_sha256 if freeze_sha256 is not None else self.freeze["freeze_sha256"]
                ),
                # ...and experiment_id is what the recorder wrote. Two fields, two values.
                "experiment_id": (
                    experiment_id if experiment_id is not None
                    else self.freeze["protocol"]["experiment_id"]
                ),
                "experiment_version": self.freeze["protocol_version"],
                "schedule_id": self.freeze["randomization"]["schedule_id"],
                "schedule_sha256": (
                    schedule_sha256 if schedule_sha256 is not None
                    else self.freeze["randomization"]["schedule_sha256"]
                ),
                "schedule_assignment_id": ASSIGNMENT_ID,
            },
            "blocks": [{
                "block_id": BLOCK_ID,
                "condition_id": CONDITION_ID,
                "start_lap": 0,
                "end_lap": 1,
            }],
            "lap_assignments": [{"lap_number": 0, "block_id": BLOCK_ID}],
            "deviations": [],
            "coaching": {"state": "enabled", "notes": "Coaching ran for the whole block."},
            "operator_notes": [],
            "created_at": "2026-10-05T10:30:00Z",
        }
        path = destination or (self.root / "collection-record.json")
        path.write_bytes(canonical_json_bytes(record))
        return path

    def ingest(self, output: Path, record: Path | None = None) -> dict:
        return ingest_research_bundle(
            self.bundle,
            output,
            record or self.collection_record(),
            project_root=ROOT,
            integration_validation=True,
            protocol_snapshot_path=self.freeze_path,
        )

    # ---- the complete path ----------------------------------------------------

    def test_one_real_block_admits_ingests_analyses_and_repeats_identically(self) -> None:
        # 1. admission against the prospective freeze
        verdict = evaluate_bundle(self.bundle, self.freeze)
        self.assertEqual([], verdict["findings"])
        self.assertTrue(verdict["admitted"])
        self.assertEqual(BLOCK_ID, verdict["block_id"])

        # 2. protocol-bound normalized ingestion
        manifest = self.ingest(self.root / "normalized")

        # 3. the normalized manifest validates, and states BOTH identities correctly
        validate_normalized_manifest(manifest)
        snapshot = manifest["collection_context"]["protocol_snapshot"]
        self.assertEqual(self.freeze["freeze_id"], snapshot["freeze_id"])
        self.assertEqual(EXPERIMENT_ID, snapshot["experiment_id"])
        self.assertNotEqual(snapshot["freeze_id"], snapshot["experiment_id"])
        self.assertEqual(self.freeze["freeze_sha256"], snapshot["freeze_sha256"])
        self.assertEqual(SCHEDULE_ID, snapshot["schedule_id"])
        self.assertEqual(
            self.freeze["randomization"]["schedule_sha256"], snapshot["schedule_sha256"])
        self.assertEqual("1.0.0", snapshot["experiment_version"])
        self.assertEqual(BLOCK_ID, manifest["collection_context"]["block_id"])
        self.assertEqual(CONDITION_ID, manifest["collection_context"]["condition_id"])
        self.assertEqual(ASSIGNMENT_ID, manifest["collection_context"]["schedule_assignment_id"])

        # 4. qualification classification: a prospective freeze yields the primary stratum,
        #    never the exploratory one.
        eligibility = manifest["scientific_eligibility"]
        self.assertEqual("primary_frozen_corpus", eligibility["stratum"])
        self.assertTrue(eligibility["prospective_protocol"])
        self.assertFalse(eligibility["collected_before_protocol_freeze"])
        self.assertNotIn("exploratory_intake", manifest)

        # 5. analysis over the protocol-bound dataset
        definition_path = self.root / "analysis-definition.json"
        definition_path.write_bytes(canonical_json_bytes(_analysis_definition()))
        run = run_analysis(
            definition_path, self.root / "normalized", self.root / "run-1",
            run_id="pbp-run-1", created_at="2026-10-05T11:00:00Z",
            code_identity=CLEAN_IDENTITY,
        )
        verify_analysis_run(self.root / "run-1", self.root / "normalized")

        # 6. deterministic second ingestion
        repeat = self.ingest(self.root / "normalized-2")
        self.assertEqual(manifest["dataset_fingerprint"], repeat["dataset_fingerprint"])
        self.assertEqual(
            (self.root / "normalized" / "records.jsonl").read_bytes(),
            (self.root / "normalized-2" / "records.jsonl").read_bytes(),
        )
        self.assertEqual(
            (self.root / "normalized" / "manifest.json").read_bytes(),
            (self.root / "normalized-2" / "manifest.json").read_bytes(),
        )

        # 7. deterministic second analysis, over the independently reproduced dataset
        rerun = run_analysis(
            definition_path, self.root / "normalized-2", self.root / "run-2",
            run_id="pbp-run-1", created_at="2026-10-05T11:00:00Z",
            code_identity=CLEAN_IDENTITY,
        )
        self.assertEqual(run["run_sha256"], rerun["run_sha256"])
        self.assertEqual(run["results"], rerun["results"])

        # 8. an unrelated frozen corpus refuses this same bundle, by block identity
        unrelated = _freeze(
            protocol=_protocol("unrelated-corpus-protocol"),
            schedule=_schedule("unrelated-corpus-b01"),
        )
        refusal = evaluate_bundle(self.bundle, unrelated)
        self.assertFalse(refusal["admitted"])
        self.assertEqual(
            ["block-not-in-schedule"], [f["code"] for f in refusal["findings"]])

    def test_the_ingested_dataset_satisfies_the_evidence_layer_binding(self) -> None:
        """The downstream evidence rule is the same two-field rule, so pin it here.

        ``build_evidence_set`` compares the freeze's ``freeze_id``/``freeze_sha256``
        against the evidence definition's ``protocol`` block, and the protocol's
        ``experiment_id``/``version`` against it SEPARATELY. Before the fix no
        protocol-bound dataset could exist to reach that comparison at all. This
        asserts the exact predicate against a real ingested manifest, so a regression
        in the ingestion identity would surface here rather than at evidence-build
        time on a campaign that took hours to collect.

        Constructing a full comparable evidence set is deliberately NOT attempted:
        that needs segment and metric definitions over many laps, and the committed
        recorder conformance fixture carries one lap and two samples. Evidence-set and
        finding construction stay covered by ``test_evidence_sets`` and
        ``test_hypothesis_lifecycle`` on campaign datasets.
        """
        manifest = self.ingest(self.root / "normalized")
        snapshot = manifest["collection_context"]["protocol_snapshot"]
        protocol = self.freeze["protocol"]

        bound_protocol = {
            "freeze_id": self.freeze["freeze_id"],
            "freeze_sha256": self.freeze["freeze_sha256"],
            "experiment_id": protocol["experiment_id"],
            "experiment_version": protocol["version"],
        }
        # The literal predicate from build_evidence_set, applied to real ingested bytes.
        self.assertEqual(bound_protocol["freeze_id"], snapshot["freeze_id"])
        self.assertEqual(bound_protocol["freeze_sha256"], snapshot["freeze_sha256"])
        self.assertEqual(bound_protocol["experiment_id"], snapshot["experiment_id"])
        self.assertEqual(bound_protocol["experiment_version"], snapshot["experiment_version"])
        # ...and the two identities remain distinct, which is the whole point.
        self.assertNotEqual(bound_protocol["freeze_id"], bound_protocol["experiment_id"])

    # ---- the contract, pinned and failing closed -------------------------------

    def test_freeze_id_carrying_the_experiment_identity_is_refused(self) -> None:
        """The exact shape the old code forced. It must now fail, not be accepted."""
        record = self.collection_record(
            self.root / "wrong-freeze-id.json", freeze_id=EXPERIMENT_ID)
        with self.assertRaises(IntegrityError) as raised:
            self.ingest(self.root / "normalized-bad", record)
        self.assertIn("freeze_id", str(raised.exception))

    def test_experiment_identity_disagreeing_with_the_recorder_is_refused(self) -> None:
        record = self.collection_record(
            self.root / "wrong-experiment.json", experiment_id="some-other-protocol")
        with self.assertRaises(IntegrityError) as raised:
            self.ingest(self.root / "normalized-bad", record)
        self.assertIn("experiment identity", str(raised.exception))

    def test_a_foreign_freeze_hash_is_refused(self) -> None:
        """Requirement 2: the record stays welded to the exact approved snapshot."""
        record = self.collection_record(
            self.root / "wrong-hash.json", freeze_sha256="e" * 64)
        with self.assertRaises(IntegrityError) as raised:
            self.ingest(self.root / "normalized-bad", record)
        self.assertIn("freeze_sha256", str(raised.exception))

    def test_a_foreign_schedule_hash_is_refused(self) -> None:
        record = self.collection_record(
            self.root / "wrong-schedule.json", schedule_sha256="f" * 64)
        with self.assertRaises(IntegrityError) as raised:
            self.ingest(self.root / "normalized-bad", record)
        self.assertIn("schedule_sha256", str(raised.exception))

    def test_a_snapshot_disagreeing_with_its_own_protocol_is_refused(self) -> None:
        """Two layers refuse it, and this pins both.

        ``validate_protocol_freeze`` rejects the snapshot outright, so ingestion never
        reaches the identity read. The identity helper carries the same check anyway,
        because it is what decides which of two disagreeing statements of the experiment
        identity would be believed, and that decision must not depend on a caller
        remembering to validate first.
        """
        snapshot = _freeze()
        snapshot["protocol_id"] = "a-different-experiment"
        path = self.root / "inconsistent-freeze.json"
        path.write_bytes(canonical_json_bytes(snapshot))
        self.freeze_path = path
        with self.assertRaises(ContractValidationError) as schema_refusal:
            self.ingest(self.root / "normalized-bad")
        self.assertIn("identity/version must match", str(schema_refusal.exception))

        with self.assertRaises(IntegrityError) as helper_refusal:
            _protocol_snapshot_identity(snapshot)
        self.assertIn("disagrees with its own protocol document", str(helper_refusal.exception))

    def test_the_identity_helper_reads_every_field_from_its_contract_location(self) -> None:
        """Four of these six do not exist at the snapshot's top level and never can.

        ``apex-labs.protocol-freeze/v1`` sets ``additionalProperties: false`` and does
        not permit ``experiment_id``, ``experiment_version``, ``schedule_id`` or
        ``schedule_sha256``. Reading them from there raised ``KeyError`` for every real
        bundle, so this asserts the locations rather than only the values.
        """
        for absent in ("experiment_id", "experiment_version", "schedule_id", "schedule_sha256"):
            self.assertNotIn(absent, self.freeze)

        identity = _protocol_snapshot_identity(self.freeze)
        self.assertEqual({
            "freeze_id": self.freeze["freeze_id"],
            "freeze_sha256": self.freeze["freeze_sha256"],
            "experiment_id": self.freeze["protocol"]["experiment_id"],
            "experiment_version": self.freeze["protocol"]["version"],
            "schedule_id": self.freeze["randomization"]["schedule_id"],
            "schedule_sha256": self.freeze["randomization"]["schedule_sha256"],
        }, identity)

    def test_a_real_bundle_without_a_protocol_snapshot_is_still_refused(self) -> None:
        """The primary gate is unchanged: no snapshot, no real ingestion."""
        from apex_labs.errors import IngestionError

        with self.assertRaises(IngestionError):
            ingest_research_bundle(
                self.bundle, self.root / "normalized-bad", self.collection_record(),
                project_root=ROOT, integration_validation=True,
            )


if __name__ == "__main__":
    unittest.main()
