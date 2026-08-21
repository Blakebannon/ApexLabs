"""Declared analysis over verified evidence: descriptive summaries and preregistered inference."""

from apex_labs.analysis.descriptive import summarize
from apex_labs.analysis.inferential import (
    run_inferential_analysis,
    verify_inferential_analysis_run,
)
from apex_labs.analysis.runner import run_analysis, verify_analysis_run

__all__ = [
    "run_analysis",
    "run_inferential_analysis",
    "summarize",
    "verify_analysis_run",
    "verify_inferential_analysis_run",
]
