"""Cross-record structural and temporal integrity checks."""

from __future__ import annotations

from collections import Counter
from typing import Any

from apex_labs.errors import IntegrityError


class NormalizedIntegrityTracker:
    """Validate one canonical record stream without repairing scientific defects."""

    def __init__(self, dataset_id: str, temporal_policy: dict[str, Any]) -> None:
        self.dataset_id = dataset_id
        self.policy = temporal_policy
        self.record_ids: set[str] = set()
        self.sessions: set[str] = set()
        self.laps: dict[str, str] = {}
        self.segments: dict[str, tuple[str, str]] = {}
        self.last_sample_index: dict[str, int] = {}
        self.last_timestamp: dict[str, float] = {}
        self.last_lap_distance: dict[str, float] = {}
        self.last_distance_bin_index: dict[str, int] = {}
        self.last_distance_bin_start: dict[str, float] = {}
        self.saw_distance_bins = False
        self.counts: Counter[str] = Counter()
        self.quality_counts: Counter[str] = Counter()
        self.expected_sequence = 0

    def _flag(self, record: dict[str, Any], flag: str) -> None:
        flags = record.setdefault("quality_flags", [])
        if flag not in flags:
            flags.append(flag)
            flags.sort()
            self.quality_counts[flag] += 1

    def _parent_invariants(self, record: dict[str, Any]) -> None:
        record_type = record["record_type"]
        session_id = record["session_id"]
        if record_type == "session":
            if session_id in self.sessions:
                raise IntegrityError(f"Duplicate session identity: {session_id}")
            self.sessions.add(session_id)
            return
        if session_id not in self.sessions:
            raise IntegrityError(f"Record {record['record_id']} references unknown or later session {session_id}")
        if record_type == "lap":
            lap_id = record["lap_id"]
            if lap_id in self.laps:
                raise IntegrityError(f"Duplicate lap identity: {lap_id}")
            self.laps[lap_id] = session_id
            return
        lap_id = record["lap_id"]
        if lap_id not in self.laps:
            raise IntegrityError(f"Record {record['record_id']} references unknown or later lap {lap_id}")
        if self.laps[lap_id] != session_id:
            raise IntegrityError(f"Record {record['record_id']} crosses session/lap containment")
        if record_type == "segment":
            segment_id = record["segment_id"]
            if segment_id in self.segments:
                raise IntegrityError(f"Duplicate segment identity: {segment_id}")
            self.segments[segment_id] = (session_id, lap_id)
        segment_id = record.get("segment_id")
        if segment_id is not None and record_type != "segment":
            if segment_id not in self.segments:
                raise IntegrityError(
                    f"Record {record['record_id']} references unknown or later segment {segment_id}"
                )
            if self.segments[segment_id] != (session_id, lap_id):
                raise IntegrityError(f"Record {record['record_id']} crosses segment containment")

    def _temporal_invariants(self, record: dict[str, Any]) -> None:
        if record["record_type"] != "telemetry_sample":
            return
        session_id = record["session_id"]
        sample_index = record["sample_index"]
        previous_index = self.last_sample_index.get(session_id)
        if previous_index is not None and sample_index <= previous_index:
            raise IntegrityError(f"Telemetry sample indices are not strictly increasing in {session_id}")
        if previous_index is not None and sample_index != previous_index + 1:
            self._flag(record, "sample_index_gap")
        self.last_sample_index[session_id] = sample_index

        timestamp_field = record["fields"]["timestamp"]
        timestamp = timestamp_field["value"]
        if timestamp is None:
            self._flag(record, "timestamp_unavailable")
            return
        timestamp = float(timestamp)
        previous = self.last_timestamp.get(session_id)
        if previous is not None:
            delta = timestamp - previous
            if delta < 0:
                if self.policy["clock_reset_policy"] == "reject":
                    raise IntegrityError(f"Normalized timestamp reset in session {session_id}")
                self._flag(record, "clock_reset")
            elif delta == 0:
                if self.policy["duplicate_timestamp_policy"] == "reject":
                    raise IntegrityError(f"Duplicate normalized timestamp in session {session_id}")
                self._flag(record, "duplicate_timestamp")
            expected = self.policy["expected_sample_period_seconds"]
            tolerance = self.policy["gap_tolerance_seconds"]
            if expected is not None and tolerance is not None and delta > expected + tolerance:
                self._flag(record, "timestamp_gap")
        self.last_timestamp[session_id] = timestamp

        lap_distance_field = record["fields"].get("lap_distance")
        if lap_distance_field is None or lap_distance_field["value"] is None:
            return
        lap_id = record["lap_id"]
        lap_distance = float(lap_distance_field["value"])
        previous_distance = self.last_lap_distance.get(lap_id)
        if previous_distance is not None and lap_distance < previous_distance:
            if self.policy["lap_distance_regression_policy"] == "reject":
                raise IntegrityError(f"Lap distance regressed within lap {lap_id}")
            self._flag(record, "lap_distance_regression")
        self.last_lap_distance[lap_id] = lap_distance

    def _distance_bin_invariants(self, record: dict[str, Any]) -> None:
        if record["record_type"] != "distance_bin":
            return
        self.saw_distance_bins = True
        lap_id = record["lap_id"]
        index = record["distance_bin_index"]
        start = float(record["distance_start_m"])
        end = float(record["distance_end_m"])
        if end <= start:
            raise IntegrityError(f"Distance bin {record['record_id']} has a non-positive width")
        previous_index = self.last_distance_bin_index.get(lap_id)
        if previous_index is None and index != 0:
            raise IntegrityError(f"Distance-bin indices must begin at zero in {lap_id}")
        if previous_index is not None and index != previous_index + 1:
            raise IntegrityError(f"Distance-bin indices are not contiguous in {lap_id}")
        previous_start = self.last_distance_bin_start.get(lap_id)
        if previous_start is not None and start <= previous_start:
            raise IntegrityError(f"Distance-bin positions are not strictly increasing in {lap_id}")
        self.last_distance_bin_index[lap_id] = index
        self.last_distance_bin_start[lap_id] = start

    def add(self, record: dict[str, Any]) -> None:
        if record["dataset_id"] != self.dataset_id:
            raise IntegrityError(f"Record {record['record_id']} has a different dataset_id")
        if record["sequence_index"] != self.expected_sequence:
            raise IntegrityError(
                f"Record sequence must be contiguous from zero; expected {self.expected_sequence}"
            )
        self.expected_sequence += 1
        record_id = record["record_id"]
        if record_id in self.record_ids:
            raise IntegrityError(f"Duplicate record identity: {record_id}")
        self.record_ids.add(record_id)
        for flag in record.get("quality_flags", []):
            self.quality_counts[flag] += 1
        self._parent_invariants(record)
        self._temporal_invariants(record)
        self._distance_bin_invariants(record)
        self.counts[record["record_type"]] += 1

    def finalize(self) -> dict[str, Any]:
        if not self.sessions:
            raise IntegrityError("Normalized dataset contains no session record")
        return {
            "record_order": "sequence_index_contiguous_parent_before_child",
            "unique_record_ids": True,
            "parent_references": "verified",
            "quality_flag_counts": dict(sorted(self.quality_counts.items())),
            "interpolation": self.policy["interpolation"],
            "gap_detection": (
                "distance_coverage_evaluated"
                if self.saw_distance_bins
                else
                "evaluated"
                if self.policy["expected_sample_period_seconds"] is not None
                and self.policy["gap_tolerance_seconds"] is not None
                else "not_evaluated_no_declared_cadence"
            ),
        }
