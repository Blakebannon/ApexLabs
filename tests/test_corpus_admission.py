"""The automated corpus-admission gate.

Validation and admission answer different questions. Every completed bundle from
the 2026-08-23 livestream passed both product and Apex Labs validation, and two
of them still carried an operator condition label naming the wrong session type.
Validation proves a bundle is internally consistent and unmutated; admission
proves it is the recording the frozen protocol asked for. These tests exist to
keep the second question from quietly becoming the first.

Bundles here are built from the committed recorder conformance fixture — real
recorder bytes — and re-sealed with `rebind`, so a product change to the sample
columns or file inventory breaks these tests rather than a live campaign.
"""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _support import ROOT  # noqa: F401  (path bootstrap)
from recorder_bundle import FIXTURE, rebind

from apex_labs.corpus.admission import admit_corpus, evaluate_bundle
from apex_labs.errors import ContractValidationError
from apex_labs.experiments.preregistration import freeze_hash, protocol_hash, schedule_hash
from apex_labs.io import read_json

PARTICIPANT = "participant-" + "a" * 24
SETUP_HASH = "c93dcfd5b6411323e190c97d050d51065f7491bbfa4e7592e3477e61e5cbc916"


def _schedule() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for pair in (1, 2):
        for position, arm in enumerate(("coached-delivery-on", "coached-delivery-off"), start=1):
            ordinal += 1
            rows.append({
                "recording_ordinal": ordinal,
                "pair_id": f"pair-{pair:02d}",
                "position_in_pair": position,
                "arm_id": arm,
                "coaching_state": "enabled" if arm.endswith("-on") else "disabled",
                "block_id": f"corpus-test-p{pair:02d}-r{position}-{arm}",
                "condition_id": arm,
                "car": "toyotagr86",
                "track": "nurburgring-gpshort",
                "layout": "nurburgring-gpshort",
                "measured_session_type_required": "offline-testing",
                "planned_minutes": 30,
            })
    return rows


def _protocol() -> dict[str, object]:
    return {
        "schema_version": "apex-labs.experiment/v1",
        "synthetic": True,
        "experiment_id": "corpus-admission-test-protocol",
        "version": "1.0.0",
        "status": "preregistered",
        "research_question": "q",
        "hypothesis": "h",
        "null_hypothesis": "n",
        "independent_variable": {
            "name": "coaching-delivery",
            "operational_definition": "one recording is one block and one arm",
            "levels": ["coached-delivery-on", "coached-delivery-off"],
        },
        "primary_dependent_metric": {
            "metric_id": "clean-lap-time-block-median",
            "definition": "d", "unit": "seconds", "provenance_expectation": "derived",
        },
        "secondary_metrics": [],
        "controlled_variables": ["one car"],
        "comparability_requirements": ["block is the unit"],
        "exclusion_criteria": ["out-laps"],
        "minimum_sample_requirements": {"state": "declared", "requirements": ["2 pairs"], "rationale": "test"},
        "baseline_condition": "delivery off",
        "intervention_conditions": ["delivery on"],
        "randomization_counterbalancing": "balanced",
        "analysis_methods": ["paired difference"],
        "predeclared_success_criteria": {"state": "declared", "criteria": ["c"], "falsification_criteria": ["f"]},
        "safety_constraints": ["simulated only"],
        "notes": ["test protocol"],
        "created_at": "2026-08-24T00:00:00Z",
        "apex_labs_source_commit": "b" * 40,
    }


def _freeze() -> dict[str, object]:
    protocol = _protocol()
    schedule = _schedule()
    snapshot: dict[str, object] = {
        "schema_version": "apex-labs.protocol-freeze/v1",
        "freeze_id": "corpus-admission-test-protocol.freeze",
        "freeze_sha256": "0" * 64,
        "protocol_id": protocol["experiment_id"],
        "protocol_version": protocol["version"],
        "protocol_sha256": protocol_hash(protocol),
        "source_commit": protocol["apex_labs_source_commit"],
        "code_identity": {
            "package_version": "0.3.0",
            "git_commit": "b" * 40,
            "git_state": "clean",
            "code_and_schema_sha256": "c" * 64,
            "schema_sha256": {"contracts/v1/experiment.schema.json": "d" * 64},
        },
        "frozen_at": "2026-08-24T00:00:00Z",
        "synthetic": True,
        "protocol": protocol,
        "randomization": {
            "strategy": "counterbalanced",
            "method": "exactly balanced, seeded permutation",
            "seed": 20261005,
            "schedule_id": "corpus-admission-test-schedule",
            "schedule": schedule,
            "schedule_sha256": schedule_hash(schedule),
        },
        "amendment_history": [],
    }
    snapshot["freeze_sha256"] = freeze_hash(snapshot)
    return snapshot


