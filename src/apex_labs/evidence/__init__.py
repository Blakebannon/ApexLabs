"""Comparable evidence: segment identity, comparability guards, and evidence sets."""

from apex_labs.evidence.builder import build_evidence_set, verify_evidence_set
from apex_labs.evidence.comparability import assess as assess_comparability
from apex_labs.evidence.comparability import comparability_key
from apex_labs.evidence.segments import (
    applicability,
    concept_coverage,
    in_region,
    require_single_geometry,
    selects,
)

__all__ = [
    "applicability",
    "assess_comparability",
    "build_evidence_set",
    "comparability_key",
    "concept_coverage",
    "in_region",
    "require_single_geometry",
    "selects",
    "verify_evidence_set",
]
