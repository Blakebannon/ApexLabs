"""Append-only hypothesis lifecycle: promotion gates, ordering, and tamper detection."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from _support import BUILT_AT, ROOT, prepared_campaign, prepared_run, synthetic_hypothesis

from apex_labs.errors import (
    ApexLabsError,
    ContractValidationError,
    IntegrityError,
    LifecycleError,
)
from apex_labs.hypotheses import (
    bindings_from_run,
    plan_bindings,
    record_transition,
    register_hypothesis,
    replay,
    verify_registry,
)
from apex_labs.hypotheses.registry import EMPTY_BINDINGS, seal_hypothesis
from apex_labs.io import read_json, write_json
from apex_labs.schemas import (
    hypothesis_hash,
    transition_hash,
    validate_hypothesis,
    validate_hypothesis_transition,
)

REVIEWED = {
    "state": "approved",
    "reviewer_id": "synthetic-reviewer",
    "reviewed_at": BUILT_AT,
    "notes": ["Fabricated evidence; approval here records a software step, not a scientific one."],
}
PENDING = {"state": "pending", "reviewer_id": None, "reviewed_at": None, "notes": []}


class LifecycleFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-lifecycle-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.prepared = prepared_campaign(cls.base / "demo")
        cls.executed = prepared_run(cls.prepared, cls.base, run_id="lifecycle-run")
        cls.evidence = cls.prepared["evidence"]
        cls.identity = cls.evidence["code_identity"]

    def _registry(self, name: str) -> Path:
        return self.base / "registries" / name

    def _register(self, name: str, hypothesis_id: str = "support-hypothesis") -> Path:
        registry = self._registry(name)
        register_hypothesis(
            synthetic_hypothesis(hypothesis_id),
            registry,
            recorded_at=BUILT_AT,
            code_identity=self.identity,
        )
        return registry

    def _plan(self) -> dict:
        return plan_bindings(
            self.evidence,
            self.executed["run"]["definition"],
            self.executed["run"]["definition_sha256"],
        )

    def _run_bindings(self) -> dict:
        return bindings_from_run(self.evidence, self.executed["run"], verified=True)

    def _walk_to_tested(self, name: str) -> Path:
        registry = self._register(name)
        record_transition(
            registry, "support-hypothesis", to_state="analysis_ready",
            rationale="Everything was frozen before the run existed.",
            recorded_at=BUILT_AT, bindings=self._plan(), code_identity=self.identity,
        )
        record_transition(
            registry, "support-hypothesis", to_state="tested",
            rationale="The preregistered analysis ran once and was independently recomputed.",
            recorded_at=BUILT_AT, bindings=self._run_bindings(), reviewer=dict(PENDING),
            code_identity=self.identity,
        )
        return registry


class LifecycleOrderingTests(LifecycleFixture):
    def test_registration_opens_the_lifecycle_at_generated(self) -> None:
        registry = self._register("opening")
        history = replay(registry, "support-hypothesis")
        self.assertEqual(history["state"], "generated")
        self.assertEqual(len(history["transitions"]), 1)
        self.assertIsNone(history["transitions"][0]["from_state"])
        self.assertIsNone(history["transitions"][0]["previous_transition_sha256"])

    def test_generation_source_is_recorded_and_confers_no_authority(self) -> None:
        hypothesis = synthetic_hypothesis("llm-proposed")
        hypothesis["generation"] = {
            "source": "llm",
            "actor": "some-model",
            "detail": "Proposed by a language model while reading the corpus.",
            "is_evidence": False,
        }
        registry = self._registry("llm")
        sealed = register_hypothesis(
            hypothesis, registry, recorded_at=BUILT_AT, code_identity=self.identity
        )
        self.assertEqual(sealed["generation"]["source"], "llm")
        self.assertFalse(sealed["generation"]["is_evidence"])
        # An LLM proposal still enters at generated and still needs a verified run.
        self.assertEqual(replay(registry, "llm-proposed")["state"], "generated")
        with self.assertRaises(LifecycleError):
            record_transition(
                registry, "llm-proposed", to_state="tested", rationale="The model was confident.",
                recorded_at=BUILT_AT, code_identity=self.identity,
            )

    def test_a_hypothesis_claiming_to_be_evidence_is_refused(self) -> None:
        hypothesis = synthetic_hypothesis("self-certifying")
        hypothesis["generation"]["is_evidence"] = True
        with self.assertRaises(ContractValidationError):
            seal_hypothesis(hypothesis)

    def test_states_are_never_skipped(self) -> None:
        registry = self._register("skipping")
        for target in ("tested", "supported_provisionally", "rejected"):
            with self.subTest(target=target):
                with self.assertRaises(LifecycleError) as error:
                    record_transition(
                        registry, "support-hypothesis", to_state=target,
                        rationale="Skipping ahead.", recorded_at=BUILT_AT,
                        code_identity=self.identity,
                    )
                self.assertIn("does not permit a transition to", str(error.exception))

    def test_rejected_is_terminal_within_a_hypothesis_version(self) -> None:
        registry = self._walk_to_tested("terminal")
        record_transition(
            registry, "support-hypothesis", to_state="rejected",
            rationale="The declared falsification criterion was met.",
            recorded_at=BUILT_AT, bindings=self._run_bindings(), reviewer=dict(REVIEWED),
            code_identity=self.identity,
        )
        with self.assertRaises(LifecycleError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="analysis_ready",
                rationale="Trying again with the same hypothesis.", recorded_at=BUILT_AT,
                bindings=self._plan(), code_identity=self.identity,
            )
        self.assertIn("terminal", str(error.exception))

    def test_a_lifecycle_is_never_restarted_in_place(self) -> None:
        registry = self._register("restart")
        with self.assertRaises(LifecycleError) as error:
            register_hypothesis(
                synthetic_hypothesis("support-hypothesis"), registry,
                recorded_at=BUILT_AT, code_identity=self.identity,
            )
        self.assertIn("never restarted in place", str(error.exception))


class PromotionGateTests(LifecycleFixture):
    def test_analysis_ready_requires_frozen_bindings_and_no_run(self) -> None:
        registry = self._register("plan-gate")
        with self.assertRaises(ContractValidationError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="analysis_ready",
                rationale="No plan was frozen.", recorded_at=BUILT_AT,
                bindings=dict(EMPTY_BINDINGS), code_identity=self.identity,
            )
        self.assertIn("frozen protocol, evidence-set, and frozen analysis-definition", str(error.exception))
        with self.assertRaises(ContractValidationError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="analysis_ready",
                rationale="Binding a run that should not exist yet.", recorded_at=BUILT_AT,
                bindings=self._run_bindings(), code_identity=self.identity,
            )
        self.assertIn("before any run exists", str(error.exception))

    def test_an_evidence_bearing_state_requires_the_complete_bindings(self) -> None:
        registry = self._register("evidence-gate")
        record_transition(
            registry, "support-hypothesis", to_state="analysis_ready",
            rationale="Frozen.", recorded_at=BUILT_AT, bindings=self._plan(),
            code_identity=self.identity,
        )
        for missing in (
            "protocol", "evidence_set", "analysis_definition", "analysis_run",
            "interpretation_ceiling", "multiple_comparison", "falsification", "replication",
        ):
            with self.subTest(missing=missing):
                bindings = self._run_bindings()
                bindings[missing] = None
                with self.assertRaises(ContractValidationError) as error:
                    record_transition(
                        registry, "support-hypothesis", to_state="tested",
                        rationale="Incomplete bindings.", recorded_at=BUILT_AT,
                        bindings=bindings, reviewer=dict(PENDING), code_identity=self.identity,
                    )
                self.assertIn("requires complete bindings", str(error.exception))

    def test_an_evidence_bearing_state_requires_a_verified_run(self) -> None:
        registry = self._register("verified-gate")
        record_transition(
            registry, "support-hypothesis", to_state="analysis_ready",
            rationale="Frozen.", recorded_at=BUILT_AT, bindings=self._plan(),
            code_identity=self.identity,
        )
        bindings = bindings_from_run(self.evidence, self.executed["run"], verified=False)
        with self.assertRaises(ContractValidationError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="tested",
                rationale="The run was never recomputed.", recorded_at=BUILT_AT,
                bindings=bindings, reviewer=dict(PENDING), code_identity=self.identity,
            )
        self.assertIn("independently verified run", str(error.exception))

    def test_an_evidence_bearing_state_requires_a_reviewer_disposition(self) -> None:
        registry = self._register("review-gate")
        record_transition(
            registry, "support-hypothesis", to_state="analysis_ready",
            rationale="Frozen.", recorded_at=BUILT_AT, bindings=self._plan(),
            code_identity=self.identity,
        )
        with self.assertRaises(ContractValidationError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="tested",
                rationale="Nobody looked.", recorded_at=BUILT_AT,
                bindings=self._run_bindings(), code_identity=self.identity,
            )
        self.assertIn("recorded reviewer disposition", str(error.exception))

    def test_provisional_support_requires_an_approved_review(self) -> None:
        registry = self._walk_to_tested("provisional-gate")
        with self.assertRaises(ContractValidationError) as error:
            record_transition(
                registry, "support-hypothesis", to_state="supported_provisionally",
                rationale="Promoting without review.", recorded_at=BUILT_AT,
                bindings=self._run_bindings(), reviewer=dict(PENDING),
                code_identity=self.identity,
            )
        self.assertIn("approved scientific review", str(error.exception))
        transition = record_transition(
            registry, "support-hypothesis", to_state="supported_provisionally",
            rationale="Reviewed and provisionally supported for mechanics purposes.",
            recorded_at=BUILT_AT, bindings=self._run_bindings(), reviewer=dict(REVIEWED),
            code_identity=self.identity,
        )
        self.assertEqual(transition["to_state"], "supported_provisionally")


class HistoryIntegrityTests(LifecycleFixture):
    def test_history_is_hash_chained_and_replayable(self) -> None:
        registry = self._walk_to_tested("chain")
        history = replay(registry, "support-hypothesis")
        self.assertEqual(history["state"], "tested")
        previous = None
        for index, transition in enumerate(history["transitions"]):
            self.assertEqual(transition["sequence_index"], index)
            self.assertEqual(transition["previous_transition_sha256"], previous)
            self.assertEqual(transition["transition_sha256"], transition_hash(transition))
            previous = transition["transition_sha256"]

    def test_rewriting_a_stored_transition_is_detected(self) -> None:
        registry = self._walk_to_tested("rewrite")
        directory = registry / "support-hypothesis" / "transitions"
        path = sorted(directory.glob("*.json"))[1]
        transition = read_json(path)
        transition["rationale"] = "Rewritten after the fact."
        write_json(path, transition)
        # Whether the contract validator or the chain replay catches it first, an
        # edited transition never replays as valid history.
        with self.assertRaises(ApexLabsError) as error:
            replay(registry, "support-hypothesis")
        self.assertIn("does not match", str(error.exception))

    def test_rewriting_the_hypothesis_text_under_its_history_is_detected(self) -> None:
        registry = self._walk_to_tested("hypothesis-rewrite")
        path = registry / "support-hypothesis" / "hypothesis.json"
        hypothesis = read_json(path)
        hypothesis["statement"] = "A conveniently different statement."
        hypothesis["hypothesis_sha256"] = hypothesis_hash(hypothesis)
        write_json(path, hypothesis)
        with self.assertRaises(IntegrityError) as error:
            replay(registry, "support-hypothesis")
        self.assertIn("cannot be rewritten under its history", str(error.exception))

    def test_removing_a_transition_breaks_the_chain(self) -> None:
        registry = self._walk_to_tested("truncate")
        directory = registry / "support-hypothesis" / "transitions"
        sorted(directory.glob("*.json"))[1].unlink()
        with self.assertRaises(ApexLabsError):
            replay(registry, "support-hypothesis")

    def test_a_transition_from_another_hypothesis_is_refused(self) -> None:
        registry = self._walk_to_tested("cross-binding")
        other = self._walk_to_tested("cross-binding-other")
        source = sorted((other / "support-hypothesis" / "transitions").glob("*.json"))[2]
        target = registry / "support-hypothesis" / "transitions" / "0003-tested-to-rejected.json"
        transition = read_json(source)
        write_json(target, transition)
        with self.assertRaises(ApexLabsError):
            replay(registry, "support-hypothesis")

    def test_registry_verification_replays_every_hypothesis(self) -> None:
        registry = self._walk_to_tested("registry-verify")
        register_hypothesis(
            synthetic_hypothesis("second-hypothesis"), registry,
            recorded_at=BUILT_AT, code_identity=self.identity,
        )
        result = verify_registry(registry)
        self.assertTrue(result["valid"])
        states = {item["hypothesis_id"]: item for item in result["hypotheses"]}
        self.assertEqual(states["support-hypothesis"]["state"], "tested")
        self.assertTrue(states["support-hypothesis"]["evidence_bearing"])
        self.assertEqual(states["second-hypothesis"]["state"], "generated")
        self.assertFalse(states["second-hypothesis"]["evidence_bearing"])

    def test_an_unregistered_hypothesis_is_refused(self) -> None:
        with self.assertRaises(LifecycleError):
            replay(self._registry("missing"), "nothing-here")


class TransitionContractTests(unittest.TestCase):
    @staticmethod
    def _transition() -> dict:
        base = {
            "schema_version": "apex-labs.hypothesis-transition/v1",
            "transition_id": "example.t0000",
            "sequence_index": 0,
            "hypothesis_id": "example",
            "hypothesis_version": "1.0.0",
            "hypothesis_sha256": "a" * 64,
            "recorded_at": BUILT_AT,
            "synthetic": True,
            "from_state": None,
            "to_state": "generated",
            "previous_transition_sha256": None,
            "transition_sha256": "0" * 64,
            "rationale": "Opened.",
            "bindings": dict(EMPTY_BINDINGS),
            "reviewer": {"state": "unreviewed", "reviewer_id": None, "reviewed_at": None, "notes": []},
            "code_identity": {
                "package_version": "0.3.0",
                "git_commit": "UNCOMMITTED",
                "git_state": "uncommitted",
                "code_and_schema_sha256": "b" * 64,
                "schema_sha256": {"contracts/v1/hypothesis.schema.json": "c" * 64},
            },
        }
        base["transition_sha256"] = transition_hash(base)
        return base

    def test_the_opening_transition_must_start_at_generated(self) -> None:
        validate_hypothesis_transition(self._transition())
        transition = self._transition()
        transition["to_state"] = "analysis_ready"
        transition["transition_sha256"] = transition_hash(transition)
        with self.assertRaises(ContractValidationError) as error:
            validate_hypothesis_transition(transition)
        self.assertIn("begins at generated", str(error.exception))

    def test_a_forbidden_edge_is_refused_by_the_contract(self) -> None:
        transition = self._transition()
        transition["sequence_index"] = 1
        transition["from_state"] = "generated"
        transition["to_state"] = "rejected"
        transition["previous_transition_sha256"] = "d" * 64
        transition["transition_sha256"] = transition_hash(transition)
        with self.assertRaises(ContractValidationError) as error:
            validate_hypothesis_transition(transition)
        self.assertIn("states are never skipped", str(error.exception))

    def test_a_resolved_review_must_name_its_reviewer(self) -> None:
        transition = self._transition()
        transition["reviewer"] = {"state": "approved", "reviewer_id": None, "reviewed_at": None, "notes": []}
        transition["transition_sha256"] = transition_hash(transition)
        with self.assertRaises(ContractValidationError):
            validate_hypothesis_transition(transition)

    def test_a_tampered_self_hash_is_refused(self) -> None:
        transition = self._transition()
        transition["rationale"] = "Edited without rehashing."
        with self.assertRaises(ContractValidationError):
            validate_hypothesis_transition(transition)

    def test_synthetic_evidence_cannot_be_laundered_through_a_real_transition(self) -> None:
        transition = self._transition()
        transition.update(
            {
                "sequence_index": 1,
                "from_state": "generated",
                "to_state": "analysis_ready",
                "previous_transition_sha256": "d" * 64,
                "bindings": {
                    **EMPTY_BINDINGS,
                    "protocol": {"freeze_id": "example-freeze", "freeze_sha256": "e" * 64},
                    "evidence_set": {
                        "evidence_set_id": "example-evidence",
                        "version": "1.0.0",
                        "evidence_set_sha256": "f" * 64,
                        "synthetic": False,
                    },
                    "analysis_definition": {
                        "analysis_id": "example-analysis",
                        "version": "1.0.0",
                        "definition_sha256": "1" * 64,
                        "classification": "confirmatory",
                    },
                },
            }
        )
        transition["transition_sha256"] = transition_hash(transition)
        with self.assertRaises(ContractValidationError) as error:
            validate_hypothesis_transition(transition)
        self.assertIn("must agree with the transition synthetic classification", str(error.exception))

    def test_a_hypothesis_self_hash_must_match_its_content(self) -> None:
        hypothesis = seal_hypothesis(synthetic_hypothesis("hash-check"))
        validate_hypothesis(hypothesis)
        tampered = copy.deepcopy(hypothesis)
        tampered["title"] = "Edited"
        with self.assertRaises(ContractValidationError):
            validate_hypothesis(tampered)


if __name__ == "__main__":
    unittest.main()