def _coaching_events(delivered: int, provenance: str | None) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    sequence = 1
    stamp = 100.0
    for index in range(delivered):
        for kind in ("coaching-directive-authorized", "coaching-delivery-receipt"):
            data: dict[str, object] = {"directive_ref": f"ref-{index:04d}"}
            if kind == "coaching-delivery-receipt":
                data["outcome"] = "Delivered"
            else:
                data["message_key"] = "objective/brake-earlier-t7/practice"
            if provenance is not None:
                data["observed_utc_provenance"] = provenance
            events.append({
                "schema_version": "apex-research-event/1.0.0",
                "sequence": sequence,
                "observed_utc": f"2026-10-05T10:{index // 60:02d}:{index % 60:02d}.0000000Z",
                "session_time_s": stamp,
                "kind": kind,
                "data": data,
            })
            sequence += 1
            stamp += 1.0

    # A coached recording must carry the authoritative evidence summary; Labs
    # refuses one without it, so a fixture without it would never reach the
    # admission rules under test.
    summary: dict[str, object] = {
        "authorization_count": delivered,
        "decision_count": delivered,
        "delivery_receipt_count": delivered,
        "source": "authoritative committed coaching event stream",
        "source_direct_identifiers_copied": False,
        "events_with_recorded_utc": delivered * 2 if provenance == "recorded_at_append" else 0,
        "events_without_recorded_utc": 0 if provenance == "recorded_at_append" else delivered * 2,
        "observed_utc_policy": "coaching-observed-utc/1.1.0",
    }
    if provenance is not None:
        summary["observed_utc_provenance"] = provenance
    events.append({
        "schema_version": "apex-research-event/1.0.0",
        "sequence": sequence,
        "observed_utc": "2026-10-05T10:29:59.0000000Z",
        "session_time_s": stamp,
        "kind": "coaching-evidence-summary",
        "data": summary,
    })
    return events


