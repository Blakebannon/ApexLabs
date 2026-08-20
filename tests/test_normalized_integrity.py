from __future__ import annotations

import copy
import math
import unittest

from _support import base_record_stream, qualified, temporal_policy

from apex_labs.errors import ContractValidationError, IntegrityError
from apex_labs.normalization.integrity import NormalizedIntegrityTracker
from apex_labs.schemas import validate_normalized_record


def run_stream(records, policy=None):
    tracker = NormalizedIntegrityTracker("integrity-dataset", policy or temporal_policy())
    for record in records:
        validate_normalized_record(record)
        tracker.add(record)
    return tracker.finalize()


def append_sample(records, *, timestamp: float, sample_index: int, distance: float = 10.0):
    sample = copy.deepcopy(records[3])
    sample["record_id"] = f"sample-{sample_index:02d}.record"
    sample["sample_index"] = sample_index
    sample["fields"]["timestamp"]["value"] = timestamp
    sample["fields"]["lap_distance"]["value"] = distance
    records.insert(-1, sample)
    for index, record in enumerate(records):
        record["sequence_index"] = index
    return sample


class RelationalIntegrityTests(unittest.TestCase):
    def test_full_session_lap_segment_sample_event_graph_is_valid(self) -> None:
        summary = run_stream(base_record_stream())
        self.assertEqual("verified", summary["parent_references"])
        self.assertTrue(summary["unique_record_ids"])

    def test_duplicate_record_session_lap_and_segment_identities_are_refused(self) -> None:
        for record_index, identity_field, duplicate_value in (
            (1, "record_id", "session-01.record"),
            (1, "lap_id", "lap-01"),
            (2, "segment_id", "segment-01"),
        ):
            records = base_record_stream()
            duplicate = copy.deepcopy(records[record_index])
            duplicate["record_id"] = f"duplicate-{record_index}.record"
            duplicate[identity_field] = duplicate_value
            duplicate["sequence_index"] = len(records)
            records.append(duplicate)
            with self.subTest(identity_field=identity_field), self.assertRaises(IntegrityError):
                run_stream(records)

    def test_missing_or_crossed_parent_references_are_refused(self) -> None:
        cases = []
        unknown_session = base_record_stream()
        unknown_session[1]["session_id"] = "missing-session"
        cases.append(unknown_session)
        unknown_lap = base_record_stream()
        unknown_lap[3]["lap_id"] = "missing-lap"
        cases.append(unknown_lap)
        unknown_segment = base_record_stream()
        unknown_segment[4]["segment_id"] = "missing-segment"
        cases.append(unknown_segment)
        for records in cases:
            with self.assertRaises(IntegrityError):
                run_stream(records)

    def test_parent_before_child_and_contiguous_sequence_are_mandatory(self) -> None:
        records = base_record_stream()
        records[1], records[3] = records[3], records[1]
        for index, record in enumerate(records):
            record["sequence_index"] = index
        with self.assertRaises(IntegrityError):
            run_stream(records)

        records = base_record_stream()
        records[2]["sequence_index"] = 7
        with self.assertRaises(IntegrityError):
            run_stream(records)


