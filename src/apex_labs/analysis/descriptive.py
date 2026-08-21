"""Deterministic descriptive computation kernels.

Every kernel is descriptive only. Nothing here performs a hypothesis test,
produces an interval, or assigns a confidence; those require a preregistered
protocol and a dedicated, reviewed analysis method.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

from apex_labs.normalization.concepts import NORMALIZED_CONCEPTS


def summarize(values: list[float | int]) -> dict[str, Any] | None:
    """Robust descriptive summary of a finite numeric sample; None when empty.

    Deterministic given the value multiset: statistics are computed over the
    sorted values, so record enumeration order cannot change any output.
    """
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    median = statistics.median(ordered)
    if count == 1:
        q1 = q3 = median
    else:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    mad = statistics.median(sorted(abs(value - median) for value in ordered))
    return {
        "count": count,
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "mean": math.fsum(ordered) / count,
        "median": median,
        "q1": q1,
        "q3": q3,
        "mad": mad,
    }


class _RecordInventory:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.record_counts: Counter[str] = Counter()
        self.quality_flag_counts: Counter[str] = Counter()

    def consume(self, record: dict[str, Any]) -> None:
        self.record_counts[record["record_type"]] += 1
        for flag in record.get("quality_flags", []):
            self.quality_flag_counts[flag] += 1

    def result(self) -> dict[str, Any]:
        return {
            "computation_id": self.spec["computation_id"],
            "kind": "record_inventory",
            "record_counts": dict(sorted(self.record_counts.items())),
            "quality_flag_counts": dict(sorted(self.quality_flag_counts.items())),
        }


class _ConceptAvailability:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.records_scanned = 0
        self.availability: dict[str, Counter[str]] = {
            concept: Counter() for concept in NORMALIZED_CONCEPTS
        }

    def consume(self, record: dict[str, Any]) -> None:
        record_type = self.spec["record_type"]
        if record_type is not None and record["record_type"] != record_type:
            return
        self.records_scanned += 1
        for concept, field in record["fields"].items():
            counter = self.availability[concept]
            counter["present"] += 1
            counter[field["provenance"]] += 1

    def result(self) -> dict[str, Any]:
        return {
            "computation_id": self.spec["computation_id"],
            "kind": "concept_availability",
            "record_type": self.spec["record_type"],
            "records_scanned": self.records_scanned,
            "concepts": {
                concept: {
                    "present": counter["present"],
                    "measured": counter["measured"],
                    "derived": counter["derived"],
                    "estimated": counter["estimated"],
                    "unavailable": counter["unavailable"],
                }
                for concept, counter in sorted(self.availability.items())
            },
        }


class _DescriptiveSummary:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.records_scanned = 0
        self.records_of_type = 0
        self.field_present = 0
        self.values_unavailable = 0
        self.groups: dict[str, list[float | int]] = {}

    def consume(self, record: dict[str, Any]) -> None:
        self.records_scanned += 1
        if record["record_type"] != self.spec["record_type"]:
            return
        self.records_of_type += 1
        group = "dataset" if self.spec["group_by"] == "dataset" else record["lap_id"]
        values = self.groups.setdefault(group, [])
        field = record["fields"].get(self.spec["concept"])
        if field is None:
            return
        self.field_present += 1
        if field["provenance"] == "unavailable":
            self.values_unavailable += 1
            return
        values.append(field["value"])

    def result(self) -> dict[str, Any]:
        values_included = self.field_present - self.values_unavailable
        payload: dict[str, Any] = {
            "computation_id": self.spec["computation_id"],
            "kind": "descriptive_summary",
            "record_type": self.spec["record_type"],
            "concept": self.spec["concept"],
            "group_by": self.spec["group_by"],
            "attrition": {
                "records_scanned": self.records_scanned,
                "records_of_type": self.records_of_type,
                "field_present": self.field_present,
                "values_included": values_included,
                "values_unavailable": self.values_unavailable,
            },
        }
        if self.spec["group_by"] == "dataset":
            payload["summary"] = summarize(self.groups.get("dataset", []))
        else:
            payload["per_lap"] = {
                lap_id: summarize(values) for lap_id, values in sorted(self.groups.items())
            }
        return payload


class _EventYield:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.total = 0
        self.per_lap: Counter[str] = Counter()
        self.per_event_type: Counter[str] = Counter()

    def consume(self, record: dict[str, Any]) -> None:
        if record["record_type"] != self.spec["record_type"]:
            return
        self.total += 1
        self.per_lap[record["lap_id"]] += 1
        if record["record_type"] == "driver_input_event":
            self.per_event_type[record["event_type"]] += 1

    def result(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "computation_id": self.spec["computation_id"],
            "kind": "event_yield",
            "record_type": self.spec["record_type"],
            "total": self.total,
            "per_lap": dict(sorted(self.per_lap.items())),
        }
        if self.spec["record_type"] == "driver_input_event":
            payload["per_event_type"] = dict(sorted(self.per_event_type.items()))
        return payload


_KERNELS = {
    "record_inventory": _RecordInventory,
    "concept_availability": _ConceptAvailability,
    "descriptive_summary": _DescriptiveSummary,
    "event_yield": _EventYield,
}


def build_computation(spec: dict[str, Any]) -> Any:
    return _KERNELS[spec["kind"]](spec)