class CorpusAdmissionTests(unittest.TestCase):
    """Every check fails closed: a missing declaration is a refusal, never a pass."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.freeze = _freeze()

    # ---- bundle construction ---------------------------------------------------

    def bundle(
        self,
        block: str,
        *,
        coaching_state: str = "enabled",
        condition_id: str | None = None,
        measured: str | None = "offline-testing",
        measured_raw: str | None = None,
        car: str = "toyotagr86",
        track: str = "nurburgring-gpshort",
        layout: str = "nurburgring-gpshort",
        minutes: float = 30.0,
        delivered: int = 12,
        provenance: str | None = "recorded_at_append",
        contradicts: bool = False,
        classification: str = "private",
        participant: str = PARTICIPANT,
        setup_hash: str = SETUP_HASH,
        source_revision: str = "d" * 40,
        simulator_version: str = "2026.07.17.02 RELEASE",
        events_dropped: int = 0,
        name: str | None = None,
    ) -> Path:
        target = self.root / (name or block)
        shutil.copytree(FIXTURE, target)

        manifest = read_json(target / "manifest.json")
        manifest["session"]["participant_pseudonym"] = participant
        manifest["session"]["car"]["id"] = car
        manifest["session"]["track"]["id"] = track
        manifest["session"]["track"]["layout"] = layout
        manifest["session"]["simulator"]["version"] = simulator_version
        manifest["session"]["start_utc"] = "2026-10-05T10:00:00.0000000Z"
        end_minute = int(minutes)
        end_second = int(round((minutes - end_minute) * 60))
        manifest["session"]["end_utc"] = f"2026-10-05T10:{end_minute:02d}:{end_second:02d}.0000000Z"
        manifest["privacy"]["classification"] = classification
        manifest["collection"]["protocol_identity"] = self.freeze["protocol"]["experiment_id"]
        (target / "manifest.json").write_bytes(json.dumps(manifest).encode("utf-8"))

        metadata = read_json(target / "recorder-metadata.json")
        metadata["recorder"]["source_revision"] = source_revision
        # recorder-metadata.json and manifest.json must agree about privacy, so a
        # bundle that claims to be real evidence has to say so in both places.
        metadata["privacy"]["classification"] = classification
        metadata["collection"] = {
            "protocol_identity": self.freeze["protocol"]["experiment_id"],
            "experimental_block_id": block,
            "condition_id": condition_id if condition_id is not None else (
                "coached-delivery-on" if coaching_state == "enabled" else "coached-delivery-off"
            ),
            "coaching_state": coaching_state,
            "session_type": measured or "unknown",
            "measured_session_type": measured,
            "measured_session_type_raw": measured_raw or (
                "Offline Testing" if measured == "offline-testing" else "Race"),
            "measured_session_type_policy": "research-measured-session-type/1.0.0",
            "operator_condition_rewritten": False,
            "condition_contradicts_measured_session_type": contradicts,
            "block_contradicts_measured_session_type": False,
        }
        metadata["metrics"]["events_dropped"] = events_dropped
        (target / "recorder-metadata.json").write_bytes(json.dumps(metadata).encode("utf-8"))

        events = [json.loads(line) for line in (target / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        events[0]["data"] = {
            "block_id": block,
            "coaching_state": coaching_state,
            "condition_id": metadata["collection"]["condition_id"],
            "protocol_identity": self.freeze["protocol"]["experiment_id"],
        }
        if coaching_state == "enabled":
            events = [events[0]] + _coaching_events(delivered, provenance)
        (target / "events.jsonl").write_text(
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8", newline="\n",
        )

        metadata = read_json(target / "recorder-metadata.json")
        metadata["metrics"]["events_written"] = len(events)
        (target / "recorder-metadata.json").write_bytes(json.dumps(metadata).encode("utf-8"))

        manifest = read_json(target / "manifest.json")
        manifest["collection"]["configuration_setup_hash"] = setup_hash
        (target / "manifest.json").write_bytes(json.dumps(manifest).encode("utf-8"))

        rebind(target)
        if setup_hash != SETUP_HASH:
            # rebind recomputes the setup hash from the file; force the override back
            # so a deliberate setup-drift test really drifts.
            manifest = read_json(target / "manifest.json")
            manifest["collection"]["configuration_setup_hash"] = setup_hash
            (target / "manifest.json").write_bytes(json.dumps(manifest).encode("utf-8"))
            (target / "COMPLETE").write_bytes(
                f"apex-research-complete/v1\n{__import__('apex_labs.provenance', fromlist=['sha256_bytes']).sha256_bytes((target / 'manifest.json').read_bytes())}\n".encode("utf-8")
            )
        return target

    def admit(self, path: Path, *, apex_data_root: Path | None = None) -> dict[str, object]:
        return evaluate_bundle(
            path, self.freeze,
            apex_data_root=apex_data_root if apex_data_root is not None else self.silent_root())

    # ---- Apex store fixtures for the control arm --------------------------------

    def apex_store(self, delivered_utc: list[str], *, column: bool = True, name: str = "apex") -> Path:
        """An Apex data root whose coaching store recorded deliveries at given instants."""
        import sqlite3
        root = self.root / name
        (root / "coaching").mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(root / "coaching" / "coaching-events.db")
        recorded = ", RecordedUtc TEXT NULL" if column else ""
        connection.execute(
            "CREATE TABLE IF NOT EXISTS Events (DriverId TEXT NOT NULL, SessionId TEXT NOT NULL, "
            f"Version INTEGER NOT NULL, Schema TEXT NOT NULL, Payload TEXT NOT NULL{recorded})")
        for index, stamp in enumerate(delivered_utc):
            payload = '{"$event":"receipt-recorded","Receipt":{"Outcome":"Delivered"}}'
            if column:
                connection.execute(
                    "INSERT INTO Events VALUES ('d','s',?, 'coaching-events/1.0.0', ?, ?)",
                    (index, payload, stamp))
            else:
                connection.execute(
                    "INSERT INTO Events VALUES ('d','s',?, 'coaching-events/1.0.0', ?)",
                    (index, payload))
        connection.commit()
        connection.close()
        return root

    def silent_root(self) -> Path:
        """An Apex store that recorded nothing — the shape a true control produces."""
        if not hasattr(self, "_silent"):
            self._silent = self.apex_store([], name="apex-silent")
        return self._silent

    def codes(self, verdict: dict[str, object]) -> set[str]:
        return {finding["code"] for finding in verdict["findings"]}

    # ---- the happy path --------------------------------------------------------

    def test_a_scheduled_coached_block_is_admitted(self) -> None:
        verdict = self.admit(self.bundle("corpus-test-p01-r1-coached-delivery-on"))
        self.assertTrue(verdict["admitted"], verdict["findings"])
        self.assertEqual(0, verdict["refusal_count"])

    def test_a_scheduled_control_block_is_admitted(self) -> None:
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled"))
        self.assertTrue(verdict["admitted"], verdict["findings"])

    # ---- the plan is the authority ---------------------------------------------

    def test_a_block_not_in_the_schedule_is_refused(self) -> None:
        verdict = self.admit(self.bundle("some-block-nobody-planned"))
        self.assertFalse(verdict["admitted"])
        self.assertIn("block-not-in-schedule", self.codes(verdict))

    def test_the_wrong_arm_for_a_scheduled_block_is_refused(self) -> None:
        # Schedule says position 1 of pair 1 is coached; record it uncoached.
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", coaching_state="disabled"))
        self.assertFalse(verdict["admitted"])
        self.assertIn("coaching-state-mismatch", self.codes(verdict))
        self.assertIn("condition-mismatch", self.codes(verdict))

    def test_a_foreign_protocol_identity_is_refused(self) -> None:
        path = self.bundle("corpus-test-p01-r1-coached-delivery-on")
        metadata = read_json(path / "recorder-metadata.json")
        metadata["collection"]["protocol_identity"] = "some-other-protocol"
        (path / "recorder-metadata.json").write_bytes(json.dumps(metadata).encode("utf-8"))
        rebind(path)
        self.assertIn("protocol-identity-mismatch", self.codes(self.admit(path)))

    # ---- measured session type -------------------------------------------------

    def test_the_wrong_measured_session_type_is_refused(self) -> None:
        verdict = self.admit(self.bundle("corpus-test-p01-r1-coached-delivery-on", measured="race"))
        self.assertFalse(verdict["admitted"])
        self.assertIn("measured-session-type-mismatch", self.codes(verdict))

    def test_an_absent_measured_session_type_is_refused_not_assumed(self) -> None:
        path = self.bundle("corpus-test-p01-r1-coached-delivery-on")
        metadata = read_json(path / "recorder-metadata.json")
        del metadata["collection"]["measured_session_type"]
        (path / "recorder-metadata.json").write_bytes(json.dumps(metadata).encode("utf-8"))
        rebind(path)
        self.assertIn("measured-session-type-absent", self.codes(self.admit(path)))

    def test_an_unknown_measured_session_type_is_refused(self) -> None:
        verdict = self.admit(self.bundle("corpus-test-p01-r1-coached-delivery-on", measured="unknown"))
        self.assertIn("measured-session-type-unknown", self.codes(verdict))

    def test_the_2026_08_23_mislabel_is_refused_not_annotated(self) -> None:
        verdict = self.admit(self.bundle("corpus-test-p01-r1-coached-delivery-on", contradicts=True))
        self.assertFalse(verdict["admitted"])
        self.assertIn("operator-label-contradicts-measurement", self.codes(verdict))

    # ---- comparability ---------------------------------------------------------

    def test_a_different_car_track_or_layout_is_refused(self) -> None:
        for kwargs, code in (
            ({"car": "bmwm2g87"}, "car-mismatch"),
            ({"track": "oulton-international"}, "track-mismatch"),
            ({"layout": "international"}, "layout-mismatch"),
        ):
            with self.subTest(code=code):
                verdict = self.admit(self.bundle(
                    "corpus-test-p01-r1-coached-delivery-on", name=f"b-{code}", **kwargs))
                self.assertIn(code, self.codes(verdict))

    # ---- timestamp provenance: the M55 corpus-facing requirement ----------------

    def test_a_legacy_timestamped_coaching_stream_is_refused(self) -> None:
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", provenance="unavailable_legacy_stream"))
        self.assertFalse(verdict["admitted"])
        self.assertIn("timestamp-provenance-legacy", self.codes(verdict))

    def test_coaching_events_with_no_provenance_declaration_are_refused(self) -> None:
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", provenance=None))
        self.assertFalse(verdict["admitted"])
        self.assertIn("timestamp-provenance-absent", self.codes(verdict))

    def test_a_coached_block_that_delivered_nothing_is_a_failed_manipulation(self) -> None:
        # The Race-stratum failure mode: a valid, complete, coached recording in
        # which coaching never actually spoke. That is not a coached observation.
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", delivered=0))
        self.assertFalse(verdict["admitted"])
        self.assertIn("coached-block-no-delivered-cues", self.codes(verdict))

    def test_non_monotonic_coaching_timestamps_are_refused(self) -> None:
        path = self.bundle("corpus-test-p01-r1-coached-delivery-on")
        lines = (path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        events[1]["observed_utc"] = "2026-10-05T23:59:59.0000000Z"
        (path / "events.jsonl").write_text(
            "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events),
            encoding="utf-8", newline="\n")
        rebind(path)
        self.assertIn("timestamp-not-monotonic", self.codes(self.admit(path)))

    # ---- the manipulation check -------------------------------------------------

    def test_a_control_block_that_delivered_a_cue_is_refused(self) -> None:
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        events.append({
            "schema_version": "apex-research-event/1.0.0", "sequence": len(events),
            "observed_utc": "2026-10-05T10:05:00.0000000Z", "session_time_s": 300.0,
            "kind": "coaching-delivery-receipt", "data": {"directive_ref": "ref-x", "outcome": "Delivered"},
        })
        (path / "events.jsonl").write_text(
            "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events),
            encoding="utf-8", newline="\n")
        metadata = read_json(path / "recorder-metadata.json")
        metadata["metrics"]["events_written"] = len(events)
        (path / "recorder-metadata.json").write_bytes(json.dumps(metadata).encode("utf-8"))
        rebind(path)
        verdict = self.admit(path)
        self.assertFalse(verdict["admitted"])
        self.assertIn("control-block-delivered-cues", self.codes(verdict))

    # ---- the control arm must be silent in FACT, not by declaration -------------

    def test_a_control_block_cannot_be_admitted_without_the_apex_store(self) -> None:
        # The bundle of a control block is silent by construction: the recorder
        # never opened the store. So the bundle can never prove the driver was
        # uncoached, and unverifiable must not read as verified.
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = evaluate_bundle(path, self.freeze, apex_data_root=None)
        self.assertFalse(verdict["admitted"])
        self.assertIn("control-arm-unverified", self.codes(verdict))

    def test_a_control_block_is_admitted_when_the_store_shows_silence(self) -> None:
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = self.admit(path, apex_data_root=self.silent_root())
        self.assertTrue(verdict["admitted"], verdict["findings"])

    def test_a_fabricated_control_is_caught_by_the_store(self) -> None:
        # The operator forgot to press Stop Coaching. The bundle looks like a clean
        # control because --coaching disabled only stops the IMPORT. The store knows.
        coached = self.apex_store(
            ["2026-10-05T10:12:00.0000000Z", "2026-10-05T10:18:00.0000000Z"], name="apex-coached")
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = self.admit(path, apex_data_root=coached)
        self.assertFalse(verdict["admitted"])
        self.assertIn("control-arm-was-coached", self.codes(verdict))

    def test_delivery_outside_the_recording_window_does_not_condemn_a_control(self) -> None:
        # Cues delivered hours earlier, in a different session, are irrelevant. The
        # window is what makes this check specific rather than merely suspicious.
        elsewhere = self.apex_store(
            ["2026-10-05T06:00:00.0000000Z", "2026-10-05T23:00:00.0000000Z"], name="apex-elsewhere")
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = self.admit(path, apex_data_root=elsewhere)
        self.assertTrue(verdict["admitted"], verdict["findings"])

    def test_a_store_predating_recorded_utc_cannot_support_a_control_arm(self) -> None:
        legacy = self.apex_store([], column=False, name="apex-legacy")
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = self.admit(path, apex_data_root=legacy)
        self.assertFalse(verdict["admitted"])
        self.assertIn("control-arm-store-predates-recorded-utc", self.codes(verdict))

    def test_an_unreadable_store_refuses_rather_than_assumes_silence(self) -> None:
        path = self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled")
        verdict = self.admit(path, apex_data_root=self.root / "no-such-root")
        self.assertFalse(verdict["admitted"])
        self.assertIn("control-arm-store-unreadable", self.codes(verdict))

    def test_a_coached_block_is_not_subjected_to_the_control_check(self) -> None:
        # A coached block SHOULD show delivery in the store; that is not a finding.
        coached = self.apex_store(["2026-10-05T10:12:00.0000000Z"], name="apex-busy")
        verdict = self.admit(
            self.bundle("corpus-test-p01-r1-coached-delivery-on"), apex_data_root=coached)
        self.assertTrue(verdict["admitted"], verdict["findings"])

    # ---- capture integrity ------------------------------------------------------

    def test_a_bundle_that_dropped_evidence_events_never_reaches_the_corpus(self) -> None:
        # Labs validation already refuses a COMPLETED bundle that declares dropped
        # evidence, so this can only ever surface as bundle-invalid. The gate keeps
        # its own events-dropped check as defence in depth for a future bundle shape
        # that reaches admission without that upstream rule.
        path = self.bundle("corpus-test-p01-r1-coached-delivery-on", events_dropped=3)
        verdict = self.admit(path)
        self.assertFalse(verdict["admitted"])
        self.assertIn("bundle-invalid", self.codes(verdict))

    def test_a_short_recording_is_refused_and_a_long_one_is_a_deviation(self) -> None:
        short = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", minutes=20.0, name="short"))
        self.assertIn("recording-too-short", self.codes(short))
        self.assertFalse(short["admitted"])

        long = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on", minutes=40.0, name="long"))
        self.assertIn("recording-long", self.codes(long))
        self.assertTrue(long["admitted"], "a long block is a recorded deviation, not a refusal")

    def test_a_synthetic_bundle_can_never_enter_a_real_corpus(self) -> None:
        verdict = self.admit(self.bundle(
            "corpus-test-p01-r1-coached-delivery-on",
            classification="synthetic", participant="synthetic-participant"))
        self.assertIn("synthetic-bundle", self.codes(verdict))

    def test_an_invalid_bundle_is_refused_rather_than_raising(self) -> None:
        path = self.bundle("corpus-test-p01-r1-coached-delivery-on")
        (path / "samples.csv").write_text("corrupt", encoding="utf-8")
        verdict = self.admit(path)
        self.assertFalse(verdict["admitted"])
        self.assertIn("bundle-invalid", self.codes(verdict))

    # ---- corpus-level rules ------------------------------------------------------

    def _freeze_file(self) -> Path:
        path = self.root / "freeze.json"
        path.write_text(json.dumps(self.freeze), encoding="utf-8")
        return path

    def _all_four(self) -> list[Path]:
        return [
            self.bundle("corpus-test-p01-r1-coached-delivery-on"),
            self.bundle("corpus-test-p01-r2-coached-delivery-off", coaching_state="disabled"),
            self.bundle("corpus-test-p02-r1-coached-delivery-on"),
            self.bundle("corpus-test-p02-r2-coached-delivery-off", coaching_state="disabled"),
        ]

    def test_a_complete_corpus_is_admitted(self) -> None:
        result = admit_corpus(self._all_four(), self._freeze_file(), apex_data_root=self.silent_root())
        self.assertTrue(result["corpus_admitted"], result)
        self.assertEqual(4, result["admitted_bundles"])

    def test_a_partial_corpus_is_refused_because_a_half_design_is_a_different_design(self) -> None:
        result = admit_corpus(self._all_four()[:2], self._freeze_file(), apex_data_root=self.silent_root())
        self.assertFalse(result["corpus_admitted"])
        self.assertIn(
            "schedule-incomplete",
            {finding["code"] for finding in result["corpus_findings"]},
        )

    def test_a_duplicated_block_is_refused(self) -> None:
        bundles = self._all_four()
        bundles.append(self.bundle("corpus-test-p01-r1-coached-delivery-on", name="again"))
        result = admit_corpus(bundles, self._freeze_file(), apex_data_root=self.silent_root())
        self.assertFalse(result["corpus_admitted"])
        self.assertIn("duplicate-block", {f["code"] for f in result["corpus_findings"]})

    def test_a_setup_or_build_change_mid_corpus_is_refused(self) -> None:
        bundles = self._all_four()
        drifted = self.bundle(
            "corpus-test-p02-r2-coached-delivery-off", coaching_state="disabled",
            source_revision="e" * 40, name="drifted")
        bundles[3] = drifted
        result = admit_corpus(bundles, self._freeze_file(), apex_data_root=self.silent_root())
        self.assertFalse(result["corpus_admitted"])
        self.assertIn("product-build-varies", {f["code"] for f in result["corpus_findings"]})

    def test_an_empty_schedule_cannot_admit_anything(self) -> None:
        self.freeze["randomization"]["schedule"] = []
        self.freeze["randomization"]["schedule_sha256"] = schedule_hash([])
        self.freeze["freeze_sha256"] = freeze_hash(self.freeze)
        with self.assertRaises(ContractValidationError):
            admit_corpus([], self._freeze_file())

    def test_the_verdict_binds_the_freeze_it_was_judged_against(self) -> None:
        verdict = self.admit(self.bundle("corpus-test-p01-r1-coached-delivery-on"))
        self.assertEqual(self.freeze["freeze_sha256"], verdict["protocol_freeze_sha256"])


if __name__ == "__main__":
    unittest.main()