class TemporalIntegrityTests(unittest.TestCase):
    def test_timestamps_and_sample_indices_are_strict_by_default(self) -> None:
        records = base_record_stream()
        append_sample(records, timestamp=0.0, sample_index=1)
        with self.assertRaises(IntegrityError):
            run_stream(records)

        records = base_record_stream()
        append_sample(records, timestamp=-0.1, sample_index=1)
        with self.assertRaises(IntegrityError):
            run_stream(records)

        records = base_record_stream()
        append_sample(records, timestamp=0.1, sample_index=0)
        with self.assertRaises(IntegrityError):
            run_stream(records)

    def test_declared_duplicate_reset_and_gap_policies_preserve_quality_flags(self) -> None:
        policy = temporal_policy()
        policy["duplicate_timestamp_policy"] = "allow_with_quality_flag"
        records = base_record_stream()
        duplicate = append_sample(records, timestamp=0.0, sample_index=1)
        summary = run_stream(records, policy)
        self.assertIn("duplicate_timestamp", duplicate["quality_flags"])
        self.assertEqual(1, summary["quality_flag_counts"]["duplicate_timestamp"])

        policy = temporal_policy()
        policy["clock_reset_policy"] = "allow_with_quality_flag"
        records = base_record_stream()
        reset = append_sample(records, timestamp=-0.1, sample_index=1)
        summary = run_stream(records, policy)
        self.assertIn("clock_reset", reset["quality_flags"])
        self.assertEqual(1, summary["quality_flag_counts"]["clock_reset"])

        policy = temporal_policy()
        policy["expected_sample_period_seconds"] = 0.1
        policy["gap_tolerance_seconds"] = 0.01
        records = base_record_stream()
        gap = append_sample(records, timestamp=0.3, sample_index=2)
        summary = run_stream(records, policy)
        self.assertEqual(
            ["sample_index_gap", "timestamp_gap"], gap["quality_flags"]
        )
        self.assertEqual("evaluated", summary["gap_detection"])

    def test_lap_distance_regression_is_rejected_or_flagged_without_repair(self) -> None:
        records = base_record_stream()
        records[3]["fields"]["lap_distance"]["value"] = 20.0
        append_sample(records, timestamp=0.1, sample_index=1, distance=19.0)
        with self.assertRaises(IntegrityError):
            run_stream(records)

        policy = temporal_policy()
        policy["lap_distance_regression_policy"] = "allow_with_quality_flag"
        records = base_record_stream()
        records[3]["fields"]["lap_distance"]["value"] = 20.0
        regressed = append_sample(records, timestamp=0.1, sample_index=1, distance=19.0)
        run_stream(records, policy)
        self.assertIn("lap_distance_regression", regressed["quality_flags"])

    def test_lap_distance_reset_between_laps_is_structurally_valid(self) -> None:
        records = base_record_stream()
        records[3]["fields"]["lap_distance"]["value"] = 100.0
        lap = copy.deepcopy(records[1])
        lap.update(
            {
                "record_id": "lap-02.record",
                "lap_id": "lap-02",
                "lap_number": 2,
                "sequence_index": 5,
            }
        )
        sample = copy.deepcopy(records[3])
        sample.update(
            {
                "record_id": "sample-01.record",
                "lap_id": "lap-02",
                "sample_index": 1,
                "sequence_index": 6,
            }
        )
        sample.pop("segment_id")
        sample["fields"]["timestamp"]["value"] = 1.0
        sample["fields"]["lap_distance"]["value"] = 0.0
        records.extend([lap, sample])
        run_stream(records)


class ValueIntegrityTests(unittest.TestCase):
    def test_unavailable_absent_and_measured_zero_are_distinct(self) -> None:
        records = base_record_stream()
        sample = records[3]
        self.assertEqual(0.0, sample["fields"]["brake"]["value"])
        self.assertEqual("measured", sample["fields"]["brake"]["provenance"])
        del sample["fields"]["brake"]
        validate_normalized_record(sample)  # absent means not supplied for this record
        sample["fields"]["brake"] = qualified(None, "ratio", concept="brake")
        validate_normalized_record(sample)
        self.assertIsNone(sample["fields"]["brake"]["value"])
        self.assertEqual("unavailable", sample["fields"]["brake"]["provenance"])

    def test_nonfinite_numbers_and_noncanonical_units_are_refused(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            record = base_record_stream()[3]
            record["fields"]["speed"] = qualified(value, "m/s", concept="speed")
            with self.subTest(value=value), self.assertRaises(ContractValidationError):
                validate_normalized_record(record)
        record = base_record_stream()[3]
        record["fields"]["speed"] = qualified(30.0, "km/h", concept="speed")
        with self.assertRaises(ContractValidationError):
            validate_normalized_record(record)

    def test_normalized_timestamp_requires_declared_monotonic_reference(self) -> None:
        record = base_record_stream()[3]
        del record["fields"]["timestamp"]["reference"]
        with self.assertRaises(ContractValidationError):
            validate_normalized_record(record)


if __name__ == "__main__":
    unittest.main()
