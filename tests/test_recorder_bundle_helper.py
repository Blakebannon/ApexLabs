"""The bundle helper must build a VALID bundle for both arms.

`build_protocol_block_bundle` used to rebuild `events.jsonl` as the collection
condition marker plus, for a coached block, the coaching evidence. For a control
block it emitted the marker alone, silently discarding the recorder fixture's own
`coaching-disabled-control` event. Labs refuses a disabled bundle without it
("disabled control condition is not explicit"), so every control bundle built
through this helper failed validation as `bundle-invalid` before any rule under
test could be reached. A control arm was, in effect, untestable through the
helper, and the failure looked like a schedule fault rather than a fixture fault.

These tests assert the helper's output directly — the marker survives, the
sequence numbering stays contract-legal, and the bundle passes the real audit —
so the helper cannot regress into producing bundles that are invalid for reasons
unrelated to whatever a caller is trying to prove.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _support import ROOT  # noqa: F401  (path bootstrap)
from recorder_bundle import DISABLED_CONTROL_KIND, build_protocol_block_bundle

from apex_labs.ingestion.apex_research import audit_research_bundle

PARTICIPANT = "participant-" + "5c" * 12
PROTOCOL = "recorder-bundle-helper-test"


def events_of(bundle: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (bundle / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class ControlBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def build(self, name: str, coaching_state: str):
        return build_protocol_block_bundle(
            self.root / name,
            protocol_identity=PROTOCOL,
            block_id=f"{PROTOCOL}-{name}",
            condition_id=f"{PROTOCOL}-condition",
            participant=PARTICIPANT,
            coaching_state=coaching_state,
            measured="offline-testing",
            measured_raw="Offline Testing",
        )

    # ---- the defect, pinned ----------------------------------------------

    def test_a_control_bundle_keeps_the_disabled_control_marker(self) -> None:
        kinds = [event["kind"] for event in events_of(self.build("control", "disabled"))]
        self.assertIn(DISABLED_CONTROL_KIND, kinds)

    def test_a_control_bundle_passes_the_real_audit(self) -> None:
        """It used to raise ContractValidationError, surfacing as bundle-invalid."""
        audit = audit_research_bundle(self.build("control-audit", "disabled"))
        self.assertEqual("disabled", audit.metadata["collection"]["coaching_state"])

    def test_a_control_bundle_carries_no_delivered_cue(self) -> None:
        kinds = [event["kind"] for event in events_of(self.build("control-quiet", "disabled"))]
        self.assertNotIn("coaching-delivery-receipt", kinds)
        self.assertNotIn("coaching-directive-authorized", kinds)

    # ---- the coached arm keeps working -----------------------------------

    def test_a_coached_bundle_passes_the_real_audit(self) -> None:
        audit = audit_research_bundle(self.build("coached", "enabled"))
        self.assertEqual("enabled", audit.metadata["collection"]["coaching_state"])

    def test_a_coached_bundle_carries_delivered_cues_and_no_control_marker(self) -> None:
        kinds = [event["kind"] for event in events_of(self.build("coached-cues", "enabled"))]
        self.assertIn("coaching-delivery-receipt", kinds)
        self.assertIn("coaching-evidence-summary", kinds)
        self.assertNotIn(DISABLED_CONTROL_KIND, kinds)

    # ---- structural invariants both arms must satisfy ---------------------

    def test_both_arms_number_events_contiguously_from_zero(self) -> None:
        for state in ("enabled", "disabled"):
            with self.subTest(coaching_state=state):
                events = events_of(self.build(f"seq-{state}", state))
                self.assertEqual(
                    list(range(len(events))), [event["sequence"] for event in events])

    def test_both_arms_open_with_the_collection_condition_marker(self) -> None:
        for state in ("enabled", "disabled"):
            with self.subTest(coaching_state=state):
                events = events_of(self.build(f"marker-{state}", state))
                self.assertEqual("collection-condition", events[0]["kind"])
                self.assertEqual(state, events[0]["data"]["coaching_state"])

    def test_the_metrics_event_count_matches_the_events_written(self) -> None:
        for state in ("enabled", "disabled"):
            with self.subTest(coaching_state=state):
                bundle = self.build(f"count-{state}", state)
                audit = audit_research_bundle(bundle)
                self.assertEqual(
                    len(events_of(bundle)), audit.metadata["metrics"]["events_written"])


if __name__ == "__main__":
    unittest.main()
