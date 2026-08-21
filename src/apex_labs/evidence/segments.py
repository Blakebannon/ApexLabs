"""Deterministic segment membership and applicability.

A segment is a geometric region on a specific layout, not a label. Two regions
that share an ordinal name such as "Turn 4" are only comparable when they are
the same region on the same verified layout geometry.
"""

from __future__ import annotations

from typing import Any

from apex_labs.errors import EvidenceError

_POSITION_CONCEPT = {"distance_range": "lap_distance", "lap_fraction_range": "lap_fraction"}


def applicability(segment: dict[str, Any], simulator: str, track: str, layout: str) -> dict[str, Any]:
    """The applicability entry for one session context, or an error.

    Evidence collected on a layout the segment definition does not cover is
    refused outright rather than compared on the strength of a shared name.
    """
    for entry in segment["applies_to"]:
        if (entry["simulator"], entry["track"], entry["layout"]) == (simulator, track, layout):
            return entry
    covered = sorted(
        f"{entry['simulator']}/{entry['track']}/{entry['layout']}" for entry in segment["applies_to"]
    )
    raise EvidenceError(
        f"Segment {segment['segment_definition_id']} does not apply to {simulator}/{track}/{layout}; "
        f"it is defined for {covered}. A segment identity is never extended to an unverified layout."
    )


def require_single_geometry(entries: list[dict[str, Any]], segment_id: str) -> str:
    """Refuse evidence spanning geometrically different regions.

    Sharing a corner ordinal across incompatible layouts does not make two
    regions the same region, so the geometry fingerprint must be single-valued
    across every dataset contributing to one evidence set.
    """
    fingerprints = sorted({entry["geometry_fingerprint"] for entry in entries})
    if len(fingerprints) > 1:
        raise EvidenceError(
            f"Segment {segment_id} resolves to {len(fingerprints)} different layout geometries "
            f"({fingerprints}); geometrically different regions are never comparable, even under one corner name."
        )
    return fingerprints[0]


def record_position(record: dict[str, Any], region_kind: str) -> float | None:
    """The along-lap position a region test is applied to, or None when absent.

    Distance-bin records are positioned at the start of their bin, which is a
    record field rather than a measured channel; time-domain samples use the
    normalized distance or lap-fraction concept.
    """
    if record["record_type"] == "distance_bin" and region_kind == "distance_range":
        return record.get("distance_start_m")
    field = record["fields"].get(_POSITION_CONCEPT[region_kind])
    if field is None or field["provenance"] == "unavailable":
        return None
    return field["value"]


def in_region(segment: dict[str, Any], position: float | None) -> bool:
    """Boundary-explicit region membership, including the wrapping case.

    A wrapping region spans the start/finish line: it holds everything from the
    start bound to the end of the lap and everything from the beginning of the
    lap to the end bound. Inclusivity is taken from the declared boundary, not
    assumed.
    """
    if position is None:
        return False
    region = segment["region"]
    start = region["start"]
    end = region["end"]
    start_inclusive = region["boundary"]["start_inclusive"]
    end_inclusive = region["boundary"]["end_inclusive"]
    after_start = position >= start if start_inclusive else position > start
    before_end = position <= end if end_inclusive else position < end
    if region["wraparound"]:
        return after_start or before_end
    return after_start and before_end


def in_phase(segment: dict[str, Any], record: dict[str, Any]) -> bool:
    """Deterministic phase membership within an already-matched region."""
    phase = segment["phase"]
    if phase is None:
        return True
    field = record["fields"].get(phase["concept"])
    if field is None or field["provenance"] == "unavailable":
        return False
    if phase["comparison"] == "at_or_above":
        return field["value"] >= phase["threshold"]
    return field["value"] < phase["threshold"]


def selects(segment: dict[str, Any], record: dict[str, Any]) -> bool:
    """True when a record falls inside the segment region and declared phase."""
    return in_region(segment, record_position(record, segment["region"]["kind"])) and in_phase(
        segment, record
    )


def concept_coverage(
    segment: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[float, dict[str, int]]:
    """Fraction of required-concept observations actually available.

    Values whose provenance is `unavailable` are absent evidence. They are
    counted as missing rather than coerced to zero, because an all-zero channel
    and an unrecorded channel are different facts.
    """
    required = segment["coverage_requirements"]["required_concepts"]
    if not records or not required:
        return 0.0, {concept: 0 for concept in required}
    present = {concept: 0 for concept in required}
    for record in records:
        for concept in required:
            field = record["fields"].get(concept)
            if field is not None and field["provenance"] != "unavailable":
                present[concept] += 1
    total = len(records) * len(required)
    return sum(present.values()) / total, present
