"""Scheduled track/layout identities must be what the recorder actually writes.

The defect this file exists to prevent
--------------------------------------
The 2026-10 corpus schedule was built from strings held in the Apex coaching
stores, which carry the space-separated iRacing form ("oulton international",
config "International"). The research recorder does not write that form. With no
``--track`` / ``--layout`` override it normalizes the WeekendInfo strings:

    value.Trim().ToLowerInvariant().Replace(' ', '-')

so a truthful capture carries "oulton-international" / "international". Every one
of the twenty scheduled blocks would therefore have been refused ``track-mismatch``
and ``layout-mismatch`` on admission, after the recording was already driven.

It survived review because the test that "proved" the schedule admitted built its
bundles FROM the schedule's own track/layout values. That comparison is
schedule-against-itself and passes for any pair of strings, truthful or not.

The invariant here breaks that circularity: a scheduled identity must be a fixed
point of the recorder's normalization. Any value the recorder would have rewritten
is not a value the recorder can produce, so no schedule may declare it. This is
checked against the normalization rule, never against another schedule value.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _support import ROOT  # noqa: F401  (path bootstrap)
from recorder_bundle import build_protocol_block_bundle
from test_protocol_bound_pipeline import (
    BLOCK_ID,
    CONDITION_ID,
    EXPERIMENT_ID,
    PARTICIPANT,
    _freeze,
    _schedule,
)

from apex_labs.corpus.admission import evaluate_bundle

#: Transcription of the recorder's no-override branch in
#: tools/ApexTrackCoach.ResearchRecorder/Program.cs (ValueOrSource).
RECORDER_IDENTITY_RULE = "value.Trim().ToLowerInvariant().Replace(' ', '-')"

#: Every identity field on a schedule row that the admission gate compares
#: character-for-character against a recorder-written bundle value.
RECORDER_IDENTITY_FIELDS = ("track", "layout")


def recorder_identity(source: str) -> str:
    """What the recorder writes for a WeekendInfo string, given no override."""
    return source.strip().lower().replace(" ", "-")


def assert_schedule_uses_recorder_identities(schedule, label="schedule"):
    """Raise unless every scheduled identity is one the recorder can produce.

    Deliberately NOT a comparison against another schedule, a bundle built from
    the schedule, or a captured expectation: it applies the recorder's own
    normalization and requires the value to be unchanged by it.
    """
    offenders = []
    for index, row in enumerate(schedule):
        for field in RECORDER_IDENTITY_FIELDS:
            if field not in row:
                continue
            declared = row[field]
            produced = recorder_identity(declared)
            if declared != produced:
                offenders.append(
                    f"{label}[{index}].{field}: declares {declared!r} but a truthful "
                    f"capture writes {produced!r}"
                )
    if offenders:
        raise AssertionError(
            f"{len(offenders)} scheduled identity value(s) the recorder cannot produce:\n  "
            + "\n  ".join(offenders)
        )


class RecorderIdentityRuleTests(unittest.TestCase):
    """The rule itself, pinned so a transcription drift fails here."""

    CASES = (
        ("nurburgring gpshort", "nurburgring-gpshort"),
        ("oulton international", "oulton-international"),
        ("International", "international"),
        ("tsukuba 2kfull", "tsukuba-2kfull"),
        ("  Padded  Name  ", "padded--name"),
        ("already-normal", "already-normal"),
    )

    def test_the_rule_matches_the_product_transcription(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(expected, recorder_identity(source))

    def test_every_recorder_output_is_a_fixed_point(self) -> None:
        """Normalizing twice must equal normalizing once, or the invariant is unusable."""
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(expected, recorder_identity(expected))

    def test_the_space_form_is_not_a_fixed_point(self) -> None:
        for space_form in ("oulton international", "nurburgring gpshort", "International"):
            with self.subTest(value=space_form):
                self.assertNotEqual(space_form, recorder_identity(space_form))


class ScheduleIdentityInvariantTests(unittest.TestCase):
    def test_a_recorder_normal_schedule_passes(self) -> None:
        assert_schedule_uses_recorder_identities(_schedule())

    def test_a_space_form_schedule_is_rejected(self) -> None:
        rows = _schedule()
        rows[0]["track"] = "oulton international"
        rows[0]["layout"] = "International"
        with self.assertRaises(AssertionError) as raised:
            assert_schedule_uses_recorder_identities(rows, label="corpus")
        message = str(raised.exception)
        self.assertIn("oulton international", message)
        self.assertIn("oulton-international", message)
        self.assertIn("International", message)

    def test_the_check_counts_every_offending_field(self) -> None:
        rows = _schedule() + _schedule("second-block")
        for row in rows:
            row["track"] = "oulton international"
            row["layout"] = "International"
        with self.assertRaises(AssertionError) as raised:
            assert_schedule_uses_recorder_identities(rows)
        self.assertIn("4 scheduled identity value(s)", str(raised.exception))


class ScheduleAdmitsRecorderShapedBundlesTests(unittest.TestCase):
    """The end of the circularity: bundles carry recorder output, not schedule text."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        # Independent of any schedule: the sim strings, put through the recorder rule.
        self.track = recorder_identity("oulton international")
        self.layout = recorder_identity("International")

    def bundle(self, name: str):
        return build_protocol_block_bundle(
            self.root / name,
            protocol_identity=EXPERIMENT_ID,
            block_id=BLOCK_ID,
            condition_id=CONDITION_ID,
            participant=PARTICIPANT,
            track=self.track,
            layout=self.layout,
        )

    def test_a_recorder_normal_schedule_admits_a_recorder_shaped_bundle(self) -> None:
        freeze = _freeze(schedule=_schedule(track=self.track, layout=self.layout))
        verdict = evaluate_bundle(self.bundle("good"), freeze)
        self.assertEqual([], verdict["findings"])
        self.assertTrue(verdict["admitted"])

    def test_a_space_form_schedule_refuses_a_recorder_shaped_bundle(self) -> None:
        """The exact 2026-10 defect, reproduced through the real gate."""
        freeze = _freeze(
            schedule=_schedule(track="oulton international", layout="International"))
        verdict = evaluate_bundle(self.bundle("bad"), freeze)
        self.assertFalse(verdict["admitted"])
        self.assertEqual(
            ["track-mismatch", "layout-mismatch"],
            [f["code"] for f in verdict["findings"]],
        )


if __name__ == "__main__":
    unittest.main()
