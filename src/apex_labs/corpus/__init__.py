"""Corpus admission: the automated gate a real bundle must pass to enter a frozen corpus."""

from apex_labs.corpus.admission import (
    AdmissionFinding,
    admit_corpus,
    coaching_binding_since,
    evaluate_bundle,
)

__all__ = [
    "AdmissionFinding",
    "admit_corpus",
    "coaching_binding_since",
    "evaluate_bundle",
]
