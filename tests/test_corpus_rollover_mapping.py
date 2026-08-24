"""The Practice -> Qualifying rollover must land on a scheduled block.

Engineering block E02 of the 2026-10 corpus is the one recording no operator
starts. When iRacing advances Practice -> Qualifying inside the E01 recorder
invocation, the recorder finalizes E01 and opens a second bundle by itself. It
does not read the next schedule row. It derives the new block id from the
outgoing one, by the Product rule in
`ApexTrackCoach.Research/ResearchRolloverIdentity.cs`:

    NextBlockId(previous, rolloverIndex, measuredSessionType)
        => $"{previous}-r{rolloverIndex}-{Slug(measuredSessionType)}"

and it carries the operator condition id over verbatim rather than regenerating
it.

So the schedule has to be written to match what the recorder will produce. The
alternative -- relabelling the finished bundle to whatever the schedule happens
to say -- is editing measured evidence after the fact, which is exactly what
this corpus exists to make impossible. These tests pin the derived identity, and
prove through the real admission gate that the Practice bundle lands on E01, the
rolled-over bundle lands on E02, and every hand-edited alternative is refused.

Bundles are built by the corpus-admission harness, from the same committed real
recorder fixture, so a product change to the bundle shape breaks these tests too.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from _support import ROOT  # noqa: F401  (path bootstrap)

from apex_labs.corpus.admission import (
    admit_corpus,
    coaching_binding_since,
    evaluate_bundle,
)
from apex_labs.experiments.preregistration import freeze_hash, schedule_hash

import test_corpus_admission as harness

# The two identities, exactly as the schedule generator computes them and
# exactly as the Product returned them when ResearchRolloverIdentity was
# executed against the E01 block id.
E01_BLOCK = "corpus-2026-10-b-e01-practice-oulton"
E02_BLOCK = "corpus-2026-10-b-e01-practice-oulton-r1-qualifying"
SHARED_CONDITION = "engineering-practice-oulton"

# The block id and condition a hand-written E02 row would carry. Both are wrong,
# and both were in the schedule before the mapping was resolved.
HANDWRITTEN_BLOCK = "corpus-2026-10-b-e02-qualifying-oulton"
HANDWRITTEN_CONDITION = "engineering-qualifying-oulton"

# Truthful recorder track identity for Oulton Park International, read from the
# owner's own Apex stores: TrackName "oulton international", TrackConfigName
# "International".
TRACK = "oulton international"
LAYOUT = "International"

ROLLOVER_INDEX = 1
ROLLOVER_SLUG = "qualifying"


def rollover_block_id(previous: str, index: int, slug: str) -> str:
    """Mirror of Product ResearchRolloverIdentity.NextBlockId."""
    return f"{previous}-r{index}-{slug}"


def _rollover_schedule() -> list[dict[str, object]]:
    """The two engineering rows one recorder invocation produces."""
    return [
        {
            "recording_ordinal": 13,
            "stratum": "engineering-diversity",
            "pair_id": None,
            "position_in_pair": None,
            "arm_id": "coached-delivery-on",
            "coaching_state": "enabled",
            "block_id": E01_BLOCK,
            "condition_id": SHARED_CONDITION,
            "car": "toyotagr86",
            "track": TRACK,
            "layout": LAYOUT,
            "measured_session_type_required": "practice",
            "planned_minutes": 30,
            "started_by": "operator",
        },
        {
            "recording_ordinal": 14,
            "stratum": "engineering-diversity",
            "pair_id": None,
            "position_in_pair": None,
            "arm_id": "coached-delivery-on",
            "coaching_state": "enabled",
            "block_id": rollover_block_id(E01_BLOCK, ROLLOVER_INDEX, ROLLOVER_SLUG),
            "condition_id": SHARED_CONDITION,
            "car": "toyotagr86",
            "track": TRACK,
            "layout": LAYOUT,
            "measured_session_type_required": "qualifying",
            "planned_minutes": 30,
            "started_by": "recorder-session-rollover",
            "produced_by_rollover": {
                "source_block_id": E01_BLOCK,
                "rollover_index": ROLLOVER_INDEX,
                "measured_session_slug": ROLLOVER_SLUG,
                "condition_id_is_carried_over": True,
            },
        },
    ]


class RolloverMappingTests(unittest.TestCase):
    """The rolled-over Qualifying bundle maps to E02 without touching evidence."""

    def setUp(self) -> None:
        # Compose the admission harness rather than inheriting from it: its own
        # 45 tests are about a different schedule and must not run again here.
        self.harness = harness.CorpusAdmissionTests("test_a_scheduled_coached_block_is_admitted")
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.root: Path = self.harness.root

        freeze = self.harness.freeze
        schedule = _rollover_schedule()
        freeze["randomization"]["schedule"] = schedule
        freeze["randomization"]["schedule_id"] = "corpus-rollover-test-schedule"
        freeze["randomization"]["schedule_sha256"] = schedule_hash(schedule)
        freeze["freeze_sha256"] = "0" * 64
        freeze["freeze_sha256"] = freeze_hash(freeze)
        self.freeze = freeze

    # ---- fixtures --------------------------------------------------------------

    def rows(self) -> dict[str, dict[str, object]]:
        return {str(r["block_id"]): r for r in self.freeze["randomization"]["schedule"]}

    def reseal(self) -> None:
        """Recompute the freeze digest after a test edits the schedule."""
        self.freeze["randomization"]["schedule_sha256"] = schedule_hash(
            self.freeze["randomization"]["schedule"])
        self.freeze["freeze_sha256"] = "0" * 64
        self.freeze["freeze_sha256"] = freeze_hash(self.freeze)

    def practice(self, **overrides: object) -> Path:
        kwargs: dict[str, object] = {
            "condition_id": SHARED_CONDITION,
            "measured": "practice",
            "measured_raw": "Practice",
            "track": TRACK,
            "layout": LAYOUT,
            "name": "e01-practice",
        }
        kwargs.update(overrides)
        block = str(kwargs.pop("block", E01_BLOCK))
        return self.harness.bundle(block, **kwargs)  # type: ignore[arg-type]

    def qualifying(self, **overrides: object) -> Path:
        """What the recorder actually writes on the far side of the transition."""
        kwargs: dict[str, object] = {
            "condition_id": SHARED_CONDITION,
            "measured": "qualifying",
            "measured_raw": "Open Qualify",
            "track": TRACK,
            "layout": LAYOUT,
            "name": "e02-qualifying",
        }
        kwargs.update(overrides)
        block = str(kwargs.pop("block", E02_BLOCK))
        return self.harness.bundle(block, **kwargs)  # type: ignore[arg-type]

    def evaluate(self, path: Path) -> dict[str, object]:
        return evaluate_bundle(
            path, self.freeze, apex_data_root=self.harness.silent_root())

    def admit(self, paths: list[Path]) -> dict[str, object]:
        freeze_path = self.root / "rollover-freeze.json"
        freeze_path.write_text(json.dumps(self.freeze), encoding="utf-8")
        return admit_corpus(
            paths, freeze_path, apex_data_root=self.harness.silent_root())

    def codes(self, verdict: dict[str, object]) -> set[str]:
        return {f["code"] for f in verdict["findings"]}

    # ---- the derivation itself -------------------------------------------------

    def test_the_e02_block_id_is_derived_from_e01_not_chosen(self) -> None:
        """If the Product rule changes, this fails here rather than at the track."""
        self.assertEqual(E02_BLOCK, rollover_block_id(E01_BLOCK, 1, "qualifying"))
        self.assertTrue(E02_BLOCK.startswith(E01_BLOCK + "-"))
        self.assertEqual(50, len(E02_BLOCK))
        self.assertNotEqual(HANDWRITTEN_BLOCK, E02_BLOCK)

    def test_the_scheduled_e02_row_is_the_derived_identity(self) -> None:
        rows = self.rows()
        self.assertIn(E02_BLOCK, rows)
        self.assertEqual(
            E01_BLOCK, rows[E02_BLOCK]["produced_by_rollover"]["source_block_id"])
        self.assertEqual("recorder-session-rollover", rows[E02_BLOCK]["started_by"])
        self.assertEqual("operator", rows[E01_BLOCK]["started_by"])

    def test_the_rolled_over_row_carries_the_source_condition(self) -> None:
        """The recorder does not regenerate the condition, so nor may the schedule."""
        rows = self.rows()
        self.assertEqual(rows[E01_BLOCK]["condition_id"], rows[E02_BLOCK]["condition_id"])

    # ---- each bundle lands on its own scheduled block ---------------------------

    def test_the_practice_bundle_maps_to_its_own_block(self) -> None:
        verdict = self.evaluate(self.practice())
        self.assertTrue(verdict["admitted"], verdict["findings"])
        self.assertEqual(E01_BLOCK, verdict["block_id"])

    def test_the_qualifying_bundle_maps_to_e02(self) -> None:
        verdict = self.evaluate(self.qualifying())
        self.assertTrue(verdict["admitted"], verdict["findings"])
        self.assertEqual(E02_BLOCK, verdict["block_id"])

    def test_the_two_bundles_admit_together_through_the_real_gate(self) -> None:
        """One recorder invocation, two bundles, both scheduled, corpus complete."""
        report = self.admit([self.practice(), self.qualifying()])
        self.assertTrue(report["corpus_admitted"], report)
        self.assertEqual(2, report["scheduled_blocks"])
        self.assertEqual(2, report["admitted_bundles"])
        self.assertEqual(0, report["refused_bundles"])
        self.assertEqual([], report["corpus_findings"])
        self.assertEqual(
            [E01_BLOCK, E02_BLOCK], [b["block_id"] for b in report["bundles"]])

    def test_the_two_bundles_are_not_the_same_block(self) -> None:
        """A rollover that reused the source id would collide, not map."""
        report = self.admit([
            self.practice(),
            self.qualifying(block=E01_BLOCK, measured="practice",
                            measured_raw="Practice", name="e02-collided"),
        ])
        self.assertFalse(report["corpus_admitted"])
        codes = {f["code"] for f in report["corpus_findings"]}
        self.assertIn("duplicate-block", codes)
        self.assertIn("schedule-incomplete", codes)

    # ---- the alternatives that must be refused ---------------------------------

    def test_a_schedule_row_written_by_hand_refuses_the_real_bundle(self) -> None:
        """The blocker itself: name E02 what it 'should' be and the gate says no.

        This is the state the schedule was in before the mapping was resolved, and
        it is why the row had to be computed rather than typed.
        """
        row = self.rows()[E02_BLOCK]
        row["block_id"] = HANDWRITTEN_BLOCK
        row["condition_id"] = HANDWRITTEN_CONDITION
        self.reseal()

        verdict = self.evaluate(self.qualifying())
        self.assertFalse(verdict["admitted"])
        self.assertIn("block-not-in-schedule", self.codes(verdict))

    def test_relabelling_the_bundle_to_fit_the_schedule_is_not_the_fix(self) -> None:
        """Editing measured evidence to match a plan is the failure mode, not a repair.

        Rename the bundle's block id to the hand-written row and the block matches
        -- and the bundle is still refused, because the condition the recorder
        carried over is not the condition a hand-written row assigns. There is no
        edit that makes a wrong row right; only the row can change.
        """
        row = self.rows()[E02_BLOCK]
        row["block_id"] = HANDWRITTEN_BLOCK
        row["condition_id"] = HANDWRITTEN_CONDITION
        self.reseal()

        relabelled = self.qualifying(block=HANDWRITTEN_BLOCK, name="e02-relabelled")
        verdict = self.evaluate(relabelled)
        self.assertFalse(verdict["admitted"])
        self.assertIn("condition-mismatch", self.codes(verdict))

    def test_a_regenerated_condition_id_on_e02_is_refused(self) -> None:
        """Right block id, invented condition. The carried-over one is the truth."""
        self.rows()[E02_BLOCK]["condition_id"] = HANDWRITTEN_CONDITION
        self.reseal()

        verdict = self.evaluate(self.qualifying())
        self.assertFalse(verdict["admitted"])
        self.assertIn("condition-mismatch", self.codes(verdict))

    def test_a_transition_that_never_happened_is_refused(self) -> None:
        """Stopping in Practice and restarting leaves E02 measuring practice."""
        verdict = self.evaluate(self.qualifying(
            measured="practice", measured_raw="Practice", name="e02-still-practice"))
        self.assertFalse(verdict["admitted"])
        self.assertIn("measured-session-type-mismatch", self.codes(verdict))

    def test_the_practice_bundle_cannot_stand_in_for_the_qualifying_one(self) -> None:
        report = self.admit([self.practice()])
        self.assertFalse(report["corpus_admitted"])
        codes = {f["code"] for f in report["corpus_findings"]}
        self.assertIn("schedule-incomplete", codes)
        self.assertIn(
            E02_BLOCK,
            next(f["message"] for f in report["corpus_findings"]
                 if f["code"] == "schedule-incomplete"))

    def test_an_unbound_rollover_bundle_never_reaches_the_gate(self) -> None:
        """The M37.2 observation-window hazard, stated as a test.

        Stopping the recorder before the new coaching session binds finalizes the
        rolled-over bundle as INCOMPLETE. Labs refuses it as invalid, so it is not
        a mapping question at all -- there is nothing to map.
        """
        target = self.qualifying(name="e02-unbound")
        (target / "COMPLETE").unlink()
        verdict = self.evaluate(target)
        self.assertFalse(verdict["admitted"])
        self.assertIn("bundle-invalid", self.codes(verdict))


class RolloverBindingConditionTests(unittest.TestCase):
    """The console condition the operator waits for at the transition.

    The recorder cannot supply it. `CoachingBindingProbe` latches: once it has
    reported Bound for the Practice session, `Evaluate` returns Quiet for the rest
    of the invocation, so the rolled-over Qualifying session gets neither a bound
    line nor a warning. The operator needs a signal from somewhere, because
    stopping the recorder before the new coaching session exists finalizes the new
    bundle as INCOMPLETE. This read-only store query is that signal.
    """

    TRANSITION = "2026-10-05T10:30:00.0000000Z"

    def setUp(self) -> None:
        self.harness = harness.CorpusAdmissionTests("test_a_scheduled_coached_block_is_admitted")
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)

    def store(self, delivered_utc: list[str], *, name: str) -> Path:
        return self.harness.apex_store(delivered_utc, name=name)

    def test_a_silent_store_is_not_binding_ready(self) -> None:
        """Nothing since the transition: the new session does not exist yet."""
        report = coaching_binding_since(self.store([], name="quiet"), self.TRANSITION)
        self.assertTrue(report["readable"])
        self.assertTrue(report["recorded_utc_available"])
        self.assertFalse(report["binding_ready"])
        self.assertEqual([], report["sessions_since"])
        self.assertEqual(0, report["delivered_since"])

    def test_practice_deliveries_before_the_transition_do_not_count(self) -> None:
        """The latch problem in miniature: the OLD session was bound, and that is
        exactly the evidence that must not be mistaken for the new one."""
        root = self.store(
            ["2026-10-05T10:05:00.0000000Z", "2026-10-05T10:20:00.0000000Z"],
            name="practice-only")
        report = coaching_binding_since(root, self.TRANSITION)
        self.assertFalse(report["binding_ready"])
        self.assertEqual(0, report["delivered_since"])

    def test_a_delivered_cue_after_the_transition_is_binding_ready(self) -> None:
        root = self.store(
            ["2026-10-05T10:20:00.0000000Z", "2026-10-05T10:39:12.0000000Z"],
            name="qualifying-bound")
        report = coaching_binding_since(root, self.TRANSITION)
        self.assertTrue(report["binding_ready"])
        self.assertEqual(1, report["delivered_since"])
        self.assertEqual(1, len(report["sessions_since"]))
        self.assertEqual("2026-10-05T10:39:12.0000000Z",
                         report["sessions_since"][0]["last_utc"])

    def test_a_store_without_recorded_utc_cannot_answer(self) -> None:
        """A pre-M55B build cannot place an event in wall-clock time, so it fails
        closed rather than reporting a binding it cannot see."""
        root = self.store(["2026-10-05T10:39:12.0000000Z"], name="legacy")
        # rebuild without the column
        import shutil
        shutil.rmtree(root)
        root = self.harness.apex_store(
            ["2026-10-05T10:39:12.0000000Z"], column=False, name="legacy")
        report = coaching_binding_since(root, self.TRANSITION)
        self.assertTrue(report["readable"])
        self.assertFalse(report["recorded_utc_available"])
        self.assertFalse(report["binding_ready"])

    def test_a_missing_store_fails_closed(self) -> None:
        report = coaching_binding_since(
            self.harness.root / "no-such-root", self.TRANSITION)
        self.assertFalse(report["readable"])
        self.assertFalse(report["binding_ready"])

    def test_an_unparseable_instant_fails_closed(self) -> None:
        root = self.store(["2026-10-05T10:39:12.0000000Z"], name="ok")
        report = coaching_binding_since(root, "not-a-timestamp")
        self.assertFalse(report["readable"])
        self.assertFalse(report["binding_ready"])



if __name__ == "__main__":
    unittest.main()
